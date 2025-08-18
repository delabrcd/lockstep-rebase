"""
CLI-specific implementation of the prompt interface.
"""

from __future__ import annotations

from typing import Dict, List
import click
from rich.console import Console
from rich.panel import Panel

from .prompt_interface import UserPrompt, BranchSyncAction


class CliPrompt(UserPrompt):
    """CLI implementation of the prompt interface using click and rich."""

    def __init__(self, console: Console = None):
        self.console = console or Console()

    def confirm_use_remote_branch(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        """Ask user if they want to use a remote branch when local doesn't exist."""
        self.console.print("\n⚠️  **Branch Missing Locally**", style="bold yellow")
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
        commits_ahead: int,
    ) -> BranchSyncAction:
        """Ask user what to do when local branch is out of sync with remote."""
        self.console.print("\n🔄 **Branch Out of Sync**", style="bold yellow")
        self.console.print(f"Repository: {repo_name}")
        self.console.print(f"Branch: {branch_name}")
        self.console.print(f"Local commit:  {local_commit}")
        self.console.print(f"Remote commit: {remote_commit}")
        self.console.print(
            f"Local is {commits_behind} commits behind and {commits_ahead} commits ahead"
        )

        choices = [
            ("sync", f"Sync local with remote (will lose {commits_ahead} local commits)"),
            ("continue", "Continue with current local branch"),
            ("abort", "Abort the operation"),
        ]

        self.console.print("\nOptions:")
        for i, (key, desc) in enumerate(choices, 1):
            self.console.print(f"  {i}. {desc}")

        while True:
            choice = click.prompt(
                "Choose an option",
                type=click.Choice(["1", "2", "3", "sync", "continue", "abort"]),
                show_choices=False,
            )

            if choice in ["1", "sync"]:
                return BranchSyncAction.SYNC_LOCAL
            elif choice in ["2", "continue"]:
                return BranchSyncAction.SKIP
            elif choice in ["3", "abort"]:
                return BranchSyncAction.ABORT

    def confirm_create_local_branch(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        """Ask user if they want to create a local branch from remote."""
        self.console.print(f"Create local tracking branch for {remote_name}/{branch_name}?")
        return click.confirm("This will create a local branch that tracks the remote", default=True)

    def show_validation_summary(
        self, missing_branches: Dict[str, List[str]], sync_issues: Dict[str, Dict[str, str]]
    ) -> None:
        """Show a summary of validation issues found."""
        if (
            not missing_branches["missing_source"]
            and not missing_branches["missing_target"]
            and not sync_issues
        ):
            return

        self.console.print("\n📋 **Branch Validation Summary**", style="bold blue")

        # Show missing branches
        if missing_branches["missing_source"]:
            self.console.print("\n❌ **Missing Source Branches:**", style="bold red")
            for repo in missing_branches["missing_source"]:
                self.console.print(f"  • {repo}")

        if missing_branches["missing_target"]:
            self.console.print("\n❌ **Missing Target Branches:**", style="bold red")
            for repo in missing_branches["missing_target"]:
                self.console.print(f"  • {repo}")

        # Show sync issues
        if sync_issues:
            self.console.print("\n⚠️  **Branch Sync Issues:**", style="bold yellow")
            for repo, issues in sync_issues.items():
                self.console.print(f"  • {repo}:")
                for branch, issue in issues.items():
                    self.console.print(f"    - {branch}: {issue}")

    # --- Auto-discovery prompts ---
    def confirm_include_updated_submodule(
        self,
        parent_repo: str,
        submodule_path: str,
        src_sha: str,
        tgt_sha: str,
        suggested_src: str,
        suggested_tgt: str,
    ) -> bool:
        """Prompt to include a submodule detected as updated in the commit range."""
        panel = Panel(
            f"[bold]Changes detected on both parent branches[/bold]\n"
            f"Parent: [cyan]{parent_repo}[/cyan]\n"
            f"Submodule: [yellow]{submodule_path}[/yellow]\n"
            f"Pointer difference (target → source): [red]{(tgt_sha or '')[:8]}[/red] → [green]{(src_sha or '')[:8]}[/green]\n\n"
            "This means the parent repository points to different commits of this submodule on the\n"
            "target and source branches.\n"
            "[bold yellow]If you do not rebase this submodule first, the parent rebase will likely hit\n"
            "merge conflicts[/bold yellow] requiring manual resolution when updating the submodule pointer.\n\n"
            f"Suggested submodule branches: [green]{suggested_src}[/green] → [blue]{suggested_tgt}[/blue]",
            title="Submodule Updated on Both Branches",
            border_style="magenta",
        )
        self.console.print(panel)
        return click.confirm("Include this submodule in the rebase plan?", default=True)

    def choose_submodule_branches(
        self, submodule_repo: str, default_src: str, default_tgt: str
    ) -> tuple[str, str]:
        """Allow user to override inferred submodule branches."""
        self.console.print(
            f"\n🧭 Configure branches for submodule [cyan]{submodule_repo}[/cyan] (press Enter to accept defaults)",
            style="bold blue",
        )
        src = click.prompt("Source branch", default=default_src, show_default=True)
        tgt = click.prompt("Target branch", default=default_tgt, show_default=True)
        return src.strip(), tgt.strip()

    def confirm_force_push(
        self, repo_name: str, branch_name: str, remote_name: str = "origin"
    ) -> bool:
        """Require the user to type 'FORCE PUSH' to confirm destructive push."""
        phrase = "FORCE PUSH"
        panel = Panel(
            f"[bold red]Destructive operation ahead[/bold red]\n\n"
            f"Repository: [cyan]{repo_name}[/cyan]\n"
            f"Branch: [green]{branch_name}[/green] → Remote: [yellow]{remote_name}[/yellow]\n\n"
            "This will overwrite the remote branch history.\n"
            f"To confirm, type [bold]{phrase}[/bold] exactly.",
            title="Confirm Force Push",
            border_style="red",
        )
        self.console.print(panel)

        try:
            entered = click.prompt(
                "Type the exact confirmation phrase", default="", show_default=False
            )
        except (click.Abort, KeyboardInterrupt):
            return False

        if entered.strip() == phrase:
            return True

        self.console.print("Confirmation phrase did not match. Skipping force push.", style="yellow")
        return False
