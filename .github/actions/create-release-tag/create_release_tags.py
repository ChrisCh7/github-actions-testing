import os
import sys

import requests

GITHUB_API = "https://api.github.com"
REQUEST_TIMEOUT = 30

# Define the list of repositories to process
REPOSITORIES = [repo.strip() for repo in os.environ["REPOSITORIES_INPUT"].split(',')]


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API request fails or returns an unexpected response."""


def get_github_token() -> str:
    """Return the GitHub token from the ``GH_TOKEN`` environment variable.

    Exits the program with status code 1 if the variable is not set.
    """
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("Error: GH_TOKEN environment variable not set.")
        sys.exit(1)
    return token


def get_headers() -> dict[str, str]:
    """Build and return default headers for GitHub API requests."""
    return {
        "Authorization": f"Bearer {get_github_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def get_commit_sha(owner: str, repo: str, ref: str) -> str:
    """Fetch and return the commit SHA for a given ref in a repository.

    Args:
        owner: GitHub organization or user that owns the repository.
        repo: Name of the repository.
        ref: Git reference path suffix, e.g. ``"heads/develop"`` or ``"tags/eah_1.2.3"``.

    Returns:
        The commit SHA string pointed to by the given ref.

    Raises:
        GitHubAPIError: If the ref cannot be retrieved from the GitHub API.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/{ref}"
    r = requests.get(url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
    if r.status_code != 200:
        raise GitHubAPIError(f"Error: Could not get ref {ref}: {r.text}")
    return r.json()["object"]["sha"]


def tag_exists(owner: str, repo: str, tag_name: str) -> bool:
    """Return a boolean indicating if a tag with the given name exists in the repository.

    Args:
        owner: GitHub organization or user that owns the repository.
        repo: Name of the repository.
        tag_name: Name of the tag to check, without the ``tags/`` prefix.

    Returns:
        ``True`` if the tag exists, ``False`` if it does not.

    Raises:
        GitHubAPIError: If the existence check fails with a non-404 error.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/ref/tags/{tag_name}"
    r = requests.get(url, headers=get_headers(), timeout=REQUEST_TIMEOUT)
    if r.status_code == 200:
        return True
    if r.status_code == 404:
        return False
    raise GitHubAPIError(f"Error checking for tag {tag_name}: {r.text}")


def create_tag(owner: str, repo: str, tag_name: str, sha: str) -> dict:
    """Create a new tag in the repository at the specified commit SHA.

    Args:
        owner: GitHub organization or user that owns the repository.
        repo: Name of the repository.
        tag_name: Name of the tag to create (without the ``refs/tags/`` prefix).
        sha: Commit SHA that the new tag should point to.

    Returns:
        The parsed JSON response describing the created ref.

    Raises:
        GitHubAPIError: If the tag cannot be created.
    """
    url = f"{GITHUB_API}/repos/{owner}/{repo}/git/refs"
    data = {
        "ref": f"refs/tags/{tag_name}",
        "sha": sha,
    }
    r = requests.post(url, json=data, headers=get_headers(), timeout=REQUEST_TIMEOUT)
    if r.status_code != 201:
        raise GitHubAPIError(f"Error: Could not create tag {tag_name}: {r.text}")
    return r.json()


def write_to_github_step_summary(text: str):
    """Append a line of text to the GitHub Actions step summary file.

    Args:
        text: Line of text to append to the summary.
    """
    with open(os.environ['GITHUB_STEP_SUMMARY'], "a") as f:
        f.write(text + '\n')


def main():
    """Entry point for creating release tags across repositories.

    The function reads configuration from environment variables and creates a
    ``eah_<RELEASE_NUMBER>`` tag.

    Environment variables used:
        RELEASE_NUMBER: Release identifier used in the tag name.
        REPOSITORIES_INPUT: Comma-separated list of ``owner/repo`` pairs.
        GH_TOKEN: GitHub token used for API authentication.
        GITHUB_STEP_SUMMARY: Path to the GitHub Actions step summary file.
    """
    release_number = os.environ["RELEASE_NUMBER"].strip()

    if not REPOSITORIES:
        print("No repositories defined in REPOSITORIES list.")
        sys.exit(1)

    created_tag_links = []
    errors = []

    for repo_full in REPOSITORIES:
        print(f"\nProcessing repository: {repo_full}")
        owner, repo = repo_full.split("/")
        try:
            # Get release branch SHA (used for tag creation)
            release_sha = get_commit_sha(owner, repo, f"heads/release/{release_number}")

            # Check if release tag already exists
            tag_name = f"eah_{release_number}"
            if tag_exists(owner, repo, tag_name):
                print(f"Release tag {tag_name} already exists. Skipping.")
                continue
            # If it does not exist, proceed

            # Create release tag from release branch
            create_tag(owner, repo, tag_name, release_sha)
            print(f"Created tag {tag_name}.")

            tag_url = f"https://github.com/{repo_full}/releases/tag/{tag_name}"
            print(f"Created tag: {tag_url}")
            created_tag_links.append(tag_url)
        except Exception as e:
            print(f"Error processing {repo_full}: {e}")
            errors.append(f"Error processing {repo_full}: {e}")
            continue

    if created_tag_links:
        print('\nCreated tags:')
        write_to_github_step_summary('Created tags:')
        print(*created_tag_links, sep="\n")
        for tag_link in created_tag_links:
            write_to_github_step_summary(f'- {tag_link}')
    if errors:
        print('\nErrors encountered:')
        write_to_github_step_summary('Errors encountered:')
        print(*errors, sep="\n")
        for error in errors:
            write_to_github_step_summary(f'- {error}')
        sys.exit(1)


if __name__ == "__main__":
    main()
