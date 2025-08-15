"""
Git Submodule Rebase Tool - Professional rebase operations for tightly coupled submodules.

This package provides tools for rebasing Git repositories that contain multiple levels
of tightly coupled submodules, with automatic conflict resolution and commit tracking.
"""

__version__ = "0.1.0"

from .rebase_orchestrator import RebaseOrchestrator
from .models import RebaseOperation, RebaseState, RepoInfo, CommitInfo
from .git_manager import GitManager
from .submodule_mapper import SubmoduleMapper
from .commit_tracker import CommitTracker, GlobalCommitTracker
from .conflict_resolver import ConflictResolver

__all__ = [
    "RebaseOrchestrator",
    "RebaseOperation", 
    "RebaseState",
    "RepoInfo",
    "CommitInfo",
    "GitManager",
    "SubmoduleMapper", 
    "CommitTracker",
    "GlobalCommitTracker",
    "ConflictResolver",
]
