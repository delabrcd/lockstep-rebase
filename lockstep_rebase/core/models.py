"""
Data models for lockstep rebase operations.

This module contains the core data classes used throughout the
lockstep rebase system.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import time


@dataclass
class RepoInfo:
    """Information about a repository and its configuration."""
    name: str
    path: str
    branch: Optional[str] = None
    base: Optional[str] = None
    submodules: List['RepoInfo'] = field(default_factory=list)

    def __post_init__(self):
        """Ensure submodules is always a list."""
        if self.submodules is None:
            self.submodules = []


@dataclass
class RebaseResult:
    """Result of a rebase operation."""
    repo_path: str
    success: bool
    commit_mapping: Dict[str, str] = field(default_factory=dict)
    backup_branch: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        """Ensure commit_mapping is always a dict."""
        if self.commit_mapping is None:
            self.commit_mapping = {}


@dataclass
class RebaseState:
    """Persistent state for rebase operations."""
    session_id: str
    timestamp: str
    root_path: str
    completed_rebases: Dict[str, Dict[str, str]] = field(default_factory=dict)
    active_rebases: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Ensure fields are properly initialized."""
        if self.completed_rebases is None:
            self.completed_rebases = {}
        if self.active_rebases is None:
            self.active_rebases = []

    @classmethod
    def create_new(cls, root_path: str) -> 'RebaseState':
        """Create a new rebase state."""
        return cls(
            session_id=f"rebase_{int(time.time())}",
            timestamp=time.strftime('%Y-%m-%d %H:%M:%S'),
            root_path=root_path
        )
