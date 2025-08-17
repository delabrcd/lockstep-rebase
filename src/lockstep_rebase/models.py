"""
Data models for the Git submodule rebase tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, TYPE_CHECKING

if TYPE_CHECKING:
    # For type checkers only; avoids runtime circular import
    from .git_manager import GitManager
    from .backup_manager import BackupManager
    from .conflict_resolver import ConflictResolver


@dataclass
class CommitInfo:
    """Information about a Git commit."""

    hash: str
    message: str
    author: str
    author_email: str
    date: str
    parents: List[str] = field(default_factory=list)


@dataclass
class RepoInfo:
    """Information about a Git repository."""

    path: Path
    name: str
    is_submodule: bool = False
    parent_repo: Optional[RepoInfo] = None
    submodules: List[RepoInfo] = field(default_factory=list)
    depth: int = 0
    git_manager: Optional["GitManager"] = None
    backup_manager: Optional["BackupManager"] = None
    conflict_resolver: Optional["ConflictResolver"] = None

    def __post_init__(self) -> None:
        """Ensure path is absolute."""
        self.path = Path(self.path).resolve()

    @property
    def relative_path(self) -> str:
        """Get relative path from current working directory."""
        try:
            return str(self.path.relative_to(Path.cwd()))
        except ValueError:
            return str(self.path)

    def get_submodule(self, name: str) -> Optional[RepoInfo]:
        for submodule in self.submodules:
            if submodule.name == name:
                return submodule
        return None


@dataclass
class RebaseState:
    """State tracking for a rebase operation."""

    repo: RepoInfo
    source_branch: str
    target_branch: str
    original_commits: List[CommitInfo] = field(default_factory=list)
    new_commits: List[CommitInfo] = field(default_factory=list)
    commit_mapping: Dict[str, str] = field(default_factory=dict)  # old_hash -> new_hash
    is_completed: bool = False
    has_conflicts: bool = False
    conflict_files: Set[str] = field(default_factory=set)


@dataclass
class RebaseOperation:
    """Complete rebase operation across multiple repositories."""

    root_repo: RepoInfo
    source_branch: str
    target_branch: str
    repo_states: List[RebaseState] = field(default_factory=list)
    # Backup metadata
    backup_session_id: Optional[str] = None
    # Map of repo path (str) -> backup branch name
    backup_branches: Dict[str, str] = field(default_factory=dict)

    def get_state_for_repo(self, repo_path: Path) -> Optional[RebaseState]:
        """Get rebase state for a specific repository."""
        for state in self.repo_states:
            if state.repo.path == repo_path:
                return state
        return None


@dataclass
class SubmoduleConflict:
    main_git_manager: GitManager
    subby_git_manager: GitManager
    main_commit: CommitInfo


class RebaseError(Exception):
    """Base exception for rebase operations."""

    pass


class GitRepositoryError(RebaseError):
    """Exception raised for Git repository related errors."""

    pass


class SubmoduleError(RebaseError):
    """Exception raised for submodule related errors."""

    pass


class ConflictResolutionError(RebaseError):
    """Exception raised during conflict resolution."""

    pass


@dataclass
class ResolvedCommit:
    """Information about a resolved commit."""

    original_hash: str
    resolved_hash: str
    message: str
    submodule_path: Path


@dataclass
class ResolutionSummary:
    """Summary of all conflict resolutions."""

    resolved_commits: List[ResolvedCommit] = field(default_factory=list)
    message_consistency_issues: List[str] = field(default_factory=list)


@dataclass
class HierarchyEntry:
    """Structured representation of an item in the repository hierarchy.

    Returned by core logic for UI formatting (e.g., Rich tables) without embedding
    presentation concerns in business logic.
    """

    name: str
    path: Path
    depth: int
    is_submodule: bool
    parent_name: Optional[str] = None


@dataclass
class BackupEntry:
    """Structured representation of a backup branch in a repository."""

    repo_path: Path
    repo_name: str
    backup_branch: str
    original_branch: str
    session: str
