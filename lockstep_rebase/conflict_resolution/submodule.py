"""
Submodule conflict resolution for lockstep rebase operations.

This module handles automatic resolution of submodule pointer conflicts
using commit mappings from previous rebase operations.
"""

import os
import subprocess
from typing import List, Dict, Optional

from ..core.models import RepoInfo, RebaseResult
from ..core.git_utils import GitUtils


class SubmoduleConflictResolver:
    """Handles automatic resolution of submodule conflicts."""

    def __init__(self, git_utils: GitUtils):
        """Initialize submodule conflict resolver.

        Args:
            git_utils: Git utilities instance
        """
        self.git_utils = git_utils

    def resolve_conflicts_automatically(
        self,
        repo_info: RepoInfo,
        submodule_conflicts: List[str],
        all_results: List[RebaseResult],
        saved_mappings: Optional[Dict[str, Dict[str, str]]] = None
    ) -> bool:
        """Automatically resolve submodule conflicts using commit mappings.

        Args:
            repo_info: Repository information
            submodule_conflicts: List of conflicted submodule paths
            all_results: Results from previous rebase operations
            saved_mappings: Previously saved commit mappings

        Returns:
            True if all conflicts were resolved successfully
        """
        if self.git_utils.verbose:
            print(
                f"\n🔗 AUTO-RESOLVING SUBMODULE CONFLICTS in {repo_info.name}")
            print("=" * 60)

        # Build submodule commit mappings
        submodule_mappings = self._build_submodule_commit_mappings(
            repo_info, all_results, saved_mappings or {}
        )

        if self.git_utils.verbose:
            self._print_available_mappings(submodule_mappings)

        resolved_count = 0

        for submodule_path in submodule_conflicts:
            if self._resolve_single_submodule_conflict(
                    submodule_path, repo_info, submodule_mappings):
                resolved_count += 1

        if self.git_utils.verbose:
            print(
                f"\n📊 Resolved {resolved_count}/{len(submodule_conflicts)} submodule conflicts")

        return resolved_count == len(submodule_conflicts)

    def _build_submodule_commit_mappings(
        self,
        repo_info: RepoInfo,
        all_results: List[RebaseResult],
        saved_mappings: Dict[str, Dict[str, str]]
    ) -> Dict[str, Dict[str, str]]:
        """Build commit mappings for all submodules.

        Args:
            repo_info: Repository information
            all_results: Results from rebase operations
            saved_mappings: Previously saved mappings

        Returns:
            Dictionary mapping submodule paths to commit mappings
        """
        submodule_mappings = {}

        if self.git_utils.verbose:
            print(
                f"\n🔍 DEBUG: Building submodule commit mappings for {repo_info.name}")
            print(f"   Saved mappings: {len(saved_mappings)} repositories")
            for path, mapping in saved_mappings.items():
                rel_path = os.path.relpath(
                    path, repo_info.path) if os.path.isabs(path) else path
                print(f"     {rel_path}: {len(mapping)} commits")
            print(f"   Current results: {len(all_results)} repositories")
            for result in all_results:
                rel_path = os.path.relpath(
                    result.repo_path, repo_info.path) if os.path.isabs(
                    result.repo_path) else result.repo_path
                print(
                    f"     {rel_path}: {len(result.commit_mapping)} commits (success: {result.success})")

        # Collect all submodules from the repository tree
        all_submodules = self._collect_submodules(repo_info)

        for submodule in all_submodules:
            abs_path = os.path.abspath(submodule.path)
            rel_path = os.path.relpath(abs_path, repo_info.path)

            if self.git_utils.verbose:
                print(f"\n   Processing submodule: {submodule.name}")
                print(f"     Relative path: {rel_path}")
                print(f"     Absolute path: {abs_path}")

            # Check if we have a saved mapping for this submodule
            if abs_path in saved_mappings:
                submodule_mappings[rel_path] = saved_mappings[abs_path]
                if self.git_utils.verbose:
                    print(
                        f"     📂 Using saved mapping: {len(saved_mappings[abs_path])} commits")
                continue

            # Otherwise, find the rebase result for this submodule from current
            # session
            found_mapping = False
            for result in all_results:
                result_abs_path = os.path.abspath(result.repo_path)
                if self.git_utils.verbose:
                    print(f"     Comparing: {result_abs_path} vs {abs_path}")

                if result_abs_path == abs_path:
                    if result.success and result.commit_mapping:
                        submodule_mappings[rel_path] = result.commit_mapping
                        found_mapping = True
                        if self.git_utils.verbose:
                            print(
                                f"     🔄 Using current session mapping: {len(result.commit_mapping)} commits")
                    else:
                        if self.git_utils.verbose:
                            print(
                                f"     ⚠️  Found result but no mapping (success: {result.success}, mapping: {len(result.commit_mapping)})")
                    break

            if not found_mapping and self.git_utils.verbose:
                print(f"     ❌ No mapping found for {rel_path}")

        return submodule_mappings

    def _collect_submodules(self, repo_info: RepoInfo) -> List[RepoInfo]:
        """Recursively collect all submodules.

        Args:
            repo_info: Repository information

        Returns:
            Flat list of all submodules
        """
        submodules = []
        for submodule in repo_info.submodules:
            submodules.append(submodule)
            submodules.extend(self._collect_submodules(submodule))
        return submodules

    def _print_available_mappings(
            self, submodule_mappings: Dict[str, Dict[str, str]]) -> None:
        """Print available commit mappings for debugging.

        Args:
            submodule_mappings: Submodule commit mappings
        """
        print(f"\n📊 Available submodule mappings:")
        for rel_path, mapping in submodule_mappings.items():
            print(f"   {rel_path}: {len(mapping)} commit mappings")
            for old_commit, new_commit in mapping.items():
                print(f"     {old_commit} -> {new_commit}")

    def _resolve_single_submodule_conflict(
        self,
        submodule_path: str,
        repo_info: RepoInfo,
        submodule_mappings: Dict[str, Dict[str, str]]
    ) -> bool:
        """Resolve a single submodule conflict.

        Args:
            submodule_path: Path to the conflicted submodule
            repo_info: Repository information
            submodule_mappings: Available commit mappings

        Returns:
            True if conflict was resolved successfully
        """
        if self.git_utils.verbose:
            print(f"\n📦 Resolving submodule: {submodule_path}")

        try:
            # Get current HEAD submodule commit
            head_commit = self.git_utils.sh(
                ['git', 'rev-parse', f'HEAD:{submodule_path}'],
                cwd=repo_info.path,
                capture=True
            )

            if self.git_utils.verbose:
                print(f"   Current HEAD submodule commit: {head_commit}")
                try:
                    head_msg = self.git_utils.sh(
                        ['git', 'log', '--oneline', '-1', head_commit],
                        cwd=os.path.join(repo_info.path, submodule_path),
                        capture=True
                    )
                    print(f"     Message: {head_msg}")
                except subprocess.CalledProcessError:
                    pass

            # Get rebase target submodule commit
            try:
                rebase_head = self.git_utils.sh(
                    ['git', 'rev-parse', 'REBASE_HEAD'], cwd=repo_info.path, capture=True)
                target_commit = self.git_utils.sh(
                    ['git', 'rev-parse', f'{rebase_head}:{submodule_path}'],
                    cwd=repo_info.path,
                    capture=True
                )

                if self.git_utils.verbose:
                    print(
                        f"   Rebase target submodule commit: {target_commit}")
                    try:
                        target_msg = self.git_utils.sh(
                            ['git', 'log', '--oneline', '-1', target_commit],
                            cwd=os.path.join(repo_info.path, submodule_path),
                            capture=True
                        )
                        print(f"     Message: {target_msg}")
                    except subprocess.CalledProcessError:
                        pass
            except subprocess.CalledProcessError:
                if self.git_utils.verbose:
                    print("   Could not get rebase target commit")

            # Get git status for this submodule
            status = self.git_utils.sh(
                ['git', 'status', '--porcelain=v1', submodule_path],
                cwd=repo_info.path,
                capture=True
            )

            if self.git_utils.verbose:
                print(f"   Git status for {submodule_path}: {status}")

            # Get Stage 2 (HEAD) and Stage 3 (incoming) commits
            try:
                stage2_commit = self.git_utils.sh(
                    ['git', 'rev-parse', f':2:{submodule_path}'],
                    cwd=repo_info.path,
                    capture=True
                )
                if self.git_utils.verbose:
                    print(f"   Stage 2 (HEAD) commit: {stage2_commit}")
            except subprocess.CalledProcessError:
                stage2_commit = None

            try:
                stage3_commit = self.git_utils.sh(
                    ['git', 'rev-parse', f':3:{submodule_path}'],
                    cwd=repo_info.path,
                    capture=True
                )
                if self.git_utils.verbose:
                    print(f"   Stage 3 (incoming) commit: {stage3_commit}")
            except subprocess.CalledProcessError:
                stage3_commit = None

            # Try to resolve using commit mapping
            resolved = self._try_resolve_with_mapping(
                submodule_path, repo_info, submodule_mappings, stage3_commit
            )

            if resolved:
                return True

            # Fallback: accept current state
            if self.git_utils.verbose:
                print(f"   ⚠️  No mapping found, accepting current state")

            self.git_utils.sh(['git', 'add', submodule_path],
                              cwd=repo_info.path)
            if self.git_utils.verbose:
                print(f"   ✅ Accepted current state of {submodule_path}")

            return True

        except subprocess.CalledProcessError as e:
            if self.git_utils.verbose:
                print(f"   ❌ Failed to resolve {submodule_path}: {e}")
            return False

    def _try_resolve_with_mapping(
        self,
        submodule_path: str,
        repo_info: RepoInfo,
        submodule_mappings: Dict[str, Dict[str, str]],
        stage3_commit: Optional[str]
    ) -> bool:
        """Try to resolve conflict using commit mapping.

        Args:
            submodule_path: Path to the submodule
            repo_info: Repository information
            submodule_mappings: Available commit mappings
            stage3_commit: Stage 3 (incoming) commit hash

        Returns:
            True if resolved using mapping
        """
        # Normalize path separators for mapping lookup
        normalized_path = submodule_path.replace('/', '\\')

        if self.git_utils.verbose:
            print(
                f"   🔍 Looking for mapping: '{submodule_path}' (normalized: '{normalized_path}')")
            print(
                f"   Available mapping keys: {list(submodule_mappings.keys())}")

        # Try different path formats
        mapping = None
        for path_variant in [
            submodule_path,
            normalized_path,
            submodule_path.replace(
                '\\',
                '/')]:
            if path_variant in submodule_mappings:
                mapping = submodule_mappings[path_variant]
                if self.git_utils.verbose:
                    print(f"   ✅ Found mapping for key: '{path_variant}'")
                break

        if not mapping:
            if self.git_utils.verbose:
                print(f"   ❌ No mapping found for submodule path")
            return False

        # Check Stage 3 (incoming) commit for mapping
        if stage3_commit:
            if self.git_utils.verbose:
                print(f"   🔍 Checking Stage 3 (incoming) commit for mapping...")

            stage3_short = stage3_commit[:8]
            stage3_full = stage3_commit

            if self.git_utils.verbose:
                print(
                    f"   Stage 3 (incoming) commit: {stage3_short} (full: {stage3_full})")

            # Try to find mapping for Stage 3 commit
            mapped_commit = None
            for old_commit, new_commit in mapping.items():
                if (old_commit == stage3_short or
                    old_commit == stage3_full or
                    stage3_short.startswith(old_commit) or
                        stage3_full.startswith(old_commit)):
                    mapped_commit = new_commit
                    if self.git_utils.verbose:
                        print(
                            f"   ✅ Found mapping (short hash): {old_commit} -> {new_commit}")
                    break

            if mapped_commit:
                return self._apply_mapping(
                    submodule_path, repo_info, mapped_commit)
            else:
                if self.git_utils.verbose:
                    print(
                        f"   ⚠️  No mapping found for Stage 3 commit {stage3_short}")
                    print(
                        f"   Available mappings: {[f'{k}->{v}' for k, v in mapping.items()]}")

        return False

    def _apply_mapping(
            self,
            submodule_path: str,
            repo_info: RepoInfo,
            mapped_commit: str) -> bool:
        """Apply commit mapping to resolve conflict.

        Args:
            submodule_path: Path to the submodule
            repo_info: Repository information
            mapped_commit: Mapped commit hash to use

        Returns:
            True if mapping was applied successfully
        """
        try:
            submodule_full_path = os.path.join(repo_info.path, submodule_path)

            # Checkout the mapped commit in the submodule
            self.git_utils.sh(
                ['git', 'checkout', mapped_commit], cwd=submodule_full_path)

            # Add the submodule to resolve the conflict
            self.git_utils.sh(['git', 'add', submodule_path],
                              cwd=repo_info.path)

            if self.git_utils.verbose:
                print(
                    f"   ✅ Updated {submodule_path} to rebased commit {mapped_commit}")

            return True

        except subprocess.CalledProcessError as e:
            if self.git_utils.verbose:
                print(f"   ❌ Failed to apply mapping: {e}")
            return False
