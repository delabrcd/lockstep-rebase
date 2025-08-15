"""
Data models for the Git submodule rebase tool.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


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
    global_commit_mapping: Dict[str, str] = field(default_factory=dict)
    
    def get_state_for_repo(self, repo_path: Path) -> Optional[RebaseState]:
        """Get rebase state for a specific repository."""
        for state in self.repo_states:
            if state.repo.path == repo_path:
                return state
        return None
    
    def add_commit_mapping(self, old_hash: str, new_hash: str) -> None:
        """Add a commit hash mapping to the global mapping."""
        self.global_commit_mapping[old_hash] = new_hash


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
    submodule_path: str
    

@dataclass
class ResolutionSummary:
    """Summary of all conflict resolutions."""
    resolved_commits_by_repo: Dict[str, List[ResolvedCommit]] = field(default_factory=dict)
    message_consistency_issues: List[str] = field(default_factory=list)
