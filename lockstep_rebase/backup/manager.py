"""
Backup management for lockstep rebase operations.

This module handles creation, listing, and deletion of backup branches
created during rebase operations.
"""

import os
import subprocess
from typing import List, Dict

from ..core.models import RebaseResult
from ..core.git_utils import GitUtils
from ..utils.discovery import RepositoryDiscovery


class BackupManager:
    """Manages backup branches for rebase operations."""

    def __init__(self, git_utils: GitUtils, discovery: RepositoryDiscovery):
        """Initialize backup manager.

        Args:
            git_utils: Git utilities instance
            discovery: Repository discovery instance
        """
        self.git_utils = git_utils
        self.discovery = discovery

    def manage_backups_interactive(self, root_path: str) -> None:
        """Interactive backup management for all repositories.

        Args:
            root_path: Root repository path
        """
        print("\n🗂️  BACKUP BRANCH MANAGER")
        print("=" * 50)

        # Discover all repositories
        root_repo = self.discovery.discover_repositories(root_path)
        all_repos = self.discovery.collect_all_repos(root_repo)

        # Find backup branches in all repositories
        total_backups = 0
        repo_backups = {}

        for repo in all_repos:
            backups = self.git_utils.find_backup_branches(repo.path)
            if backups:
                repo_backups[repo.path] = backups
                total_backups += len(backups)

        if total_backups == 0:
            print("\n✅ No backup branches found.")
            return

        print(
            f"\n📊 Found {total_backups} backup branches across {len(repo_backups)} repositories:")

        for repo_path, backups in repo_backups.items():
            repo_name = os.path.basename(repo_path)
            print(f"\n📁 {repo_name} ({len(backups)} backups):")
            for i, backup in enumerate(backups, 1):
                print(f"  {i}. {backup}")

        print("\n📋 BACKUP MANAGEMENT OPTIONS:")
        print("  1. Delete all backup branches")
        print("  2. Delete backups by repository")
        print("  3. Delete specific backup branches")
        print("  4. Exit without changes")

        while True:
            choice = input("\nChoose an option (1-4): ").strip()

            if choice == '1':
                if self._confirm_delete_all_backups(total_backups):
                    self._delete_all_backups(repo_backups)
                break
            elif choice == '2':
                self._delete_backups_by_repo(repo_backups)
                break
            elif choice == '3':
                self._delete_specific_backups(repo_backups)
                break
            elif choice == '4':
                print("\n⏹️  Exiting without changes.")
                break
            else:
                print("Please enter a number between 1 and 4.")

    def _confirm_delete_all_backups(self, total_count: int) -> bool:
        """Confirm deletion of all backup branches.

        Args:
            total_count: Total number of backup branches

        Returns:
            True if user confirms deletion
        """
        print(f"\n⚠️  This will delete ALL {total_count} backup branches.")
        print("This action cannot be undone!")

        while True:
            confirm = input(
                "\nAre you sure? Type 'DELETE ALL' to confirm: ").strip()
            if confirm == 'DELETE ALL':
                return True
            elif confirm.lower() in ['n', 'no', 'cancel', '']:
                return False
            else:
                print("Please type 'DELETE ALL' to confirm or 'no' to cancel.")

    def _delete_all_backups(self, repo_backups: Dict[str, List[str]]) -> None:
        """Delete all backup branches.

        Args:
            repo_backups: Dictionary mapping repo paths to backup branch lists
        """
        deleted_count = 0

        for repo_path, backups in repo_backups.items():
            repo_name = os.path.basename(repo_path)
            print(f"\n🗑️  Deleting backups in {repo_name}...")

            for backup in backups:
                try:
                    self.git_utils.sh(
                        ['git', 'branch', '-D', backup], cwd=repo_path)
                    print(f"  ✅ Deleted {backup}")
                    deleted_count += 1
                except subprocess.CalledProcessError as e:
                    print(f"  ❌ Failed to delete {backup}: {e}")

        print(f"\n✅ Deleted {deleted_count} backup branches.")

    def _delete_backups_by_repo(
            self, repo_backups: Dict[str, List[str]]) -> None:
        """Delete backup branches by repository.

        Args:
            repo_backups: Dictionary mapping repo paths to backup branch lists
        """
        repo_list = list(repo_backups.keys())

        print("\n📁 Select repositories to clean up:")
        for i, repo_path in enumerate(repo_list, 1):
            repo_name = os.path.basename(repo_path)
            backup_count = len(repo_backups[repo_path])
            print(f"  {i}. {repo_name} ({backup_count} backups)")

        while True:
            selection = input(
                "\nEnter repository numbers (comma-separated) or 'all': ").strip()

            if selection.lower() == 'all':
                selected_repos = repo_list
                break
            else:
                try:
                    indices = [int(x.strip()) -
                               1 for x in selection.split(',')]
                    selected_repos = [repo_list[i]
                                      for i in indices if 0 <= i < len(repo_list)]
                    if selected_repos:
                        break
                    else:
                        print("No valid repositories selected.")
                except (ValueError, IndexError):
                    print("Please enter valid repository numbers.")

        for repo_path in selected_repos:
            repo_name = os.path.basename(repo_path)
            backups = repo_backups[repo_path]

            print(f"\n🗑️  Deleting {len(backups)} backups in {repo_name}...")
            for backup in backups:
                try:
                    self.git_utils.sh(
                        ['git', 'branch', '-D', backup], cwd=repo_path)
                    print(f"  ✅ Deleted {backup}")
                except subprocess.CalledProcessError as e:
                    print(f"  ❌ Failed to delete {backup}: {e}")

    def _delete_specific_backups(
            self, repo_backups: Dict[str, List[str]]) -> None:
        """Delete specific backup branches.

        Args:
            repo_backups: Dictionary mapping repo paths to backup branch lists
        """
        # Create a flat list of all backups with repo context
        all_backups = []
        for repo_path, backups in repo_backups.items():
            repo_name = os.path.basename(repo_path)
            for backup in backups:
                all_backups.append((repo_path, repo_name, backup))

        print("\n📋 Select backup branches to delete:")
        for i, (repo_path, repo_name, backup) in enumerate(all_backups, 1):
            print(f"  {i}. {repo_name}: {backup}")

        while True:
            selection = input(
                "\nEnter backup numbers (comma-separated): ").strip()

            try:
                indices = [int(x.strip()) - 1 for x in selection.split(',')]
                selected_backups = [all_backups[i]
                                    for i in indices if 0 <= i < len(all_backups)]
                if selected_backups:
                    break
                else:
                    print("No valid backups selected.")
            except (ValueError, IndexError):
                print("Please enter valid backup numbers.")

        print(f"\n🗑️  Deleting {len(selected_backups)} backup branches...")
        for repo_path, repo_name, backup in selected_backups:
            try:
                self.git_utils.sh(
                    ['git', 'branch', '-D', backup], cwd=repo_path)
                print(f"  ✅ Deleted {repo_name}: {backup}")
            except subprocess.CalledProcessError as e:
                print(f"  ❌ Failed to delete {repo_name}: {backup} - {e}")

    def prompt_cleanup_backups_after_push(
            self, results: List[RebaseResult]) -> None:
        """Prompt user to clean up backup branches after successful push.

        Args:
            results: List of rebase results
        """
        # Find all backup branches from successful results
        backup_branches = []
        for result in results:
            if result.success and result.backup_branch:
                repo_name = os.path.basename(result.repo_path)
                backup_branches.append(
                    (result.repo_path, repo_name, result.backup_branch))

        if not backup_branches:
            return

        print(
            f"\n🗂️  Found {len(backup_branches)} backup branches created during this rebase:")
        for repo_path, repo_name, backup_branch in backup_branches:
            print(f"  📁 {repo_name}: {backup_branch}")

        while True:
            cleanup = input(
                "\nRemove these backup branches? (y/N): ").strip().lower()
            if cleanup in ['y', 'yes']:
                print("\n🗑️  Cleaning up backup branches...")
                for repo_path, repo_name, backup_branch in backup_branches:
                    try:
                        self.git_utils.sh(
                            ['git', 'branch', '-D', backup_branch], cwd=repo_path)
                        print(f"  ✅ Deleted {repo_name}: {backup_branch}")
                    except subprocess.CalledProcessError as e:
                        print(
                            f"  ❌ Failed to delete {repo_name}: {backup_branch} - {e}")
                break
            elif cleanup in ['n', 'no', '']:
                print("\n📦 Backup branches preserved.")
                break
            else:
                print("Please enter 'y' or 'n' (default: no).")
