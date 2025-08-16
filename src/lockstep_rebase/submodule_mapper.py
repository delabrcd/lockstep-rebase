"""
Submodule discovery and hierarchy mapping.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from git import Repo, InvalidGitRepositoryError

from .models import RepoInfo, SubmoduleError, HierarchyEntry
from .prompt_interface import UserPrompt, NoOpPrompt, BranchSyncAction
from .git_manager import GitManager


logger = logging.getLogger(__name__)


class SubmoduleMapper:
    """Maps and manages Git submodule hierarchies."""

    def __init__(self, root_repo_path: Path) -> None:
        """Initialize with root repository path."""
        self.root_repo_path = Path(root_repo_path).resolve()
        self._repo_cache: Dict[Path, Repo] = {}

    def _get_repo(self, repo_path: Path) -> Repo:
        """Get or create a cached Repo instance."""
        repo_path = repo_path.resolve()
        if repo_path not in self._repo_cache:
            try:
                self._repo_cache[repo_path] = Repo(repo_path)
            except InvalidGitRepositoryError as e:
                raise SubmoduleError(f"Invalid Git repository at {repo_path}") from e
        return self._repo_cache[repo_path]

    def discover_repository_hierarchy(self) -> RepoInfo:
        """
        Discover the complete repository hierarchy starting from root.

        Returns:
            RepoInfo tree with all submodules mapped
        """
        try:
            root_repo = self._get_repo(self.root_repo_path)
            root_info = RepoInfo(
                path=self.root_repo_path, name=self.root_repo_path.name, is_submodule=False, depth=0
            )

            # Recursively discover submodules
            self._discover_submodules_recursive(root_info, root_repo)

            logger.info(
                f"Discovered repository hierarchy with {self._count_repos(root_info)} repositories"
            )
            return root_info

        except Exception as e:
            logger.error(f"Error discovering repository hierarchy: {e}")
            raise SubmoduleError(f"Failed to discover repository hierarchy: {e}")

    def _discover_submodules_recursive(self, parent_info: RepoInfo, parent_repo: Repo) -> None:
        """Recursively discover submodules for a repository."""
        try:
            # Get submodules from .gitmodules file
            if not hasattr(parent_repo, "submodules"):
                return

            for submodule in parent_repo.submodules:
                submodule_path = Path(parent_repo.working_dir) / submodule.path

                # Skip if submodule directory doesn't exist or isn't initialized
                if not submodule_path.exists() or not (submodule_path / ".git").exists():
                    logger.warning(
                        f"Submodule {submodule.name} at {submodule_path} is not initialized"
                    )
                    continue

                try:
                    submodule_repo = self._get_repo(submodule_path)
                    submodule_info = RepoInfo(
                        path=submodule_path,
                        name=submodule.name,
                        is_submodule=True,
                        parent_repo=parent_info,
                        depth=parent_info.depth + 1,
                    )

                    parent_info.submodules.append(submodule_info)

                    # Recursively discover nested submodules
                    self._discover_submodules_recursive(submodule_info, submodule_repo)

                    logger.debug(
                        f"Discovered submodule: {submodule_info.name} at depth {submodule_info.depth}"
                    )

                except Exception as e:
                    logger.error(f"Error processing submodule {submodule.name}: {e}")
                    continue

        except Exception as e:
            logger.error(f"Error discovering submodules for {parent_info.name}: {e}")

    def _count_repos(self, repo_info: RepoInfo) -> int:
        """Count total number of repositories in the hierarchy."""
        count = 1  # Count this repo
        for submodule in repo_info.submodules:
            count += self._count_repos(submodule)
        return count

    def get_repositories_by_depth(self, root_info: RepoInfo) -> Dict[int, List[RepoInfo]]:
        """
        Get repositories organized by depth level.

        Returns:
            Dictionary mapping depth to list of repositories at that depth
        """
        depth_map: Dict[int, List[RepoInfo]] = {}
        self._collect_by_depth(root_info, depth_map)
        return depth_map

    def _collect_by_depth(self, repo_info: RepoInfo, depth_map: Dict[int, List[RepoInfo]]) -> None:
        """Recursively collect repositories by depth."""
        if repo_info.depth not in depth_map:
            depth_map[repo_info.depth] = []
        depth_map[repo_info.depth].append(repo_info)

        for submodule in repo_info.submodules:
            self._collect_by_depth(submodule, depth_map)

    def get_rebase_order(self, root_info: RepoInfo) -> List[RepoInfo]:
        """
        Get repositories in the order they should be rebased.

        Repositories are ordered from deepest (leaf submodules) to shallowest (root).
        This ensures that submodule commits are rebased before their parent repositories.

        Returns:
            List of RepoInfo in rebase order
        """
        depth_map = self.get_repositories_by_depth(root_info)
        rebase_order = []

        # Sort by depth (deepest first)
        for depth in sorted(depth_map.keys(), reverse=True):
            rebase_order.extend(depth_map[depth])

        logger.info(f"Rebase order determined for {len(rebase_order)} repositories")
        return rebase_order

    def validate_branches_exist(
        self, root_info: RepoInfo, source_branch: str, target_branch: str, prompt: UserPrompt = None
    ) -> Dict[str, List[str]]:
        """
        Validate that required branches exist in all repositories.

        Args:
            root_info: Root repository information
            source_branch: Source branch name
            target_branch: Target branch name
            prompt: Optional prompt interface for user interactions

        Returns:
            Dictionary with 'missing_source' and 'missing_target' keys containing
            lists of repository names where branches are missing
        """
        if prompt is None:
            prompt = NoOpPrompt()

        missing_branches = {"missing_source": [], "missing_target": []}
        sync_issues = {}

        all_repos = self._get_all_repositories(root_info)

        for repo_info in all_repos:
            try:
                repo = self._get_repo(repo_info.path)

                # Check and handle source branch
                source_result = self._check_and_handle_branch(
                    repo, repo_info, source_branch, prompt
                )
                if not source_result["exists"]:
                    missing_branches["missing_source"].append(repo_info.name)
                if source_result.get("sync_issue"):
                    sync_issues[repo_info.name] = source_result["sync_issue"]

                # Check and handle target branch
                target_result = self._check_and_handle_branch(
                    repo, repo_info, target_branch, prompt
                )
                if not target_result["exists"]:
                    missing_branches["missing_target"].append(repo_info.name)
                if target_result.get("sync_issue"):
                    if repo_info.name not in sync_issues:
                        sync_issues[repo_info.name] = {}
                    sync_issues[repo_info.name].update(target_result["sync_issue"])

            except Exception as e:
                logger.error(f"Error validating branches for {repo_info.name}: {e}")
                missing_branches["missing_source"].append(repo_info.name)
                missing_branches["missing_target"].append(repo_info.name)

        # Show validation summary if there are issues
        if missing_branches["missing_source"] or missing_branches["missing_target"] or sync_issues:
            prompt.show_validation_summary(missing_branches, sync_issues)

        return missing_branches

    def _check_and_handle_branch(
        self, repo: Repo, repo_info: RepoInfo, branch_name: str, prompt: UserPrompt
    ) -> Dict[str, any]:
        """Check if branch exists and handle missing/out-of-sync branches."""
        result = {"exists": False, "sync_issue": None}

        try:
            gm = GitManager(Path(repo.working_dir))
            # Check if branch exists locally / remotely via GitManager
            local_exists = gm.branch_exists(branch_name)
            remote_exists = gm.remote_branch_exists(branch_name, "origin")

            if local_exists:
                result["exists"] = True

                # Check if local branch is in sync with remote
                if remote_exists:
                    sync_status = self._check_branch_sync(repo, branch_name)
                    if sync_status["needs_sync"]:
                        action = prompt.confirm_sync_branch(
                            repo_info.name,
                            branch_name,
                            sync_status["local_commit"],
                            sync_status["remote_commit"],
                            sync_status["commits_behind"],
                            sync_status["commits_ahead"],
                        )

                        if action == BranchSyncAction.SYNC_LOCAL:
                            self._sync_local_branch(repo, branch_name)
                        elif action == BranchSyncAction.ABORT:
                            result["exists"] = False
                        else:
                            result["sync_issue"] = {
                                branch_name: f"Local branch is {sync_status['commits_behind']} commits behind and {sync_status['commits_ahead']} commits ahead of origin"
                            }

            elif remote_exists:
                # Local doesn't exist but remote does
                if prompt.confirm_use_remote_branch(repo_info.name, branch_name):
                    if prompt.confirm_create_local_branch(repo_info.name, branch_name):
                        # Delegate creation to GitManager to avoid duplication
                        gm.create_local_branch_from_remote(branch_name, "origin")
                        result["exists"] = True
                    else:
                        # Use remote branch directly (checkout will handle this)
                        result["exists"] = True

            return result

        except Exception as e:
            logger.error(f"Error checking branch {branch_name} in {repo_info.name}: {e}")
            return result

    def _branch_exists_locally(self, repo: Repo, branch_name: str) -> bool:
        """Check if a branch exists locally (delegates to GitManager)."""
        try:
            gm = GitManager(Path(repo.working_dir))
            return gm.branch_exists(branch_name)
        except Exception as e:
            logger.debug(f"Error checking local branches: {e}")
            return False

    def _branch_exists_remotely(
        self, repo: Repo, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        """Check if a branch exists on remote (delegates to GitManager)."""
        try:
            gm = GitManager(Path(repo.working_dir))
            return gm.remote_branch_exists(branch_name, remote_name)
        except Exception as e:
            logger.debug(f"Error checking remote branches: {e}")
            return False

    def _check_branch_sync(
        self, repo: Repo, branch_name: str, remote_name: str = "origin"
    ) -> Dict[str, any]:
        """Check if local branch is in sync with remote."""
        try:
            local_ref = repo.heads[branch_name]
            remote_ref = getattr(repo.remotes, remote_name).refs[branch_name]

            local_commit = local_ref.commit
            remote_commit = remote_ref.commit

            if local_commit == remote_commit:
                return {"needs_sync": False}

            # Count commits behind and ahead
            commits_behind = list(repo.iter_commits(f"{local_commit}..{remote_commit}"))
            commits_ahead = list(repo.iter_commits(f"{remote_commit}..{local_commit}"))

            return {
                "needs_sync": True,
                "local_commit": str(local_commit)[:8],
                "remote_commit": str(remote_commit)[:8],
                "commits_behind": len(commits_behind),
                "commits_ahead": len(commits_ahead),
            }

        except Exception as e:
            logger.debug(f"Error checking branch sync for {branch_name}: {e}")
            return {"needs_sync": False}

    def _sync_local_branch(self, repo: Repo, branch_name: str, remote_name: str = "origin") -> None:
        """Sync local branch with remote (fast-forward or reset)."""
        try:
            # Checkout the branch
            repo.heads[branch_name].checkout()

            # Fetch latest from remote
            origin = getattr(repo.remotes, remote_name)
            origin.fetch()

            # Reset to remote branch
            remote_ref = origin.refs[branch_name]
            repo.head.reset(remote_ref, index=True, working_tree=True)

            logger.info(f"Synced local branch {branch_name} with {remote_name}/{branch_name}")

        except Exception as e:
            logger.error(f"Error syncing branch {branch_name}: {e}")
            raise

    def _create_local_branch_from_remote(
        self, repo: Repo, branch_name: str, remote_name: str = "origin"
    ) -> None:
        """Create a local branch from a remote-tracking branch (delegates to GitManager)."""
        try:
            gm = GitManager(Path(repo.working_dir))
            gm.create_local_branch_from_remote(branch_name, remote_name)
        except Exception as e:
            logger.error(f"Error creating local branch {branch_name}: {e}")
            raise

    def _branch_exists(self, repo: Repo, branch_name: str) -> bool:
        """Check if a branch exists in the repository (local or remote)."""
        return self._branch_exists_locally(repo, branch_name) or self._branch_exists_remotely(
            repo, branch_name
        )

    def _get_all_repositories(self, root_info: RepoInfo) -> List[RepoInfo]:
        """Get a flat list of all repositories in the hierarchy."""
        all_repos = [root_info]
        for submodule in root_info.submodules:
            all_repos.extend(self._get_all_repositories(submodule))
        return all_repos

    def get_repository_by_path(self, root_info: RepoInfo, target_path: Path) -> Optional[RepoInfo]:
        """Find a repository in the hierarchy by its path."""
        target_path = target_path.resolve()

        if root_info.path == target_path:
            return root_info

        for submodule in root_info.submodules:
            result = self.get_repository_by_path(submodule, target_path)
            if result:
                return result

        return None

    def get_hierarchy_lines(self, root_info: RepoInfo, indent: int = 0) -> List[str]:
        """Build and return hierarchy lines for the given repository tree."""
        prefix = "  " * indent
        repo_type = "submodule" if root_info.is_submodule else "root"
        lines = [f"{prefix}{root_info.name} ({repo_type}) - depth {root_info.depth}"]

        for submodule in root_info.submodules:
            lines.extend(self.get_hierarchy_lines(submodule, indent + 1))

        return lines

    def get_hierarchy_entries(self, root_info: RepoInfo) -> List[HierarchyEntry]:
        """Return structured hierarchy entries for UI formatting."""
        entries: List[HierarchyEntry] = []

        def _collect(repo: RepoInfo, parent_name: Optional[str]) -> None:
            entries.append(
                HierarchyEntry(
                    name=repo.name,
                    path=repo.path,
                    depth=repo.depth,
                    is_submodule=repo.is_submodule,
                    parent_name=parent_name,
                )
            )
            for sm in repo.submodules:
                _collect(sm, repo.name)

        _collect(root_info, None)
        return entries
