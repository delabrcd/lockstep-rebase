"""
CLI-specific implementation of the conflict prompt interface.
"""

from __future__ import annotations

from typing import List
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .conflict_prompt_interface import ConflictPrompt
from .models import RepoInfo, ResolutionSummary


class CliConflictPrompt(ConflictPrompt):
    """CLI implementation of the conflict prompt interface using click and rich."""
    
    def __init__(self, console: Console = None):
        self.console = console or Console()
    
    def prompt_for_conflict_resolution(
        self, 
        repo_info: RepoInfo,
        file_conflicts: List[str],
        unresolved_submodule_conflicts: List[str]
    ) -> bool:
        """Prompt user to resolve conflicts and wait for confirmation."""
        self.console.print(f"\n🔥 **MERGE CONFLICTS DETECTED** in {repo_info.name}", style="bold red")
        self.console.print(f"Repository: {repo_info.relative_path}")
        
        if file_conflicts:
            self.console.print(f"\n📄 **File Conflicts** ({len(file_conflicts)}):", style="bold yellow")
            for conflict_file in file_conflicts:
                self.console.print(f"  - {conflict_file}")
        
        if unresolved_submodule_conflicts:
            self.console.print(f"\n📦 **Submodule Conflicts** ({len(unresolved_submodule_conflicts)}):", style="bold yellow")
            for submodule in unresolved_submodule_conflicts:
                self.console.print(f"  - {submodule}")
        
        # Create instructions panel
        instructions = [
            f"1. Navigate to: {repo_info.path}",
            "2. Resolve the conflicts in the files/submodules listed above",
            "3. Stage your changes: `git add <resolved-files>`",
            "4. Do NOT commit - just stage the resolved files",
            "5. Return here and type 'resolved' to continue"
        ]
        
        instructions_panel = Panel(
            "\n".join(instructions),
            title="Instructions",
            title_align="left",
            border_style="blue"
        )
        self.console.print(instructions_panel)
        
        while True:
            user_input = click.prompt(
                "\nType 'resolved' when conflicts are fixed, or 'abort' to cancel",
                type=click.Choice(['resolved', 'abort'], case_sensitive=False),
                show_choices=False
            ).lower()
            
            if user_input == 'resolved':
                # Import here to avoid circular imports
                from .conflict_resolver import ConflictResolver
                resolver = ConflictResolver(None)  # We only need the verification method
                
                if resolver._verify_conflicts_resolved(repo_info.path):
                    self.console.print("✅ Conflicts verified as resolved. Continuing rebase...", style="bold green")
                    return True
                else:
                    self.console.print("❌ Conflicts still exist. Please resolve all conflicts before continuing.", style="bold red")
                    continue
            elif user_input == 'abort':
                self.console.print("🚫 Rebase operation aborted by user.", style="bold red")
                return False
    
    def display_resolution_summary(self, summary: ResolutionSummary) -> None:
        """Display a formatted summary of automatic conflict resolutions."""
        if not summary.resolved_commits_by_repo:
            self.console.print("\n✅ **No automatic conflict resolutions were needed.**", style="bold green")
            return
        
        self.console.print("\n🔧 **Automatic Conflict Resolution Summary**", style="bold blue")
        
        # Create table for resolved commits
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Repository", style="cyan")
        table.add_column("Submodule", style="yellow")
        table.add_column("Original Hash", style="red")
        table.add_column("Resolved Hash", style="green")
        table.add_column("Message", style="dim")
        
        # Sort repositories by name for consistent display
        for repo_name in sorted(summary.resolved_commits_by_repo.keys()):
            commits = summary.resolved_commits_by_repo[repo_name]
            if not commits:
                continue
            
            for i, commit in enumerate(commits):
                # Only show repo name for first commit of each repo
                repo_display = repo_name if i == 0 else ""
                
                table.add_row(
                    repo_display,
                    commit.submodule_path,
                    commit.original_hash[:8],
                    commit.resolved_hash[:8],
                    commit.message
                )
        
        self.console.print(table)
        
        # Show message consistency issues
        if summary.message_consistency_issues:
            self.console.print("\n⚠️  **Message Consistency Issues:**", style="bold yellow")
            for issue in summary.message_consistency_issues:
                self.console.print(f"   • {issue}")
        else:
            total_resolutions = sum(len(commits) for commits in summary.resolved_commits_by_repo.values())
            self.console.print(f"\n✅ **All {total_resolutions} resolved commits have consistent messages.**", style="bold green")
