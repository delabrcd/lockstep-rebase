"""
Git command utilities for lockstep rebase operations.

This module provides a centralized interface for executing Git commands
with proper error handling and logging.
"""

import os
import subprocess
from typing import List, Optional, Dict


class GitUtils:
    """Utility class for Git operations."""

    def __init__(self, verbose: bool = False):
        """Initialize Git utilities.

        Args:
            verbose: Enable verbose command logging
        """
        self.verbose = verbose

    def run(
            self,
            cmd: List[str],
            cwd: Optional[str] = None,
            capture: bool = False,
            env: Optional[Dict] = None) -> str:
        """Execute a command with optional output capture.

        Args:
            cmd: Command and arguments to execute
            cwd: Working directory for the command
            capture: Whether to capture and return output
            env: Additional environment variables

        Returns:
            Command output if capture=True, empty string otherwise

        Raises:
            subprocess.CalledProcessError: If command fails
        """
        # Set up environment for non-interactive Git operations
        final_env = os.environ.copy()
        if env:
            final_env.update(env)

        # For Git commands, set GIT_EDITOR to true to avoid opening editor
        if cmd and cmd[0] == 'git':
            # 'true' command always succeeds and does nothing
            final_env['GIT_EDITOR'] = 'true'

        if capture:
            result = subprocess.check_output(
                cmd, cwd=cwd, env=final_env, stderr=subprocess.STDOUT)
            return result.decode().strip()
        else:
            subprocess.check_call(cmd, cwd=cwd, env=final_env)
            return ""

    def sh(
            self,
            cmd: List[str],
            cwd: Optional[str] = None,
            capture: bool = False) -> str:
        """Execute a shell command with logging.

        Args:
            cmd: Command and arguments to execute
            cwd: Working directory for the command
            capture: Whether to capture and return output

        Returns:
            Command output if capture=True, empty string otherwise
        """
        if self.verbose:
            print(f"$ {' '.join(cmd)} (cwd={cwd})")
        return self.run(cmd, cwd=cwd, capture=capture)

    def find_git_root(self, start_path: str) -> Optional[str]:
        """Find the Git repository root starting from a given path.

        Args:
            start_path: Path to start searching from

        Returns:
            Path to Git repository root, or None if not found
        """
        try:
            output = self.sh(
                ['git', 'rev-parse', '--show-toplevel'], cwd=start_path, capture=True)
            if self.verbose:
                print(f"🔍 Found Git repository root: {output}")
            return output
        except subprocess.CalledProcessError:
            return None

    def get_current_branch(self, repo_path: str) -> str:
        """Get the current branch name.

        Args:
            repo_path: Path to the repository

        Returns:
            Current branch name
        """
        try:
            return self.sh(['git', 'symbolic-ref', '--short',
                           'HEAD'], cwd=repo_path, capture=True)
        except subprocess.CalledProcessError:
            # Might be in detached HEAD state
            return self.sh(['git', 'rev-parse', '--short',
                           'HEAD'], cwd=repo_path, capture=True)

    def get_branches(self, repo_path: str) -> List[str]:
        """Get all available branches.

        Args:
            repo_path: Path to the repository

        Returns:
            List of branch names
        """
        try:
            output = self.sh(['git', 'branch', '-a'],
                             cwd=repo_path, capture=True)
            branches = []

            for line in output.split('\n'):
                line = line.strip().lstrip('* ')
                if line and not line.startswith('remotes/origin/HEAD'):
                    if line.startswith('remotes/origin/'):
                        branch_name = line.replace('remotes/origin/', '')
                        if branch_name not in branches:
                            branches.append(branch_name)
                    else:
                        branches.append(line)

            return branches
        except subprocess.CalledProcessError:
            return []

    def is_rebase_in_progress(self, repo_path: str) -> bool:
        """Check if there's an active rebase in progress.

        Args:
            repo_path: Path to the repository

        Returns:
            True if rebase is in progress
        """
        try:
            # Check if .git/rebase-merge or .git/rebase-apply exists
            git_dir = os.path.join(repo_path, '.git')
            rebase_merge = os.path.join(git_dir, 'rebase-merge')
            rebase_apply = os.path.join(git_dir, 'rebase-apply')

            return os.path.exists(rebase_merge) or os.path.exists(rebase_apply)
        except Exception:
            return False

    def get_conflicted_files(
            self, repo_path: str) -> tuple[List[str], List[str]]:
        """Get lists of conflicted files and submodules.

        Args:
            repo_path: Path to the repository

        Returns:
            Tuple of (regular_conflicts, submodule_conflicts)
        """
        try:
            status_output = self.sh(
                ['git', 'status', '--porcelain=v1'], cwd=repo_path, capture=True)
            regular_conflicts = []
            submodule_conflicts = []

            for line in status_output.split('\n'):
                if line.startswith('UU '):
                    file_path = line[3:].strip()
                    # Check if this is a submodule
                    try:
                        self.sh(['git', 'ls-files', '--stage',
                                file_path], cwd=repo_path, capture=True)
                        # If we can get stage info, check if it's a submodule
                        # (mode 160000)
                        stage_info = self.sh(
                            ['git', 'ls-files', '--stage', file_path], cwd=repo_path, capture=True)
                        if '160000' in stage_info:
                            submodule_conflicts.append(file_path)
                        else:
                            regular_conflicts.append(file_path)
                    except subprocess.CalledProcessError:
                        regular_conflicts.append(file_path)

            return regular_conflicts, submodule_conflicts
        except subprocess.CalledProcessError:
            return [], []

    def find_backup_branches(self, repo_path: str) -> List[str]:
        """Find all backup branches created by this script.

        Args:
            repo_path: Path to the repository

        Returns:
            List of backup branch names
        """
        try:
            branches_output = self.sh(
                ['git', 'branch'], cwd=repo_path, capture=True)
            backup_branches = []

            for line in branches_output.split('\n'):
                line = line.strip().lstrip('* ')
                if '-backup-' in line and line.endswith(tuple('0123456789')):
                    backup_branches.append(line)

            return backup_branches
        except subprocess.CalledProcessError:
            return []
