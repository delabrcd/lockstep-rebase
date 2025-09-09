"""
Command-line interface for the Git submodule rebase tool.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
import sys
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.tree import Tree

from .rebase_orchestrator import RebaseOrchestrator
from .cli_prompt import CliPrompt
from .cli_conflict_prompt import CliConflictPrompt
from .models import RebaseError, ResolutionSummary
from . import __version__ as PACKAGE_VERSION


console = Console()
logger = logging.getLogger(__name__)


def _print_version(ctx, param, value):
    """Eager option callback to print version and exit."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(f"lockstep-rebase {PACKAGE_VERSION}")
    ctx.exit()


def _default_log_path() -> Path:
    """Determine default log file path (~/.lockstep-rebase/lockstep-rebase.log)."""
    env_path = os.environ.get("LOCKSTEP_REBASE_LOG")
    if env_path:
        p = Path(env_path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    base = Path.home() / ".lockstep-rebase"
    base.mkdir(parents=True, exist_ok=True)
    return base / "lockstep-rebase.log"


class SafeConsoleFormatter(logging.Formatter):
    """Formatter that replaces characters not encodable by the target console encoding.

    This prevents UnicodeEncodeError on Windows terminals using legacy code pages (e.g., cp1252)
    when log messages include emoji or other non-representable characters. File handlers keep
    full UTF-8 output; only console output is sanitized.
    """

    def __init__(self, fmt: Optional[str] = None, datefmt: Optional[str] = None, style: str = "%", encoding: Optional[str] = None):
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)
        self.encoding = encoding or getattr(sys.stderr, "encoding", None) or "utf-8"

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        try:
            msg.encode(self.encoding, errors="strict")
            return msg
        except Exception:
            # Replace unencodable characters for display only
            return msg.encode(self.encoding, errors="replace").decode(self.encoding, errors="replace")


class SafeConsoleFilter(logging.Filter):
    """Sanitize record messages for console by replacing unencodable characters.

    This runs before handler emission and is effective with RichHandler which may
    bypass standard formatters for message text.
    """

    def __init__(self, encoding: Optional[str] = None):
        super().__init__()
        self.encoding = encoding or getattr(sys.stderr, "encoding", None) or "utf-8"

    def filter(self, record: logging.LogRecord) -> bool:  # always keep the record
        try:
            message = record.getMessage()
        except Exception:
            return True
        try:
            message.encode(self.encoding, errors="strict")
            return True
        except Exception:
            safe = message.encode(self.encoding, errors="replace").decode(self.encoding, errors="replace")
            # Replace the message and clear args to avoid double formatting
            record.msg = safe
            record.args = ()
            return True


def setup_logging(verbose: bool = False, console_level: Optional[str] = None, log_file: Optional[Path] = None) -> Path:
    """Setup logging with per-run file + stable aggregate, fully cross-platform:
    - Per-run log file: <stem>-YYYYMMDD_HHMMSS.log (non-rotating)
    - Stable aggregate log: <stem>.log (rotated)
    - Best-effort hardlink: <stem>-current.log -> per-run file (Windows-friendly)
    - Console logging disabled by default; enable via --verbose or --log-level
    Returns the best path to open for this run (current-link if created, else aggregate, else per-run).
    """
    # Determine base paths
    provided = Path(log_file) if log_file else _default_log_path()
    if provided.exists() and provided.is_dir():
        base_dir = provided
        base_stem = "lockstep-rebase"
        stable_aggregate_path = base_dir / f"{base_stem}.log"
    else:
        base_dir = provided.parent
        base_stem = provided.stem or "lockstep-rebase"
        stable_aggregate_path = provided
    base_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    per_run_path = base_dir / f"{base_stem}-{timestamp}.log"
    current_link_path = base_dir / f"{base_stem}-current.log"

    root = logging.getLogger()
    # Clear existing handlers to avoid duplication in tests / repeated invocations
    root.handlers.clear()
    root.setLevel(logging.DEBUG)

    # File handler -> per-run file (non-rotating; bounded by run duration)
    run_file_handler = logging.FileHandler(str(per_run_path), encoding="utf-8")
    run_file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    run_file_handler.setFormatter(file_fmt)
    root.addHandler(run_file_handler)

    # Second handler -> stable aggregate file (provides an easy always-on path)
    aggregate_handler = RotatingFileHandler(
        str(stable_aggregate_path), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    aggregate_handler.setLevel(logging.DEBUG)
    aggregate_handler.setFormatter(file_fmt)
    root.addHandler(aggregate_handler)

    # Best-effort: create a hardlink pointing at the current run (works on NTFS/Unix without admin)
    created_hardlink = False
    try:
        if current_link_path.exists():
            try:
                current_link_path.unlink()
            except Exception:
                pass
        os.link(per_run_path, current_link_path)
        created_hardlink = True
    except Exception:
        # Hardlinks may be unsupported across volumes or filesystems; ignore
        created_hardlink = False

    # Console handler (optional)
    if verbose or console_level:
        level_map = {
            None: logging.INFO,
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "warning": logging.WARNING,
            "error": logging.ERROR,
        }
        ch_level = level_map.get((console_level or "info").lower(), logging.INFO)
        console_handler = RichHandler(console=console, rich_tracebacks=True)
        console_handler.setLevel(ch_level)
        # Determine console stream encoding and sanitize messages for display
        try:
            stream = getattr(console, "file", sys.stderr)
            enc = getattr(stream, "encoding", None) or getattr(sys.stderr, "encoding", None) or "utf-8"
        except Exception:
            enc = getattr(sys.stderr, "encoding", None) or "utf-8"
        console_handler.setFormatter(SafeConsoleFormatter("%(message)s", encoding=enc))
        console_handler.addFilter(SafeConsoleFilter(encoding=enc))
        root.addHandler(console_handler)

    # Choose the most convenient path to present to the user
    if created_hardlink:
        notice_path = current_link_path
    elif stable_aggregate_path:
        notice_path = stable_aggregate_path
    else:
        notice_path = per_run_path
    return notice_path


def _maybe_print_log_notice(verbose: bool, console_level: Optional[str], log_path: Path) -> None:
    """Inform user about logging destination and how to enable console logs."""
    if verbose or console_level:
        return
    console.print(f"[dim]Logs are written to {log_path}. Console logs are disabled by default. Use -v or --log-level to enable.[/dim]")


@click.group()
@click.option(
    "--version",
    "-V",
    is_flag=True,
    callback=_print_version,
    expose_value=False,
    is_eager=True,
    help="Show version and exit.",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose console logging (INFO)")
@click.option(
    "--log-level",
    type=click.Choice(["debug", "info", "warning", "error"], case_sensitive=False),
    default=None,
    help="Console log level. By default, console logging is disabled.",
)
@click.option(
    "--repo-path",
    type=click.Path(exists=True, path_type=Path),
    help="Path to repository (defaults to current directory)",
)
@click.pass_context
def cli(ctx: click.Context, verbose: bool, log_level: Optional[str], repo_path: Optional[Path]) -> None:
    """Git Submodule Rebase Tool - Professional rebase operations for tightly coupled submodules."""
    log_path = setup_logging(verbose, console_level=log_level)

    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose
    ctx.obj["console_level"] = log_level
    ctx.obj["log_path"] = log_path
    normalized_repo = repo_path.resolve() if isinstance(repo_path, Path) else None
    ctx.obj["repo_path"] = normalized_repo
    try:
        logger.debug(
            f"CLI init: cwd={Path.cwd()} repo_path_in={repo_path} normalized_repo={normalized_repo}"
        )
    except Exception:
        pass


@cli.command()
@click.argument("source_branch")
@click.argument("target_branch")
@click.option("--dry-run", is_flag=True, help="Show what would be done without executing")
@click.option("--force", is_flag=True, help="Force rebase even with validation warnings")
@click.option(
    "--no-auto-planning",
    "no_auto_planning",
    is_flag=True,
    help="Disable auto-discovery planning (use manual planning instead)",
)
@click.option(
    "--include",
    "includes",
    multiple=True,
    help="Include only these repositories (name or relative path). Repeatable.",
)
@click.option(
    "--exclude",
    "excludes",
    multiple=True,
    help="Exclude these repositories (name or relative path). Repeatable.",
)
@click.option(
    "--branch-map",
    "branch_map_items",
    multiple=True,
    help="Per-repo branch mapping: repo=SRC[:TGT]. Repeatable.",
)
@click.option(
    "--offer-force-push",
    is_flag=True,
    help="After successful rebase, offer to force push updated local branches to origin (requires typed confirmation).",
)
@click.pass_context
def rebase(
    ctx: click.Context,
    source_branch: str,
    target_branch: str,
    dry_run: bool,
    force: bool,
    no_auto_planning: bool,
    includes: tuple[str, ...],
    excludes: tuple[str, ...],
    branch_map_items: tuple[str, ...],
    offer_force_push: bool,
) -> None:
    """
    Rebase SOURCE_BRANCH onto TARGET_BRANCH across all submodules.

    Example: lockstep-rebase rebase feature/my-feature main
    """
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
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

        # Parse include/exclude and branch map
        include_set = {s.strip() for s in includes if s.strip()}
        exclude_set = {s.strip() for s in excludes if s.strip()}

        branch_map: dict[str, tuple[str, str | None]] = {}
        for item in branch_map_items:
            if not item or "=" not in item:
                continue
            key, val = item.split("=", 1)
            key = key.strip()
            src, sep, tgt = val.partition(":")
            src = src.strip()
            tgt = tgt.strip() if sep else None
            if key and src:
                branch_map[key] = (src, tgt or None)

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

        if no_auto_planning:
            console.print("Mode: Manual planning (auto-discovery disabled) 🚫")
            operation = orchestrator.plan_rebase(
                source_branch,
                target_branch,
                prompt,
                include=include_set or None,
                exclude=exclude_set or None,
                branch_map=branch_map or None,
            )
        else:
            console.print("Mode: Auto-discovery of updated submodules ✅")
            operation = orchestrator.plan_rebase_auto(
                source_branch,
                target_branch,
                prompt,
                include=include_set or None,
                exclude=exclude_set or None,
                branch_map_overrides=branch_map or None,
            )

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
        if not orchestrator.execute_rebase(operation):
            console.print("\n❌ **Rebase failed!**", style="bold red")
            return

        console.print("\n🎉 **Rebase completed successfully!**", style="bold green")

        # Get resolution summary for display (only if explicitly True)
        resolution_summary = orchestrator.collect_resolution_summary()
        # Show commit mappings with auto-resolved commits organized by repository
        _display_commit_mappings(resolution_summary)

        # Optionally offer to force push updated branches with explicit confirmation
        if offer_force_push:
            orchestrator.maybe_force_push(operation, prompt)

        # Prompt to delete backups
        # Prefer showing the count across the hierarchy for the current session
        total_backups = len(operation.backup_branches)
        session_id = getattr(operation, "backup_session_id", None)
        if isinstance(session_id, str) and session_id:
            entries = orchestrator.list_backups_across_hierarchy()
            total_backups = len([e for e in entries if e.session == session_id])

        if total_backups:
            if click.confirm(
                f"\nDelete {total_backups} backup branch(es) created for this rebase session?",
                default=False,
            ):
                deleted = orchestrator.delete_backups(operation)
                console.print(f"🧹 Deleted {deleted} backup branch(es)", style="bold green")
            else:
                console.print(
                    "🔒 Keeping backup branches. Use 'lockstep-rebase backups' to manage them.",
                    style="yellow",
                )

    except RebaseError as e:
        console.print(f"\n❌ **Rebase Error:** {e}", style="bold red")
        # Debug stack trace to file logs for diagnostics
        logger.debug("Rebase aborted due to RebaseError", exc_info=True)
        sys.exit(1)
    except (click.Abort, KeyboardInterrupt):
        console.print("\n\n🚫 **Operation cancelled by user**", style="bold yellow")
        # Debug stack trace for cancellation context
        logger.debug("Operation cancelled by user", exc_info=True)
        sys.exit(130)
    except Exception as e:
        console.print(f"\n💥 **Unexpected Error:** {e}", style="bold red")
        if ctx.obj.get("verbose"):
            console.print_exception()
        # Debug stack trace to file logs for diagnostics
        logger.debug("Unexpected error during rebase", exc_info=True)
        sys.exit(1)


@cli.group()
@click.pass_context
def backups(ctx: click.Context) -> None:
    """Manage backup branches in the current repository."""
    pass


@backups.command("list")
@click.option("--original-branch", "original_branch", type=str, help="Filter by original branch")
@click.option("--session-id", type=str, help="Filter by session id (timestamp)")
@click.option(
    "--latest",
    is_flag=True,
    help="Show only the most recent session (ignored if --session-id is given)",
)
@click.option(
    "--repo-path",
    type=click.Path(exists=True, path_type=Path),
    help="Restrict to a single repository path",
)
@click.pass_context
def backups_list(
    ctx: click.Context,
    original_branch: str,
    session_id: Optional[str],
    latest: bool,
    repo_path: Optional[Path],
) -> None:
    """List backup branches. By default, lists across the repository hierarchy."""
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
        root = repo_path or ctx.obj.get("repo_path")
        orchestrator = RebaseOrchestrator(root)

        if repo_path:
            entries = orchestrator.list_parsed_backups_in_repo(
                repo_path, original_branch=original_branch
            )
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
        # Debug stack trace to file logs for diagnostics
        logger.debug("Error in backups list", exc_info=True)
        sys.exit(1)


@backups.command("delete")
@click.option(
    "--branch", "backup_branch", multiple=True, help="Backup branch to delete (repeatable)"
)
@click.option("--all", "delete_all", is_flag=True, help="Delete all backup branches")
@click.option(
    "--session-id",
    type=str,
    help="Delete all backups for a session (hierarchy-wide unless --repo-path is given)",
)
@click.option(
    "--latest",
    is_flag=True,
    help="Delete backups from the most recent session (ignored if --session-id is given)",
)
@click.option(
    "--original-branch",
    "original_branch",
    type=str,
    help="Filter by original branch when using --session-id/--latest",
)
@click.option("--repo-path", type=click.Path(exists=True, path_type=Path), help="Repository path")
@click.pass_context
def backups_delete(
    ctx: click.Context,
    backup_branch: List[str],
    delete_all: bool,
    session_id: Optional[str],
    latest: bool,
    original_branch: Optional[str],
    repo_path: Optional[Path],
) -> None:
    """Delete backup branches (interactive if no options provided)."""
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
        root = repo_path or ctx.obj.get("repo_path")
        orchestrator = RebaseOrchestrator(root)

        # Session-based deletion (preferred). Operates across hierarchy by default.
        if session_id or latest:
            if repo_path:
                entries = orchestrator.list_parsed_backups_in_repo(repo_path)
            else:
                entries = orchestrator.list_backups_across_hierarchy()

            # Optional filtering by original branch to narrow scope
            if original_branch:
                entries = [e for e in entries if e.original_branch == original_branch]

            if session_id:
                entries = [e for e in entries if e.session == session_id]
                effective_session = session_id
            elif latest and entries:
                latest_session = max({e.session for e in entries})
                entries = [e for e in entries if e.session == latest_session]
                effective_session = latest_session
            else:
                effective_session = None

            if not entries:
                console.print("No backups matching the given session id.")
                return

            count = 0
            for e in entries:
                if orchestrator.delete_backup_in_repo(e.backup_branch, e.repo_path):
                    count += 1
            if effective_session:
                console.print(
                    f"🧹 Deleted {count} backup branch(es) for session {effective_session}"
                )
            else:
                console.print(f"🧹 Deleted {count} backup branch(es)")
            return

        # Per-repo deletion modes if explicitly requested
        target_path = repo_path or ctx.obj.get("repo_path")
        if delete_all:
            branches = orchestrator.list_backups_in_repo(target_path)
            count = 0
            for b in branches:
                if orchestrator.delete_backup_in_repo(b, target_path):
                    count += 1
            console.print(f"🧹 Deleted {count} backup branch(es)")
            return

        if backup_branch:
            count = 0
            for b in backup_branch:
                if orchestrator.delete_backup_in_repo(b, target_path):
                    count += 1
            console.print(f"🧹 Deleted {count} backup branch(es)")
            return

        # Default: interactive session picker across the hierarchy
        entries = orchestrator.list_backups_across_hierarchy(
            original_branch=original_branch
        )
        if not entries:
            console.print("No backup branches found.")
            return

        sessions = sorted({e.session for e in entries}, reverse=True)
        console.print("\nAvailable backup sessions:")
        for i, s in enumerate(sessions, start=1):
            count = sum(1 for e in entries if e.session == s)
            console.print(f"  {i}. {s} • {count} backup(s)")

        try:
            idx = click.prompt(
                "Select a session to delete (default: 1 = latest)", type=int, default=1
            )
            if idx < 1 or idx > len(sessions):
                console.print("Invalid selection.")
                return
            chosen_session = sessions[idx - 1]

            # Preview session details similar to 'backups list'
            session_entries = [e for e in entries if e.session == chosen_session]
            preview = Tree(f"🗂️ Session: [bold]{chosen_session}[/bold]", guide_style="dim")
            by_orig: Dict[str, List] = {}
            for e in session_entries:
                by_orig.setdefault(e.original_branch, []).append(e)
            for orig in sorted(by_orig.keys()):
                group = by_orig[orig]
                backup_branch = group[0].backup_branch if group else ""
                items = []
                for entry in sorted(group, key=lambda e: (e.repo_name, str(e.repo_path))):
                    try:
                        rel = str(entry.repo_path.relative_to(orchestrator.root_path))
                    except Exception:
                        rel = str(entry.repo_path)
                    items.append(f"{entry.repo_name} ({rel})")
                node = preview.add(
                    f"[green]{orig}[/green] • [cyan]{backup_branch}[/cyan] • {len(group)} repo(s)"
                )
                node.add(", ".join(items))
            console.print(preview)

            if not click.confirm(
                f"Delete all backups for session {chosen_session}?", default=False
            ):
                console.print("Deletion cancelled.")
                return
            count = orchestrator.delete_backups_by_session(
                chosen_session, original_branch=original_branch
            )
            console.print(
                f"🧹 Deleted {count} backup branch(es) for session {chosen_session}"
            )
            return
        except (click.Abort, KeyboardInterrupt):
            console.print("Deletion cancelled.")
            return

        console.print(f"🧹 Deleted {count} backup branch(es)")
    except Exception as e:
        console.print(f"\n❌ **Error deleting backups:** {e}", style="bold red")
        # Debug stack trace to file logs for diagnostics
        logger.debug("Error in backups delete", exc_info=True)
        sys.exit(1)


@backups.command("restore")
@click.argument("original_branch", required=False)
@click.option(
    "--session-id",
    type=str,
    help="Session id (timestamp) of backup to restore. If provided without original_branch, restores all branches with that session.",
)
@click.option(
    "--latest", is_flag=True, help="Use most recent session if --session-id is not provided"
)
@click.pass_context
def backups_restore(
    ctx: click.Context, original_branch: Optional[str], session_id: Optional[str], latest: bool
) -> None:
    """Restore the original branch across the hierarchy from backups."""
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
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
        # Debug stack trace to file logs for diagnostics
        logger.debug("Error in backups restore", exc_info=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show status of all repositories in the hierarchy."""
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
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
        # Debug stack trace to file logs for diagnostics
        logger.debug("Error in status command", exc_info=True)
        sys.exit(1)


@cli.command()
@click.pass_context
def hierarchy(ctx: click.Context) -> None:
    """Display the repository hierarchy."""
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
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
        # Debug stack trace to file logs for diagnostics
        logger.debug("Error in hierarchy command", exc_info=True)
        sys.exit(1)


@cli.command()
@click.argument("source_branch")
@click.argument("target_branch")
@click.pass_context
def validate(ctx: click.Context, source_branch: str, target_branch: str) -> None:
    """Validate that branches exist and repositories are ready for rebase."""
    try:
        _maybe_print_log_notice(ctx.obj.get("verbose"), ctx.obj.get("console_level"), ctx.obj.get("log_path"))
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
        # Debug stack trace to file logs for diagnostics
        logger.debug("Error in validate command", exc_info=True)
        sys.exit(1)


@cli.command()
def version() -> None:
    """Print the current lockstep-rebase version."""
    console.print(f"lockstep-rebase {PACKAGE_VERSION}")


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


def _display_commit_mappings(resolution_summary: Dict[str, ResolutionSummary]) -> None:
    """Display commit hash mappings after successful rebase."""
    if not isinstance(resolution_summary, dict) or not resolution_summary:
        console.print("\n📦 **No auto-resolved commits found.**", style="bold yellow")
        return

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
    for repo_name in sorted(resolution_summary.keys()):
        repo_summary = resolution_summary.get(repo_name)
        commits = getattr(repo_summary, "resolved_commits", []) or []
        try:
            iterator = list(commits)
        except Exception:
            continue

        for i, commit in enumerate(iterator):
            # Only show repo name for first commit of each repo
            repo_display = repo_name if i == 0 else ""

            # Check if this commit has message consistency issues
            status = "✅ OK"
            try:
                issues = getattr(repo_summary, "message_consistency_issues", []) or []
            except Exception:
                issues = []
            for issue in issues:
                try:
                    if f"{repo_name}/{commit.submodule_path}" in issue:
                        status = "⚠️ Message Mismatch"
                        break
                except Exception:
                    # If commit object doesn't have expected attrs, skip mismatch check
                    pass

            try:
                old_hash = commit.original_hash[:8]
                new_hash = commit.resolved_hash[:8]
                message = commit.message
                submodule = str(commit.submodule_path.relative_to(Path.cwd()))
            except Exception:
                # If commit doesn't have expected attributes, skip rendering this row
                continue

            table.add_row(
                repo_display,
                submodule,
                old_hash,
                new_hash,
                message,
                status,
            )

    console.print(table)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n\n🚫 **Operation cancelled by user**", style="bold yellow")
        # Debug stack trace for cancellation context
        logger.debug("Top-level cancellation (KeyboardInterrupt)", exc_info=True)
        sys.exit(130)
    except Exception as e:
        console.print(f"\n💥 **Unexpected error:** {e}", style="bold red")
        # Debug stack trace to file logs for diagnostics
        logger.debug("Unexpected error in main()", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
