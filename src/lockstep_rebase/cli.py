"""
Command-line interface for the Git submodule rebase tool.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, List

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.tree import Tree

from .rebase_orchestrator import RebaseOrchestrator
from .cli_prompt import CliPrompt
from .cli_conflict_prompt import CliConflictPrompt
from .models import RebaseError


console = Console()


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option(
    "--repo-path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to repository (defaults to current directory)",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, repo_path: Optional[Path]) -> None:
    """Git Submodule Rebase Tool - Professional rebase operations for tightly coupled submodules."""
    setup_logging(verbose)

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["repo_path"] = repo_path


@cli.command()
@click.argument("source_branch")
@click.argument("target_branch")
@click.option("--dry-run", is_flag=True, help="Show what would be done without executing")
@click.option("--force", is_flag=True, help="Force rebase even with validation warnings")
@click.pass_context
def rebase(
    ctx: click.Context, source_branch: str, target_branch: str, dry_run: bool, force: bool
) -> None:
    """
    Rebase SOURCE_BRANCH onto TARGET_BRANCH across all submodules.

    Example: lockstep-rebase rebase feature/my-feature main
    """
    try:
        conflict_prompt = CliConflictPrompt(console)
        orchestrator = RebaseOrchestrator(ctx.obj.get("repo_path"), conflict_prompt)
        prompt = CliPrompt(console)

        # Show repository hierarchy
        console.print("\n🔍 **Discovered Repository Structure**")
        try:
            hierarchy_lines = orchestrator.get_repo_heirarchy()
        except Exception:
            hierarchy_lines = None
        if isinstance(hierarchy_lines, (list, tuple)):
            for line in hierarchy_lines:
                console.print(line)

        # Validate repository state
        validation_errors = orchestrator.validate_repository_state(prompt)
        if validation_errors and not force:
            console.print("\n❌ **Validation Errors:**", style="bold red")
            for error in validation_errors:
                console.print(f"  • {error}")
            console.print("\nUse --force to proceed anyway, or fix the issues above.")
            sys.exit(1)
        elif validation_errors:
            console.print(
                "\n⚠️  **Validation Warnings (proceeding with --force):**", style="bold yellow"
            )
            for error in validation_errors:
                console.print(f"  • {error}")

        # Plan the rebase
        console.print("\n📋 **Planning Rebase Operation**")
        console.print(f"Source Branch: {source_branch}")
        console.print(f"Target Branch: {target_branch}")

        operation = orchestrator.plan_rebase(source_branch, target_branch, prompt)

        # Show rebase plan
        _display_rebase_plan(operation)

        if dry_run:
            console.print("\n🔍 **Dry Run Complete** - No changes made")
            return

        # Confirm execution
        if not click.confirm("\nProceed with rebase operation?"):
            console.print("Operation cancelled.")
            return

        # Execute the rebase
        if orchestrator.execute_rebase(operation):
            console.print("\n🎉 **Rebase completed successfully!**", style="bold green")

            # Get resolution summary for display
            resolution_summary = None
            if orchestrator.conflict_resolver.has_resolutions():
                resolution_summary = orchestrator.conflict_resolver.get_resolution_summary()

            # Show commit mappings with auto-resolved commits organized by repository
            _display_commit_mappings(operation, resolution_summary)

            # Prompt to delete backups
            try:
                backups = len(operation.backup_branches)
            except Exception:
                backups = 0
            if backups:
                if click.confirm(
                    f"\nDelete {backups} backup branch(es) created for this rebase?", default=False
                ):
                    deleted = orchestrator.delete_backups(operation)
                    console.print(
                        f"🧹 Deleted {deleted} backup branch(es)", style="bold green"
                    )
                else:
                    console.print(
                        "🔒 Keeping backup branches. Use 'lockstep-rebase backups' to manage them.",
                        style="yellow",
                    )
        else:
            console.print("\n❌ **Rebase failed!**", style="bold red")
            sys.exit(1)

    except RebaseError as e:
        console.print(f"\n❌ **Rebase Error:** {e}", style="bold red")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n💥 **Unexpected Error:** {e}", style="bold red")
        if ctx.obj.get("verbose"):
            console.print_exception()
        sys.exit(1)


@cli.group()
@click.pass_context
def backups(ctx: click.Context) -> None:
    """Manage backup branches in the current repository."""
    pass


@backups.command("list")
@click.option("--original-branch", "original_branch", type=str, help="Filter by original branch")
@click.option("--session-id", type=str, help="Filter by session id (timestamp)")
@click.option("--latest", is_flag=True, help="Show only the most recent session (ignored if --session-id is given)")
@click.option("--repo-path", type=click.Path(exists=True, path_type=Path), help="Restrict to a single repository path")
@click.pass_context
def backups_list(
    ctx: click.Context, original_branch: str, session_id: Optional[str], latest: bool, repo_path: Optional[Path]
) -> None:
    """List backup branches. By default, lists across the repository hierarchy."""
    try:
        root = repo_path or ctx.obj.get("repo_path")
        orchestrator = RebaseOrchestrator(root)

        if repo_path:
            entries = orchestrator.list_parsed_backups_in_repo(repo_path, original_branch=original_branch)
        else:
            entries = orchestrator.list_backups_across_hierarchy(original_branch=original_branch)

        # Narrow by session: explicit session-id takes precedence over --latest
        if session_id:
            entries = [e for e in entries if e.session == session_id]
        elif latest and entries:
            latest_session = max({e.session for e in entries})
            entries = [e for e in entries if e.session == latest_session]

        if not entries:
            console.print("No backup branches found.")
            return

        # Group by session -> original_branch, display compact tables with only repo/path
        sessions: dict[str, dict[str, list]] = {}
        for e in entries:
            sessions.setdefault(e.session, {}).setdefault(e.original_branch, []).append(e)

        for session in sorted(sessions.keys(), reverse=True):
            session_tree = Tree(f"🗂️ Session: [bold]{session}[/bold]", guide_style="dim")

            for orig in sorted(sessions[session].keys()):
                group = sessions[session][orig]
                backup_branch = group[0].backup_branch if group else ""

                # Inline list of repos to minimize vertical space
                items = []
                for entry in sorted(group, key=lambda e: (e.repo_name, str(e.repo_path))):
                    rel = str(entry.repo_path.relative_to(orchestrator.root_path))
                    items.append(f"{entry.repo_name} ({rel})")
                repos_line = ", ".join(items)

                branch_node = session_tree.add(
                    f"[green]{orig}[/green] • [cyan]{backup_branch}[/cyan] • {len(group)} repo(s)"
                )
                branch_node.add(repos_line)

            console.print(session_tree)
    except Exception as e:
        console.print(f"\n❌ **Error listing backups:** {e}", style="bold red")
        sys.exit(1)


@backups.command("delete")
@click.option("--branch", "backup_branch", multiple=True, help="Backup branch to delete (repeatable)")
@click.option("--all", "delete_all", is_flag=True, help="Delete all backup branches")
@click.option("--session-id", type=str, help="Delete all backups for a session (hierarchy-wide unless --repo-path is given)")
@click.option("--latest", is_flag=True, help="Delete backups from the most recent session (ignored if --session-id is given)")
@click.option("--repo-path", type=click.Path(exists=True, path_type=Path), help="Repository path")
@click.pass_context
def backups_delete(
    ctx: click.Context,
    backup_branch: List[str],
    delete_all: bool,
    session_id: Optional[str],
    latest: bool,
    repo_path: Optional[Path],
) -> None:
    """Delete backup branches (interactive if no options provided)."""
    try:
        root = repo_path or ctx.obj.get("repo_path")
        orchestrator = RebaseOrchestrator(root)

        # Session-based deletion (preferred)
        if session_id or latest:
            if repo_path:
                entries = orchestrator.list_parsed_backups_in_repo(repo_path)
            else:
                entries = orchestrator.list_backups_across_hierarchy()

            if session_id:
                entries = [e for e in entries if e.session == session_id]
            elif latest and entries:
                latest_session = max({e.session for e in entries})
                entries = [e for e in entries if e.session == latest_session]

            if not entries:
                console.print("No backups matching the given session id.")
                return

            count = 0
            for e in entries:
                if orchestrator.delete_backup_in_repo(e.backup_branch, e.repo_path):
                    count += 1
            effective_session = session_id if session_id else latest_session
            console.print(f"🧹 Deleted {count} backup branch(es) for session {effective_session}")
            return

        target_path = repo_path or ctx.obj.get("repo_path")
        branches = orchestrator.list_backups_in_repo(target_path)

        if delete_all:
            count = 0
            for b in branches:
                if orchestrator.delete_backup_in_repo(b, target_path):
                    count += 1
            console.print(f"🧹 Deleted {count} backup branch(es)")
            return

        to_delete = list(backup_branch)
        if not to_delete:
            if not branches:
                console.print("No backup branches to delete.")
                return
            console.print("Select backups to delete:")
            for idx, b in enumerate(sorted(branches), 1):
                console.print(f"  {idx}. {b}")
            choices = click.prompt(
                "Enter numbers separated by commas (or empty to cancel)", default=""
            )
            if not choices.strip():
                console.print("Cancelled.")
                return
            try:
                indices = {int(x.strip()) for x in choices.split(",") if x.strip()}
            except ValueError:
                console.print("Invalid selection.")
                sys.exit(1)
            sorted_branches = list(sorted(branches))
            for i in indices:
                if 1 <= i <= len(sorted_branches):
                    to_delete.append(sorted_branches[i - 1])

        count = 0
        for b in to_delete:
            if orchestrator.delete_backup_in_repo(b, target_path):
                count += 1
        console.print(f"🧹 Deleted {count} backup branch(es)")
    except Exception as e:
        console.print(f"\n❌ **Error deleting backups:** {e}", style="bold red")
        sys.exit(1)


@backups.command("restore")
@click.argument("original_branch", required=False)
@click.option("--session-id", type=str, help="Session id (timestamp) of backup to restore. If provided without original_branch, restores all branches with that session.")
@click.option("--latest", is_flag=True, help="Use most recent session if --session-id is not provided")
@click.pass_context
def backups_restore(
    ctx: click.Context, original_branch: Optional[str], session_id: Optional[str], latest: bool
) -> None:
    """Restore the original branch across the hierarchy from backups."""
    try:
        orchestrator = RebaseOrchestrator(ctx.obj.get("repo_path"))

        # If restoring by session only (no original branch specified)
        if (session_id or latest) and not original_branch:
            entries = orchestrator.list_backups_across_hierarchy()
            if session_id:
                entries = [e for e in entries if e.session == session_id]
                effective_session = session_id
            elif latest and entries:
                effective_session = max({e.session for e in entries})
                entries = [e for e in entries if e.session == effective_session]
            else:
                effective_session = None
            if not entries:
                console.print("No matching backups found for the session id.")
                return

            branches = sorted({e.original_branch for e in entries})
            total_restored = 0
            for br in branches:
                total_restored += orchestrator.restore_original_branches_across_hierarchy(
                    br, session_id=effective_session
                )
            if total_restored == 0:
                console.print("No matching backups found.")
            else:
                console.print(
                    f"✅ Restored original branch(es) in {total_restored} repos for session {effective_session}"
                )
            return

        # Default behavior: restore a specific original branch (optionally restricted to a session)
        if not original_branch:
            console.print("You must specify either ORIGINAL_BRANCH or --session-id.")
            sys.exit(1)

        # If --latest provided for a specific original branch
        if latest and not session_id:
            entries = orchestrator.list_backups_across_hierarchy(original_branch=original_branch)
            if not entries:
                console.print("No matching backups found.")
                return
            session_id = max({e.session for e in entries})

        restored = orchestrator.restore_original_branches_across_hierarchy(
            original_branch, session_id=session_id
        )
        if restored == 0:
            console.print("No matching backups found.")
        else:
            console.print(f"✅ Restored original branch in {restored} repos")
    except Exception as e:
        console.print(f"\n❌ **Error restoring backups:** {e}", style="bold red")
        sys.exit(1)
@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show status of all repositories in the hierarchy."""
    try:
        orchestrator = RebaseOrchestrator(ctx.obj.get("repo_path"))

        console.print("\n📊 **Repository Status**")
        status_info = orchestrator.get_repository_status()

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Repository", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Current Branch", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Type", style="blue")

        for repo_name, info in status_info.items():
            if "error" in info:
                table.add_row(
                    repo_name,
                    info.get("path", "Unknown"),
                    "Error",
                    f"❌ {info['error']}",
                    "Unknown",
                )
            else:
                status_text = "🔄 Rebasing" if info["is_rebasing"] == "True" else "✅ Clean"
                repo_type = (
                    f"📦 Submodule (L{info['depth']})"
                    if info["is_submodule"] == "True"
                    else "📁 Root"
                )

                table.add_row(
                    repo_name, info["path"], info["current_branch"], status_text, repo_type
                )

        console.print(table)

    except Exception as e:
        console.print(f"\n❌ **Error getting status:** {e}", style="bold red")
        sys.exit(1)


@cli.command()
@click.pass_context
def hierarchy(ctx: click.Context) -> None:
    """Display the repository hierarchy."""
    try:
        orchestrator = RebaseOrchestrator(ctx.obj.get("repo_path"))
        console.print("\n📁 **Repository Hierarchy**")

        # Prefer structured entries for a rich table view
        displayed_table = False
        try:
            entries = orchestrator.get_hierarchy_entries()
        except Exception:
            entries = None

        if isinstance(entries, (list, tuple)) and entries:
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Repository", style="cyan")
            table.add_column("Path", style="dim")
            table.add_column("Depth", justify="right")
            table.add_column("Type", style="blue")
            table.add_column("Parent", style="yellow")

            for e in entries:
                repo_type = "📦 Submodule" if getattr(e, "is_submodule", False) else "📁 Root"
                table.add_row(
                    getattr(e, "name", ""),
                    str(getattr(e, "path", "")),
                    str(getattr(e, "depth", "")),
                    repo_type,
                    getattr(e, "parent_name", "") or "",
                )

            console.print(table)
            displayed_table = True

        # Backward-compatible call expected by tests; print as fallback only
        try:
            lines = orchestrator.print_repository_hierarchy()
        except Exception:
            lines = None
        if not displayed_table and isinstance(lines, (list, tuple)):
            for line in lines:
                console.print(line)

    except Exception as e:
        console.print(f"\n❌ **Error displaying hierarchy:** {e}", style="bold red")
        sys.exit(1)


@cli.command()
@click.argument("source_branch")
@click.argument("target_branch")
@click.pass_context
def validate(ctx: click.Context, source_branch: str, target_branch: str) -> None:
    """Validate that branches exist and repositories are ready for rebase."""
    try:
        orchestrator = RebaseOrchestrator(ctx.obj.get("repo_path"))

        console.print("\n🔍 **Validating Rebase Prerequisites**")
        console.print(f"Source Branch: {source_branch}")
        console.print(f"Target Branch: {target_branch}")

        # Validate repository state
        validation_errors = orchestrator.validate_repository_state()

        # Try to plan the rebase to validate branches
        try:
            orchestrator.plan_rebase(source_branch, target_branch)
            console.print("\n✅ **Branch Validation:** All branches exist", style="bold green")
        except RebaseError as e:
            console.print(f"\n❌ **Branch Validation Failed:** {e}", style="bold red")
            validation_errors.append(f"Branch validation: {e}")

        if validation_errors:
            console.print("\n❌ **Repository State Issues:**", style="bold red")
            for error in validation_errors:
                console.print(f"  • {error}")
            sys.exit(1)
        else:
            console.print("\n🎉 **All validations passed!**", style="bold green")

    except Exception as e:
        console.print(f"\n❌ **Validation error:** {e}", style="bold red")
        sys.exit(1)


def _display_rebase_plan(operation) -> None:
    """Display the rebase execution plan."""
    console.print("\n📋 **Rebase Execution Plan**")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Order", justify="center")
    table.add_column("Repository", style="cyan")
    table.add_column("Path", style="dim")
    table.add_column("Commits to Rebase", justify="center", style="yellow")
    table.add_column("Type", style="blue")

    for i, state in enumerate(operation.repo_states, 1):
        repo_type = f"📦 Submodule (L{state.repo.depth})" if state.repo.is_submodule else "📁 Root"

        table.add_row(
            str(i),
            state.repo.name,
            state.repo.relative_path,
            str(len(state.original_commits)),
            repo_type,
        )

    console.print(table)


def _display_commit_mappings(operation, resolution_summary=None) -> None:
    """Display commit hash mappings after successful rebase."""
    if not operation.global_commit_mapping:
        return

    console.print("\n🔗 **Commit Hash Mappings**")

    # If we have resolution summary, show auto-resolved commits organized by repo
    if resolution_summary and resolution_summary.resolved_commits_by_repo:
        console.print("\n📦 **Auto-Resolved Submodule Commits by Repository:**")

        # Create table for auto-resolved commits
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Repository", style="cyan")
        table.add_column("Submodule", style="yellow")
        table.add_column("Old Hash", style="red")
        table.add_column("New Hash", style="green")
        table.add_column("Message", style="dim")
        table.add_column("Status", style="blue")

        # Sort repositories by name for consistent display
        for repo_name in sorted(resolution_summary.resolved_commits_by_repo.keys()):
            commits = resolution_summary.resolved_commits_by_repo[repo_name]
            if not commits:
                continue

            for i, commit in enumerate(commits):
                # Only show repo name for first commit of each repo
                repo_display = repo_name if i == 0 else ""

                # Check if this commit has message consistency issues
                status = "✅ OK"
                for issue in resolution_summary.message_consistency_issues:
                    if f"{repo_name}/{commit.submodule_path}" in issue:
                        status = "⚠️ Message Mismatch"
                        break

                table.add_row(
                    repo_display,
                    commit.submodule_path,
                    commit.original_hash[:8],
                    commit.resolved_hash[:8],
                    commit.message,
                    status,
                )

        console.print(table)

        # Show message consistency issues if any
        if resolution_summary.message_consistency_issues:
            console.print("\n⚠️  **Message Consistency Issues:**", style="bold yellow")
            for issue in resolution_summary.message_consistency_issues:
                console.print(f"   • {issue}")


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n\n🚫 **Operation cancelled by user**", style="bold yellow")
        sys.exit(130)
    except Exception as e:
        console.print(f"\n💥 **Unexpected error:** {e}", style="bold red")
        sys.exit(1)


if __name__ == "__main__":
    main()
