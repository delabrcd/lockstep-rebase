"""
Main rebase orchestration logic for multi-repository operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from .models import RebaseOperation, RebaseState, RepoInfo, RebaseError
from .git_manager import GitManager
from .submodule_mapper import SubmoduleMapper
from .commit_tracker import GlobalCommitTracker
from .conflict_resolver import ConflictResolver
from .prompt_interface import UserPrompt, NoOpPrompt
from .conflict_prompt_interface import ConflictPrompt, NoOpConflictPrompt


logger = logging.getLogger(__name__)


class RebaseOrchestrator:
    """Orchestrates rebase operations across multiple repositories with submodules."""
    
    def __init__(self, root_path: Optional[Path] = None, conflict_prompt: ConflictPrompt = None) -> None:
        """Initialize the rebase orchestrator."""
        self.root_path = root_path or Path.cwd()
        self.git_manager = GitManager(self.root_path)
        self.submodule_mapper = SubmoduleMapper(self.root_path)
        self.global_tracker = GlobalCommitTracker()
        self.conflict_resolver = ConflictResolver(self.global_tracker, conflict_prompt)
        
        # Discover repository hierarchy
        self.root_repo_info = self.submodule_mapper.discover_repository_hierarchy()
        logger.info(f"Initialized rebase orchestrator for {self.root_repo_info.name}")
    
    def plan_rebase(self, source_branch: str, target_branch: str, prompt: UserPrompt = None) -> RebaseOperation:
        """
        Plan a rebase operation across all repositories.
        
        Args:
            source_branch: The branch to rebase (e.g., 'feature/my-feature')
            target_branch: The branch to rebase onto (e.g., 'main')
            
        Returns:
            RebaseOperation with planned states for all repositories
        """
        logger.info(f"Planning rebase from {source_branch} to {target_branch}")
        
        if prompt is None:
            prompt = NoOpPrompt()
        
        # Validate branches exist in all repositories
        missing_branches = self.submodule_mapper.validate_branches_exist(
            self.root_repo_info, source_branch, target_branch, prompt
        )
        
        if missing_branches['missing_source']:
            raise RebaseError(
                f"Source branch '{source_branch}' missing in: {', '.join(missing_branches['missing_source'])}"
            )
        
        if missing_branches['missing_target']:
            raise RebaseError(
                f"Target branch '{target_branch}' missing in: {', '.join(missing_branches['missing_target'])}"
            )
        
        # Create rebase operation
        operation = RebaseOperation(
            root_repo=self.root_repo_info,
            source_branch=source_branch,
            target_branch=target_branch
        )
        
        # Get repositories in rebase order (deepest first)
        rebase_order = self.submodule_mapper.get_rebase_order(self.root_repo_info)
        
        # Create rebase states for each repository
        for repo_info in rebase_order:
            git_manager = GitManager(repo_info.path)
            
            # Get commits that will be rebased
            original_commits = git_manager.get_commits_between(
                target_branch, source_branch, repo_info.path
            )
            
            state = RebaseState(
                repo=repo_info,
                source_branch=source_branch,
                target_branch=target_branch,
                original_commits=original_commits
            )
            
            operation.repo_states.append(state)
            logger.debug(f"Planned rebase for {repo_info.name}: {len(original_commits)} commits")
        
        logger.info(f"Planned rebase operation for {len(operation.repo_states)} repositories")
        return operation
    
    def execute_rebase(self, operation: RebaseOperation) -> bool:
        """
        Execute the planned rebase operation.
        
        Returns:
            True if rebase completed successfully, False if aborted
        """
        logger.info("Starting rebase execution")
        
        try:
            for state in operation.repo_states:
                if not self._execute_repository_rebase(state, operation):
                    logger.error(f"Rebase failed for {state.repo.name}")
                    return False
            
            logger.info("✅ Rebase operation completed successfully!")
            return True
            
        except Exception as e:
            logger.error(f"Rebase execution failed: {e}")
            self._cleanup_failed_rebase(operation)
            raise RebaseError(f"Rebase execution failed: {e}")
    
    def _execute_repository_rebase(
        self, 
        state: RebaseState, 
        operation: RebaseOperation
    ) -> bool:
        """Execute rebase for a single repository."""
        logger.info(f"🔄 Rebasing {state.repo.name} ({state.repo.relative_path})")
        
        git_manager = GitManager(state.repo.path)
        repo_tracker = self.global_tracker.get_tracker(state.repo.name)
        
        try:
            # Checkout source branch
            git_manager.checkout_branch(state.source_branch, state.repo.path)
            
            # Start rebase
            success, conflict_files = git_manager.start_rebase(
                state.target_branch, state.repo.path
            )
            
            if success:
                # Rebase completed without conflicts
                return self._handle_successful_rebase(state, git_manager, repo_tracker, operation)
            else:
                # Handle conflicts
                return self._handle_rebase_conflicts(
                    state, git_manager, repo_tracker, operation, conflict_files
                )
                
        except Exception as e:
            logger.error(f"Error during rebase of {state.repo.name}: {e}")
            return False
    
    def _handle_successful_rebase(
        self,
        state: RebaseState,
        git_manager: GitManager,
        repo_tracker,
        operation: RebaseOperation
    ) -> bool:
        """Handle a rebase that completed without conflicts."""
        try:
            # Get updated commits
            new_commits = git_manager.get_updated_commits(
                state.original_commits, state.repo.path
            )
            
            # Map old commits to new commits
            commit_mappings = repo_tracker.map_commits(state.original_commits, new_commits)
            
            # Update state
            state.new_commits = new_commits
            state.commit_mapping = commit_mappings
            state.is_completed = True
            
            # Add to global mappings
            for old_hash, new_hash in commit_mappings.items():
                operation.add_commit_mapping(old_hash, new_hash)
            
            logger.info(f"✅ Successfully rebased {state.repo.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error handling successful rebase: {e}")
            return False
    
    def _handle_rebase_conflicts(
        self,
        state: RebaseState,
        git_manager: GitManager,
        repo_tracker,
        operation: RebaseOperation,
        initial_conflict_files: List[str]
    ) -> bool:
        """Handle rebase conflicts through resolution loop."""
        state.has_conflicts = True
        
        while True:
            # Analyze conflicts
            conflicts = self.conflict_resolver.analyze_conflicts(state.repo.path)
            
            if not conflicts['file_conflicts'] and not conflicts['submodule_conflicts']:
                # No more conflicts, try to continue
                success, new_conflicts = git_manager.continue_rebase(state.repo.path)
                
                if success:
                    # Rebase completed
                    return self._handle_successful_rebase(state, git_manager, repo_tracker, operation)
                elif new_conflicts:
                    # More conflicts appeared
                    continue
                else:
                    # Other error
                    logger.error(f"Failed to continue rebase for {state.repo.name}")
                    return False
            
            # Try to auto-resolve submodule conflicts
            resolved_submodules, unresolved_submodules = [], []
            if conflicts['submodule_conflicts']:
                resolved_submodules, unresolved_submodules = (
                    self.conflict_resolver.auto_resolve_submodule_conflicts(
                        state.repo.path, conflicts['submodule_conflicts']
                    )
                )
            
            # Check if we still have unresolved conflicts
            remaining_conflicts = conflicts['file_conflicts'] + unresolved_submodules
            
            if remaining_conflicts:
                # Prompt user for manual resolution
                if not self.conflict_resolver.prompt_user_for_conflict_resolution(
                    state.repo, conflicts['file_conflicts'], unresolved_submodules
                ):
                    # User chose to abort
                    logger.info("User aborted rebase operation")
                    return False
            
            # Continue the loop to check for more conflicts
    
    def _cleanup_failed_rebase(self, operation: RebaseOperation) -> None:
        """Clean up after a failed rebase operation."""
        logger.info("Cleaning up failed rebase operation")
        
        for state in operation.repo_states:
            try:
                git_manager = GitManager(state.repo.path)
                if git_manager.is_rebase_in_progress(state.repo.path):
                    git_manager.abort_rebase(state.repo.path)
                    logger.info(f"Aborted rebase for {state.repo.name}")
            except Exception as e:
                logger.error(f"Error cleaning up {state.repo.name}: {e}")
    
    def get_repository_status(self) -> Dict[str, Dict[str, str]]:
        """Get status information for all repositories."""
        status = {}
        
        all_repos = self._get_all_repositories(self.root_repo_info)
        
        for repo_info in all_repos:
            try:
                git_manager = GitManager(repo_info.path)
                current_branch = git_manager.get_current_branch(repo_info.path)
                is_rebasing = git_manager.is_rebase_in_progress(repo_info.path)
                
                status[repo_info.name] = {
                    'path': str(repo_info.relative_path),
                    'current_branch': current_branch,
                    'is_rebasing': str(is_rebasing),
                    'is_submodule': str(repo_info.is_submodule),
                    'depth': str(repo_info.depth)
                }
            except Exception as e:
                status[repo_info.name] = {
                    'path': str(repo_info.relative_path),
                    'error': str(e)
                }
        
        return status
    
    def _get_all_repositories(self, root_info: RepoInfo) -> List[RepoInfo]:
        """Get a flat list of all repositories."""
        all_repos = [root_info]
        for submodule in root_info.submodules:
            all_repos.extend(self._get_all_repositories(submodule))
        return all_repos
    
    def print_repository_hierarchy(self) -> None:
        """Print the discovered repository hierarchy."""
        print(f"\n📁 **Repository Hierarchy**")
        self.submodule_mapper.print_hierarchy(self.root_repo_info)
    
    def validate_repository_state(self, prompt: UserPrompt = None) -> List[str]:
        """
        Validate that all repositories are in a clean state for rebase.
        
        Args:
            prompt: Optional prompt interface for user interactions
        
        Returns:
            List of validation errors (empty if all good)
        """
        if prompt is None:
            prompt = NoOpPrompt()
            
        errors = []
        all_repos = self._get_all_repositories(self.root_repo_info)
        
        for repo_info in all_repos:
            try:
                git_manager = GitManager(repo_info.path)
                
                # Check for ongoing rebase
                if git_manager.is_rebase_in_progress(repo_info.path):
                    errors.append(f"{repo_info.name}: Rebase already in progress")
                
                # Check for unstaged changes
                if self.conflict_resolver.has_unstaged_changes(repo_info.path):
                    errors.append(f"{repo_info.name}: Has unstaged changes")
                
            except Exception as e:
                errors.append(f"{repo_info.name}: Error validating state - {e}")
        
        return errors
