"""
Backup branch management for repositories and submodules.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from .git_manager import GitManager
from .models import GitRepositoryError, BackupEntry

logger = logging.getLogger(__name__)


BACKUP_PREFIX = "lockstep/backup"


class BackupManager:
    """Manage creation, listing, deletion, and restoration of backup branches for a single repo."""

    def __init__(self, git_manager: GitManager) -> None:
        self.gm = git_manager
        # Derive repo metadata from GitPython Repo
        self.repo_path = Path(self.gm.repo.working_dir).resolve()
        self.repo_name = self.repo_path.name

    def make_backup_name(self, original_branch: str, session_id: Optional[str] = None) -> str:
        ts = session_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        # Keep branch hierarchy to encode original branch name
        return f"{BACKUP_PREFIX}/{original_branch}/{ts}"

    def create_backup_branch(self, original_branch: str, session_id: Optional[str] = None) -> str:
        """Create a backup branch pointing at the current tip of original_branch.

        Returns the created backup branch name.
        """
        backup_name = self.make_backup_name(original_branch, session_id)
        try:
            # Create or update backup branch to point to original_branch ref
            self.gm.create_or_update_branch(backup_name, original_branch)
            logger.info(f"Created backup branch {backup_name} from {original_branch} in {self.repo_path}")
            return backup_name
        except GitRepositoryError as e:
            logger.error(f"Failed to create backup for {self.repo_name}:{original_branch}: {e}")
            raise

    def list_backup_branches(self) -> List[str]:
        """List backup branches in the repository."""
        try:
            branches = self.gm.list_local_branches()
            return [b for b in branches if b.startswith(f"{BACKUP_PREFIX}/")]
        except GitRepositoryError:
            return []

    def _parse_backup_branch(self, backup_branch: str) -> Optional[Tuple[str, str]]:
        """Parse a backup branch name into (original_branch, session) or None if invalid."""
        parts = backup_branch.split("/")
        prefix_parts = BACKUP_PREFIX.split("/")
        if len(parts) < len(prefix_parts) + 2:
            return None
        if parts[: len(prefix_parts)] != prefix_parts:
            return None
        original_parts = parts[len(prefix_parts) : -1]
        session = parts[-1]
        original_branch = "/".join(original_parts)
        if not original_branch or not session:
            return None
        return original_branch, session

    def list_parsed_backups(self, original_branch: Optional[str] = None) -> List[BackupEntry]:
        """Return structured backup entries for a repo, with optional exact original branch filter."""
        entries: List[BackupEntry] = []
        for b in self.list_backup_branches():
            parsed = self._parse_backup_branch(b)
            if not parsed:
                continue
            orig, sess = parsed
            if original_branch is not None and orig != original_branch:
                continue
            entries.append(
                BackupEntry(
                    repo_path=self.repo_path,
                    repo_name=self.repo_name,
                    backup_branch=b,
                    original_branch=orig,
                    session=sess,
                )
            )
        return entries

    def get_backups_for_original_branch(self, original_branch: str) -> List[str]:
        """Return backups that correspond to a given original branch (exact match)."""
        return [e.backup_branch for e in self.list_parsed_backups(original_branch=original_branch)]

    def get_latest_backup_for_original_branch(self, original_branch: str) -> Optional[str]:
        """Find the most recent backup for an original branch based on session suffix (string-desc)."""
        entries = self.list_parsed_backups(original_branch=original_branch)
        if not entries:
            return None
        entries.sort(key=lambda e: e.session, reverse=True)
        return entries[0].backup_branch

    def delete_backup_branch(self, backup_branch: str) -> None:
        try:
            self.gm.delete_branch(backup_branch)
            logger.info(f"Deleted backup branch {backup_branch} in {self.repo_path}")
        except GitRepositoryError as e:
            logger.error(f"Failed to delete backup branch {backup_branch}: {e}")
            raise

    def restore_branch_from_backup(self, original_branch: str, backup_branch: str) -> None:
        """Restore the original branch from the backup by hard-resetting it to backup commit."""
        try:
            # If a rebase is in progress, abort it before forcing branch updates
            if self.gm.is_rebase_in_progress():
                logger.warning(
                    f"Rebase in progress in {self.repo_path}. Aborting rebase before restoring backup."
                )
                self.gm.abort_rebase()

            # Ensure backup exists
            if not self.gm.branch_exists(backup_branch):
                raise GitRepositoryError(f"Backup branch does not exist: {backup_branch}")
            # Create or update the original branch to point at the backup ref
            self.gm.create_or_update_branch(original_branch, backup_branch)
            logger.info(f"Restored {original_branch} from {backup_branch} in {self.repo_path}")
        except GitRepositoryError as e:
            logger.error(f"Failed to restore {original_branch} from {backup_branch}: {e}")
            raise
