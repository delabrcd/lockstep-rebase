"""
Backup management for lockstep rebase operations.

This package contains functionality for managing backup branches
created during rebase operations.
"""

from .manager import BackupManager

__all__ = [
    "BackupManager",
]
