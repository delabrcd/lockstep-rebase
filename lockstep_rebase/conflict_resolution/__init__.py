"""
Conflict resolution modules for lockstep rebase operations.

This package contains specialized conflict resolution handlers for
different types of Git conflicts encountered during rebasing.
"""

from .submodule import SubmoduleConflictResolver
from .interactive import InteractiveConflictHandler
from .planned import PlannedSubmoduleResolver

__all__ = [
    'SubmoduleConflictResolver',
    'InteractiveConflictHandler',
    'PlannedSubmoduleResolver'
]
