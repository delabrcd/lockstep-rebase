"""
Planned submodule conflict resolution.

This module provides conflict resolution using pre-calculated rebase plans,
enabling deterministic and reliable submodule pointer updates.
"""

import os
import subprocess
from typing import List, Optional

from ..core.models import RepoInfo
from ..core.git_utils import GitUtils
from ..core.planner import RebasePlan, CommitPlan


class PlannedSubmoduleResolver:
    """Resolve submodule conflicts using pre-calculated rebase plans."""

    def __init__(self, git_utils: GitUtils):
        """Initialize the planned resolver.

        Args:
            git_utils: Git utilities instance
        """
        self.git_utils = git_utils

    def resolve_conflicts_with_plan(
        self,
        repo_info: RepoInfo,
        plan: RebasePlan,
        current_commit: Optional[str] = None
    ) -> bool:
        """Resolve submodule conflicts using the rebase plan.

        Args:
            repo_info: Repository information
            plan: Pre-calculated rebase plan
            current_commit: Current commit being rebased (if known)

        Returns:
            True if conflicts were resolved, False otherwise
        """
        if self.git_utils.verbose:
            print(f"\n🎯 Resolving conflicts with plan for {repo_info.name}")

        # Get conflicted files
        conflicted_files = self._get_conflicted_submodules(repo_info)

        if not conflicted_files:
            if self.git_utils.verbose:
                print("   ✅ No submodule conflicts found")
            return True

        if self.git_utils.verbose:
            print(f"   📋 Found {len(conflicted_files)} conflicted submodules")

        # Try to determine which commit we're rebasing
        commit_plan = self._find_current_commit_plan(
            repo_info, plan, current_commit)

        if not commit_plan:
            if self.git_utils.verbose:
                print("   ⚠️  Could not determine current commit plan")
            return self._fallback_resolution(repo_info, conflicted_files, plan)

        if self.git_utils.verbose:
            print(
                f"   📝 Using plan for commit: {commit_plan.old_commit[:8]} - {commit_plan.old_commit_message}")

        # Resolve each conflicted submodule
        resolved_count = 0
        for submodule_path in conflicted_files:
            if self._resolve_submodule_with_plan(
                    repo_info, submodule_path, commit_plan):
                resolved_count += 1

        success = resolved_count == len(conflicted_files)

        if self.git_utils.verbose:
            if success:
                print(
                    f"   ✅ Successfully resolved all {resolved_count} submodule conflicts")
            else:
                print(
                    f"   ⚠️  Resolved {resolved_count}/{len(conflicted_files)} submodule conflicts")

        return success

    def _get_conflicted_submodules(self, repo_info: RepoInfo) -> List[str]:
        """Get list of conflicted submodule paths.

        Args:
            repo_info: Repository information

        Returns:
            List of conflicted submodule paths
        """
        try:
            # Get conflicted files
            output = self.git_utils.sh([
                'git', 'diff', '--name-only', '--diff-filter=U'
            ], cwd=repo_info.path, capture=True)

            conflicted_files = [f.strip()
                                for f in output.split('\n') if f.strip()]

            # Filter for submodules only
            submodule_conflicts = []
            for file_path in conflicted_files:
                if self._is_submodule_path(repo_info, file_path):
                    submodule_conflicts.append(file_path)

            return submodule_conflicts
        except subprocess.CalledProcessError:
            return []

    def _is_submodule_path(self, repo_info: RepoInfo, file_path: str) -> bool:
        """Check if a file path represents a submodule.

        Args:
            repo_info: Repository information
            file_path: File path to check

        Returns:
            True if the path is a submodule
        """
        try:
            # Check if it's listed as a submodule
            self.git_utils.sh([
                'git', 'ls-files', '--stage', file_path
            ], cwd=repo_info.path, capture=True)

            # Get the file mode
            output = self.git_utils.sh([
                'git', 'ls-files', '--stage', file_path
            ], cwd=repo_info.path, capture=True)

            # Submodules have mode 160000
            return '160000' in output
        except subprocess.CalledProcessError:
            return False

    def _find_current_commit_plan(
        self,
        repo_info: RepoInfo,
        plan: RebasePlan,
        current_commit: Optional[str] = None
    ) -> Optional[CommitPlan]:
        """Find the commit plan for the current rebase state.

        Args:
            repo_info: Repository information
            plan: Rebase plan
            current_commit: Hint about current commit

        Returns:
            Matching commit plan or None
        """
        # If we have a hint, try to use it
        if current_commit:
            for commit_plan in plan.commit_plans:
                if (commit_plan.old_commit.startswith(current_commit) or
                        current_commit.startswith(commit_plan.old_commit)):
                    return commit_plan

        # Try to determine from rebase state
        try:
            # Check if we're in a rebase
            rebase_head_name = os.path.join(
                repo_info.path, '.git', 'rebase-merge', 'head-name')
            rebase_onto = os.path.join(
                repo_info.path, '.git', 'rebase-merge', 'onto')

            if os.path.exists(
                    rebase_head_name) and os.path.exists(rebase_onto):
                # We're in an interactive rebase, try to get current commit
                try:
                    # Get the commit being applied
                    output = self.git_utils.sh([
                        'git', 'rev-parse', 'REBASE_HEAD'
                    ], cwd=repo_info.path, capture=True)

                    rebase_head = output.strip()

                    # Find matching plan
                    for commit_plan in plan.commit_plans:
                        if (commit_plan.old_commit.startswith(rebase_head)
                                or rebase_head.startswith(commit_plan.old_commit)):
                            return commit_plan
                except subprocess.CalledProcessError:
                    pass
        except Exception:
            pass

        # Fallback: try to match based on commit message or other heuristics
        try:
            # Get the last commit message
            last_commit_msg = self.git_utils.sh([
                'git', 'log', '--format=%s', '-n', '1', 'HEAD'
            ], cwd=repo_info.path, capture=True)

            # Find plan with matching message
            for commit_plan in plan.commit_plans:
                if commit_plan.old_commit_message.strip() == last_commit_msg.strip():
                    return commit_plan
        except subprocess.CalledProcessError:
            pass

        return None

    def _resolve_submodule_with_plan(
        self,
        repo_info: RepoInfo,
        submodule_path: str,
        commit_plan: CommitPlan
    ) -> bool:
        """Resolve a single submodule conflict using the commit plan.

        Args:
            repo_info: Repository information
            submodule_path: Path to the conflicted submodule
            commit_plan: Plan for the current commit

        Returns:
            True if resolved successfully
        """
        # Normalize path for lookup
        normalized_path = submodule_path.replace('\\', '/')

        # Find target commit in the plan
        target_commit = None
        for path_variant in [
            submodule_path,
            normalized_path,
            submodule_path.replace(
                '/',
                '\\')]:
            if path_variant in commit_plan.submodule_targets:
                target_commit = commit_plan.submodule_targets[path_variant]
                break

        if not target_commit:
            if self.git_utils.verbose:
                print(
                    f"     ❌ No target found for {submodule_path} in commit plan")
            return False

        if self.git_utils.verbose:
            print(f"     🎯 Resolving {submodule_path} -> {target_commit[:8]}")

        try:
            # Update the submodule pointer
            full_submodule_path = os.path.join(repo_info.path, submodule_path)

            # Checkout the target commit in the submodule
            self.git_utils.sh([
                'git', 'checkout', target_commit
            ], cwd=full_submodule_path)

            # Stage the submodule change in the parent repo
            self.git_utils.sh([
                'git', 'add', submodule_path
            ], cwd=repo_info.path)

            if self.git_utils.verbose:
                print(f"     ✅ Successfully resolved {submodule_path}")

            return True
        except subprocess.CalledProcessError as e:
            if self.git_utils.verbose:
                print(f"     ❌ Failed to resolve {submodule_path}: {e}")
            return False

    def _fallback_resolution(
        self,
        repo_info: RepoInfo,
        conflicted_files: List[str],
        plan: RebasePlan
    ) -> bool:
        """Fallback resolution when commit plan cannot be determined.

        Args:
            repo_info: Repository information
            conflicted_files: List of conflicted submodule paths
            plan: Rebase plan

        Returns:
            True if conflicts were resolved
        """
        if self.git_utils.verbose:
            print("   🔄 Using fallback resolution strategy")

        resolved_count = 0

        for submodule_path in conflicted_files:
            # Try to resolve using any available mapping
            if self._fallback_resolve_submodule(
                    repo_info, submodule_path, plan):
                resolved_count += 1

        success = resolved_count == len(conflicted_files)

        if self.git_utils.verbose:
            if success:
                print(f"   ✅ Fallback resolved all {resolved_count} conflicts")
            else:
                print(
                    f"   ⚠️  Fallback resolved {resolved_count}/{len(conflicted_files)} conflicts")

        return success

    def _fallback_resolve_submodule(
        self,
        repo_info: RepoInfo,
        submodule_path: str,
        plan: RebasePlan
    ) -> bool:
        """Fallback resolution for a single submodule.

        Args:
            repo_info: Repository information
            submodule_path: Path to the conflicted submodule
            plan: Rebase plan

        Returns:
            True if resolved successfully
        """
        try:
            # Get the conflicted commits (stages 2 and 3)
            output = self.git_utils.sh([
                'git', 'ls-files', '--stage', submodule_path
            ], cwd=repo_info.path, capture=True)

            stage_commits = {}
            for line in output.split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 3:
                        stage = parts[2]  # Stage number
                        commit = parts[1]  # Commit hash
                        stage_commits[stage] = commit

            # Try to map the incoming commit (stage 3)
            if '3' in stage_commits:
                incoming_commit = stage_commits['3']

                # Look for this commit in any submodule mapping
                normalized_path = submodule_path.replace('\\', '/')

                for path_variant in [
                    submodule_path,
                    normalized_path,
                    submodule_path.replace(
                        '/',
                        '\\')]:
                    if path_variant in plan.submodule_mappings:
                        mapping = plan.submodule_mappings[path_variant]

                        # Try to find mapping for this commit
                        for old_commit, new_commit in mapping.items():
                            if (old_commit == incoming_commit or
                                old_commit == incoming_commit[:8] or
                                    incoming_commit.startswith(old_commit)):

                                # Found a mapping, use it
                                return self._apply_submodule_resolution(
                                    repo_info, submodule_path, new_commit
                                )

            # No mapping found, try using the incoming commit as-is
            if '3' in stage_commits:
                return self._apply_submodule_resolution(
                    repo_info, submodule_path, stage_commits['3']
                )

            return False
        except subprocess.CalledProcessError:
            return False

    def _apply_submodule_resolution(
        self,
        repo_info: RepoInfo,
        submodule_path: str,
        target_commit: str
    ) -> bool:
        """Apply a submodule resolution.

        Args:
            repo_info: Repository information
            submodule_path: Path to the submodule
            target_commit: Target commit hash

        Returns:
            True if applied successfully
        """
        try:
            full_submodule_path = os.path.join(repo_info.path, submodule_path)

            # Checkout the target commit
            self.git_utils.sh([
                'git', 'checkout', target_commit
            ], cwd=full_submodule_path)

            # Stage the change
            self.git_utils.sh([
                'git', 'add', submodule_path
            ], cwd=repo_info.path)

            if self.git_utils.verbose:
                print(
                    f"     ✅ Applied resolution: {submodule_path} -> {target_commit[:8]}")

            return True
        except subprocess.CalledProcessError as e:
            if self.git_utils.verbose:
                print(f"     ❌ Failed to apply resolution: {e}")
            return False
