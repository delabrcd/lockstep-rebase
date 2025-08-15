"""
UI-agnostic prompt interface for user interactions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List
from enum import Enum


class PromptChoice(Enum):
    """Standard prompt choices."""

    YES = "yes"
    NO = "no"
    ABORT = "abort"


class BranchSyncAction(Enum):
    """Actions for branch synchronization."""

    USE_REMOTE = "use_remote"
    CREATE_LOCAL = "create_local"
    SYNC_LOCAL = "sync_local"
    SKIP = "skip"
    ABORT = "abort"


class UserPrompt(ABC):
    """Abstract interface for prompting users for decisions."""

    @abstractmethod
    def confirm_use_remote_branch(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        """
        Ask user if they want to use a remote branch when local doesn't exist.

        Args:
            repo_name: Name of the repository
            branch_name: Name of the branch
            remote_name: Name of the remote (default: origin)

        Returns:
            True if user wants to use remote branch, False otherwise
        """
        pass

    @abstractmethod
    def confirm_sync_branch(
        self,
        repo_name: str,
        branch_name: str,
        local_commit: str,
        remote_commit: str,
        commits_behind: int,
        commits_ahead: int,
    ) -> BranchSyncAction:
        """
        Ask user what to do when local branch is out of sync with remote.

        Args:
            repo_name: Name of the repository
            branch_name: Name of the branch
            local_commit: Local commit hash (short)
            remote_commit: Remote commit hash (short)
            commits_behind: Number of commits local is behind remote
            commits_ahead: Number of commits local is ahead of remote

        Returns:
            BranchSyncAction indicating what the user wants to do
        """
        pass

    @abstractmethod
    def confirm_create_local_branch(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        """
        Ask user if they want to create a local branch from remote.

        Args:
            repo_name: Name of the repository
            branch_name: Name of the branch
            remote_name: Name of the remote (default: origin)

        Returns:
            True if user wants to create local branch, False otherwise
        """
        pass

    @abstractmethod
    def show_validation_summary(
        self, missing_branches: Dict[str, List[str]], sync_issues: Dict[str, Dict[str, str]]
    ) -> None:
        """
        Show a summary of validation issues found.

        Args:
            missing_branches: Dict with 'missing_source' and 'missing_target' lists
            sync_issues: Dict mapping repo names to sync issue descriptions
        """
        pass


class NoOpPrompt(UserPrompt):
    """No-operation prompt that always returns safe defaults."""

    def confirm_use_remote_branch(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        return False

    def confirm_sync_branch(
        self,
        repo_name: str,
        branch_name: str,
        local_commit: str,
        remote_commit: str,
        commits_behind: int,
        commits_ahead: int,
    ) -> BranchSyncAction:
        return BranchSyncAction.SKIP

    def confirm_create_local_branch(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        return False

    def show_validation_summary(
        self, missing_branches: Dict[str, List[str]], sync_issues: Dict[str, Dict[str, str]]
    ) -> None:
        pass
