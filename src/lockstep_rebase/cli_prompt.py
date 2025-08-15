"""
CLI-specific implementation of the prompt interface.
"""

from __future__ import annotations

from typing import Dict, List
import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from .prompt_interface import UserPrompt, BranchSyncAction


class CliPrompt(UserPrompt):
    """CLI implementation of the prompt interface using click and rich."""
    
    def __init__(self, console: Console = None):
        self.console = console or Console()
    
    def confirm_use_remote_branch(
        self, 
        repo_name: str, 
        branch_name: str, 
        remote_name: str = "origin"
    ) -> bool:
        """Ask user if they want to use a remote branch when local doesn't exist."""
        self.console.print(f"\n⚠️  **Branch Missing Locally**", style="bold yellow")
        self.console.print(f"Repository: {repo_name}")
        self.console.print(f"Branch: {branch_name}")
        self.console.print(f"Local branch not found, but {remote_name}/{branch_name} exists.")
        
        return click.confirm(f"Use remote branch {remote_name}/{branch_name}?", default=True)
    
    def confirm_sync_branch(
        self, 
        repo_name: str, 
        branch_name: str, 
        local_commit: str,
        remote_commit: str,
        commits_behind: int,
        commits_ahead: int
    ) -> BranchSyncAction:
        """Ask user what to do when local branch is out of sync with remote."""
        self.console.print(f"\n🔄 **Branch Out of Sync**", style="bold yellow")
        self.console.print(f"Repository: {repo_name}")
        self.console.print(f"Branch: {branch_name}")
        self.console.print(f"Local commit:  {local_commit}")
        self.console.print(f"Remote commit: {remote_commit}")
        self.console.print(f"Local is {commits_behind} commits behind and {commits_ahead} commits ahead")
        
        choices = [
            ("sync", f"Sync local with remote (will lose {commits_ahead} local commits)"),
            ("continue", "Continue with current local branch"),
            ("abort", "Abort the operation")
        ]
        
        self.console.print("\nOptions:")
        for i, (key, desc) in enumerate(choices, 1):
            self.console.print(f"  {i}. {desc}")
        
        while True:
            choice = click.prompt(
                "Choose an option", 
                type=click.Choice(['1', '2', '3', 'sync', 'continue', 'abort']),
                show_choices=False
            )
            
            if choice in ['1', 'sync']:
                return BranchSyncAction.SYNC_LOCAL
            elif choice in ['2', 'continue']:
                return BranchSyncAction.SKIP
            elif choice in ['3', 'abort']:
                return BranchSyncAction.ABORT
    
    def confirm_create_local_branch(
        self, 
        repo_name: str, 
        branch_name: str, 
        remote_name: str = "origin"
    ) -> bool:
        """Ask user if they want to create a local branch from remote."""
        self.console.print(f"Create local tracking branch for {remote_name}/{branch_name}?")
        return click.confirm("This will create a local branch that tracks the remote", default=True)
    
    def show_validation_summary(
        self, 
        missing_branches: Dict[str, List[str]], 
        sync_issues: Dict[str, Dict[str, str]]
    ) -> None:
        """Show a summary of validation issues found."""
        if not missing_branches['missing_source'] and not missing_branches['missing_target'] and not sync_issues:
            return
        
        self.console.print("\n📋 **Branch Validation Summary**", style="bold blue")
        
        # Show missing branches
        if missing_branches['missing_source']:
            self.console.print(f"\n❌ **Missing Source Branches:**", style="bold red")
            for repo in missing_branches['missing_source']:
                self.console.print(f"  • {repo}")
        
        if missing_branches['missing_target']:
            self.console.print(f"\n❌ **Missing Target Branches:**", style="bold red")
            for repo in missing_branches['missing_target']:
                self.console.print(f"  • {repo}")
        
        # Show sync issues
        if sync_issues:
            self.console.print(f"\n⚠️  **Branch Sync Issues:**", style="bold yellow")
            for repo, issues in sync_issues.items():
                self.console.print(f"  • {repo}:")
                for branch, issue in issues.items():
                    self.console.print(f"    - {branch}: {issue}")
