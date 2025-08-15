"""
Conflict resolution handling for Git rebase operations.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import ConflictResolutionError, RepoInfo, ResolvedCommit, ResolutionSummary
from .commit_tracker import GlobalCommitTracker
from .conflict_prompt_interface import ConflictPrompt, NoOpConflictPrompt


logger = logging.getLogger(__name__)


class ConflictResolver:
    """Handles merge conflict resolution during rebase operations."""

    def __init__(
        self, global_tracker: GlobalCommitTracker, conflict_prompt: ConflictPrompt = None
    ) -> None:
        """Initialize conflict resolver with global commit tracker."""
        self.global_tracker = global_tracker
        self.resolution_summary = ResolutionSummary()
        self.conflict_prompt = conflict_prompt or NoOpConflictPrompt()

    def analyze_conflicts(self, repo_path: Path) -> Dict[str, List[str]]:
        """
        Analyze conflicts in a repository.

        Returns:
            Dictionary with 'file_conflicts' and 'submodule_conflicts' keys
        """
        conflicts = {"file_conflicts": [], "submodule_conflicts": []}

        try:
            # Get conflicted files
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue

                status = line[:2]
                filepath = line[3:]

                # Check for merge conflicts (UU, AA, etc.)
                if "U" in status or "A" in status:
                    if self._is_submodule_path(repo_path, filepath):
                        conflicts["submodule_conflicts"].append(filepath)
                    else:
                        conflicts["file_conflicts"].append(filepath)

            logger.debug(
                f"Found {len(conflicts['file_conflicts'])} file conflicts and "
                f"{len(conflicts['submodule_conflicts'])} submodule conflicts"
            )

        except subprocess.CalledProcessError as e:
            logger.error(f"Error analyzing conflicts: {e}")
            raise ConflictResolutionError(f"Failed to analyze conflicts: {e}")

        return conflicts

    def _is_submodule_path(self, repo_path: Path, filepath: str) -> bool:
        """Check if a file path corresponds to a submodule."""
        try:
            # Check if .gitmodules exists and contains this path
            gitmodules_path = repo_path / ".gitmodules"
            if not gitmodules_path.exists():
                return False

            with open(gitmodules_path, "r") as f:
                content = f.read()
                return f"path = {filepath}" in content

        except Exception as e:
            logger.debug(f"Error checking submodule path: {e}")
            return False

    def auto_resolve_submodule_conflicts(
        self, repo_path: Path, submodule_conflicts: List[str]
    ) -> Tuple[List[str], List[str]]:
        """
        Attempt to automatically resolve submodule conflicts using commit mappings.

        Returns:
            Tuple of (resolved_conflicts, unresolved_conflicts)
        """
        resolved = []
        unresolved = []

        for submodule_path in submodule_conflicts:
            try:
                if self._resolve_submodule_conflict(repo_path, submodule_path):
                    resolved.append(submodule_path)
                    logger.info(f"Auto-resolved submodule conflict: {submodule_path}")
                else:
                    unresolved.append(submodule_path)
                    logger.warning(f"Could not auto-resolve submodule conflict: {submodule_path}")
            except Exception as e:
                logger.error(f"Error resolving submodule conflict {submodule_path}: {e}")
                unresolved.append(submodule_path)

        return resolved, unresolved

    def _resolve_submodule_conflict(self, repo_path: Path, submodule_path: str) -> bool:
        """
        Resolve a single submodule conflict by finding the correct commit hash.

        Returns:
            True if resolved successfully, False otherwise
        """
        try:
            # Get the conflicted submodule information
            result = subprocess.run(
                ["git", "ls-files", "-u", submodule_path],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            if not result.stdout.strip():
                return False

            # Parse the conflicted entries
            entries = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    mode_hash = parts[0].split()
                    if len(mode_hash) >= 2:
                        entries.append(
                            {"stage": mode_hash[2], "hash": mode_hash[1], "path": parts[1]}
                        )

            # Find the incoming commit hash (stage 3)
            incoming_hash = None
            for entry in entries:
                if entry["stage"] == "3":  # Theirs (incoming)
                    incoming_hash = entry["hash"]
                    break

            if not incoming_hash:
                logger.warning(f"Could not find incoming hash for submodule {submodule_path}")
                return False

            # Try to resolve using commit mappings
            resolved_hash = self._find_resolved_submodule_hash(incoming_hash)
            if not resolved_hash:
                logger.warning(f"Could not find resolved hash for {incoming_hash[:8]}")
                return False

            # Update the submodule to the resolved hash
            submodule_full_path = repo_path / submodule_path
            subprocess.run(
                ["git", "checkout", resolved_hash],
                cwd=submodule_full_path,
                check=True,
                capture_output=True,
            )

            # Stage the resolved submodule
            subprocess.run(
                ["git", "add", submodule_path], cwd=repo_path, check=True, capture_output=True
            )

            # Get commit messages for tracking
            original_message = self._get_commit_message(submodule_full_path, incoming_hash)
            resolved_message = self._get_commit_message(submodule_full_path, resolved_hash)

            # Track the resolution
            repo_name = repo_path.name
            self._track_resolved_commit(
                repo_name,
                incoming_hash,
                resolved_hash,
                resolved_message or "<unknown>",
                submodule_path,
            )

            # Check message consistency
            if original_message and resolved_message and original_message != resolved_message:
                self.resolution_summary.message_consistency_issues.append(
                    f"{repo_name}/{submodule_path}: Original message '{original_message}' != Resolved message '{resolved_message}'"
                )

            logger.info(f"Resolved submodule {submodule_path} to commit {resolved_hash[:8]}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Git command failed while resolving submodule conflict: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error resolving submodule conflict: {e}")
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

    def _get_commit_message(self, repo_path: Path, commit_hash: str) -> Optional[str]:
        """Get the commit message for a given commit hash."""
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%s", commit_hash],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.debug(f"Could not get commit message for {commit_hash[:8]}: {e}")
            return None

    def _track_resolved_commit(
        self,
        repo_name: str,
        original_hash: str,
        resolved_hash: str,
        message: str,
        submodule_path: str,
    ) -> None:
        """Track a resolved commit for later reporting."""
        if repo_name not in self.resolution_summary.resolved_commits_by_repo:
            self.resolution_summary.resolved_commits_by_repo[repo_name] = []

        resolved_commit = ResolvedCommit(
            original_hash=original_hash,
            resolved_hash=resolved_hash,
            message=message,
            submodule_path=submodule_path,
        )

        self.resolution_summary.resolved_commits_by_repo[repo_name].append(resolved_commit)

        # Keep the list sorted by submodule path for consistent display
        self.resolution_summary.resolved_commits_by_repo[repo_name].sort(
            key=lambda x: x.submodule_path
        )

    def get_resolution_summary(self) -> ResolutionSummary:
        """Get the complete resolution summary."""
        return self.resolution_summary

    def has_resolutions(self) -> bool:
        """Check if any automatic resolutions were made."""
        return bool(self.resolution_summary.resolved_commits_by_repo)

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
            # Check for unmerged files
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            unresolved_files = [f.strip() for f in result.stdout.split("\n") if f.strip()]

            if unresolved_files:
                return False, [
                    f"❌ Still have unresolved conflicts in: {', '.join(unresolved_files)}"
                ]

            # Check that changes are staged
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            staged_files = [f.strip() for f in result.stdout.split("\n") if f.strip()]

            if not staged_files:
                return False, [
                    "❌ No changes are staged. Please stage your resolved files with 'git add'"
                ]

            return True, []

        except subprocess.CalledProcessError as e:
            logger.error(f"Error verifying conflict resolution: {e}")
            return False, [f"Error verifying conflict resolution: {e}"]

    # Backward-compatible alias; prefer verify_conflicts_resolved
    def _verify_conflicts_resolved(self, repo_path: Path) -> Tuple[bool, List[str]]:  # noqa: N802
        return self.verify_conflicts_resolved(repo_path)

    def stage_resolved_conflicts(self, repo_path: Path, resolved_files: List[str]) -> None:
        """Stage resolved conflict files."""
        try:
            for file_path in resolved_files:
                subprocess.run(
                    ["git", "add", file_path], cwd=repo_path, check=True, capture_output=True
                )

            logger.info(f"Staged {len(resolved_files)} resolved files")

        except subprocess.CalledProcessError as e:
            logger.error(f"Error staging resolved files: {e}")
            raise ConflictResolutionError(f"Failed to stage resolved files: {e}")

    def has_unstaged_changes(self, repo_path: Path) -> bool:
        """Check if repository has unstaged changes."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )

            return bool(result.stdout.strip())

        except subprocess.CalledProcessError:
            return False
