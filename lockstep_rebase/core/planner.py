"""
Rebase planning for lockstep operations.

This module provides proactive analysis and planning for submodule pointer
mappings during rebase operations, enabling deterministic conflict resolution.
"""

import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .models import RepoInfo, RebaseResult
from .git_utils import GitUtils


@dataclass
class CommitPlan:
    """Plan for handling a single commit during rebase."""
    old_commit: str
    old_commit_message: str
    new_commit: Optional[str] = None  # Filled during rebase execution
    submodule_targets: Dict[str, str] = field(
        default_factory=dict)  # submodule_path -> target_commit

    def __post_init__(self):
        if self.submodule_targets is None:
            self.submodule_targets = {}


@dataclass
class RebasePlan:
    """Complete plan for handling submodule pointers during a repository rebase."""
    repo_path: str
    branch: str
    base: str
    commit_plans: List[CommitPlan] = field(default_factory=list)
    submodule_mappings: Dict[str, Dict[str, str]] = field(
        default_factory=dict)  # submodule_path -> {old_commit -> new_commit}

    def __post_init__(self):
        if self.commit_plans is None:
            self.commit_plans = []
        if self.submodule_mappings is None:
            self.submodule_mappings = {}


class RebasePlanner:
    """Proactive planner for lockstep rebase operations."""

    def __init__(self, git_utils: GitUtils):
        """Initialize the rebase planner.

        Args:
            git_utils: Git utilities instance
        """
        self.git_utils = git_utils

    def create_rebase_plan(
        self,
        repo_info: RepoInfo,
        submodule_results: List[RebaseResult]
    ) -> RebasePlan:
        """Create a comprehensive rebase plan for a repository.

        Args:
            repo_info: Repository information
            submodule_results: Results from submodule rebases (for mapping)

        Returns:
            Complete rebase plan with submodule targets
        """
        if not repo_info.branch or not repo_info.base:
            # No rebase needed
            return RebasePlan(
                repo_path=repo_info.path,
                branch=repo_info.branch or "",
                base=repo_info.base or ""
            )

        if self.git_utils.verbose:
            print(f"\n📋 Creating rebase plan for {repo_info.name}")
            print(f"   Branch: {repo_info.branch} -> Base: {repo_info.base}")

        # Create the plan
        plan = RebasePlan(
            repo_path=repo_info.path,
            branch=repo_info.branch,
            base=repo_info.base
        )

        # Build submodule mappings from results
        plan.submodule_mappings = self._build_submodule_mappings(
            repo_info, submodule_results)

        # Get commits to be rebased
        commits_to_rebase = self._get_commits_to_rebase(repo_info)

        if self.git_utils.verbose:
            print(f"   📊 Found {len(commits_to_rebase)} commits to rebase")

        # Create plan for each commit
        for i, commit in enumerate(commits_to_rebase):
            commit_plan = self._create_commit_plan(
                repo_info, commit, plan.submodule_mappings)
            plan.commit_plans.append(commit_plan)

            if self.git_utils.verbose:
                submodule_count = len(commit_plan.submodule_targets)
                print(
                    f"   📝 Commit {i+1}/{len(commits_to_rebase)}: {commit[:8]} ({submodule_count} submodules)")

        return plan

    def _build_submodule_mappings(
        self,
        repo_info: RepoInfo,
        submodule_results: List[RebaseResult]
    ) -> Dict[str, Dict[str, str]]:
        """Build submodule commit mappings from rebase results.

        Args:
            repo_info: Repository information
            submodule_results: Results from submodule rebases

        Returns:
            Dictionary mapping submodule paths to commit mappings
        """
        mappings = {}

        # Process each submodule result
        for result in submodule_results:
            if not result.success or not result.commit_mapping:
                continue

            # Calculate relative path from this repo to the submodule
            try:
                rel_path = os.path.relpath(result.repo_path, repo_info.path)
                # Normalize path separators
                rel_path = rel_path.replace('\\', '/')
                mappings[rel_path] = result.commit_mapping

                if self.git_utils.verbose:
                    print(
                        f"   🔗 Mapped submodule: {rel_path} ({len(result.commit_mapping)} commits)")
            except ValueError:
                # Paths are on different drives or not related
                if self.git_utils.verbose:
                    print(
                        f"   ⚠️  Skipping unrelated submodule: {result.repo_path}")
                continue

        return mappings

    def _get_commits_to_rebase(self, repo_info: RepoInfo) -> List[str]:
        """Get the list of commits that will be rebased.

        Args:
            repo_info: Repository information

        Returns:
            List of commit hashes in reverse chronological order (oldest first)
        """
        try:
            # Get commits between base and branch (oldest first for rebase
            # order)
            output = self.git_utils.sh([
                'git', 'rev-list', '--reverse', f'{repo_info.base}..{repo_info.branch}'
            ], cwd=repo_info.path, capture=True)

            commits = [line.strip()
                       for line in output.split('\n') if line.strip()]
            return commits
        except subprocess.CalledProcessError:
            if self.git_utils.verbose:
                print(f"   ⚠️  Could not get commits to rebase")
            return []

    def _create_commit_plan(
        self,
        repo_info: RepoInfo,
        commit: str,
        submodule_mappings: Dict[str, Dict[str, str]]
    ) -> CommitPlan:
        """Create a plan for handling a single commit.

        Args:
            repo_info: Repository information
            commit: Commit hash to plan for
            submodule_mappings: Available submodule mappings

        Returns:
            Plan for this commit
        """
        # Get commit message
        try:
            commit_message = self.git_utils.sh([
                'git', 'log', '--format=%s', '-n', '1', commit
            ], cwd=repo_info.path, capture=True)
        except subprocess.CalledProcessError:
            commit_message = f"Commit {commit[:8]}"

        # Create the plan
        plan = CommitPlan(
            old_commit=commit,
            old_commit_message=commit_message
        )

        # Find submodules in this commit and calculate their targets
        submodules_in_commit = self._get_submodules_in_commit(
            repo_info, commit)

        for submodule_path in submodules_in_commit:
            target_commit = self._calculate_submodule_target(
                repo_info, commit, submodule_path, submodule_mappings
            )

            if target_commit:
                plan.submodule_targets[submodule_path] = target_commit

                if self.git_utils.verbose:
                    old_commit = self._get_submodule_commit_in_commit(
                        repo_info, commit, submodule_path)
                    print(
                        f"     📦 {submodule_path}: {old_commit[:8] if old_commit else 'None'} -> {target_commit[:8]}")

        return plan

    def _get_submodules_in_commit(
            self,
            repo_info: RepoInfo,
            commit: str) -> List[str]:
        """Get list of submodules present in a commit.

        Args:
            repo_info: Repository information
            commit: Commit hash

        Returns:
            List of submodule paths
        """
        try:
            # Get all files in the commit with their modes
            output = self.git_utils.sh([
                'git', 'ls-tree', '-r', commit
            ], cwd=repo_info.path, capture=True)

            submodules = []
            for line in output.split('\n'):
                if line.strip() and '160000' in line:  # Submodule mode
                    # Format: "mode type hash\tpath"
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        submodule_path = parts[1]
                        submodules.append(submodule_path)

            return submodules
        except subprocess.CalledProcessError:
            return []

    def _get_submodule_commit_in_commit(
        self,
        repo_info: RepoInfo,
        commit: str,
        submodule_path: str
    ) -> Optional[str]:
        """Get the submodule commit hash for a specific commit.

        Args:
            repo_info: Repository information
            commit: Parent commit hash
            submodule_path: Path to the submodule

        Returns:
            Submodule commit hash or None
        """
        try:
            submodule_commit = self.git_utils.sh([
                'git', 'rev-parse', f'{commit}:{submodule_path}'
            ], cwd=repo_info.path, capture=True)
            return submodule_commit
        except subprocess.CalledProcessError:
            return None

    def _calculate_submodule_target(
        self,
        repo_info: RepoInfo,
        commit: str,
        submodule_path: str,
        submodule_mappings: Dict[str, Dict[str, str]]
    ) -> Optional[str]:
        """Calculate what a submodule pointer should become after rebase.

        Args:
            repo_info: Repository information
            commit: Parent commit being rebased
            submodule_path: Path to the submodule
            submodule_mappings: Available commit mappings

        Returns:
            Target commit hash for the submodule
        """
        # Get the current submodule commit in this commit
        old_submodule_commit = self._get_submodule_commit_in_commit(
            repo_info, commit, submodule_path
        )

        if not old_submodule_commit:
            return None

        # Normalize submodule path for lookup
        normalized_path = submodule_path.replace('\\', '/')

        # Try different path formats to find mapping
        for path_variant in [
            submodule_path,
            normalized_path,
            submodule_path.replace(
                '/',
                '\\')]:
            if path_variant in submodule_mappings:
                mapping = submodule_mappings[path_variant]

                # Try to find mapping for this commit (both short and full
                # hash)
                old_short = old_submodule_commit[:8]
                old_full = old_submodule_commit

                for old_commit, new_commit in mapping.items():
                    if (old_commit == old_short or
                        old_commit == old_full or
                        old_short.startswith(old_commit) or
                            old_full.startswith(old_commit)):
                        return new_commit

                # If no mapping found, the submodule commit might not have changed
                # Check if the old commit exists in the rebased submodule
                submodule_full_path = os.path.join(
                    repo_info.path, submodule_path)
                if os.path.exists(submodule_full_path):
                    try:
                        # Check if the old commit still exists (might be
                        # unchanged)
                        self.git_utils.sh([
                            'git', 'rev-parse', '--verify', f'{old_submodule_commit}^{{commit}}'
                        ], cwd=submodule_full_path, capture=True)

                        # Commit exists, use it as-is
                        return old_submodule_commit
                    except subprocess.CalledProcessError:
                        # Commit doesn't exist, can't map it
                        pass

                break

        # No mapping found - this might be a problem
        if self.git_utils.verbose:
            print(
                f"     ⚠️  No mapping found for {submodule_path}:{old_submodule_commit[:8]}")

        return None

    def get_plan_for_commit(
            self,
            plan: RebasePlan,
            old_commit: str) -> Optional[CommitPlan]:
        """Get the plan for a specific commit.

        Args:
            plan: Rebase plan
            old_commit: Original commit hash

        Returns:
            Commit plan or None if not found
        """
        for commit_plan in plan.commit_plans:
            if commit_plan.old_commit.startswith(
                    old_commit) or old_commit.startswith(commit_plan.old_commit):
                return commit_plan
        return None
