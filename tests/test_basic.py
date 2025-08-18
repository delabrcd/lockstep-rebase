"""
Basic tests for the Git submodule rebase tool.
"""

import pytest
from lockstep_rebase import __version__
from lockstep_rebase import (
    RebaseOrchestrator, RebaseOperation, RebaseState, RepoInfo, CommitInfo,
    GitManager, SubmoduleMapper, CommitTracker, GlobalCommitTracker, ConflictResolver
)


def test_version_format():
    assert isinstance(__version__, str)
    assert __version__ != ""

def test_version_matches_semver():
    import re
    semver_pattern = r"^\d+\.\d+\.\d+$"
    assert re.match(semver_pattern, __version__)

def test_import():
    """Test that the package can be imported."""
    import lockstep_rebase
    assert lockstep_rebase is not None


def test_all_imports():
    """Test that all main classes can be imported."""
    # Test that all classes are importable
    assert RebaseOrchestrator is not None
    assert RebaseOperation is not None
    assert RebaseState is not None
    assert RepoInfo is not None
    assert CommitInfo is not None
    assert GitManager is not None
    assert SubmoduleMapper is not None
    assert CommitTracker is not None
    assert GlobalCommitTracker is not None
    assert ConflictResolver is not None


def test_package_structure():
    """Test package structure and __all__ exports."""
    import lockstep_rebase
    
    # Check that __all__ contains expected exports
    expected_exports = [
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
    
    for export in expected_exports:
        assert hasattr(lockstep_rebase, export), f"Missing export: {export}"
