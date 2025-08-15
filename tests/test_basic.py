"""
Basic tests for the Git submodule rebase tool.
"""

import pytest
from windsurf_project import __version__
from windsurf_project import (
    RebaseOrchestrator, RebaseOperation, RebaseState, RepoInfo, CommitInfo,
    GitManager, SubmoduleMapper, CommitTracker, GlobalCommitTracker, ConflictResolver
)


def test_version():
    """Test that version is defined."""
    assert __version__ == "0.1.0"


def test_import():
    """Test that the package can be imported."""
    import windsurf_project
    assert windsurf_project is not None


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
    import windsurf_project
    
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
        assert hasattr(windsurf_project, export), f"Missing export: {export}"
