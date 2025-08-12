"""
Command-line interface for lockstep rebase operations.

This module provides the main CLI entry point and argument parsing
for the lockstep rebase tool.
"""

import argparse
import os
import sys
from typing import NoReturn

from ._version import VERSION

from .core.manager import NestedRebaseManager


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the CLI.
    
    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(
        description="Recursively rebase repositories with nested submodules in lockstep",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be rebased (auto-discovers Git root)
  lockstep-rebase --dry-run
  
  # Rebase with verbose output
  lockstep-rebase --verbose
  
  # Start discovery from a specific directory
  lockstep-rebase --root /path/to/somewhere/in/repo
  
  # Manage existing backup branches
  lockstep-rebase --manage-backups
  
  # The tool automatically finds the Git repository root regardless
  # of where you run it from within the repository
        """
    )
    
    parser.add_argument(
        '--root',
        default='.',
        help='Starting path for Git repository discovery (default: current directory)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--manage-backups',
        action='store_true',
        help='Manage backup branches (list, delete) instead of running rebase'
    )
    parser.add_argument(
        '--version',
        action='version',
        version=f'%(prog)s {VERSION}'
    )
    
    return parser


def find_and_validate_root_path(specified_root: str, verbose: bool = False) -> str:
    """Find and validate the Git repository root path.
    
    Args:
        specified_root: User-specified root path (may be relative or not the actual root)
        verbose: Enable verbose output
        
    Returns:
        Absolute path to the actual Git repository root
        
    Raises:
        SystemExit: If no valid Git repository is found
    """
    from .core.git_utils import GitUtils
    
    git_utils = GitUtils(verbose=verbose)
    
    # Convert to absolute path
    start_path = os.path.abspath(specified_root)
    
    # Check if the specified path exists
    if not os.path.exists(start_path):
        print(f"❌ Error: Path '{start_path}' does not exist")
        sys.exit(1)
    
    if not os.path.isdir(start_path):
        print(f"❌ Error: Path '{start_path}' is not a directory")
        sys.exit(1)
    
    # Try to find the Git repository root
    git_root = git_utils.find_git_root(start_path)
    
    if not git_root:
        print(f"❌ Error: No Git repository found in '{start_path}' or any parent directories")
        print("   Make sure you're running this command from within a Git repository.")
        sys.exit(1)
    
    # If the found root is different from what was specified, inform the user
    if git_root != start_path:
        if verbose:
            print(f"📍 Auto-discovered Git repository root: {git_root}")
            print(f"   (started from: {start_path})")
        else:
            print(f"📍 Using Git repository root: {os.path.basename(git_root)}")
    
    return git_root


def main() -> NoReturn:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    # Find and validate the actual Git repository root
    root_path = find_and_validate_root_path(args.root, args.verbose)
    
    # Create the rebase manager
    manager = NestedRebaseManager(dry_run=args.dry_run, verbose=args.verbose)
    
    # Handle backup management mode
    if args.manage_backups:
        try:
            manager.manage_backups_interactive(root_path)
        except KeyboardInterrupt:
            print("\n\n⏹️  Backup management cancelled by user")
        except Exception as e:
            print(f"\n❌ Error: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
        sys.exit(0)
    
    # Run the nested rebase
    try:
        manager.run_nested_rebase(root_path)
    except KeyboardInterrupt:
        print("\n\n⏹️  Operation cancelled by user")
        print("🛑 Cleaning up active rebases...")
        manager.abort_all_active_rebases()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("🛑 Cleaning up active rebases...")
        manager.abort_all_active_rebases()
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
