"""
UI-agnostic interface for conflict resolution prompting.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List
from .models import RepoInfo, ResolutionSummary


class ConflictPrompt(ABC):
    """Abstract interface for prompting users during conflict resolution."""

    @abstractmethod
    def prompt_for_conflict_resolution(
        self,
        repo_info: RepoInfo,
        file_conflicts: List[str],
        unresolved_submodule_conflicts: List[str],
    ) -> bool:
        """
        Prompt user to resolve conflicts and wait for confirmation.

        Args:
            repo_info: Information about the repository with conflicts
            file_conflicts: List of files with conflicts
            unresolved_submodule_conflicts: List of submodules with conflicts

        Returns:
            True if user indicates conflicts are resolved, False to abort
        """
        pass

    @abstractmethod
    def show_messages(self, messages: List[str], style: str = "") -> None:
        """Display generic user-facing messages from core logic.

        Args:
            messages: List of strings to display
            style: Optional style hint for UI implementations
        """
        pass

    @abstractmethod
    def display_resolution_summary(self, summary: ResolutionSummary) -> None:
        """
        Display a summary of automatic conflict resolutions.

        Args:
            summary: The resolution summary to display
        """
        pass


class NoOpConflictPrompt(ConflictPrompt):
    """No-operation conflict prompt that always aborts."""

    def prompt_for_conflict_resolution(
        self,
        repo_info: RepoInfo,
        file_conflicts: List[str],
        unresolved_submodule_conflicts: List[str],
    ) -> bool:
        return False

    def display_resolution_summary(self, summary: ResolutionSummary) -> None:
        pass

    def show_messages(self, messages: List[str], style: str = "") -> None:
        pass
