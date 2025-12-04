import os
import re
import sys

import requests
from packaging.version import parse as parse_version

GITHUB_API = "https://api.github.com"

# Define the list of repositories to process
REPOSITORIES = [repo.strip() for repo in os.environ["REPOSITORIES_INPUT"].split(',')]


def get_github_token():
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("Error: GH_TOKEN environment variable not set.")
        sys.exit(1)
    return token


def get_commit_sha(owner, repo, ref, headers):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/{ref}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"Error: Could not get ref {ref}: {r.text}")
    return r.json()["object"]["sha"]


def compare_commits(owner, repo, base, head, headers):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/compare/{base}...{head}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        raise Exception(f"Error: Could not compare {base}...{head}: {r.text}")
    return r.json()


def create_branch(owner, repo, branch_name, sha, headers):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/refs"
    data = {
        "ref": f"refs/heads/{branch_name}",
        "sha": sha
    }
    r = requests.post(url, json=data, headers=headers)
    if r.status_code != 201:
        raise Exception(f"Error: Could not create branch {branch_name}: {r.text}")
    return r.json()


def create_pr(owner, repo, head, base, title, body, headers):
    url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls"
    data = {
        "title": title,
        "body": body,
        "head": head,
        "base": base
    }
    r = requests.post(url, json=data, headers=headers)
    if r.status_code != 201:
        raise Exception(f"Error: Could not create PR: {r.text}")
    return r.json()


def get_latest_eah_tag(owner, repo, headers):
    tags = []
    page = 1
    while True:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/tags?page={page}&per_page=100"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            raise Exception(f"Error: Could not fetch tags: {r.text}")
        data = r.json()
        if not data:
            break
        tags.extend([t['name'] for t in data if t['name'].startswith('eah_')])
        if len(data) < 100:
            break
        page += 1
    if not tags:
        raise Exception("No tags found matching 'eah_' pattern.")

    # Extract version part and sort
    def tag_key(tag):
        m = re.match(r'eah_(.*)', tag)
        return parse_version(m.group(1)) if m else parse_version('0')

    tags.sort(key=tag_key, reverse=True)
    return tags[0]


def write_to_github_step_summary(text):
    with open(os.environ['GITHUB_STEP_SUMMARY'], "a") as f:
        f.write(text + '\n')


def main():
    release_number = os.environ["RELEASE_NUMBER"]
    token = get_github_token()
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}

    if not REPOSITORIES:
        print("No repositories defined in REPOSITORIES list.")
        sys.exit(1)

    created_pr_links = []
    errors = []

    for repo_full in REPOSITORIES:
        print(f"\nProcessing repository: {repo_full}")
        owner, repo = repo_full.split("/")
        try:
            # Get latest eah_ tag
            tag = get_latest_eah_tag(owner, repo, headers)
            print(f"Latest eah_ tag: {tag}")

            # Get develop SHA (used for branch creation)
            develop_sha = get_commit_sha(owner, repo, "heads/develop", headers)

            # Check if release branch already exists
            branch_name = f"release/{release_number}"
            url = f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/heads/{branch_name}"
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                print(f"Release branch {branch_name} already exists. Skipping.")
                continue
            elif r.status_code != 404:
                print(f"Error checking for branch {branch_name}: {r.text}")
                continue
            # If 404, branch does not exist, proceed

            # Compare develop to tag
            cmp = compare_commits(owner, repo, tag, "develop", headers)
            if cmp["status"] == "identical" or cmp["ahead_by"] == 0:
                print(f"Tag {tag} is up to date with develop. No release branch needed.")
                continue
            print(f"Develop is ahead of tag {tag} by {cmp['ahead_by']} commits. Creating release branch.")

            # Create release branch from develop
            create_branch(owner, repo, branch_name, develop_sha, headers)
            print(f"Created branch {branch_name}.")

            # Create PR to master
            pr_title = f"feat(merge): merge {branch_name} into master"
            pr_body = f"PR to merge {branch_name} into master."
            pr = create_pr(owner, repo, branch_name, "master", pr_title, pr_body, headers)
            print(f"Created PR: {pr['html_url']}")
            created_pr_links.append(pr['html_url'])
        except Exception as e:
            print(f"Error processing {repo_full}: {e}")
            errors.append(f"Error processing {repo_full}: {e}")
            continue

    if created_pr_links:
        print('\nCreated PRs:')
        write_to_github_step_summary('Created PRs:')
        print(*created_pr_links, sep="\n")
        for pr_link in created_pr_links:
            write_to_github_step_summary(f'- {pr_link}')
    if errors:
        print('\nErrors encountered:')
        write_to_github_step_summary('Errors encountered:')
        print(*errors, sep="\n")
        for error in errors:
            write_to_github_step_summary(f'- {error}')
        sys.exit(1)


if __name__ == "__main__":
    main()
