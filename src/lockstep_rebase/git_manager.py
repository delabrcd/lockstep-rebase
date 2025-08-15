"""
Git repository management and operations.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple
from git import Repo, InvalidGitRepositoryError

from .models import CommitInfo, GitRepositoryError, RepoInfo


logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git operations for repositories and submodules."""

    def __init__(self, repo_path: Optional[Path] = None) -> None:
        """Initialize Git manager with optional repository path."""
        self.repo_path = repo_path or Path.cwd()
        self._repo: Optional[Repo] = None

    @property
    def repo(self) -> Repo:
        """Get the Git repository instance."""
        if self._repo is None:
            self._repo = self._discover_repository()
        return self._repo

    def _discover_repository(self) -> Repo:
        """Discover the Git repository from current or specified path."""
        search_path = self.repo_path

        # Walk up the directory tree to find a Git repository
        while search_path != search_path.parent:
            try:
                repo = Repo(search_path)
                logger.info(f"Found Git repository at: {search_path}")
                return repo
            except InvalidGitRepositoryError:
                search_path = search_path.parent

        # Try current directory as last resort
        try:
            repo = Repo(self.repo_path)
            return repo
        except InvalidGitRepositoryError as e:
            raise GitRepositoryError(
                f"No Git repository found at {self.repo_path} or any parent directory"
            ) from e

    def get_repo_info(self, repo_path: Optional[Path] = None) -> RepoInfo:
        """Get repository information."""
        if repo_path is None:
            repo_path = Path(self.repo.working_dir)

        repo_name = repo_path.name
        is_submodule = self._is_submodule(repo_path)

        return RepoInfo(path=repo_path, name=repo_name, is_submodule=is_submodule)

    def _is_submodule(self, repo_path: Path) -> bool:
        """Check if a repository is a submodule."""
        try:
            # Check if .git is a file (submodule) or directory (regular repo)
            git_path = repo_path / ".git"
            return git_path.is_file()
        except Exception:
            return False

    def branch_exists(self, branch_name: str, repo_path: Optional[Path] = None) -> bool:
        """Check if a local branch exists (supports full names with slashes)."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
            else:
                temp_repo = self.repo

            # Local heads only
            head_names = [h.name for h in temp_repo.heads]
            # Backward-compatible check against last component
            short_names = [n.split("/")[-1] for n in head_names]
            return branch_name in head_names or branch_name in short_names
        except Exception as e:
            logger.error(f"Error checking branch existence: {e}")
            return False

    def get_current_branch(self, repo_path: Optional[Path] = None) -> str:
        """Get the current branch name."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
                return temp_repo.active_branch.name
            else:
                return self.repo.active_branch.name
        except Exception as e:
            logger.error(f"Error getting current branch: {e}")
            raise GitRepositoryError(f"Could not determine current branch: {e}")

    def checkout_branch(self, branch_name: str, repo_path: Optional[Path] = None) -> None:
        """Checkout a specific branch."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
                temp_repo.git.checkout(branch_name)
            else:
                self.repo.git.checkout(branch_name)

            logger.info(f"Checked out branch: {branch_name}")
        except Exception as e:
            logger.error(f"Error checking out branch {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to checkout branch {branch_name}: {e}")

    def list_local_branches(self, repo_path: Optional[Path] = None) -> List[str]:
        """List local branch names (full names, including slashes)."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
            else:
                temp_repo = self.repo
            return [h.name for h in temp_repo.heads]
        except Exception as e:
            logger.error(f"Error listing local branches: {e}")
            return []

    def create_or_update_branch(
        self, branch_name: str, target: str, repo_path: Optional[Path] = None
    ) -> None:
        """Create or force-update a local branch to point at target (commitish)."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
            else:
                temp_repo = self.repo

            current = None
            try:
                current = temp_repo.active_branch.name
            except Exception:
                current = None

            if current == branch_name:
                # When updating the currently checked out branch, use reset --hard
                temp_repo.git.reset("--hard", target)
            else:
                temp_repo.git.branch("-f", branch_name, target)

            logger.info(f"Created/updated branch {branch_name} -> {target}")
        except Exception as e:
            logger.error(f"Error creating/updating branch {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to create/update branch {branch_name}: {e}")

    def delete_branch(self, branch_name: str, repo_path: Optional[Path] = None) -> None:
        """Delete a local branch (force)."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
                temp_repo.git.branch("-D", branch_name)
            else:
                self.repo.git.branch("-D", branch_name)
            logger.info(f"Deleted branch {branch_name}")
        except Exception as e:
            logger.error(f"Error deleting branch {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to delete branch {branch_name}: {e}")

    def get_commits_between(
        self, base_branch: str, feature_branch: str, repo_path: Optional[Path] = None
    ) -> List[CommitInfo]:
        """Get commits that would be rebased (commits in feature_branch not in base_branch)."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
            else:
                temp_repo = self.repo

            # Get commits in feature_branch that are not in base_branch
            commits = list(temp_repo.iter_commits(f"{base_branch}..{feature_branch}"))

            commit_infos = []
            for commit in commits:
                commit_info = CommitInfo(
                    hash=commit.hexsha,
                    message=commit.message.strip(),
                    author=commit.author.name,
                    author_email=commit.author.email,
                    date=commit.committed_datetime.isoformat(),
                    parents=[parent.hexsha for parent in commit.parents],
                )
                commit_infos.append(commit_info)

            return commit_infos
        except Exception as e:
            logger.error(f"Error getting commits between branches: {e}")
            raise GitRepositoryError(f"Failed to get commits between branches: {e}")

    def start_rebase(
        self, target_branch: str, repo_path: Optional[Path] = None
    ) -> Tuple[bool, List[str]]:
        """
        Start a rebase operation.

        Returns:
            Tuple of (success, conflict_files)
        """
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                working_dir = repo_path
            else:
                working_dir = Path(self.repo.working_dir)

            # Start the rebase
            result = subprocess.run(
                ["git", "rebase", target_branch], cwd=working_dir, capture_output=True, text=True
            )

            if result.returncode == 0:
                logger.info("Rebase completed successfully")
                return True, []
            else:
                # Check for conflicts
                conflict_files = self._get_conflict_files(working_dir)
                if conflict_files:
                    logger.warning(f"Rebase has conflicts in files: {conflict_files}")
                    return False, conflict_files
                else:
                    # Other error
                    logger.error(f"Rebase failed: {result.stderr}")
                    raise GitRepositoryError(f"Rebase failed: {result.stderr}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Git rebase command failed: {e}")
            raise GitRepositoryError(f"Git rebase command failed: {e}")
        except Exception as e:
            logger.error(f"Error during rebase: {e}")
            raise GitRepositoryError(f"Error during rebase: {e}")

    def _get_conflict_files(self, repo_path: Path) -> List[str]:
        """Get list of files with merge conflicts."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )

            if result.returncode == 0:
                return [f.strip() for f in result.stdout.split("\n") if f.strip()]
            else:
                return []
        except Exception as e:
            logger.error(f"Error getting conflict files: {e}")
            return []

    def continue_rebase(self, repo_path: Optional[Path] = None) -> Tuple[bool, List[str]]:
        """Continue a rebase after conflicts are resolved."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                working_dir = repo_path
            else:
                working_dir = Path(self.repo.working_dir)

            # Set environment to avoid interactive commit message prompts
            env = os.environ.copy()
            env["GIT_EDITOR"] = "true"

            result = subprocess.run(
                ["git", "rebase", "--continue"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                env=env,
            )

            if result.returncode == 0:
                logger.info("Rebase continued successfully")
                return True, []
            else:
                # Check for more conflicts
                conflict_files = self._get_conflict_files(working_dir)
                if conflict_files:
                    logger.warning(f"Rebase still has conflicts: {conflict_files}")
                    return False, conflict_files
                else:
                    logger.error(f"Rebase continue failed: {result.stderr}")
                    raise GitRepositoryError(f"Rebase continue failed: {result.stderr}")

        except Exception as e:
            logger.error(f"Error continuing rebase: {e}")
            raise GitRepositoryError(f"Error continuing rebase: {e}")

    def abort_rebase(self, repo_path: Optional[Path] = None) -> None:
        """Abort a rebase operation."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                working_dir = repo_path
            else:
                working_dir = Path(self.repo.working_dir)

            subprocess.run(["git", "rebase", "--abort"], cwd=working_dir, check=True)

            logger.info("Rebase aborted successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to abort rebase: {e}")
            raise GitRepositoryError(f"Failed to abort rebase: {e}")

    def is_rebase_in_progress(self, repo_path: Optional[Path] = None) -> bool:
        """Check if a rebase is currently in progress."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                git_dir = repo_path / ".git"
            else:
                git_dir = Path(self.repo.git_dir)

            # Check for rebase-related files
            rebase_files = [git_dir / "rebase-merge", git_dir / "rebase-apply"]

            return any(f.exists() for f in rebase_files)
        except Exception as e:
            logger.error(f"Error checking rebase status: {e}")
            return False

    def get_updated_commits(
        self, original_commits: List[CommitInfo], repo_path: Optional[Path] = None
    ) -> List[CommitInfo]:
        """Get the updated commit information after a rebase."""
        try:
            if repo_path and repo_path != Path(self.repo.working_dir):
                temp_repo = Repo(repo_path)
            else:
                temp_repo = self.repo

            # Get recent commits (same number as original commits)
            recent_commits = list(temp_repo.iter_commits(max_count=len(original_commits)))

            updated_commits = []
            for commit in recent_commits:
                commit_info = CommitInfo(
                    hash=commit.hexsha,
                    message=commit.message.strip(),
                    author=commit.author.name,
                    author_email=commit.author.email,
                    date=commit.committed_datetime.isoformat(),
                    parents=[parent.hexsha for parent in commit.parents],
                )
                updated_commits.append(commit_info)

            return updated_commits
        except Exception as e:
            logger.error(f"Error getting updated commits: {e}")
            raise GitRepositoryError(f"Failed to get updated commits: {e}")
