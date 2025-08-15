"""
Commit tracking and hash mapping during rebase operations.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from .models import CommitInfo, RebaseError


logger = logging.getLogger(__name__)


class CommitTracker:
    """Tracks commit changes and maintains hash mappings during rebases."""
    
    def __init__(self) -> None:
        """Initialize the commit tracker."""
        self.commit_mappings: Dict[str, str] = {}  # old_hash -> new_hash
        self.reverse_mappings: Dict[str, str] = {}  # new_hash -> old_hash
    
    def map_commits(
        self, 
        original_commits: List[CommitInfo], 
        new_commits: List[CommitInfo]
    ) -> Dict[str, str]:
        """
        Map original commits to their rebased equivalents.
        
        This uses commit message and author matching since commit hashes change during rebase.
        
        Args:
            original_commits: List of commits before rebase
            new_commits: List of commits after rebase
            
        Returns:
            Dictionary mapping old commit hash to new commit hash
        """
        mappings = {}
        
        # Reverse the lists since commits are typically returned in reverse chronological order
        original_commits = list(reversed(original_commits))
        new_commits = list(reversed(new_commits))
        
        # Try to match commits by message and author
        for i, original in enumerate(original_commits):
            best_match = self._find_best_match(original, new_commits[i:i+3])  # Look at next 3 commits
            
            if best_match:
                mappings[original.hash] = best_match.hash
                logger.debug(f"Mapped commit {original.hash[:8]} -> {best_match.hash[:8]}")
            else:
                logger.warning(f"Could not find mapping for commit {original.hash[:8]}: {original.message[:50]}")
        
        # Update internal mappings
        self.commit_mappings.update(mappings)
        for old_hash, new_hash in mappings.items():
            self.reverse_mappings[new_hash] = old_hash
        
        return mappings
    
    def _find_best_match(
        self, 
        original_commit: CommitInfo, 
        candidate_commits: List[CommitInfo]
    ) -> Optional[CommitInfo]:
        """Find the best matching commit from candidates."""
        if not candidate_commits:
            return None
        
        # First, try exact message match
        for candidate in candidate_commits:
            if (candidate.message == original_commit.message and 
                candidate.author == original_commit.author):
                return candidate
        
        # If no exact match, try message similarity
        for candidate in candidate_commits:
            if (self._messages_similar(original_commit.message, candidate.message) and
                candidate.author == original_commit.author):
                return candidate
        
        # Last resort: same author, closest position
        for candidate in candidate_commits:
            if candidate.author == original_commit.author:
                return candidate
        
        return None
    
    def _messages_similar(self, msg1: str, msg2: str) -> bool:
        """Check if two commit messages are similar enough to be considered the same."""
        # Simple similarity check - could be enhanced with more sophisticated algorithms
        msg1_clean = msg1.strip().lower()
        msg2_clean = msg2.strip().lower()
        
        # Check if messages are identical after cleaning
        if msg1_clean == msg2_clean:
            return True
        
        # Check if one message contains the other (for amended commits)
        if msg1_clean in msg2_clean or msg2_clean in msg1_clean:
            return True
        
        return False
    
    def get_new_hash(self, old_hash: str) -> Optional[str]:
        """Get the new hash for an old commit hash."""
        return self.commit_mappings.get(old_hash)
    
    def get_old_hash(self, new_hash: str) -> Optional[str]:
        """Get the old hash for a new commit hash."""
        return self.reverse_mappings.get(new_hash)
    
    def resolve_submodule_hash(self, old_submodule_hash: str) -> Optional[str]:
        """
        Resolve a submodule commit hash to its new value after rebase.
        
        This is used when resolving submodule conflicts during parent repository rebases.
        """
        new_hash = self.get_new_hash(old_submodule_hash)
        if new_hash:
            logger.debug(f"Resolved submodule hash {old_submodule_hash[:8]} -> {new_hash[:8]}")
        else:
            logger.warning(f"Could not resolve submodule hash: {old_submodule_hash[:8]}")
        
        return new_hash
    
    def add_mapping(self, old_hash: str, new_hash: str) -> None:
        """Manually add a commit hash mapping."""
        self.commit_mappings[old_hash] = new_hash
        self.reverse_mappings[new_hash] = old_hash
        logger.debug(f"Added manual mapping {old_hash[:8]} -> {new_hash[:8]}")
    
    def get_all_mappings(self) -> Dict[str, str]:
        """Get all commit hash mappings."""
        return self.commit_mappings.copy()
    
    def clear_mappings(self) -> None:
        """Clear all commit mappings."""
        self.commit_mappings.clear()
        self.reverse_mappings.clear()
        logger.debug("Cleared all commit mappings")
    
    def export_mappings(self) -> Dict[str, Dict[str, str]]:
        """Export mappings for serialization or debugging."""
        return {
            'commit_mappings': self.commit_mappings.copy(),
            'reverse_mappings': self.reverse_mappings.copy()
        }
    
    def import_mappings(self, mappings_data: Dict[str, Dict[str, str]]) -> None:
        """Import mappings from serialized data."""
        self.commit_mappings = mappings_data.get('commit_mappings', {})
        self.reverse_mappings = mappings_data.get('reverse_mappings', {})
        logger.info(f"Imported {len(self.commit_mappings)} commit mappings")


class GlobalCommitTracker:
    """Manages commit tracking across multiple repositories."""
    
    def __init__(self) -> None:
        """Initialize the global commit tracker."""
        self.repo_trackers: Dict[str, CommitTracker] = {}
    
    def get_tracker(self, repo_name: str) -> CommitTracker:
        """Get or create a commit tracker for a repository."""
        if repo_name not in self.repo_trackers:
            self.repo_trackers[repo_name] = CommitTracker()
        return self.repo_trackers[repo_name]
    
    def resolve_cross_repo_hash(self, commit_hash: str) -> Optional[Tuple[str, str]]:
        """
        Resolve a commit hash across all repositories.
        
        Returns:
            Tuple of (repo_name, new_hash) if found, None otherwise
        """
        for repo_name, tracker in self.repo_trackers.items():
            new_hash = tracker.get_new_hash(commit_hash)
            if new_hash:
                return repo_name, new_hash
        
        return None
    
    def get_all_mappings(self) -> Dict[str, Dict[str, str]]:
        """Get all commit mappings from all repositories."""
        all_mappings = {}
        for repo_name, tracker in self.repo_trackers.items():
            all_mappings[repo_name] = tracker.get_all_mappings()
        return all_mappings
    
    def clear_all_mappings(self) -> None:
        """Clear all commit mappings from all repositories."""
        for tracker in self.repo_trackers.values():
            tracker.clear_mappings()
        logger.info("Cleared all commit mappings from all repositories")
