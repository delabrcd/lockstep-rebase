"""
Interactive conflict resolution for lockstep rebase operations.

This module handles user interaction for resolving conflicts that
cannot be automatically resolved.
"""

import subprocess
from typing import List

from ..core.models import RepoInfo
from ..core.git_utils import GitUtils


class InteractiveConflictHandler:
    """Handles interactive conflict resolution."""

    def __init__(self, git_utils: GitUtils):
        """Initialize interactive conflict handler.

        Args:
            git_utils: Git utilities instance
        """
        self.git_utils = git_utils

    def handle_merge_conflicts(self, repo_info: RepoInfo) -> bool:
        """Handle merge conflicts interactively.

        Args:
            repo_info: Repository information

        Returns:
            True if conflicts were resolved successfully
        """
        print(f"\n⚠️  MERGE CONFLICTS DETECTED in {repo_info.name}")
        print("=" * 60)

        # Get conflict information
        regular_conflicts, submodule_conflicts = self.git_utils.get_conflicted_files(
            repo_info.path)

        if submodule_conflicts:
            print(f"📦 Submodule conflicts ({len(submodule_conflicts)}):")
            for submodule in submodule_conflicts:
                print(f"  • {submodule}")

        if regular_conflicts:
            print(f"📄 File conflicts ({len(regular_conflicts)}):")
            for file_path in regular_conflicts:
                print(f"  • {file_path}")

        # Show current rebase progress
        try:
            rebase_head_name = self.git_utils.sh(
                ['git', 'symbolic-ref', '--short', 'HEAD'],
                cwd=repo_info.path,
                capture=True
            )
            print(f"\n🔄 Currently rebasing: {rebase_head_name}")
        except subprocess.CalledProcessError:
            pass

        # Handle submodule conflicts first if they exist
        if submodule_conflicts:
            return self.handle_submodule_conflicts(
                repo_info, submodule_conflicts)

        # Handle regular file conflicts
        print("\n📋 RESOLUTION OPTIONS:")
        print("  1. Resolve conflicts manually and continue")
        print("  2. Skip this repository (abort rebase)")
        print("  3. Open a new terminal/editor to resolve conflicts")

        while True:
            choice = input("\nChoose an option (1/2/3): ").strip()

            if choice == '1':
                return self._wait_for_conflict_resolution(repo_info)
            elif choice == '2':
                print(f"⏭️  Skipping {repo_info.name} - aborting rebase")
                try:
                    self.git_utils.sh(
                        ['git', 'rebase', '--abort'], cwd=repo_info.path)
                    print("✅ Rebase aborted successfully")
                except subprocess.CalledProcessError as e:
                    print(f"❌ Failed to abort rebase: {e}")
                return False
            elif choice == '3':
                print(f"\n🖥️  Opening new terminal for {repo_info.name}")
                print(f"   Path: {repo_info.path}")
                print(
                    "   Resolve conflicts manually, then return here and choose option 1")
                input("\nPress Enter when you're ready to continue...")
            else:
                print("Please enter 1, 2, or 3")

    def handle_submodule_conflicts(
            self,
            repo_info: RepoInfo,
            submodule_conflicts: List[str]) -> bool:
        """Handle submodule conflicts interactively.

        Args:
            repo_info: Repository information
            submodule_conflicts: List of conflicted submodule paths

        Returns:
            True if conflicts were resolved successfully
        """
        print(f"\n📦 SUBMODULE CONFLICTS in {repo_info.name}")
        print("=" * 50)

        for submodule_path in submodule_conflicts:
            print(f"\n🔍 Submodule: {submodule_path}")

            # Show submodule conflict details
            try:
                # Get Stage 2 (HEAD) commit
                stage2_commit = self.git_utils.sh(
                    ['git', 'rev-parse', f':2:{submodule_path}'],
                    cwd=repo_info.path,
                    capture=True
                )
                print(f"   HEAD commit: {stage2_commit[:8]}")
            except subprocess.CalledProcessError:
                print("   HEAD commit: (none)")

            try:
                # Get Stage 3 (incoming) commit
                stage3_commit = self.git_utils.sh(
                    ['git', 'rev-parse', f':3:{submodule_path}'],
                    cwd=repo_info.path,
                    capture=True
                )
                print(f"   Incoming commit: {stage3_commit[:8]}")
            except subprocess.CalledProcessError:
                print("   Incoming commit: (none)")

            print(f"\n📋 SUBMODULE RESOLUTION OPTIONS:")
            print(f"  1. Keep HEAD commit (current)")
            print(f"  2. Use incoming commit")
            print(f"  3. Manually resolve in submodule")
            print(f"  4. Skip this submodule")

            while True:
                choice = input(
                    f"\nChoose option for {submodule_path} (1/2/3/4): ").strip()

                if choice == '1':
                    # Keep HEAD commit
                    try:
                        self.git_utils.sh(
                            ['git', 'add', submodule_path], cwd=repo_info.path)
                        print(f"✅ Keeping HEAD commit for {submodule_path}")
                        break
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Failed to resolve {submodule_path}: {e}")
                        return False

                elif choice == '2':
                    # Use incoming commit
                    try:
                        stage3_commit = self.git_utils.sh(
                            ['git', 'rev-parse', f':3:{submodule_path}'],
                            cwd=repo_info.path,
                            capture=True
                        )
                        submodule_full_path = f"{repo_info.path}/{submodule_path}"
                        self.git_utils.sh(
                            ['git', 'checkout', stage3_commit], cwd=submodule_full_path)
                        self.git_utils.sh(
                            ['git', 'add', submodule_path], cwd=repo_info.path)
                        print(f"✅ Using incoming commit for {submodule_path}")
                        break
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Failed to resolve {submodule_path}: {e}")
                        return False

                elif choice == '3':
                    # Manual resolution
                    submodule_full_path = f"{repo_info.path}/{submodule_path}"
                    print(f"\n🖥️  Manual resolution for {submodule_path}")
                    print(f"   Path: {submodule_full_path}")
                    print("   Resolve the submodule state manually, then return here")
                    input("\nPress Enter when resolved...")

                    try:
                        self.git_utils.sh(
                            ['git', 'add', submodule_path], cwd=repo_info.path)
                        print(f"✅ Manually resolved {submodule_path}")
                        break
                    except subprocess.CalledProcessError as e:
                        print(f"❌ Failed to add {submodule_path}: {e}")
                        return False

                elif choice == '4':
                    print(f"⏭️  Skipping {submodule_path}")
                    return False

                else:
                    print("Please enter 1, 2, 3, or 4")

        # Try to continue the rebase
        try:
            self.git_utils.sh(
                ['git', 'rebase', '--continue'], cwd=repo_info.path)
            print("✅ Submodule conflicts resolved, rebase continued")
            return True
        except subprocess.CalledProcessError:
            print("⚠️  Rebase continue failed, may need additional resolution")
            return self._wait_for_conflict_resolution(repo_info)

    def _wait_for_conflict_resolution(self, repo_info: RepoInfo) -> bool:
        """Wait for user to resolve conflicts manually.

        Args:
            repo_info: Repository information

        Returns:
            True if conflicts were resolved successfully
        """
        print(f"\n⏳ Waiting for conflict resolution in {repo_info.name}")
        print("   Please resolve all conflicts manually, then:")
        print("   1. Stage your changes: git add <files>")
        print("   2. Continue the rebase: git rebase --continue")
        print("   3. Return here and press Enter")

        while True:
            input("\nPress Enter when conflicts are resolved and rebase continued...")

            # Check if rebase is still in progress
            if not self.git_utils.is_rebase_in_progress(repo_info.path):
                print("✅ Rebase completed successfully!")
                return True

            # Check for remaining conflicts
            regular_conflicts, submodule_conflicts = self.git_utils.get_conflicted_files(
                repo_info.path)

            if regular_conflicts or submodule_conflicts:
                print("⚠️  Conflicts still detected:")
                if regular_conflicts:
                    print(
                        f"   📄 File conflicts: {', '.join(regular_conflicts)}")
                if submodule_conflicts:
                    print(
                        f"   📦 Submodule conflicts: {', '.join(submodule_conflicts)}")
                print("   Please continue resolving conflicts...")
                continue

            # Try to continue the rebase
            try:
                self.git_utils.sh(
                    ['git', 'rebase', '--continue'], cwd=repo_info.path)
                print("✅ Rebase continued successfully!")

                # Check if rebase is now complete
                if not self.git_utils.is_rebase_in_progress(repo_info.path):
                    print("✅ Rebase completed successfully!")
                    return True
                else:
                    print("🔄 Rebase continuing, may encounter more conflicts...")
                    continue

            except subprocess.CalledProcessError as e:
                print(f"⚠️  Failed to continue rebase: {e}")
                print("   Please check the repository state and try again")
                continue
