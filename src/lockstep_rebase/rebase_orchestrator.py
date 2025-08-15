"""
Main rebase orchestration logic for multi-repository operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

from .models import RebaseOperation, RebaseState, RepoInfo, RebaseError, HierarchyEntry, BackupEntry
from .git_manager import GitManager
from .submodule_mapper import SubmoduleMapper
from .commit_tracker import GlobalCommitTracker
from .conflict_resolver import ConflictResolver
from .prompt_interface import UserPrompt, NoOpPrompt
from .conflict_prompt_interface import ConflictPrompt
from .backup_manager import BackupManager, BACKUP_PREFIX


logger = logging.getLogger(__name__)


class RebaseOrchestrator:
    """Orchestrates rebase operations across multiple repositories with submodules."""

    def __init__(
        self, root_path: Optional[Path] = None, conflict_prompt: ConflictPrompt = None
    ) -> None:
        """Initialize the rebase orchestrator."""
        self.root_path = root_path or Path.cwd()
        self.git_manager = GitManager(self.root_path)
        self.submodule_mapper = SubmoduleMapper(self.root_path)
        self.global_tracker = GlobalCommitTracker()
        self.conflict_resolver = ConflictResolver(self.global_tracker, conflict_prompt)
        self.backup_manager = BackupManager()

        # Discover repository hierarchy
        self.root_repo_info = self.submodule_mapper.discover_repository_hierarchy()
        logger.info(f"Initialized rebase orchestrator for {self.root_repo_info.name}")

    def plan_rebase(
        self,
        source_branch: str,
        target_branch: str,
        prompt: UserPrompt = None,
        *,
        include: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
        branch_map: Optional[dict[str, tuple[str, Optional[str]]]] = None,
    ) -> RebaseOperation:
        """
        Plan a rebase operation across all repositories.

        Args:
            source_branch: The branch to rebase (e.g., 'feature/my-feature')
            target_branch: The branch to rebase onto (e.g., 'main')

        Returns:
            RebaseOperation with planned states for all repositories
        """
        logger.info(f"Planning rebase from {source_branch} to {target_branch}")

        if prompt is None:
            prompt = NoOpPrompt()

        # Create rebase operation (global defaults)
        operation = RebaseOperation(
            root_repo=self.root_repo_info, source_branch=source_branch, target_branch=target_branch
        )

        # Compute repositories in rebase order (deepest first)
        full_order = self.submodule_mapper.get_rebase_order(self.root_repo_info)

        # Filter include/exclude
        def _matches(repo: RepoInfo, token: str) -> bool:
            rel = str(repo.path.relative_to(self.root_path)) if self.root_path in repo.path.parents or repo.path == self.root_path else str(repo.path)
            return token == repo.name or token == rel or token == str(repo.path)

        if include:
            selected = [r for r in full_order if any(_matches(r, t) for t in include)]
            if not selected:
                raise RebaseError("No repositories matched --include filters")
        else:
            selected = list(full_order)

        if exclude:
            selected = [r for r in selected if not any(_matches(r, t) for t in exclude)]
            if not selected:
                raise RebaseError("All repositories were excluded by --exclude filters")

        # Per-repo branch resolve using branch_map overrides
        def _resolve_branches(repo: RepoInfo) -> tuple[str, str]:
            if not branch_map:
                return source_branch, target_branch
            # Priority: name, relative path, absolute path
            rel = str(repo.path.relative_to(self.root_path)) if self.root_path in repo.path.parents or repo.path == self.root_path else str(repo.path)
            keys = [repo.name, rel, str(repo.path)]
            for k in keys:
                if k in branch_map:
                    src, tgt = branch_map[k]
                    return src or source_branch, (tgt if tgt is not None else target_branch)
            return source_branch, target_branch

        # Validate branches per repo and build states
        missing_src: list[str] = []
        missing_tgt: list[str] = []

        for repo_info in selected:
            gm = GitManager(repo_info.path)
            src_br, tgt_br = _resolve_branches(repo_info)

            if not gm.branch_exists(src_br, repo_info.path):
                missing_src.append(f"{repo_info.name} ({src_br})")
            if not gm.branch_exists(tgt_br, repo_info.path):
                missing_tgt.append(f"{repo_info.name} ({tgt_br})")

        if missing_src:
            raise RebaseError(
                "Source branch missing in: " + ", ".join(missing_src)
            )
        if missing_tgt:
            raise RebaseError(
                "Target branch missing in: " + ", ".join(missing_tgt)
            )

        # Build rebase states
        for repo_info in selected:
            gm = GitManager(repo_info.path)
            src_br, tgt_br = _resolve_branches(repo_info)

            original_commits = gm.get_commits_between(tgt_br, src_br, repo_info.path)

            state = RebaseState(
                repo=repo_info,
                source_branch=src_br,
                target_branch=tgt_br,
                original_commits=original_commits,
            )

            operation.repo_states.append(state)
            logger.debug(
                f"Planned rebase for {repo_info.name}: {len(original_commits)} commits ({src_br} -> {tgt_br})"
            )

        logger.info(f"Planned rebase operation for {len(operation.repo_states)} repositories")
        return operation

    def execute_rebase(self, operation: RebaseOperation) -> bool:
        """
        Execute the planned rebase operation.

        Returns:
            True if rebase completed successfully, False if aborted
        """
        logger.info("Starting rebase execution")

        try:
            # Ensure backups exist before any mutations if not already prepared
            if not operation.backup_session_id:
                self.create_backups(operation)

            for state in operation.repo_states:
                if not self._execute_repository_rebase(state, operation):
                    logger.error(f"Rebase failed for {state.repo.name}")
                    return False

            logger.info("✅ Rebase operation completed successfully!")
            return True

        except Exception as e:
            logger.error(f"Rebase execution failed: {e}")
            self._cleanup_failed_rebase(operation)
            raise RebaseError(f"Rebase execution failed: {e}")

    def create_backups(self, operation: RebaseOperation) -> None:
        """Create backup branches for all repositories' source branches.

        This should be called after planning and before execution. Idempotent if called twice in the same session.
        """
        # Initialize session id if not present
        if not operation.backup_session_id:
            operation.backup_session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        created = 0
        for state in operation.repo_states:
            repo_path = state.repo.path
            key = str(repo_path)
            if key in operation.backup_branches:
                continue
            try:
                backup_name = self.backup_manager.create_backup_branch(
                    repo_path, state.source_branch, session_id=operation.backup_session_id
                )
                operation.backup_branches[key] = backup_name
                created += 1
            except Exception as e:
                logger.error(
                    f"Failed to create backup for {state.repo.name} ({state.source_branch}): {e}"
                )
                raise RebaseError(
                    f"Failed to create backup branch in {state.repo.name}: {e}"
                )
        logger.info(f"Created {created} backup branches for session {operation.backup_session_id}")

    def delete_backups(self, operation: RebaseOperation) -> int:
        """Delete all backup branches recorded for this operation.

        Returns number of deleted backups.
        """
        deleted = 0
        for path_str, backup_name in list(operation.backup_branches.items()):
            try:
                self.backup_manager.delete_backup_branch(Path(path_str), backup_name)
                deleted += 1
                del operation.backup_branches[path_str]
            except Exception as e:
                logger.error(f"Failed to delete backup {backup_name} in {path_str}: {e}")
        return deleted

    def list_backups_in_repo(self, repo_path: Optional[Path] = None) -> List[str]:
        """List backup branches in the specified or root repository."""
        target = repo_path or self.root_path
        return self.backup_manager.list_backup_branches(target)

    def list_parsed_backups_in_repo(
        self, repo_path: Optional[Path] = None, original_branch: Optional[str] = None
    ) -> List[BackupEntry]:
        """List structured backup entries in the specified or root repository."""
        target = repo_path or self.root_path
        return self.backup_manager.list_parsed_backups(target, original_branch=original_branch)

    def list_backups_across_hierarchy(self, original_branch: Optional[str] = None) -> List[BackupEntry]:
        """Aggregate structured backup entries across the repository hierarchy."""
        entries: List[BackupEntry] = []
        for repo_info in self._get_all_repositories(self.root_repo_info):
            try:
                entries.extend(
                    self.backup_manager.list_parsed_backups(
                        repo_info.path, original_branch=original_branch
                    )
                )
            except Exception:
                # Ignore repos that error on listing
                continue
        return entries

    def delete_backup_in_repo(self, backup_branch: str, repo_path: Optional[Path] = None) -> bool:
        """Delete a specific backup branch in the given repository."""
        target = repo_path or self.root_path
        try:
            self.backup_manager.delete_backup_branch(target, backup_branch)
            return True
        except Exception:
            return False

    def restore_original_branch_in_repo(
        self,
        original_branch: str,
        repo_path: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """Restore original branch from a backup in the given repo.

        If session_id is provided, uses that exact backup name. Otherwise picks the latest backup.

        Returns the backup branch name used on success, or None if no suitable backup found.
        """
        target = repo_path or self.root_path
        backup_name: Optional[str] = None
        if session_id:
            candidate = f"{BACKUP_PREFIX}/{original_branch}/{session_id}"
            backups = self.backup_manager.list_backup_branches(target)
            if candidate in backups:
                backup_name = candidate
        else:
            backup_name = self.backup_manager.get_latest_backup_for_original_branch(
                target, original_branch
            )

        if not backup_name:
            return None

        self.backup_manager.restore_branch_from_backup(target, original_branch, backup_name)
        return backup_name

    def restore_original_branches_across_hierarchy(
        self, original_branch: str, session_id: Optional[str] = None
    ) -> int:
        """Restore the original branch from backups across all repositories in the hierarchy.

        Returns number of repositories restored.
        """
        restored = 0
        for repo_info in self._get_all_repositories(self.root_repo_info):
            used = self.restore_original_branch_in_repo(
                original_branch, repo_info.path, session_id=session_id
            )
            if used:
                restored += 1
        return restored

    def _execute_repository_rebase(self, state: RebaseState, operation: RebaseOperation) -> bool:
        """Execute rebase for a single repository."""
        logger.info(f"🔄 Rebasing {state.repo.name} ({state.repo.relative_path})")

        git_manager = GitManager(state.repo.path)
        repo_tracker = self.global_tracker.get_tracker(state.repo.name)

        try:
            # Checkout source branch
            git_manager.checkout_branch(state.source_branch, state.repo.path)

            # Start rebase
            success, conflict_files = git_manager.start_rebase(state.target_branch, state.repo.path)

            if success:
                # Rebase completed without conflicts
                return self._handle_successful_rebase(state, git_manager, repo_tracker, operation)
            else:
                # Handle conflicts
                return self._handle_rebase_conflicts(
                    state, git_manager, repo_tracker, operation, conflict_files
                )

        except Exception as e:
            logger.error(f"Error during rebase of {state.repo.name}: {e}")
            return False

    def _handle_successful_rebase(
        self, state: RebaseState, git_manager: GitManager, repo_tracker, operation: RebaseOperation
    ) -> bool:
        """Handle a rebase that completed without conflicts."""
        try:
            # Get updated commits
            new_commits = git_manager.get_updated_commits(state.original_commits, state.repo.path)

            # Map old commits to new commits
            commit_mappings = repo_tracker.map_commits(state.original_commits, new_commits)

            # Update state
            state.new_commits = new_commits
            state.commit_mapping = commit_mappings
            state.is_completed = True

            # Add to global mappings
            for old_hash, new_hash in commit_mappings.items():
                operation.add_commit_mapping(old_hash, new_hash)

            logger.info(f"✅ Successfully rebased {state.repo.name}")
            return True

        except Exception as e:
            logger.error(f"Error handling successful rebase: {e}")
            return False

    def _handle_rebase_conflicts(
        self,
        state: RebaseState,
        git_manager: GitManager,
        repo_tracker,
        operation: RebaseOperation,
        initial_conflict_files: List[str],
    ) -> bool:
        """Handle rebase conflicts through resolution loop."""
        state.has_conflicts = True

        while True:
            # Analyze conflicts
            conflicts = self.conflict_resolver.analyze_conflicts(state.repo.path)

            if not conflicts["file_conflicts"] and not conflicts["submodule_conflicts"]:
                # No more conflicts, try to continue
                success, new_conflicts = git_manager.continue_rebase(state.repo.path)

                if success:
                    # Rebase completed
                    return self._handle_successful_rebase(
                        state, git_manager, repo_tracker, operation
                    )
                elif new_conflicts:
                    # More conflicts appeared
                    continue
                else:
                    # Other error
                    logger.error(f"Failed to continue rebase for {state.repo.name}")
                    return False

            # Try to auto-resolve submodule conflicts
            resolved_submodules, unresolved_submodules = [], []
            if conflicts["submodule_conflicts"]:
                resolved_submodules, unresolved_submodules = (
                    self.conflict_resolver.auto_resolve_submodule_conflicts(
                        state.repo.path, conflicts["submodule_conflicts"]
                    )
                )

            # Check if we still have unresolved conflicts
            remaining_conflicts = conflicts["file_conflicts"] + unresolved_submodules

            if remaining_conflicts:
                # Prompt user for manual resolution
                if not self.conflict_resolver.prompt_user_for_conflict_resolution(
                    state.repo, conflicts["file_conflicts"], unresolved_submodules
                ):
                    # User chose to abort
                    logger.info("User aborted rebase operation")
                    return False

            # Continue the loop to check for more conflicts

    def _cleanup_failed_rebase(self, operation: RebaseOperation) -> None:
        """Clean up after a failed rebase operation."""
        logger.info("Cleaning up failed rebase operation")

        for state in operation.repo_states:
            try:
                git_manager = GitManager(state.repo.path)
                if git_manager.is_rebase_in_progress(state.repo.path):
                    git_manager.abort_rebase(state.repo.path)
                    logger.info(f"Aborted rebase for {state.repo.name}")
            except Exception as e:
                logger.error(f"Error cleaning up {state.repo.name}: {e}")

    def get_repository_status(self) -> Dict[str, Dict[str, str]]:
        """Get status information for all repositories."""
        status = {}

        all_repos = self._get_all_repositories(self.root_repo_info)

        for repo_info in all_repos:
            try:
                git_manager = GitManager(repo_info.path)
                current_branch = git_manager.get_current_branch(repo_info.path)
                is_rebasing = git_manager.is_rebase_in_progress(repo_info.path)

                status[repo_info.name] = {
                    "path": str(repo_info.relative_path),
                    "current_branch": current_branch,
                    "is_rebasing": str(is_rebasing),
                    "is_submodule": str(repo_info.is_submodule),
                    "depth": str(repo_info.depth),
                }
            except Exception as e:
                status[repo_info.name] = {"path": str(repo_info.relative_path), "error": str(e)}

        return status

    def _get_all_repositories(self, root_info: RepoInfo) -> List[RepoInfo]:
        """Get a flat list of all repositories."""
        all_repos = [root_info]
        for submodule in root_info.submodules:
            all_repos.extend(self._get_all_repositories(submodule))
        return all_repos

    def get_repo_heirarchy(self) -> List[str]:
        """Return the discovered repository hierarchy as lines for CLI display."""
        return self.submodule_mapper.get_hierarchy_lines(self.root_repo_info)

    def print_repository_hierarchy(self) -> List[str]:
        """Backward-compatible wrapper to satisfy older callers/tests."""
        return self.get_repo_heirarchy()

    def get_hierarchy_entries(self) -> List[HierarchyEntry]:
        """Return structured hierarchy entries for UI formatting."""
        return self.submodule_mapper.get_hierarchy_entries(self.root_repo_info)

    def validate_repository_state(self, prompt: UserPrompt = None) -> List[str]:
        """
        Validate that all repositories are in a clean state for rebase.

        Args:
            prompt: Optional prompt interface for user interactions

        Returns:
            List of validation errors (empty if all good)
        """
        if prompt is None:
            prompt = NoOpPrompt()

        errors = []
        all_repos = self._get_all_repositories(self.root_repo_info)

        for repo_info in all_repos:
            try:
                git_manager = GitManager(repo_info.path)

                # Check for ongoing rebase
                if git_manager.is_rebase_in_progress(repo_info.path):
                    errors.append(f"{repo_info.name}: Rebase already in progress")

                # Check for unstaged changes
                if self.conflict_resolver.has_unstaged_changes(repo_info.path):
                    errors.append(f"{repo_info.name}: Has unstaged changes")

            except Exception as e:
                errors.append(f"{repo_info.name}: Error validating state - {e}")

        return errors
