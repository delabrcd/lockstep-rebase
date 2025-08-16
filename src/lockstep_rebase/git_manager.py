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

    def get_repo_info(self) -> RepoInfo:
        """Get repository information for this instance's repo."""
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

    def branch_exists(self, branch_name: str) -> bool:
        """Check if a local branch exists (supports full names with slashes)."""
        try:
            temp_repo = self.repo

            # Local heads only
            head_names = [h.name for h in temp_repo.heads]
            # Backward-compatible check against last component
            short_names = [n.split("/")[-1] for n in head_names]
            return branch_name in head_names or branch_name in short_names
        except Exception as e:
            logger.error(f"Error checking branch existence: {e}")
            return False

    def remote_branch_exists(self, branch_name: str, remote_name: str = "origin") -> bool:
        """Check if a remote branch exists (e.g., origin/feature/x)."""
        try:
            temp_repo = self.repo

            remote = temp_repo.remote(remote_name)
            remote_ref_names = [ref.name for ref in remote.refs]
            full = f"{remote_name}/{branch_name}"
            if full in remote_ref_names:
                return True
            # Also allow matching by last component in case of nested names
            return branch_name in [n.split("/", 1)[1] if "/" in n else n for n in remote_ref_names]
        except Exception as e:
            logger.error(f"Error checking remote branch existence: {e}")
            return False

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        try:
            return self.repo.active_branch.name
        except Exception as e:
            logger.error(f"Error getting current branch: {e}")
            raise GitRepositoryError(f"Could not determine current branch: {e}")

    def checkout_branch(self, branch_name: str) -> None:
        """Checkout a specific branch."""
        try:
            self.repo.git.checkout(branch_name)

            logger.info(f"Checked out branch: {branch_name}")
        except Exception as e:
            logger.error(f"Error checking out branch {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to checkout branch {branch_name}: {e}")

    def list_local_branches(self) -> List[str]:
        """List local branch names (full names, including slashes)."""
        try:
            temp_repo = self.repo
            return [h.name for h in temp_repo.heads]
        except Exception as e:
            logger.error(f"Error listing local branches: {e}")
            return []

    def create_or_update_branch(self, branch_name: str, target: str) -> None:
        """Create or force-update a local branch to point at target (commitish)."""
        try:
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

    def delete_branch(self, branch_name: str) -> None:
        """Delete a local branch (force)."""
        try:
            self.repo.git.branch("-D", branch_name)
            logger.info(f"Deleted branch {branch_name}")
        except Exception as e:
            logger.error(f"Error deleting branch {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to delete branch {branch_name}: {e}")

    def create_local_branch_from_remote(self, branch_name: str, remote_name: str = "origin") -> None:
        """Create a local branch from a remote-tracking branch.

        This creates or updates a local branch named `branch_name` to point at
        `remote_name/branch_name`. Upstream tracking is not strictly required
        for rebase planning, so this function does not configure it.
        """
        try:
            temp_repo = self.repo

            remote_ref = f"{remote_name}/{branch_name}"
            # Ensure the remote ref exists in this repo
            ref_names = [r.name for r in temp_repo.remotes[remote_name].refs]
            if remote_ref not in ref_names:
                raise GitRepositoryError(
                    f"Remote branch {remote_ref} not found while creating local branch"
                )
            # Create or fast-forward local branch to remote tip
            temp_repo.git.branch("-f", branch_name, remote_ref)
            logger.info(f"Created local branch {branch_name} from {remote_ref}")
        except Exception as e:
            logger.error(f"Error creating local branch from remote: {e}")
            raise GitRepositoryError(
                f"Failed to create local branch {branch_name} from {remote_name}/{branch_name}: {e}"
            )

    def get_commits_between(self, base_branch: str, feature_branch: str) -> List[CommitInfo]:
        """Get commits that would be rebased (commits in feature_branch not in base_branch)."""
        try:
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

    def start_rebase(self, target_branch: str) -> Tuple[bool, List[str]]:
        """
        Start a rebase operation.

        Returns:
            Tuple of (success, conflict_files)
        """
        try:
            working_dir = Path(self.repo.working_dir)

            # Start the rebase
            result = subprocess.run(
                ["git", "rebase", target_branch], cwd=working_dir, capture_output=True, text=True
            )

            logger.debug(f"Called 'git rebase {target_branch}' in {working_dir}")

            if result.returncode == 0:
                # Verify index/working tree are clean before declaring success
                if not self.is_index_clean():
                    dirty = self.get_dirty_paths()
                    logger.error(f"Rebase completed but index is dirty: {dirty}")
                    raise GitRepositoryError("Rebase left repository with a dirty index")
                logger.info("Rebase completed successfully")
                return True, []
            else:
                # Check for conflicts
                conflict_files = self._get_conflict_files()
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

    def _get_conflict_files(self) -> List[str]:
        """Get list of files with merge conflicts."""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=Path(self.repo.working_dir),
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

    def get_conflict_files(self) -> List[str]:
        """Public wrapper to return unresolved merge paths (files and gitlinks)."""
        try:
            return self._get_conflict_files()
        except Exception:
            return []

    def continue_rebase(self) -> Tuple[bool, List[str]]:
        """Continue a rebase after conflicts are resolved."""
        try:
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
                # Verify index/working tree are clean before declaring success
                if not self.is_index_clean():
                    dirty = self.get_dirty_paths()
                    logger.error(f"Rebase continued but index is dirty: {dirty}")
                    raise GitRepositoryError("Rebase continue left repository with a dirty index")
                logger.info("Rebase continued successfully")
                return True, []
            else:
                # Check for more conflicts
                conflict_files = self._get_conflict_files()
                if conflict_files:
                    logger.warning(f"Rebase still has conflicts: {conflict_files}")
                    return False, conflict_files
                else:
                    logger.error(f"Rebase continue failed: {result.stderr}")
                    raise GitRepositoryError(f"Rebase continue failed: {result.stderr}")

        except Exception as e:
            logger.error(f"Error continuing rebase: {e}")
            raise GitRepositoryError(f"Error continuing rebase: {e}")

    def abort_rebase(self) -> None:
        """Abort a rebase operation."""
        try:
            working_dir = Path(self.repo.working_dir)

            subprocess.run(["git", "rebase", "--abort"], cwd=working_dir, check=True)

            logger.info("Rebase aborted successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to abort rebase: {e}")
            raise GitRepositoryError(f"Failed to abort rebase: {e}")

    def is_rebase_in_progress(self) -> bool:
        """Check if a rebase is currently in progress."""
        try:
            git_dir = Path(self.repo.git_dir)

            # Check for rebase-related files
            rebase_files = [git_dir / "rebase-merge", git_dir / "rebase-apply"]

            return any(f.exists() for f in rebase_files)
        except Exception as e:
            logger.error(f"Error checking rebase status: {e}")
            return False

    def get_updated_commits(self, original_commits: List[CommitInfo]) -> List[CommitInfo]:
        """Get the updated commit information after a rebase."""
        try:
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

    # --- Generic Git helpers used by ConflictResolver and others ---
    def is_submodule_path(self, filepath: str) -> bool:
        """Return True if the given path corresponds to a submodule entry in repo."""
        try:
            gitmodules_path = Path(self.repo.working_dir) / ".gitmodules"
            if not gitmodules_path.exists():
                return False
            content = gitmodules_path.read_text(encoding="utf-8", errors="ignore")
            return f"path = {filepath}" in content
        except Exception:
            return False

    def get_unmerged_index_entries(self, path: str) -> List[dict]:
        """Return parsed entries from `git ls-files -u -- <path>` for an unmerged path.

        Each entry is a dict with keys: stage, hash, path
        """
        try:
            result = subprocess.run(
                ["git", "ls-files", "-u", "--", path],
                cwd=Path(self.repo.working_dir),
                capture_output=True,
                text=True,
                check=True,
            )
            if not result.stdout.strip():
                return []
            entries: List[dict] = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split("\t")
                if len(parts) >= 2:
                    mode_hash = parts[0].split()
                    if len(mode_hash) >= 3:
                        entries.append({
                            "stage": mode_hash[2],
                            "hash": mode_hash[1],
                            "path": parts[1],
                        })
            return entries
        except subprocess.CalledProcessError:
            return []
        except Exception:
            return []

    def checkout_commit(self, commitish: str) -> None:
        """Checkout a commit-ish in the specified repository path."""
        try:
            working_dir = Path(self.repo.working_dir)
            subprocess.run(["git", "checkout", commitish], cwd=working_dir, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to checkout {commitish} in {working_dir}: {e}")
            raise GitRepositoryError(f"Failed to checkout {commitish}: {e}")

    def add_paths(self, paths: List[str]) -> None:
        """Stage the given paths in the specified repository path."""
        try:
            working_dir = Path(self.repo.working_dir)
            for p in paths:
                subprocess.run(["git", "add", p], cwd=working_dir, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to add paths {paths} in {working_dir}: {e}")
            raise GitRepositoryError(f"Failed to stage paths: {e}")

    def get_commit_subject(self, commit_hash: str) -> Optional[str]:
        """Return the one-line subject for a commit hash in the given repo."""
        try:
            working_dir = Path(self.repo.working_dir)
            result = subprocess.run(
                ["git", "log", "-1", "--format=%s", commit_hash],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return None
        except Exception:
            return None

    def get_short_commit_for_ref(self, ref: str) -> Optional[str]:
        """Return the short commit hash for a given ref name (branch, tag, or remote ref).

        Example refs: 'main', 'feature/x', 'origin/main', 'HEAD'.
        """
        try:
            working_dir = Path(self.repo.working_dir)
            result = subprocess.run(
                ["git", "rev-parse", "--short", ref],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            value = result.stdout.strip()
            return value if value else None
        except subprocess.CalledProcessError:
            return None
        except Exception:
            return None

    def get_staged_files(self) -> List[str]:
        """Return list of staged (cached) paths (names only)."""
        try:
            working_dir = Path(self.repo.working_dir)
            result = subprocess.run(
                ["git", "diff", "--cached", "--name-only"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return [f.strip() for f in result.stdout.split("\n") if f.strip()]
        except subprocess.CalledProcessError:
            return []
        except Exception:
            return []

    def has_unstaged_changes(self) -> bool:
        """Return True if there are unstaged changes in the working tree."""
        try:
            working_dir = Path(self.repo.working_dir)
            # Use --quiet for efficiency; returncode 1 means changes present
            result = subprocess.run(
                ["git", "diff", "--quiet"], cwd=working_dir
            )
            return result.returncode != 0
        except Exception:
            return False

    # --- Helpers for submodule auto-discovery ---
    def get_submodule_pointer_at(self, branch: str, submodule_path: str) -> Optional[str]:
        """Return the gitlink SHA for a submodule path at a given branch in the parent repo.

        Args:
            branch: Parent repository branch or commit-ish
            submodule_path: Path to the submodule relative to parent repo root
            repo_path: Parent repository path (defaults to manager's repo)

        Returns:
            The gitlink SHA (40-hex) if present, otherwise None.
        """
        try:
            working_dir = Path(self.repo.working_dir)
            # Use ls-tree to read the tree entry; gitlink mode is 160000 and type 'commit'
            result = subprocess.run(
                ["git", "ls-tree", branch, "--", submodule_path],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return None
            line = result.stdout.strip()
            if not line:
                return None
            # Expected format: "160000 commit <sha>\t<path>"
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "160000" and parts[1] == "commit":
                return parts[2]
            return None
        except Exception as e:
            logger.error(f"Error reading submodule pointer at {branch}:{submodule_path}: {e}")
            return None

    def submodule_changed_between(
        self, base_branch: str, feature_branch: str, submodule_path: str
    ) -> bool:
        """Return True if the submodule entry changed between base..feature in the parent repo.

        Implementation uses `git log --name-only` restricted to the submodule path to detect
        any commits that touched the gitlink entry.
        """
        try:
            working_dir = Path(self.repo.working_dir)
            result = subprocess.run(
                [
                    "git",
                    "log",
                    "--pretty=format:",
                    "--name-only",
                    f"{base_branch}..{feature_branch}",
                    "--",
                    submodule_path,
                ],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return False
            # If any path is listed, the submodule entry was changed in that range
            touched = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
            return len(touched) > 0
        except Exception as e:
            logger.error(
                f"Error checking submodule changes for {submodule_path} between {base_branch}..{feature_branch}: {e}"
            )
            return False

    def branches_containing_commit(self, commit_sha: str, include_remotes: bool = True) -> Tuple[List[str], List[str]]:
        """Return (local_branches, remote_branches) that contain the given commit.

        Remote branch names are returned with their full refs as shown by `git branch -r`
        (e.g., "origin/feature/x"). Local branches are returned as their short names.
        """
        try:
            temp_repo = self.repo

            local_branches: List[str] = []
            try:
                # GitPython's branch command output is easier via porcelain
                output = temp_repo.git.branch("--contains", commit_sha)
                # Lines like: "* main" or "  feature/x"
                for ln in output.splitlines():
                    name = ln.replace("*", "").strip()
                    if not name:
                        continue
                    # Ignore detached HEAD or any non-branch annotations
                    # e.g. '(HEAD detached at 1234abcd)'
                    if (
                        name.startswith("(")
                        or "detached" in name.lower()
                        or name.lower().startswith("head")
                    ):
                        continue
                    local_branches.append(name)
            except Exception:
                local_branches = []

            remote_branches: List[str] = []
            if include_remotes:
                try:
                    output_r = temp_repo.git.branch("-r", "--contains", commit_sha)
                    for ln in output_r.splitlines():
                        name = ln.replace("*", "").strip()
                        if not name:
                            continue
                        # Exclude symbolic refs like 'origin/HEAD -> origin/main'
                        if "->" in name:
                            continue
                        remote_branches.append(name)
                except Exception:
                    remote_branches = []

            # Further sanitize locals to only actual local heads present in repo
            try:
                head_names = {h.name for h in temp_repo.heads}
                local_branches = [b for b in local_branches if b in head_names]
            except Exception:
                # If we cannot list heads, keep parsed list as-is
                pass

            return local_branches, remote_branches
        except Exception as e:
            logger.error(f"Error listing branches containing {commit_sha}: {e}")
            return [], []

    # --- Remote synchronization helpers ---
    def fetch_remote(self, remote_name: str = "origin") -> None:
        """Fetch updates from a remote."""
        try:
            working_dir = Path(self.repo.working_dir)
            subprocess.run(["git", "fetch", "--prune", remote_name], cwd=working_dir, check=True)
            logger.info(f"Fetched updates from {remote_name} in {working_dir}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to fetch from {remote_name}: {e}")
            raise GitRepositoryError(f"Failed to fetch from {remote_name}: {e}")

    def branch_ahead_behind(self, branch_name: str, remote_name: str = "origin") -> Tuple[int, int]:
        """Return (ahead, behind) counts of local branch vs remote/branch.

        If the remote ref does not exist, returns (0, 0).
        """
        try:
            working_dir = Path(self.repo.working_dir)
            remote_ref = f"{remote_name}/{branch_name}"
            # If remote ref doesn't exist, treat as in sync for our purposes
            try:
                Repo(working_dir).remotes[remote_name].refs
            except Exception:
                return 0, 0

            # rev-list --left-right --count remote...local => left=behind, right=ahead
            result = subprocess.run(
                [
                    "git",
                    "rev-list",
                    "--left-right",
                    "--count",
                    f"{remote_ref}...{branch_name}",
                ],
                cwd=working_dir,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return 0, 0
            left_right = result.stdout.strip().split()
            if len(left_right) != 2:
                return 0, 0
            behind = int(left_right[0])
            ahead = int(left_right[1])
            return ahead, behind
        except Exception:
            return 0, 0

    def is_branch_up_to_date_with_remote(self, branch_name: str, remote_name: str = "origin") -> bool:
        """Return True if local branch is not behind its remote tracking branch."""
        ahead, behind = self.branch_ahead_behind(branch_name, remote_name)
        return behind == 0

    def fast_forward_branch_to_remote(self, branch_name: str, remote_name: str = "origin") -> None:
        """Fast-forward local branch to remote/branch if possible.

        If the branch is currently checked out, performs a --ff-only merge from
        the remote ref. Otherwise, force-moves the branch ref to the remote tip.
        """
        try:
            working_dir = Path(self.repo.working_dir)
            remote_ref = f"{remote_name}/{branch_name}"
            temp_repo = Repo(working_dir)
            current_branch = None
            try:
                current_branch = temp_repo.active_branch.name
            except Exception:
                current_branch = None

            if current_branch == branch_name:
                # Checked out: use ff-only merge
                subprocess.run(["git", "merge", "--ff-only", remote_ref], cwd=working_dir, check=True)
            else:
                # Move branch ref to remote tip
                temp_repo.git.branch("-f", branch_name, remote_ref)
            logger.info(f"Fast-forwarded {branch_name} to {remote_ref}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to fast-forward {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to fast-forward {branch_name}: {e}")
        except Exception as e:
            logger.error(f"Error fast-forwarding {branch_name}: {e}")
            raise GitRepositoryError(f"Error fast-forwarding {branch_name}: {e}")

    # --- Working tree / index cleanliness ---
    def is_index_clean(self) -> bool:
        """Return True if there are no staged or unstaged changes (untracked ignored)."""
        try:
            working_dir = Path(self.repo.working_dir)
            # No unstaged changes
            res_wt = subprocess.run(["git", "diff", "--quiet"], cwd=working_dir)
            if res_wt.returncode != 0:
                return False
            # No staged changes
            res_idx = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=working_dir)
            if res_idx.returncode != 0:
                return False
            # No unresolved merges
            res_unmerged = subprocess.run(["git", "ls-files", "-u"], cwd=working_dir, capture_output=True, text=True)
            if res_unmerged.stdout.strip():
                return False
            return True
        except Exception:
            return False

    def get_dirty_paths(self) -> List[str]:
        """Return list of paths that are staged or unstaged (untracked ignored)."""
        try:
            working_dir = Path(self.repo.working_dir)
            result = subprocess.run(
                ["git", "status", "--porcelain"], cwd=working_dir, capture_output=True, text=True
            )
            if result.returncode != 0:
                return []
            dirty: List[str] = []
            for line in result.stdout.splitlines():
                if not line.strip():
                    continue
                # First two columns are status codes; path follows
                # Ignore untracked (??)
                if line.startswith("??"):
                    continue
                path = line[3:].strip()
                if path:
                    dirty.append(path)
            return dirty
        except Exception:
            return []
