"""
Git repository management and operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple, Union
from git import Repo, InvalidGitRepositoryError
from git.exc import GitCommandError

from .models import CommitInfo, GitRepositoryError, RepoInfo


logger = logging.getLogger(__name__)


class GitManager:
    """Manages Git operations for repositories and submodules."""

    def __init__(self, repo_path: Optional[Path] = None) -> None:
        """Initialize Git manager with optional repository path."""
        self.repo_path = (repo_path or Path.cwd()).resolve()
        self._repo: Optional[Repo] = None

    # --- Path normalization helpers ---
    def _to_repo_relative_str(self, p: Union[str, Path]) -> str:
        """Return a POSIX-style path relative to repo root for any given path.

        If `p` is absolute and inside the repository working directory, it is
        converted to a relative path. If `p` is already relative, it is
        normalized to POSIX separators. If `p` is outside the repo, the POSIX
        string form is returned as-is.
        """
        try:
            base = Path(self.repo.working_dir).resolve()
        except Exception:
            # If repo is not yet discovered, fall back to current repo_path
            base = self.repo_path

        pp = Path(p)
        try:
            if pp.is_absolute():
                rel = pp.resolve().relative_to(base)
                return rel.as_posix()
            # Already relative: ensure POSIX separators
            return pp.as_posix()
        except Exception:
            # Outside the repo or resolution failed: best-effort POSIX string
            s = pp.as_posix()
            logger.debug(f"Path '{s}' not under repo root '{base}'; passing as-is")
            return s

    @property
    def repo(self) -> Repo:
        """Get the Git repository instance."""
        if self._repo is None:
            self._repo = self._discover_repository()
        return self._repo

    def _discover_repository(self) -> Repo:
        """Discover the Git repository from current or specified path."""
        search_path = self.repo_path

        logger.debug(f"Discovering repository in: {search_path}")
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
        return RepoInfo(path=repo_path, name=repo_name, is_submodule=is_submodule, git_manager=self)

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
            logger.debug(f"Called 'git rebase {target_branch}' in {working_dir}")
            # Execute rebase via GitPython; errors raise GitCommandError
            self.repo.git.rebase(target_branch)

            # Verify index/working tree are clean before declaring success
            if not self.is_index_clean():
                dirty = self.get_dirty_paths()
                logger.error(f"Rebase completed but index is dirty: {dirty}")
                raise GitRepositoryError("Rebase left repository with a dirty index")
            logger.info("Rebase completed successfully")
            return True, []
        except GitCommandError as e:
            # Check for conflicts
            conflict_files = self._get_conflict_files()
            if conflict_files:
                logger.warning(f"Rebase has conflicts in files: {conflict_files}")
                return False, conflict_files
            logger.error(f"Rebase failed: {e}")
            raise GitRepositoryError(f"Rebase failed: {e}")
        except Exception as e:
            logger.error(f"Error during rebase: {e}")
            raise GitRepositoryError(f"Error during rebase: {e}")

    def _get_conflict_files(self) -> List[Path]:
        """Get list of files with merge conflicts."""
        try:
            output = self.repo.git.diff("--name-only", "--diff-filter=U")
            return [Path(self.repo.working_dir) / Path(f.strip()) for f in output.split("\n") if f.strip()]
        except Exception as e:
            logger.error(f"Error getting conflict files: {e}")
            return []

    def get_conflict_files(self) -> List[Path]:
        """Public wrapper to return unresolved merge paths (files and gitlinks)."""
        try:
            return self._get_conflict_files()
        except Exception:
            return []

    def continue_rebase(self) -> Tuple[bool, List[Path]]:
        """Continue a rebase after conflicts are resolved."""
        try:
            # Avoid interactive editor prompt
            with self.repo.git.custom_environment(GIT_EDITOR="true"):
                self.repo.git.rebase("--continue")

            # Verify index/working tree are clean before declaring success
            if not self.is_index_clean():
                dirty = self.get_dirty_paths()
                logger.error(f"Rebase continued but index is dirty: {dirty}")
                raise GitRepositoryError("Rebase continue left repository with a dirty index")
            logger.info("Rebase continued successfully")
            return True, []
        except GitCommandError as e:
            # Check for more conflicts
            conflict_files = self._get_conflict_files()
            if conflict_files:
                logger.warning(f"Rebase still has conflicts: {conflict_files}")
                return False, conflict_files
            logger.error(f"Rebase continue failed: {e}")
            raise GitRepositoryError(f"Rebase continue failed: {e}")
        except Exception as e:
            logger.error(f"Error continuing rebase: {e}")
            raise GitRepositoryError(f"Error continuing rebase: {e}")

    def abort_rebase(self) -> None:
        """Abort a rebase operation."""
        try:
            self.repo.git.rebase("--abort")
            logger.info("Rebase aborted successfully")
        except GitCommandError as e:
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
            rel = self._to_repo_relative_str(filepath)
            return f"path = {rel}" in content
        except Exception:
            return False

    def get_unmerged_index_entries(self, path: Path) -> List[dict]:
        """Return parsed entries from `git ls-files -u -- <path>` for an unmerged path.

        Each entry is a dict with keys: stage, hash, path
        """
        try:
            rel = self._to_repo_relative_str(path)
            output = self.repo.git.ls_files("-u", "--", rel)
            if not output.strip():
                return []
            entries: List[dict] = []
            for line in output.strip().split("\n"):
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
        except Exception:
            return []

    def checkout_commit(self, commitish: str) -> None:
        """Checkout a commit-ish in the specified repository path."""
        try:
            self.repo.git.checkout(commitish)
        except GitCommandError as e:
            logger.error(f"Failed to checkout {commitish} in {self.repo.working_dir}: {e}")
            raise GitRepositoryError(f"Failed to checkout {commitish}: {e}")

    def add_paths(self, paths: List[Path]) -> None:
        """Stage the given paths in the specified repository path."""
        try:
            # Use porcelain 'git add -- <path>' for better handling of gitlinks (submodules)
            str_paths = [self._to_repo_relative_str(p) for p in paths]
            for p in str_paths:
                # The '--' ensures pathspec is not interpreted as an option
                self.repo.git.add("--", p)
            # Refresh index to ensure merge state/index entries are updated
            try:
                self.repo.git.update_index("--refresh")
            except Exception:
                # Non-fatal; continue even if refresh is unsupported in this context
                pass
        except Exception as e:
            logger.error(f"Failed to add paths {paths} in {self.repo.working_dir}: {e}")
            raise GitRepositoryError(f"Failed to stage paths: {e}")

    def get_commit_subject(self, commit_hash: str) -> Optional[str]:
        """Return the one-line subject for a commit hash in the given repo."""
        # Primary: GitPython commit object
        try:
            subj = self.repo.commit(commit_hash).summary
            return subj.strip() if subj else None
        except Exception:
            pass

        # Fallback 1: porcelain 'git show -s --format=%s <hash>'
        try:
            output = self.repo.git.show("-s", "--format=%s", commit_hash)
            output = output.strip()
            if output:
                return output
        except Exception:
            pass

        # Fallback 2: porcelain 'git log -1 --format=%s <hash>'
        try:
            output = self.repo.git.log("-1", "--format=%s", commit_hash)
            output = output.strip()
            if output:
                return output
        except Exception:
            pass

        return None

    def get_short_commit_for_ref(self, ref: str) -> Optional[str]:
        """Return the short commit hash for a given ref name (branch, tag, or remote ref).

        Example refs: 'main', 'feature/x', 'origin/main', 'HEAD'.
        """
        try:
            value = self.repo.git.rev_parse("--short", ref).strip()
            return value if value else None
        except Exception:
            return None

    def get_staged_files(self) -> List[str]:
        """Return list of staged (cached) paths (names only)."""
        try:
            output = self.repo.git.diff("--cached", "--name-only")
            return [f.strip() for f in output.split("\n") if f.strip()]
        except Exception:
            return []

    def has_unstaged_changes(self) -> bool:
        """Return True if there are unstaged changes in the working tree.

        Untracked files are ignored. This checks only working tree changes (not index).
        """
        try:
            return self.repo.is_dirty(index=False, working_tree=True, untracked_files=False)
        except Exception:
            return False

    def get_submodule_pointer_at(self, branch: str, submodule_path: Union[str, Path]) -> Optional[str]:
        """Return the gitlink commit SHA for a submodule path at a given branch/ref.

        Args:
            branch: The ref/branch name or full ref to inspect in the parent repository.
            submodule_path: The submodule path. Can be absolute Path, relative Path, or str.

        Returns:
            The commit SHA string if the gitlink exists at that ref, otherwise None.
        """
        try:
            rel = self._to_repo_relative_str(submodule_path)
            # Use porcelain ls-tree to read the tree entry for the given path at the ref
            output = self.repo.git.ls_tree(branch, "--", rel)
            line = output.strip()
            if not line:
                return None
            # Expected format: "160000 commit <sha>\t<path>"
            parts = line.split()
            if len(parts) >= 3 and parts[0] == "160000" and parts[1] == "commit":
                return parts[2]
            return None
        except Exception as e:
            logger.error(
                f"Error reading submodule pointer at {branch}:{submodule_path}: {e}"
            )
            return None

    def submodule_changed_between(
        self, base_branch: str, feature_branch: str, submodule_path: Path
    ) -> bool:
        """Return True if the submodule entry changed between base..feature in the parent repo.

        Implementation uses `git log --name-only` restricted to the submodule path to detect
        any commits that touched the gitlink entry.
        """
        try:
            rel = self._to_repo_relative_str(submodule_path)
            output = self.repo.git.log(
                "--pretty=format:",
                "--name-only",
                f"{base_branch}..{feature_branch}",
                "--",
                rel,
            )
            touched = [ln.strip() for ln in output.splitlines() if ln.strip()]
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
            self.repo.remotes[remote_name].fetch(prune=True)
            logger.info(f"Fetched updates from {remote_name} in {self.repo.working_dir}")
        except Exception as e:
            logger.error(f"Failed to fetch from {remote_name}: {e}")
            raise GitRepositoryError(f"Failed to fetch from {remote_name}: {e}")

    def branch_ahead_behind(self, branch_name: str, remote_name: str = "origin") -> Tuple[int, int]:
        """Return (ahead, behind) counts of local branch vs remote/branch.

        If the remote ref does not exist, returns (0, 0).
        """
        try:
            remote_ref = f"{remote_name}/{branch_name}"
            # If remote ref doesn't exist, treat as in sync for our purposes
            try:
                _ = self.repo.remotes[remote_name].refs
            except Exception:
                return 0, 0

            output = self.repo.git.rev_list("--left-right", "--count", f"{remote_ref}...{branch_name}")
            left_right = output.strip().split()
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
            remote_ref = f"{remote_name}/{branch_name}"
            current_branch = None
            try:
                current_branch = self.repo.active_branch.name
            except Exception:
                current_branch = None

            if current_branch == branch_name:
                # Checked out: use ff-only merge
                self.repo.git.merge("--ff-only", remote_ref)
            else:
                # Move branch ref to remote tip
                self.repo.git.branch("-f", branch_name, remote_ref)
            logger.info(f"Fast-forwarded {branch_name} to {remote_ref}")
        except GitCommandError as e:
            logger.error(f"Failed to fast-forward {branch_name}: {e}")
            raise GitRepositoryError(f"Failed to fast-forward {branch_name}: {e}")
        except Exception as e:
            logger.error(f"Error fast-forwarding {branch_name}: {e}")
            raise GitRepositoryError(f"Error fast-forwarding {branch_name}: {e}")

    # --- Working tree / index cleanliness ---
    def is_index_clean(self) -> bool:
        """Return True if there are no staged or unstaged changes (untracked ignored)."""
        try:
            # No staged or unstaged changes; ignore untracked files
            if self.repo.is_dirty(index=True, working_tree=True, untracked_files=False):
                return False
            # No unresolved merges
            if self.repo.git.ls_files("-u").strip():
                return False
            return True
        except Exception:
            return False

    def get_dirty_paths(self) -> List[str]:
        """Return list of paths that are staged or unstaged (untracked ignored)."""
        try:
            output = self.repo.git.status("--porcelain")
            dirty: List[str] = []
            for line in output.splitlines():
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
