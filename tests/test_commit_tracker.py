"""
Tests for commit tracking functionality.
"""

import pytest
from windsurf_project.commit_tracker import CommitTracker, GlobalCommitTracker
from windsurf_project.models import CommitInfo


class TestCommitTracker:
    """Test CommitTracker class."""
    
    def test_commit_tracker_initialization(self):
        """Test CommitTracker initialization."""
        tracker = CommitTracker()
        assert tracker.commit_mappings == {}
        assert tracker.reverse_mappings == {}
    
    def test_map_commits_exact_match(self):
        """Test mapping commits with exact message and author match."""
        tracker = CommitTracker()
        
        original_commits = [
            CommitInfo(
                hash="old1",
                message="First commit",
                author="Author One",
                author_email="author1@example.com",
                date="2023-01-01T12:00:00"
            ),
            CommitInfo(
                hash="old2",
                message="Second commit",
                author="Author Two",
                author_email="author2@example.com",
                date="2023-01-01T13:00:00"
            )
        ]
        
        new_commits = [
            CommitInfo(
                hash="new1",
                message="First commit",
                author="Author One",
                author_email="author1@example.com",
                date="2023-01-01T12:00:00"
            ),
            CommitInfo(
                hash="new2",
                message="Second commit",
                author="Author Two",
                author_email="author2@example.com",
                date="2023-01-01T13:00:00"
            )
        ]
        
        mappings = tracker.map_commits(original_commits, new_commits)
        
        assert mappings["old1"] == "new1"
        assert mappings["old2"] == "new2"
        assert tracker.get_new_hash("old1") == "new1"
        assert tracker.get_old_hash("new1") == "old1"
    
    def test_map_commits_similar_messages(self):
        """Test mapping commits with similar messages."""
        tracker = CommitTracker()
        
        original_commits = [
            CommitInfo(
                hash="old1",
                message="Fix bug in module",
                author="Author One",
                author_email="author1@example.com",
                date="2023-01-01T12:00:00"
            )
        ]
        
        new_commits = [
            CommitInfo(
                hash="new1",
                message="Fix bug in module\n\nAdditional details",
                author="Author One",
                author_email="author1@example.com",
                date="2023-01-01T12:00:00"
            )
        ]
        
        mappings = tracker.map_commits(original_commits, new_commits)
        assert mappings["old1"] == "new1"
    
    def test_add_manual_mapping(self):
        """Test manually adding commit mappings."""
        tracker = CommitTracker()
        
        tracker.add_mapping("manual_old", "manual_new")
        
        assert tracker.get_new_hash("manual_old") == "manual_new"
        assert tracker.get_old_hash("manual_new") == "manual_old"
    
    def test_resolve_submodule_hash(self):
        """Test resolving submodule commit hashes."""
        tracker = CommitTracker()
        tracker.add_mapping("submodule_old", "submodule_new")
        
        resolved = tracker.resolve_submodule_hash("submodule_old")
        assert resolved == "submodule_new"
        
        unresolved = tracker.resolve_submodule_hash("nonexistent")
        assert unresolved is None
    
    def test_clear_mappings(self):
        """Test clearing all mappings."""
        tracker = CommitTracker()
        tracker.add_mapping("test_old", "test_new")
        
        assert len(tracker.commit_mappings) == 1
        
        tracker.clear_mappings()
        
        assert len(tracker.commit_mappings) == 0
        assert len(tracker.reverse_mappings) == 0
    
    def test_export_import_mappings(self):
        """Test exporting and importing mappings."""
        tracker = CommitTracker()
        tracker.add_mapping("export_old", "export_new")
        
        exported = tracker.export_mappings()
        
        new_tracker = CommitTracker()
        new_tracker.import_mappings(exported)
        
        assert new_tracker.get_new_hash("export_old") == "export_new"


class TestGlobalCommitTracker:
    """Test GlobalCommitTracker class."""
    
    def test_global_tracker_initialization(self):
        """Test GlobalCommitTracker initialization."""
        global_tracker = GlobalCommitTracker()
        assert global_tracker.repo_trackers == {}
    
    def test_get_tracker(self):
        """Test getting repository trackers."""
        global_tracker = GlobalCommitTracker()
        
        tracker1 = global_tracker.get_tracker("repo1")
        tracker2 = global_tracker.get_tracker("repo1")  # Same repo
        tracker3 = global_tracker.get_tracker("repo2")  # Different repo
        
        assert tracker1 is tracker2  # Should return same instance
        assert tracker1 is not tracker3  # Should be different instances
        assert len(global_tracker.repo_trackers) == 2
    
    def test_resolve_cross_repo_hash(self):
        """Test resolving commit hashes across repositories."""
        global_tracker = GlobalCommitTracker()
        
        # Add mappings to different repos
        tracker1 = global_tracker.get_tracker("repo1")
        tracker1.add_mapping("hash1", "new_hash1")
        
        tracker2 = global_tracker.get_tracker("repo2")
        tracker2.add_mapping("hash2", "new_hash2")
        
        # Test resolving
        result1 = global_tracker.resolve_cross_repo_hash("hash1")
        assert result1 == ("repo1", "new_hash1")
        
        result2 = global_tracker.resolve_cross_repo_hash("hash2")
        assert result2 == ("repo2", "new_hash2")
        
        result3 = global_tracker.resolve_cross_repo_hash("nonexistent")
        assert result3 is None
    
    def test_get_all_mappings(self):
        """Test getting all mappings from all repositories."""
        global_tracker = GlobalCommitTracker()
        
        tracker1 = global_tracker.get_tracker("repo1")
        tracker1.add_mapping("hash1", "new_hash1")
        
        tracker2 = global_tracker.get_tracker("repo2")
        tracker2.add_mapping("hash2", "new_hash2")
        
        all_mappings = global_tracker.get_all_mappings()
        
        assert "repo1" in all_mappings
        assert "repo2" in all_mappings
        assert all_mappings["repo1"]["hash1"] == "new_hash1"
        assert all_mappings["repo2"]["hash2"] == "new_hash2"
    
    def test_clear_all_mappings(self):
        """Test clearing all mappings from all repositories."""
        global_tracker = GlobalCommitTracker()
        
        tracker1 = global_tracker.get_tracker("repo1")
        tracker1.add_mapping("hash1", "new_hash1")
        
        tracker2 = global_tracker.get_tracker("repo2")
        tracker2.add_mapping("hash2", "new_hash2")
        
        global_tracker.clear_all_mappings()
        
        assert len(tracker1.commit_mappings) == 0
        assert len(tracker2.commit_mappings) == 0
