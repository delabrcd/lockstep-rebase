"""
Main manager class for lockstep rebase operations.

This module contains the core NestedRebaseManager class that orchestrates
the entire lockstep rebase process.
"""

import os
import subprocess
import sys
import time
from typing import List, Optional, Dict

from .models import RepoInfo, RebaseResult, RebaseState
from .git_utils import GitUtils
from .planner import RebasePlanner, RebasePlan
from ..utils.state import StateManager
from ..utils.discovery import RepositoryDiscovery
from ..utils.ui import BranchSelector, InteractivePrompt
from ..conflict_resolution.submodule import SubmoduleConflictResolver
from ..conflict_resolution.interactive import InteractiveConflictHandler
from ..conflict_resolution.planned import PlannedSubmoduleResolver
from ..backup.manager import BackupManager


class NestedRebaseManager:
    """Main manager for nested repository rebase operations."""
    
    def __init__(self, dry_run: bool = False, verbose: bool = False):
        """Initialize the nested rebase manager.
        
        Args:
            dry_run: If True, show what would be done without making changes
            verbose: Enable verbose output
        """
        self.dry_run = dry_run
        self.verbose = verbose
        
        # Initialize components
        self.git_utils = GitUtils(verbose=verbose)
        self.state_manager = StateManager(verbose=verbose)
        self.discovery = RepositoryDiscovery(self.git_utils)
        self.planner = RebasePlanner(self.git_utils)
        self.submodule_resolver = SubmoduleConflictResolver(self.git_utils)
        self.planned_resolver = PlannedSubmoduleResolver(self.git_utils)
        self.interactive_handler = InteractiveConflictHandler(self.git_utils)
        self.backup_manager = BackupManager(self.git_utils, self.discovery)
        
        # Runtime state
        self.repo_tree: Optional[RepoInfo] = None
        self.results: List[RebaseResult] = []
        self.active_rebases: List[str] = []
        self.rebase_plans: Dict[str, RebasePlan] = {}  # repo_path -> rebase_plan
    
    def run_nested_rebase(self, root_path: str) -> None:
        """Main entry point for nested repository rebasing.
        
        Args:
            root_path: Root repository path
        """
        print("🔍 Discovering repository structure...")
        
        # Check for existing rebase state
        existing_state = self.state_manager.load_state(root_path)
        if existing_state:
            print(f"\n📂 Found existing rebase state from {existing_state.timestamp}")
            print(f"   Session ID: {existing_state.session_id}")
            print(f"   Completed rebases: {len(existing_state.completed_rebases)}")
            print(f"   Active rebases: {len(existing_state.active_rebases)}")
            
            while True:
                resume = input("\nResume previous rebase session? (y/n): ").strip().lower()
                if resume in ['y', 'yes']:
                    self._resume_rebase_session(existing_state, root_path)
                    return
                elif resume in ['n', 'no']:
                    print("Starting fresh rebase session...")
                    self.state_manager.cleanup_state_file(root_path)
                    break
                else:
                    print("Please enter 'y' or 'n'")
        
        # Discover repository structure
        self.repo_tree = self.discovery.discover_repositories(root_path)
        
        # Print repository tree
        print(f"\n🌳 Repository structure:")
        self.discovery.print_tree(self.repo_tree)
        
        # Interactive configuration
        self._configure_repositories_interactive(self.repo_tree)
        
        # Create new rebase state
        state = RebaseState.create_new(root_path)
        self.state_manager.save_state(state, root_path)
        
        # Execute rebases
        print(f"\n🚀 Starting nested rebase...")
        self.results = self._rebase_tree_recursive(self.repo_tree)
        
        # Show summary
        self._summarize_changes(self.results)
        
        # Confirm and push changes
        if not self.dry_run and self._confirm_push_all(self.results):
            self._push_all_changes(self.results, self.repo_tree)
            print("\n✅ Nested rebase completed successfully!")
            # Clean up state file on successful completion
            self.state_manager.cleanup_state_file(root_path)
        else:
            print("\n⏹️  Rebase completed without pushing changes.")
            # Keep state file in case user wants to resume later
    
    def _configure_repositories_interactive(self, repo_info: RepoInfo) -> None:
        """Configure repositories interactively.
        
        Args:
            repo_info: Repository information tree
        """
        # Configure submodules first (depth-first)
        for submodule in repo_info.submodules:
            self._configure_repositories_interactive(submodule)
        
        # Configure this repository
        self._configure_single_repository(repo_info)
    
    def _configure_single_repository(self, repo_info: RepoInfo) -> None:
        """Configure a single repository interactively with enhanced UI.
        
        Args:
            repo_info: Repository information
        """
        try:
            current_branch = self.git_utils.get_current_branch(repo_info.path)
            branches = self.git_utils.get_branches(repo_info.path)
            
            print(f"\n📁 Repository: {repo_info.name}")
            print(f"   Path: {repo_info.path}")
            
            # Ask if user wants to rebase this repo using enhanced prompt
            if InteractivePrompt.yes_no(f"Do you want to rebase {repo_info.name}?", default=False):
                # Create branch selector for enhanced branch selection
                branch_selector = BranchSelector(branches, current_branch)
                
                # Get branch to rebase with bash-style inline autocomplete
                selected_branch = branch_selector.select_branch_inline(
                    f"Select branch to rebase for {repo_info.name}"
                )
                
                if selected_branch:
                    repo_info.branch = selected_branch
                    print(f"✅ Selected branch: {selected_branch}")
                    
                    # Get base branch/commit with bash-style inline autocomplete
                    base_branch = branch_selector.select_branch_inline(
                        f"Select base branch/commit for {selected_branch}"
                    )
                    
                    if base_branch:
                        # Validate that the base exists
                        try:
                            self.git_utils.sh(['git', 'rev-parse', base_branch], cwd=repo_info.path, capture=True)
                            repo_info.base = base_branch
                            print(f"✅ Selected base: {base_branch}")
                        except subprocess.CalledProcessError:
                            # Base might be a commit hash or tag, try manual input
                            print(f"⚠️  '{base_branch}' not found as a branch, trying as commit/tag...")
                            base_commit = self._get_base_commit_manual(repo_info, selected_branch)
                            if base_commit:
                                repo_info.base = base_commit
                            else:
                                print(f"❌ Could not configure base for {repo_info.name}")
                                return
                    else:
                        # User cancelled base selection, try manual input
                        base_commit = self._get_base_commit_manual(repo_info, selected_branch)
                        if base_commit:
                            repo_info.base = base_commit
                        else:
                            print(f"❌ Could not configure base for {repo_info.name}")
                            return
                else:
                    print(f"⏭️  No branch selected, skipping {repo_info.name}")
            else:
                print(f"⏭️  Skipping {repo_info.name}")
        
        except subprocess.CalledProcessError as e:
            print(f"❌ Error configuring {repo_info.name}: {e}")
    
    def _get_base_commit_manual(self, repo_info: RepoInfo, branch: str) -> Optional[str]:
        """Get base commit/branch manually with validation.
        
        Args:
            repo_info: Repository information
            branch: Branch being rebased
            
        Returns:
            Valid base commit/branch or None if cancelled
        """
        print(f"\n🎯 Enter base branch/commit for {branch}:")
        print("   You can enter:")
        print("   - A branch name (e.g., 'main', 'develop')")
        print("   - A commit hash (e.g., 'abc123')")
        print("   - A tag (e.g., 'v1.0.0')")
        print("   - Type 'cancel' to skip this repository")
        
        while True:
            try:
                base = input(f"Base for {branch}: ").strip()
                
                if not base or base.lower() in ['cancel', 'skip']:
                    return None
                
                if base.lower() in ['quit', 'exit']:
                    print("Cancelled by user")
                    sys.exit(0)
                
                # Validate that the base exists
                try:
                    self.git_utils.sh(['git', 'rev-parse', base], cwd=repo_info.path, capture=True)
                    print(f"✅ Valid base: {base}")
                    return base
                except subprocess.CalledProcessError:
                    print(f"❌ Base '{base}' not found. Please enter a valid branch/commit/tag.")
                    
            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                sys.exit(0)
            except EOFError:
                print("\n\nCancelled by user")
                sys.exit(0)
    
    def _rebase_tree_recursive(self, repo_info: RepoInfo) -> List[RebaseResult]:
        """Recursively rebase repositories in dependency order (submodules first).
        
        Args:
            repo_info: Repository information tree
            
        Returns:
            List of rebase results
        """
        results = []
        
        # First, rebase all submodules
        for submodule in repo_info.submodules:
            submodule_results = self._rebase_tree_recursive(submodule)
            results.extend(submodule_results)
        
        # Then rebase this repository, passing all previous results for conflict resolution
        result = self._rebase_repository(repo_info, results)
        results.append(result)
        
        return results
    
    def _rebase_repository(self, repo_info: RepoInfo, all_results: List[RebaseResult]) -> RebaseResult:
        """Rebase a single repository using proactive planning.
        
        Args:
            repo_info: Repository information
            all_results: Results from previous rebase operations
            
        Returns:
            Rebase result
        """
        if not repo_info.branch or not repo_info.base:
            return RebaseResult(
                repo_path=repo_info.path,
                success=True,
                error_message="Skipped (not configured for rebase)"
            )
        
        print(f"\n🔄 Rebasing {repo_info.name} ({repo_info.branch} onto {repo_info.base})")
        
        try:
            # Add to active rebases for cleanup tracking
            self.active_rebases.append(repo_info.path)
            
            # Create rebase plan BEFORE starting the rebase
            if self.verbose:
                print(f"📋 Creating rebase plan...")
            rebase_plan = self.planner.create_rebase_plan(repo_info, all_results)
            self.rebase_plans[repo_info.path] = rebase_plan
            
            # Checkout the target branch
            if not self.dry_run:
                self.git_utils.sh(['git', 'checkout', repo_info.branch], cwd=repo_info.path)
            
            # Create backup branch
            backup_branch = None
            if not self.dry_run:
                timestamp = self.state_manager.timestamp()
                backup_branch = f"{repo_info.branch}-backup-{timestamp}"
                self.git_utils.sh(['git', 'branch', backup_branch], cwd=repo_info.path)
                print(f"📦 Created backup branch: {backup_branch}")
            
            # Perform the rebase
            if self.dry_run:
                print(f"[DRY RUN] Would rebase {repo_info.branch} onto {repo_info.base}")
                if rebase_plan.commit_plans:
                    print(f"[DRY RUN] Plan includes {len(rebase_plan.commit_plans)} commits with submodule mappings")
                result = RebaseResult(
                    repo_path=repo_info.path,
                    success=True,
                    commit_mapping={},
                    backup_branch=backup_branch
                )
            else:
                # Execute rebase with planned conflict resolution
                success, commit_mapping = self._execute_planned_rebase(repo_info, rebase_plan)
                
                if success:
                    result = RebaseResult(
                        repo_path=repo_info.path,
                        success=True,
                        commit_mapping=commit_mapping,
                        backup_branch=backup_branch
                    )
                else:
                    # Remove from active rebases since we're aborting
                    if repo_info.path in self.active_rebases:
                        self.active_rebases.remove(repo_info.path)
                    return RebaseResult(
                        repo_path=repo_info.path,
                        success=False,
                        error_message="Rebase failed with planned resolution"
                    )
            
            # Remove from active rebases on success
            if repo_info.path in self.active_rebases:
                self.active_rebases.remove(repo_info.path)
            
            return result
            
        except Exception as e:
            # Remove from active rebases on error
            if repo_info.path in self.active_rebases:
                self.active_rebases.remove(repo_info.path)
            
            return RebaseResult(
                repo_path=repo_info.path,
                success=False,
                error_message=f"Rebase failed: {e}"
            )
    
    def _execute_planned_rebase(self, repo_info: RepoInfo, rebase_plan: RebasePlan) -> tuple[bool, Dict[str, str]]:
        """Execute a rebase using the proactive planning system.
        
        Args:
            repo_info: Repository information
            rebase_plan: Pre-calculated rebase plan
            
        Returns:
            Tuple of (success, commit_mapping)
        """
        if self.verbose:
            print(f"🎯 Executing planned rebase with {len(rebase_plan.commit_plans)} commits")
        
        commit_mapping = {}
        
        try:
            # Start the rebase
            self.git_utils.sh(['git', 'rebase', repo_info.base], cwd=repo_info.path)
            print(f"✅ Rebase completed successfully without conflicts!")
            
            # Get the final commit mapping
            commit_mapping = self._extract_commit_mapping_after_rebase(repo_info, rebase_plan)
            return True, commit_mapping
            
        except subprocess.CalledProcessError:
            # Rebase hit conflicts - use planned resolution
            if self.verbose:
                print(f"⚠️  Rebase conflicts detected - using planned resolution")
            
            return self._resolve_rebase_with_plan(repo_info, rebase_plan)
    
    def _resolve_rebase_with_plan(self, repo_info: RepoInfo, rebase_plan: RebasePlan) -> tuple[bool, Dict[str, str]]:
        """Resolve rebase conflicts using the pre-calculated plan.
        
        Args:
            repo_info: Repository information
            rebase_plan: Pre-calculated rebase plan
            
        Returns:
            Tuple of (success, commit_mapping)
        """
        commit_mapping = {}
        attempt = 0
        max_attempts = len(rebase_plan.commit_plans) + 10  # Safety limit
        
        while attempt < max_attempts:
            attempt += 1
            
            # Check if rebase is still active
            if not self.git_utils.is_rebase_in_progress(repo_info.path):
                if self.verbose:
                    print(f"✅ Rebase completed successfully after {attempt-1} conflict resolutions!")
                commit_mapping = self._extract_commit_mapping_after_rebase(repo_info, rebase_plan)
                return True, commit_mapping
            
            if self.verbose:
                print(f"\n🔄 Resolving conflicts (attempt {attempt})...")
            
            # Use planned resolver to handle conflicts
            if self.planned_resolver.resolve_conflicts_with_plan(repo_info, rebase_plan):
                # Conflicts resolved, try to continue
                try:
                    self.git_utils.sh(['git', 'rebase', '--continue'], cwd=repo_info.path)
                    if self.verbose:
                        print(f"✅ Continued rebase after planned resolution")
                    continue  # Check for more conflicts
                except subprocess.CalledProcessError:
                    # Still have conflicts or other issues
                    if self.verbose:
                        print(f"⚠️  Rebase --continue failed, checking for remaining conflicts")
                    
                    # Check what kind of conflicts remain
                    regular_conflicts, submodule_conflicts = self.git_utils.get_conflicted_files(repo_info.path)
                    
                    if regular_conflicts:
                        # We have non-submodule conflicts that need manual resolution
                        print(f"❌ Found {len(regular_conflicts)} non-submodule conflicts requiring manual resolution")
                        if not self.interactive_handler.handle_merge_conflicts(repo_info):
                            return False, {}
                        continue
                    elif submodule_conflicts:
                        # Still have submodule conflicts - our plan might be incomplete
                        if self.verbose:
                            print(f"⚠️  Still have {len(submodule_conflicts)} unresolved submodule conflicts")
                        continue  # Try again with the planned resolver
                    else:
                        # No conflicts but rebase --continue failed - might be done
                        if self.verbose:
                            print(f"⚠️  No conflicts detected but rebase --continue failed")
                        break
            else:
                # Planned resolver failed
                if self.verbose:
                    print(f"❌ Planned conflict resolution failed")
                
                # Fall back to interactive resolution
                if not self.interactive_handler.handle_merge_conflicts(repo_info):
                    return False, {}
                continue
        
        # If we get here, we've exceeded max attempts
        print(f"❌ Rebase failed: exceeded maximum conflict resolution attempts ({max_attempts})")
        return False, {}
    
    def _extract_commit_mapping_after_rebase(self, repo_info: RepoInfo, rebase_plan: RebasePlan) -> Dict[str, str]:
        """Extract the commit mapping after a successful rebase.
        
        Args:
            repo_info: Repository information
            rebase_plan: Original rebase plan
            
        Returns:
            Dictionary mapping old commits to new commits
        """
        commit_mapping = {}
        
        try:
            # Get the new commits on the rebased branch
            new_commits_output = self.git_utils.sh([
                'git', 'rev-list', '--reverse', f'{repo_info.base}..{repo_info.branch}'
            ], cwd=repo_info.path, capture=True)
            
            new_commits = [line.strip() for line in new_commits_output.split('\n') if line.strip()]
            
            # Map old commits to new commits based on position
            # This assumes the rebase preserved the order of commits
            for i, commit_plan in enumerate(rebase_plan.commit_plans):
                if i < len(new_commits):
                    commit_mapping[commit_plan.old_commit] = new_commits[i]
                    # Update the plan with the new commit
                    commit_plan.new_commit = new_commits[i]
            
            if self.verbose and commit_mapping:
                print(f"📊 Extracted {len(commit_mapping)} commit mappings")
            
        except subprocess.CalledProcessError:
            if self.verbose:
                print(f"⚠️  Could not extract commit mapping after rebase")
        
        return commit_mapping
    
    def _resolve_submodule_conflicts_automatically(
        self, 
        repo_info: RepoInfo, 
        submodule_conflicts: List[str], 
        all_results: List[RebaseResult]
    ) -> bool:
        """Resolve submodule conflicts automatically and continue rebase.
        
        Args:
            repo_info: Repository information
            submodule_conflicts: List of conflicted submodule paths
            all_results: Results from previous rebase operations
            
        Returns:
            True if all conflicts were resolved and rebase completed
        """
        # Load saved mappings from state file
        saved_mappings = {}
        existing_state = self.state_manager.load_state(repo_info.path)
        if existing_state:
            saved_mappings = existing_state.completed_rebases
        
        # Try to resolve conflicts automatically
        if self.submodule_resolver.resolve_conflicts_automatically(
            repo_info, submodule_conflicts, all_results, saved_mappings
        ):
            # Try to continue the rebase with auto-resolution
            return self._continue_rebase_with_auto_resolve(repo_info)
        else:
            print(f"⚠️  Could not resolve all submodule conflicts automatically")
            return False
    
    def _continue_rebase_with_auto_resolve(self, repo_info: RepoInfo) -> bool:
        """Continue rebase and auto-resolve submodule conflicts until completion or failure.
        
        Args:
            repo_info: Repository information
            
        Returns:
            True if rebase completed successfully
        """
        attempt = 0
        while True:
            attempt += 1
            
            # First check if there's actually an active rebase
            if not self.git_utils.is_rebase_in_progress(repo_info.path):
                print(f"✅ No active rebase - rebase completed successfully!")
                return True
            
            try:
                print(f"\n🔄 Continuing rebase (step {attempt})...")
                self.git_utils.sh(['git', 'rebase', '--continue'], cwd=repo_info.path)
                print(f"✅ Rebase step completed!")
                # Don't return here - check if more steps remain
                
            except subprocess.CalledProcessError as e:
                if self.verbose:
                    print(f"⚠️  Rebase continue failed: {e}")
                
                # Check if the rebase is actually complete (no active rebase)
                if not self.git_utils.is_rebase_in_progress(repo_info.path):
                    print(f"✅ Rebase completed successfully!")
                    return True
                
                # Check if there are conflicts to resolve
                regular_conflicts, submodule_conflicts = self.git_utils.get_conflicted_files(repo_info.path)
                
                if submodule_conflicts:
                    print(f"🤖 Found {len(submodule_conflicts)} submodule conflicts, attempting auto-resolution...")
                    
                    # Try to auto-resolve the submodule conflicts
                    if self.submodule_resolver.resolve_conflicts_automatically(repo_info, submodule_conflicts, []):
                        print(f"✅ Auto-resolved submodule conflicts, continuing...")
                        continue  # Try git rebase --continue again
                    else:
                        print(f"❌ Could not auto-resolve submodule conflicts")
                        return False
                        
                elif regular_conflicts:
                    print(f"❌ Found {len(regular_conflicts)} non-submodule conflicts - manual resolution required")
                    return False
                    
                else:
                    print(f"❌ Rebase failed for unknown reason")
                    return False
    
    def _get_commit_mapping(self, repo_info: RepoInfo) -> Dict[str, str]:
        """Get commit mapping for a repository rebase.
        
        Args:
            repo_info: Repository information
            
        Returns:
            Dictionary mapping old commits to new commits
        """
        if self.dry_run:
            return {}
        
        try:
            # Get commits that will be rebased
            commits_output = self.git_utils.sh(
                ['git', 'rev-list', f'{repo_info.base}..{repo_info.branch}'], 
                cwd=repo_info.path, 
                capture=True
            )
            
            commits = [line.strip() for line in commits_output.split('\n') if line.strip()]
            
            # For now, return empty mapping - this would be populated after actual rebase
            # In a real implementation, we'd capture the mapping during rebase
            return {commit: commit for commit in commits}
            
        except subprocess.CalledProcessError:
            return {}
    
    def _summarize_changes(self, results: List[RebaseResult]) -> None:
        """Print a summary of all changes that will be made.
        
        Args:
            results: List of rebase results
        """
        print("\n" + "="*80)
        print("📋 REBASE SUMMARY")
        print("="*80)
        
        successful_rebases = [r for r in results if r.success and r.commit_mapping]
        skipped_rebases = [r for r in results if r.success and not r.commit_mapping]
        failed_rebases = [r for r in results if not r.success]
        
        if successful_rebases:
            print(f"\n✅ Successful rebases ({len(successful_rebases)}):")
            for result in successful_rebases:
                repo_name = os.path.basename(result.repo_path)
                commit_count = len(result.commit_mapping)
                print(f"  📁 {repo_name}: {commit_count} commits rebased")
                if result.backup_branch:
                    print(f"     Backup: {result.backup_branch}")
        
        if skipped_rebases:
            print(f"\n⏭️  Skipped rebases ({len(skipped_rebases)}):")
            for result in skipped_rebases:
                repo_name = os.path.basename(result.repo_path)
                print(f"  📁 {repo_name}: {result.error_message or 'No changes needed'}")
        
        if failed_rebases:
            print(f"\n❌ Failed rebases ({len(failed_rebases)}):")
            for result in failed_rebases:
                repo_name = os.path.basename(result.repo_path)
                print(f"  📁 {repo_name}: {result.error_message}")
        
        print("\n" + "="*80)
    
    def _confirm_push_all(self, results: List[RebaseResult]) -> bool:
        """Confirm pushing all successful rebases.
        
        Args:
            results: List of rebase results
            
        Returns:
            True if user confirms push
        """
        successful_results = [r for r in results if r.success and r.commit_mapping]
        
        if not successful_results:
            print("No repositories to push.")
            return False
        
        print(f"\n🚀 Ready to push {len(successful_results)} repositories:")
        for result in successful_results:
            repo_name = os.path.basename(result.repo_path)
            print(f"  📁 {repo_name}")
        
        while True:
            confirm = input("\nProceed with force push to all repositories? (yes/no): ").strip().lower()
            if confirm in ['yes', 'y']:
                return True
            elif confirm in ['no', 'n']:
                return False
            print("Please enter 'yes' or 'no'")
    
    def _push_all_changes(self, results: List[RebaseResult], repo_info: RepoInfo) -> None:
        """Push all successful rebases.
        
        Args:
            results: List of rebase results
            repo_info: Root repository information
        """
        successful_results = [r for r in results if r.success and r.commit_mapping]
        
        for result in successful_results:
            repo_name = os.path.basename(result.repo_path)
            
            # Find the corresponding repo info to get the branch name
            branch = self._find_branch_for_path(repo_info, result.repo_path)
            if not branch:
                print(f"⚠️  Could not find branch for {repo_name}, skipping push")
                continue
            
            print(f"\n🚀 Pushing {repo_name} (branch: {branch})")
            
            try:
                if not self.dry_run:
                    # leaving this out for testing
                    # self.git_utils.sh(['git', 'push', '--force-with-lease', 'origin', branch], cwd=result.repo_path)
                    print(f"✅ Successfully pushed {repo_name}")
                else:
                    print(f"[DRY RUN] Would push {branch} to origin")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to push {repo_name}: {e}")
        
        # After all pushes are complete, prompt for backup cleanup
        if not self.dry_run and successful_results:
            self.backup_manager.prompt_cleanup_backups_after_push(results)
    
    def _find_branch_for_path(self, repo_info: RepoInfo, target_path: str) -> Optional[str]:
        """Find the branch name for a given repository path.
        
        Args:
            repo_info: Repository information tree
            target_path: Target repository path
            
        Returns:
            Branch name if found
        """
        if os.path.abspath(repo_info.path) == os.path.abspath(target_path):
            return repo_info.branch
        
        for submodule in repo_info.submodules:
            branch = self._find_branch_for_path(submodule, target_path)
            if branch:
                return branch
        
        return None
    
    def _resume_rebase_session(self, state: RebaseState, root_path: str) -> None:
        """Resume a previous rebase session.
        
        Args:
            state: Previous rebase state
            root_path: Root repository path
        """
        print(f"🔄 Resuming rebase session {state.session_id}...")
        # Implementation would restore state and continue from where left off
        # For now, just clean up and start fresh
        print("⚠️  Resume functionality not yet implemented, starting fresh...")
        self.state_manager.cleanup_state_file(root_path)
        self.run_nested_rebase(root_path)
    
    def abort_all_active_rebases(self) -> None:
        """Abort all active rebases for cleanup."""
        if not self.active_rebases:
            return
        
        print(f"\n🛑 Aborting {len(self.active_rebases)} active rebases...")
        
        for repo_path in self.active_rebases[:]:  # Copy list to avoid modification during iteration
            try:
                # Check if there's actually a rebase in progress
                status_output = self.git_utils.sh(['git', 'status', '--porcelain'], cwd=repo_path, capture=True)
                if self.git_utils.is_rebase_in_progress(repo_path):
                    repo_name = os.path.basename(repo_path)
                    print(f"  🔄 Aborting rebase in {repo_name}")
                    self.git_utils.sh(['git', 'rebase', '--abort'], cwd=repo_path)
                    print(f"  ✅ Aborted rebase in {repo_name}")
                
                self.active_rebases.remove(repo_path)
            except subprocess.CalledProcessError as e:
                repo_name = os.path.basename(repo_path)
                print(f"  ❌ Failed to abort rebase in {repo_name}: {e}")
        
        print("🛑 All active rebases aborted")
    
    def manage_backups_interactive(self, root_path: str) -> None:
        """Manage backup branches interactively.
        
        Args:
            root_path: Root repository path
        """
        self.backup_manager.manage_backups_interactive(root_path)
