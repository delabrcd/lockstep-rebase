"""
User interface utilities for interactive prompts.

This module provides enhanced UI components including fuzzy search
and autocomplete functionality for better user experience.
"""

import sys
from typing import List, Optional

# Try to import advanced terminal control libraries
try:
    import msvcrt  # Windows
    WINDOWS = True
except ImportError:
    msvcrt = None  # type: ignore
    WINDOWS = False


class FuzzyMatcher:
    """Simple fuzzy string matching utility."""

    @staticmethod
    def score_match(query: str, candidate: str) -> float:
        """Score how well a query matches a candidate string.

        Args:
            query: Search query
            candidate: String to match against

        Returns:
            Match score (higher is better, 0 means no match)
        """
        if not query:
            return 1.0

        query = query.lower()
        candidate = candidate.lower()

        # Exact match gets highest score
        if query == candidate:
            return 100.0

        # Prefix match gets high score
        if candidate.startswith(query):
            return 90.0 - len(candidate) * 0.1

        # Contains match gets medium score
        if query in candidate:
            return 70.0 - candidate.index(query) * 0.1

        # Fuzzy match - check if all characters in query appear in order
        query_idx = 0
        for char in candidate:
            if query_idx < len(query) and char == query[query_idx]:
                query_idx += 1

        if query_idx == len(query):
            # All characters matched in order
            return 50.0 - (len(candidate) - len(query)) * 0.1

        return 0.0

    @staticmethod
    def filter_and_sort(
            query: str,
            candidates: List[str],
            max_results: int = 10) -> List[str]:
        """Filter and sort candidates by fuzzy match score.

        Args:
            query: Search query
            candidates: List of candidate strings
            max_results: Maximum number of results to return

        Returns:
            Sorted list of best matches
        """
        if not query:
            return candidates[:max_results]

        # Score all candidates
        scored = []
        for candidate in candidates:
            score = FuzzyMatcher.score_match(query, candidate)
            if score > 0:
                scored.append((score, candidate))

        # Sort by score (descending) and return candidates
        scored.sort(key=lambda x: x[0], reverse=True)
        return [candidate for _, candidate in scored[:max_results]]


class InlineAutocomplete:
    """Bash-style inline autocomplete with real-time closest match display."""

    def __init__(self, candidates: List[str]):
        """Initialize the autocomplete system.

        Args:
            candidates: List of strings to autocomplete from
        """
        self.candidates = candidates
        self.matcher = FuzzyMatcher()

    def get_input_with_autocomplete(
            self,
            prompt: str,
            default: str = "") -> Optional[str]:
        """Get user input with real-time autocomplete suggestions.

        Args:
            prompt: Prompt to display
            default: Default value if user just presses Enter

        Returns:
            Selected input or None if cancelled
        """
        if WINDOWS:
            return self._get_input_windows(prompt, default)
        else:
            return self._get_input_unix(prompt, default)

    def _get_input_windows(self, prompt: str, default: str) -> Optional[str]:
        """Windows implementation of inline autocomplete."""
        print(f"\n{prompt}")
        if default:
            print(f"Default: {default} (press Enter to use)")
        print("Type to search, Tab for best match, Enter to confirm, Ctrl+C to cancel:")

        current_input = ""
        # cursor_pos = 0  # Not used in current implementation

        while True:
            # Show current state
            matches = self.matcher.filter_and_sort(
                current_input, self.candidates, max_results=1)
            best_match = matches[0] if matches else ""

            # Clear line and show prompt with autocomplete
            print(f"\r🔍 {current_input}", end="")
            if best_match and current_input and best_match.lower(
            ).startswith(current_input.lower()):
                # Show the completion in gray (if terminal supports it)
                remaining = best_match[len(current_input):]
                print(f"\033[90m{remaining}\033[0m", end="")
            print(" " * 10, end="")  # Clear any remaining characters
            print(f"\r🔍 {current_input}", end="")
            if best_match and current_input and best_match.lower(
            ).startswith(current_input.lower()):
                remaining = best_match[len(current_input):]
                print(f"\033[90m{remaining}\033[0m", end="")

            # Get next character
            try:
                if WINDOWS and msvcrt and msvcrt.kbhit():
                    char = msvcrt.getch()

                    if char == b'\r':  # Enter
                        print()  # New line
                        if not current_input and default:
                            return default
                        elif best_match and current_input:
                            return best_match
                        elif current_input:
                            return current_input
                        else:
                            return None

                    elif char == b'\x03':  # Ctrl+C
                        print("\n\nCancelled by user")
                        return None

                    elif char == b'\x08':  # Backspace
                        if current_input:
                            current_input = current_input[:-1]

                    elif char == b'\t':  # Tab - accept best match
                        if best_match:
                            current_input = best_match

                    elif char == b'\x1b':  # Escape - cancel
                        print("\n\nCancelled")
                        return None

                    elif len(char) == 1 and char.isalnum() or char in b'-_./\\':  # Printable characters
                        current_input += char.decode('utf-8', errors='ignore')

            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                return None

    def _get_input_unix(self, prompt: str, default: str) -> Optional[str]:
        """Unix implementation of inline autocomplete."""
        # For Unix systems, fall back to simpler implementation
        # Full terminal control would require more complex implementation
        print(f"\n{prompt}")
        if default:
            print(f"Default: {default} (press Enter to use)")
        print("Type to search (real-time matching):")

        current_input = ""

        while True:
            try:
                # Show current matches
                matches = self.matcher.filter_and_sort(
                    current_input, self.candidates, max_results=3)

                if matches:
                    print(
                        f"\r🔍 '{current_input}' → Top matches: {', '.join(matches[:3])}",
                        end="")
                else:
                    print(f"\r🔍 '{current_input}' → No matches", end="")

                # Simple input (fallback for Unix)
                user_input = input(f"\n🔍 Search: ").strip()

                if not user_input:
                    if default:
                        return default
                    elif matches:
                        return matches[0]  # Return best match
                    else:
                        return None

                if user_input.lower() in ['cancel', 'quit', 'exit']:
                    return None

                # Check for exact match
                if user_input in self.candidates:
                    return user_input

                # Find best match
                matches = self.matcher.filter_and_sort(
                    user_input, self.candidates, max_results=1)
                if matches:
                    return matches[0]

                current_input = user_input

            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                return None
            except EOFError:
                print("\n\nCancelled by user")
                return None


class BranchSelector:
    """Interactive branch selector with fuzzy search."""

    def __init__(self, branches: List[str], current_branch: str):
        """Initialize the branch selector.

        Args:
            branches: List of available branches
            current_branch: Currently checked out branch
        """
        self.branches = branches
        self.current_branch = current_branch
        self.matcher = FuzzyMatcher()
        self.autocomplete = InlineAutocomplete(branches)

    def select_branch_inline(
            self,
            prompt: str = "Select branch") -> Optional[str]:
        """Interactive branch selection with bash-style inline autocomplete.

        Args:
            prompt: Prompt message to display

        Returns:
            Selected branch name or None if cancelled
        """
        print(f"\n{prompt}")
        print(f"Current branch: {self.current_branch}")
        print(
            f"Available branches ({len(self.branches)}): {', '.join(self.branches[:5])}")
        if len(self.branches) > 5:
            print(f"... and {len(self.branches) - 5} more")

        # Use inline autocomplete for bash-style experience
        selected = self.autocomplete.get_input_with_autocomplete(
            "🔍 Type branch name (Tab to complete, Enter to select):",
            default=self.current_branch
        )

        if selected:
            # Validate the selection
            if self.validate_branch(selected):
                return selected
            else:
                # Try fuzzy matching if exact match fails
                matches = self.suggest_branches(selected, max_suggestions=1)
                if matches:
                    print(
                        f"⚠️  Branch '{selected}' not found. Did you mean '{matches[0]}'?")
                    if InteractivePrompt.yes_no(
                            f"Use '{matches[0]}'?", default=True):
                        return matches[0]
                print(f"❌ Branch '{selected}' not found.")
                return None

        return None

    def select_branch(self, prompt: str = "Select branch") -> Optional[str]:
        """Interactive branch selection with fuzzy search.

        Args:
            prompt: Prompt message to display

        Returns:
            Selected branch name or None if cancelled
        """
        print(f"\n{prompt}")
        print(f"Current branch: {self.current_branch}")
        print(
            f"Available branches ({len(self.branches)}): {', '.join(self.branches[:5])}")
        if len(self.branches) > 5:
            print(f"... and {len(self.branches) - 5} more")
        print("\nType to search, press Enter to select, or 'none' to skip:")

        while True:
            try:
                # Get user input
                query = input("🔍 Branch search: ").strip()

                # Handle special cases
                if query.lower() in ['', 'none', 'skip', 'cancel']:
                    return None

                if query.lower() in ['quit', 'exit']:
                    print("Cancelled by user")
                    sys.exit(0)

                # Find matches
                matches = self.matcher.filter_and_sort(
                    query, self.branches, max_results=10)

                if not matches:
                    print(
                        f"❌ No branches match '{query}'. Try a different search term.")
                    continue

                # If exact match, use it
                if len(matches) == 1 or (
                        matches and matches[0].lower() == query.lower()):
                    selected = matches[0]
                    print(f"✅ Selected: {selected}")
                    return selected

                # Show matches and let user choose
                print(f"\n📋 Found {len(matches)} matches:")
                for i, branch in enumerate(matches, 1):
                    marker = "👉" if branch == self.current_branch else "  "
                    print(f"{marker} {i}. {branch}")

                # Get selection
                while True:
                    try:
                        choice = input(
                            f"\nSelect 1-{len(matches)}, or refine search: ").strip()

                        # Check if it's a number selection
                        if choice.isdigit():
                            idx = int(choice) - 1
                            if 0 <= idx < len(matches):
                                selected = matches[idx]
                                print(f"✅ Selected: {selected}")
                                return selected
                            else:
                                print(
                                    f"❌ Please enter a number between 1 and {len(matches)}")
                                continue

                        # Check for special commands
                        if choice.lower() in ['none', 'skip', 'cancel']:
                            return None

                        if choice.lower() in ['quit', 'exit']:
                            print("Cancelled by user")
                            sys.exit(0)

                        # If not a number, treat as new search query
                        if choice:
                            query = choice
                            break
                        else:
                            print(
                                "❌ Please enter a number, search term, or 'none' to skip")
                            continue

                    except KeyboardInterrupt:
                        print("\n\nCancelled by user")
                        sys.exit(0)
                    except EOFError:
                        print("\n\nCancelled by user")
                        sys.exit(0)

            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                sys.exit(0)
            except EOFError:
                print("\n\nCancelled by user")
                sys.exit(0)

    def validate_branch(self, branch_name: str) -> bool:
        """Validate that a branch name exists.

        Args:
            branch_name: Branch name to validate

        Returns:
            True if branch exists
        """
        return branch_name in self.branches

    def suggest_branches(
            self,
            query: str,
            max_suggestions: int = 5) -> List[str]:
        """Get branch suggestions for a query.

        Args:
            query: Search query
            max_suggestions: Maximum number of suggestions

        Returns:
            List of suggested branch names
        """
        return self.matcher.filter_and_sort(
            query, self.branches, max_suggestions)


class InteractivePrompt:
    """Enhanced interactive prompts with validation."""

    @staticmethod
    def yes_no(prompt: str, default: Optional[bool] = None) -> bool:
        """Interactive yes/no prompt with validation.

        Args:
            prompt: Question to ask
            default: Default value if user just presses Enter

        Returns:
            True for yes, False for no
        """
        if default is True:
            suffix = " [Y/n]"
        elif default is False:
            suffix = " [y/N]"
        else:
            suffix = " [y/n]"

        while True:
            try:
                response = input(f"{prompt}{suffix}: ").strip().lower()

                if not response and default is not None:
                    return default

                if response in ['y', 'yes', 'true', '1']:
                    return True
                elif response in ['n', 'no', 'false', '0']:
                    return False
                else:
                    print("❌ Please enter 'y' for yes or 'n' for no")

            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                sys.exit(0)
            except EOFError:
                print("\n\nCancelled by user")
                sys.exit(0)

    @staticmethod
    def choice(
            prompt: str,
            choices: List[str],
            default: Optional[str] = None) -> str:
        """Interactive choice prompt with validation.

        Args:
            prompt: Question to ask
            choices: List of valid choices
            default: Default choice if user just presses Enter

        Returns:
            Selected choice
        """
        choices_str = "/".join(choices)
        if default:
            choices_str = choices_str.replace(default, default.upper())

        while True:
            try:
                response = input(f"{prompt} [{choices_str}]: ").strip().lower()

                if not response and default:
                    return default

                # Check for exact match
                for choice in choices:
                    if response == choice.lower():
                        return choice

                # Check for partial match
                matches = [
                    c for c in choices if c.lower().startswith(response)]
                if len(matches) == 1:
                    return matches[0]
                elif len(matches) > 1:
                    print(
                        f"❌ Ambiguous choice. Did you mean: {', '.join(matches)}?")
                else:
                    print(
                        f"❌ Invalid choice. Please enter one of: {', '.join(choices)}")

            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                sys.exit(0)
            except EOFError:
                print("\n\nCancelled by user")
                sys.exit(0)
