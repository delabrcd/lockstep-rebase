"""
Command-line interface for the Git submodule rebase tool.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.panel import Panel

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
        handlers=[RichHandler(console=console, rich_tracebacks=True)]
    )


@click.group()
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose logging')
@click.option('--repo-path', type=click.Path(exists=True, path_type=Path), 
              help='Path to repository (defaults to current directory)')
@click.pass_context
def cli(ctx: click.Context, verbose: bool, repo_path: Optional[Path]) -> None:
    """Git Submodule Rebase Tool - Professional rebase operations for tightly coupled submodules."""
    setup_logging(verbose)
    
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['repo_path'] = repo_path


@cli.command()
@click.argument('source_branch')
@click.argument('target_branch')
@click.option('--dry-run', is_flag=True, help='Show what would be done without executing')
@click.option('--force', is_flag=True, help='Force rebase even with validation warnings')
@click.pass_context
def rebase(
    ctx: click.Context, 
    source_branch: str, 
    target_branch: str, 
    dry_run: bool,
    force: bool
) -> None:
    """
    Rebase SOURCE_BRANCH onto TARGET_BRANCH across all submodules.
    
    Example: lockstep-rebase rebase feature/my-feature main
    """
    try:
        conflict_prompt = CliConflictPrompt(console)
        orchestrator = RebaseOrchestrator(ctx.obj.get('repo_path'), conflict_prompt)
        prompt = CliPrompt(console)
        
        # Show repository hierarchy
        console.print("\n🔍 **Discovered Repository Structure**")
        orchestrator.print_repository_hierarchy()
        
        # Validate repository state
        validation_errors = orchestrator.validate_repository_state(prompt)
        if validation_errors and not force:
            console.print("\n❌ **Validation Errors:**", style="bold red")
            for error in validation_errors:
                console.print(f"  • {error}")
            console.print("\nUse --force to proceed anyway, or fix the issues above.")
            sys.exit(1)
        elif validation_errors:
            console.print("\n⚠️  **Validation Warnings (proceeding with --force):**", style="bold yellow")
            for error in validation_errors:
                console.print(f"  • {error}")
        
        # Plan the rebase
        console.print(f"\n📋 **Planning Rebase Operation**")
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
        else:
            console.print("\n❌ **Rebase failed!**", style="bold red")
            sys.exit(1)
            
    except RebaseError as e:
        console.print(f"\n❌ **Rebase Error:** {e}", style="bold red")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n💥 **Unexpected Error:** {e}", style="bold red")
        if ctx.obj.get('verbose'):
            console.print_exception()
        sys.exit(1)


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show status of all repositories in the hierarchy."""
    try:
        orchestrator = RebaseOrchestrator(ctx.obj.get('repo_path'))
        
        console.print("\n📊 **Repository Status**")
        status_info = orchestrator.get_repository_status()
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Repository", style="cyan")
        table.add_column("Path", style="dim")
        table.add_column("Current Branch", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Type", style="blue")
        
        for repo_name, info in status_info.items():
            if 'error' in info:
                table.add_row(
                    repo_name,
                    info.get('path', 'Unknown'),
                    "Error",
                    f"❌ {info['error']}",
                    "Unknown"
                )
            else:
                status_text = "🔄 Rebasing" if info['is_rebasing'] == 'True' else "✅ Clean"
                repo_type = f"📦 Submodule (L{info['depth']})" if info['is_submodule'] == 'True' else "📁 Root"
                
                table.add_row(
                    repo_name,
                    info['path'],
                    info['current_branch'],
                    status_text,
                    repo_type
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
        orchestrator = RebaseOrchestrator(ctx.obj.get('repo_path'))
        orchestrator.print_repository_hierarchy()
        
    except Exception as e:
        console.print(f"\n❌ **Error displaying hierarchy:** {e}", style="bold red")
        sys.exit(1)


@cli.command()
@click.argument('source_branch')
@click.argument('target_branch')
@click.pass_context
def validate(ctx: click.Context, source_branch: str, target_branch: str) -> None:
    """Validate that branches exist and repositories are ready for rebase."""
    try:
        orchestrator = RebaseOrchestrator(ctx.obj.get('repo_path'))
        
        console.print(f"\n🔍 **Validating Rebase Prerequisites**")
        console.print(f"Source Branch: {source_branch}")
        console.print(f"Target Branch: {target_branch}")
        
        # Validate repository state
        validation_errors = orchestrator.validate_repository_state()
        
        # Try to plan the rebase to validate branches
        try:
            operation = orchestrator.plan_rebase(source_branch, target_branch)
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
            repo_type
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
                    status
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


if __name__ == '__main__':
    main()
