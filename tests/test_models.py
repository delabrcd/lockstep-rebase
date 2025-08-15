"""
Tests for data models.
"""

import pytest
from pathlib import Path
from lockstep_rebase.models import (
    CommitInfo, RepoInfo, RebaseState, RebaseOperation,
    RebaseError, GitRepositoryError, SubmoduleError, ConflictResolutionError
)


class TestCommitInfo:
    """Test CommitInfo model."""
    
    def test_commit_info_creation(self):
        """Test creating a CommitInfo instance."""
        commit = CommitInfo(
            hash="abc123def456",
            message="Test commit",
            author="Test Author",
            author_email="test@example.com",
            date="2023-01-01T12:00:00"
        )
        
        assert commit.hash == "abc123def456"
        assert commit.message == "Test commit"
        assert commit.author == "Test Author"
        assert commit.author_email == "test@example.com"
        assert commit.date == "2023-01-01T12:00:00"
        assert commit.parents == []
    
    def test_commit_info_with_parents(self):
        """Test CommitInfo with parent commits."""
        commit = CommitInfo(
            hash="abc123def456",
            message="Merge commit",
            author="Test Author",
            author_email="test@example.com",
            date="2023-01-01T12:00:00",
            parents=["parent1", "parent2"]
        )
        
        assert len(commit.parents) == 2
        assert "parent1" in commit.parents
        assert "parent2" in commit.parents


class TestRepoInfo:
    """Test RepoInfo model."""
    
    def test_repo_info_creation(self):
        """Test creating a RepoInfo instance."""
        repo = RepoInfo(
            path=Path("/test/repo"),
            name="test-repo"
        )
        
        assert repo.path == Path("/test/repo").resolve()
        assert repo.name == "test-repo"
        assert repo.is_submodule is False
        assert repo.parent_repo is None
        assert repo.submodules == []
        assert repo.depth == 0
    
    def test_repo_info_submodule(self):
        """Test RepoInfo for a submodule."""
        parent = RepoInfo(path=Path("/test/parent"), name="parent")
        submodule = RepoInfo(
            path=Path("/test/parent/submodule"),
            name="submodule",
            is_submodule=True,
            parent_repo=parent,
            depth=1
        )
        
        assert submodule.is_submodule is True
        assert submodule.parent_repo == parent
        assert submodule.depth == 1
    
    def test_relative_path_property(self):
        """Test relative_path property."""
        repo = RepoInfo(
            path=Path.cwd() / "test",
            name="test-repo"
        )
        
        assert repo.relative_path == "test"


class TestRebaseState:
    """Test RebaseState model."""
    
    def test_rebase_state_creation(self):
        """Test creating a RebaseState instance."""
        repo = RepoInfo(path=Path("/test/repo"), name="test-repo")
        state = RebaseState(
            repo=repo,
            source_branch="feature/test",
            target_branch="main"
        )
        
        assert state.repo == repo
        assert state.source_branch == "feature/test"
        assert state.target_branch == "main"
        assert state.original_commits == []
        assert state.new_commits == []
        assert state.commit_mapping == {}
        assert state.is_completed is False
        assert state.has_conflicts is False
        assert state.conflict_files == set()


class TestRebaseOperation:
    """Test RebaseOperation model."""
    
    def test_rebase_operation_creation(self):
        """Test creating a RebaseOperation instance."""
        root_repo = RepoInfo(path=Path("/test/root"), name="root")
        operation = RebaseOperation(
            root_repo=root_repo,
            source_branch="feature/test",
            target_branch="main"
        )
        
        assert operation.root_repo == root_repo
        assert operation.source_branch == "feature/test"
        assert operation.target_branch == "main"
        assert operation.repo_states == []
        assert operation.global_commit_mapping == {}
    
    def test_get_state_for_repo(self):
        """Test getting state for a specific repository."""
        root_repo = RepoInfo(path=Path("/test/root"), name="root")
        operation = RebaseOperation(
            root_repo=root_repo,
            source_branch="feature/test",
            target_branch="main"
        )
        
        # Add a state
        repo = RepoInfo(path=Path("/test/repo"), name="test-repo")
        state = RebaseState(repo=repo, source_branch="feature/test", target_branch="main")
        operation.repo_states.append(state)
        
        # Test finding the state
        found_state = operation.get_state_for_repo(Path("/test/repo"))
        assert found_state == state
        
        # Test not finding a state
        not_found = operation.get_state_for_repo(Path("/test/other"))
        assert not_found is None
    
    def test_add_commit_mapping(self):
        """Test adding commit mappings."""
        root_repo = RepoInfo(path=Path("/test/root"), name="root")
        operation = RebaseOperation(
            root_repo=root_repo,
            source_branch="feature/test",
            target_branch="main"
        )
        
        operation.add_commit_mapping("old_hash", "new_hash")
        assert operation.global_commit_mapping["old_hash"] == "new_hash"


class TestExceptions:
    """Test custom exceptions."""
    
    def test_rebase_error(self):
        """Test RebaseError exception."""
        with pytest.raises(RebaseError) as exc_info:
            raise RebaseError("Test error")
        
        assert str(exc_info.value) == "Test error"
    
    def test_git_repository_error(self):
        """Test GitRepositoryError exception."""
        with pytest.raises(GitRepositoryError) as exc_info:
            raise GitRepositoryError("Git error")
        
        assert str(exc_info.value) == "Git error"
        assert isinstance(exc_info.value, RebaseError)
    
    def test_submodule_error(self):
        """Test SubmoduleError exception."""
        with pytest.raises(SubmoduleError) as exc_info:
            raise SubmoduleError("Submodule error")
        
        assert str(exc_info.value) == "Submodule error"
        assert isinstance(exc_info.value, RebaseError)
    
    def test_conflict_resolution_error(self):
        """Test ConflictResolutionError exception."""
        with pytest.raises(ConflictResolutionError) as exc_info:
            raise ConflictResolutionError("Conflict error")
        
        assert str(exc_info.value) == "Conflict error"
        assert isinstance(exc_info.value, RebaseError)
