"""
Core functionality for lockstep rebase operations.

This module contains the main classes and utilities for managing
nested repository rebasing operations.
"""

from .manager import NestedRebaseManager
from .models import RepoInfo, RebaseResult, RebaseState
from .git_utils import GitUtils
from .planner import RebasePlanner, RebasePlan, CommitPlan

__all__ = [
    "NestedRebaseManager",
    "RepoInfo",
    "RebaseResult", 
    "RebaseState",
    "GitUtils",
    "RebasePlanner",
    "RebasePlan",
    "CommitPlan"
]
