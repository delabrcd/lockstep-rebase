"""
Conflict resolution handling for Git rebase operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import  List, Optional, Tuple

from .models import ConflictResolutionError, RepoInfo, ResolvedCommit, ResolutionSummary
from .commit_tracker import GlobalCommitTracker
from .conflict_prompt_interface import ConflictPrompt, NoOpConflictPrompt
from .git_manager import GitManager


logger = logging.getLogger(__name__)


class ConflictResolver:
    """Handles merge conflict resolution during rebase operations.

    Requires a bound GitManager for the target repository. Repo_path parameters
    are kept for signature compatibility but are generally ignored; the attached
    GitManager is always used for the parent repository. A new GitManager may be
    created only when operating inside a submodule's working directory.
    """

    def __init__(
        self,
        global_tracker: GlobalCommitTracker,
        conflict_prompt: ConflictPrompt = None,
        git_manager: GitManager = None,
    ) -> None:
        """Initialize conflict resolver with global commit tracker and optional GitManager."""
        self.global_tracker = global_tracker
        self.resolution_summary = ResolutionSummary()
        self.conflict_prompt = conflict_prompt or NoOpConflictPrompt()
        self.git_manager: GitManager = git_manager

    def analyze_conflicts(self) -> Tuple[List[str], List[str]]:
        """
        Analyze conflicts in a repository.

        Returns:
            Tuple of (file_conflicts, submodule_conflicts)
        """
        file_conflicts = []
        submodule_conflicts = []

        try:
            unresolved_paths = self.git_manager.get_conflict_files()

            for filepath in unresolved_paths:
                if self.git_manager.is_submodule_path(filepath):
                    submodule_conflicts.append(filepath)
                else:
                    file_conflicts.append(filepath)

            logger.debug(
                f"Found {len(file_conflicts)} file conflicts and "
                f"{len(submodule_conflicts)} submodule conflicts"
            )

        except Exception as e:
            logger.error(f"Error analyzing conflicts: {e}")
            raise ConflictResolutionError(f"Failed to analyze conflicts: {e}")

        return file_conflicts, submodule_conflicts

    def auto_resolve_submodule_conflicts(
        self, conflicted_submodules: List[RepoInfo]
    ) -> Tuple[List[str], List[str]]:
        """
        Attempt to automatically resolve submodule conflicts using commit mappings.

        Returns:
            Tuple of (resolved_conflicts, unresolved_conflicts)
        """
        resolved = []
        unresolved = []

        for submodule in conflicted_submodules:
            # Defensive: tolerate None or unexpected entries to avoid crashes
            if submodule is None:
                logger.warning(
                    "auto_resolve_submodule_conflicts received a None entry; skipping"
                )
                unresolved.append("<unknown-submodule>")
                continue

            try:
                if self._resolve_submodule_conflict(submodule):
                    resolved.append(submodule.path)
                else:
                    unresolved.append(submodule.path)
            except Exception as e:
                logger.error(f"Error while resolving submodule conflict entry: {e}")
                try:
                    unresolved.append(getattr(submodule, "path", "<unknown-submodule>"))
                except Exception:
                    unresolved.append("<unknown-submodule>")

        return resolved, unresolved

    def _resolve_submodule_conflict(self, submodule: RepoInfo) -> bool:
        """
        Resolve a single submodule conflict by finding the correct commit hash.

        Returns:
            True if resolved successfully, False otherwise
        """
        try:
            gm_parent = self.git_manager

            entries = gm_parent.get_unmerged_index_entries(submodule.path)
            if not entries:
                return False

            # Find the incoming commit hash (stage 3)
            incoming_hash = None
            for entry in entries:
                if entry.get("stage") == "3":  # Theirs (incoming)
                    incoming_hash = entry.get("hash")
                    break

            if not incoming_hash:
                logger.warning(f"Could not find incoming hash for submodule {submodule.path}")
                return False

            # Try to resolve using commit mappings
            resolved_hash = self._find_resolved_submodule_hash(incoming_hash)
            if not resolved_hash:
                logger.warning(f"Could not find resolved hash for {incoming_hash[:8]}")
                return False

            gm_sub = submodule.git_manager
            gm_sub.checkout_commit(resolved_hash)

            # Stage the resolved submodule in parent repo
            gm_parent.add_paths([submodule.path])

            # Verify that the index reflects the resolution and the path is staged
            try:
                remaining = gm_parent.get_unmerged_index_entries(submodule.path)
                if remaining:
                    logger.warning(
                        f"Submodule {submodule.path} still has unmerged index entries after staging: {remaining}"
                    )
                else:
                    staged = gm_parent.get_staged_files()
                    if submodule.path not in staged:
                        logger.warning(
                            f"Submodule {submodule.path} did not appear in staged files after staging; staged now: {staged}"
                        )
                    else:
                        logger.debug(
                            f"Submodule {submodule.path} staged successfully in parent repo"
                        )
                # Additional check: ensure the path is no longer reported as a conflict
                still_conflicted = gm_parent.get_conflict_files()
                if submodule.path in still_conflicted:
                    logger.warning(
                        f"Submodule {submodule.path} still reported as conflicted after staging"
                    )
            except Exception:
                # Diagnostics only; do not fail the resolution if logging checks error out
                pass

            # Get commit messages for tracking from the submodule repo
            # The incoming/resolved hashes belong to the submodule, not the parent
            original_message = gm_sub.get_commit_subject(incoming_hash)
            resolved_message = gm_sub.get_commit_subject(resolved_hash)

            # Track the resolution
            self._track_resolved_commit(
                incoming_hash,
                resolved_hash,
                resolved_message or "<unknown>",
                submodule.path,
            )

            # Check message consistency
            if original_message and resolved_message and original_message != resolved_message:
                self.resolution_summary.message_consistency_issues.append(
                    f"{submodule.path}: Original message '{original_message}' != Resolved message '{resolved_message}'"
                )

            logger.info(f"Resolved submodule {submodule.path} to commit {resolved_hash[:8]}")
            return True

        except Exception as e:
            logger.error(f"Error resolving submodule conflict: {e}")
            return False

    def _find_resolved_submodule_hash(self, original_hash: str) -> Optional[str]:
        """Find the resolved hash for a submodule commit."""
        # Try to find the hash in any of our tracked repositories
        result = self.global_tracker.resolve_cross_repo_hash(original_hash)
        if result:
            repo_name, new_hash = result
            logger.debug(
                f"Found resolved hash {new_hash[:8]} for {original_hash[:8]} in {repo_name}"
            )
            return new_hash

        return None

    def _get_commit_message(self, commit_hash: str) -> Optional[str]:
        """Get the commit message for a given commit hash via GitManager."""
        return self.git_manager.get_commit_subject(commit_hash)

    def _track_resolved_commit(
        self,
        original_hash: str,
        resolved_hash: str,
        message: str,
        submodule_path: Path,
    ) -> None:
        """Track a resolved commit for later reporting."""

        resolved_commit = ResolvedCommit(
            original_hash=original_hash,
            resolved_hash=resolved_hash,
            message=message,
            submodule_path=submodule_path,
        )

        self.resolution_summary.resolved_commits.append(resolved_commit)

        # Keep the list sorted by submodule path for consistent display
        self.resolution_summary.resolved_commits.sort(
            key=lambda x: x.submodule_path
        )

    def get_resolution_summary(self) -> ResolutionSummary:
        """Get the complete resolution summary."""
        return self.resolution_summary

    def has_resolutions(self) -> bool:
        """Check if any automatic resolutions were made."""
        return bool(self.resolution_summary.resolved_commits)

    def clear_resolution_summary(self) -> None:
        """Clear the resolution summary (useful for new operations)."""
        self.resolution_summary = ResolutionSummary()

    def prompt_user_for_conflict_resolution(
        self,
        repo_info: RepoInfo,
        file_conflicts: List[str],
        unresolved_submodule_conflicts: List[str],
    ) -> bool:
        """
        Prompt user to resolve conflicts and verify before continuing.

        Returns:
            True once conflicts are verified as resolved and staged, False if user aborts
        """
        while True:
            proceed = self.conflict_prompt.prompt_for_conflict_resolution(
                repo_info, file_conflicts, unresolved_submodule_conflicts
            )
            if not proceed:
                return False

            is_resolved, messages = self.verify_conflicts_resolved(repo_info.path)
            if is_resolved:
                self.conflict_prompt.show_messages(
                    ["✅ Conflicts verified as resolved. Continuing rebase..."], style="bold green"
                )
                return True
            else:
                if messages:
                    self.conflict_prompt.show_messages(messages, style="bold red")
                else:
                    self.conflict_prompt.show_messages(
                        [
                            "❌ Conflicts still exist. Please resolve all conflicts and stage changes before continuing.",
                        ],
                        style="bold red",
                    )
                # Loop again to allow further resolution

    def verify_conflicts_resolved(self, repo_path: Path) -> Tuple[bool, List[str]]:
        """Verify that all conflicts are resolved and changes are staged.

        Returns:
            Tuple of (is_resolved, messages). If is_resolved is False, messages
            contains user-facing guidance strings suitable for CLI display.
        """
        try:
            if not self.git_manager:
                raise ConflictResolutionError("No GitManager attached to ConflictResolver")
            # Check for unmerged files via attached GitManager
            unresolved_files = self.git_manager.get_conflict_files()

            if unresolved_files:
                return False, [
                    f"❌ Still have unresolved conflicts in: {', '.join(unresolved_files)}"
                ]

            # Check that changes are staged via attached GitManager
            staged_files = self.git_manager.get_staged_files()

            if not staged_files:
                return False, [
                    "❌ No changes are staged. Please stage your resolved files with 'git add'"
                ]

            return True, []

        except Exception as e:
            logger.error(f"Error verifying conflict resolution: {e}")
            return False, [f"Error verifying conflict resolution: {e}"]

    # Backward-compatible alias; prefer verify_conflicts_resolved
    def _verify_conflicts_resolved(self, repo_path: Path) -> Tuple[bool, List[str]]:  # noqa: N802
        return self.verify_conflicts_resolved(repo_path)

    def stage_resolved_conflicts(self, repo_path: Path, resolved_files: List[str]) -> None:
        """Stage resolved conflict files using GitManager."""
        try:
            if not self.git_manager:
                raise ConflictResolutionError("No GitManager attached to ConflictResolver")
            self.git_manager.add_paths(resolved_files)
            logger.info(f"Staged {len(resolved_files)} resolved files")
        except Exception as e:
            logger.error(f"Error staging resolved files: {e}")
            raise ConflictResolutionError(f"Failed to stage resolved files: {e}")

    def has_unstaged_changes(self, repo_path: Path) -> bool:
        """Check if repository has unstaged changes via GitManager."""
        try:
            if not self.git_manager:
                raise ConflictResolutionError("No GitManager attached to ConflictResolver")
            return self.git_manager.has_unstaged_changes()
        except Exception:
            return False
