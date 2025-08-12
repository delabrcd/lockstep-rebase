"""
Repository discovery utilities for lockstep rebase operations.

This module handles discovery and traversal of Git repositories
and their nested submodules.
"""

import os
import subprocess
from typing import List

from ..core.models import RepoInfo
from ..core.git_utils import GitUtils


class RepositoryDiscovery:
    """Handles discovery of repositories and submodules."""

    def __init__(self, git_utils: GitUtils):
        """Initialize repository discovery.

        Args:
            git_utils: Git utilities instance
        """
        self.git_utils = git_utils

    def discover_repositories(self, root_path: str) -> RepoInfo:
        """Discover all repositories and submodules starting from root.

        Args:
            root_path: Root repository path

        Returns:
            Repository information tree
        """
        repo_name = os.path.basename(root_path)
        repo_info = RepoInfo(name=repo_name, path=root_path)

        # Discover submodules
        repo_info.submodules = self._discover_submodules(root_path)

        return repo_info

    def _discover_submodules(self, repo_path: str) -> List[RepoInfo]:
        """Discover submodules in a repository.

        Args:
            repo_path: Path to the repository

        Returns:
            List of submodule information
        """
        submodules = []

        try:
            # Get submodule information
            submodule_output = self.git_utils.sh(
                ['git', 'submodule', 'status'],
                cwd=repo_path,
                capture=True
            )

            for line in submodule_output.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # Parse submodule status line
                # Format: " commit_hash path (tag)" or "-commit_hash path"
                parts = line.split()
                if len(parts) >= 2:
                    submodule_path = parts[1]
                    full_path = os.path.join(repo_path, submodule_path)

                    if os.path.exists(full_path):
                        submodule_name = os.path.basename(submodule_path)
                        submodule_info = RepoInfo(
                            name=submodule_name,
                            path=full_path
                        )

                        # Recursively discover nested submodules
                        submodule_info.submodules = self._discover_submodules(
                            full_path)
                        submodules.append(submodule_info)

        except subprocess.CalledProcessError:
            # No submodules or error getting submodule info
            pass

        return submodules

    def print_tree(self, repo_info: RepoInfo, indent: int = 0) -> None:
        """Print a tree view of the repository structure.

        Args:
            repo_info: Repository information
            indent: Current indentation level
        """
        prefix = "  " * indent
        print(f"{prefix}📁 {repo_info.name}")

        for submodule in repo_info.submodules:
            self.print_tree(submodule, indent + 1)

    def collect_all_repos(self, repo_info: RepoInfo) -> List[RepoInfo]:
        """Collect all repositories in a flat list.

        Args:
            repo_info: Root repository information

        Returns:
            Flat list of all repositories
        """
        all_repos = [repo_info]

        for submodule in repo_info.submodules:
            all_repos.extend(self.collect_all_repos(submodule))

        return all_repos
