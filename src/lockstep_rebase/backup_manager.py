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
    """Manage creation, listing, deletion, and restoration of backup branches."""

    def __init__(self) -> None:
        pass

    def make_backup_name(self, original_branch: str, session_id: Optional[str] = None) -> str:
        ts = session_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        # Keep branch hierarchy to encode original branch name
        return f"{BACKUP_PREFIX}/{original_branch}/{ts}"

    def create_backup_branch(self, repo_path: Path, original_branch: str, session_id: Optional[str] = None) -> str:
        """Create a backup branch pointing at the current tip of original_branch.

        Returns the created backup branch name.
        """
        repo_path = Path(repo_path)
        backup_name = self.make_backup_name(original_branch, session_id)
        try:
            # Create or update backup branch to point to original_branch ref
            gm = GitManager(repo_path)
            gm.create_or_update_branch(backup_name, original_branch)
            logger.info(f"Created backup branch {backup_name} from {original_branch} in {repo_path}")
            return backup_name
        except GitRepositoryError as e:
            logger.error(f"Failed to create backup for {repo_path.name}:{original_branch}: {e}")
            raise

    def list_backup_branches(self, repo_path: Path) -> List[str]:
        """List backup branches in the repository."""
        repo_path = Path(repo_path)
        try:
            gm = GitManager(repo_path)
            branches = gm.list_local_branches()
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

    def list_parsed_backups(
        self, repo_path: Path, original_branch: Optional[str] = None
    ) -> List[BackupEntry]:
        """Return structured backup entries for a repo, with optional exact original branch filter."""
        repo_path = Path(repo_path)
        entries: List[BackupEntry] = []
        for b in self.list_backup_branches(repo_path):
            parsed = self._parse_backup_branch(b)
            if not parsed:
                continue
            orig, sess = parsed
            if original_branch is not None and orig != original_branch:
                continue
            entries.append(
                BackupEntry(
                    repo_path=repo_path,
                    repo_name=repo_path.name,
                    backup_branch=b,
                    original_branch=orig,
                    session=sess,
                )
            )
        return entries

    def get_backups_for_original_branch(self, repo_path: Path, original_branch: str) -> List[str]:
        """Return backups that correspond to a given original branch (exact match)."""
        return [e.backup_branch for e in self.list_parsed_backups(repo_path, original_branch=original_branch)]

    def get_latest_backup_for_original_branch(self, repo_path: Path, original_branch: str) -> Optional[str]:
        """Find the most recent backup for an original branch based on session suffix (string-desc)."""
        entries = self.list_parsed_backups(repo_path, original_branch=original_branch)
        if not entries:
            return None
        entries.sort(key=lambda e: e.session, reverse=True)
        return entries[0].backup_branch

    def delete_backup_branch(self, repo_path: Path, backup_branch: str) -> None:
        repo_path = Path(repo_path)
        try:
            gm = GitManager(repo_path)
            gm.delete_branch(backup_branch)
            logger.info(f"Deleted backup branch {backup_branch} in {repo_path}")
        except GitRepositoryError as e:
            logger.error(f"Failed to delete backup branch {backup_branch}: {e}")
            raise

    def restore_branch_from_backup(self, repo_path: Path, original_branch: str, backup_branch: str) -> None:
        """Restore the original branch from the backup by hard-resetting it to backup commit."""
        repo_path = Path(repo_path)
        try:
            # Ensure backup exists
            gm = GitManager(repo_path)
            if not gm.branch_exists(backup_branch):
                raise GitRepositoryError(f"Backup branch does not exist: {backup_branch}")
            # Create or update the original branch to point at the backup ref
            gm.create_or_update_branch(original_branch, backup_branch)
            logger.info(f"Restored {original_branch} from {backup_branch} in {repo_path}")
        except GitRepositoryError as e:
            logger.error(f"Failed to restore {original_branch} from {backup_branch}: {e}")
            raise
