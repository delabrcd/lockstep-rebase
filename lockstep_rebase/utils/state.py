"""
State management for lockstep rebase operations.

This module handles persistence and loading of rebase state to allow
resuming interrupted operations.
"""

import json
import os
import time
from typing import List, Optional, Dict, Any

from ..core.models import RebaseState


class StateManager:
    """Manages persistent state for rebase operations."""

    def __init__(self, verbose: bool = False):
        """Initialize state manager.

        Args:
            verbose: Enable verbose logging
        """
        self.verbose = verbose

    def get_state_file_path(self, root_path: str) -> str:
        """Get the path to the state file for a repository.

        Args:
            root_path: Root repository path

        Returns:
            Path to the state file
        """
        git_dir = os.path.join(root_path, '.git')
        return os.path.join(git_dir, 'nested_rebase_state.json')

    def save_state(self, state: RebaseState, root_path: str) -> None:
        """Save rebase state to file.

        Args:
            state: Rebase state to save
            root_path: Root repository path
        """
        state_file = self.get_state_file_path(root_path)

        # Convert to dictionary for JSON serialization
        state_dict = {
            'session_id': state.session_id,
            'timestamp': state.timestamp,
            'root_path': state.root_path,
            'completed_rebases': state.completed_rebases,
            'active_rebases': state.active_rebases
        }

        try:
            with open(state_file, 'w') as f:
                json.dump(state_dict, f, indent=2)

            if self.verbose:
                print(f"💾 Saved rebase state to {state_file}")
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Failed to save state: {e}")

    def load_state(self, root_path: str) -> Optional[RebaseState]:
        """Load rebase state from file.

        Args:
            root_path: Root repository path

        Returns:
            Loaded rebase state or None if not found
        """
        state_file = self.get_state_file_path(root_path)

        if not os.path.exists(state_file):
            return None

        try:
            with open(state_file, 'r') as f:
                state_dict = json.load(f)

            state = RebaseState(
                session_id=state_dict['session_id'],
                timestamp=state_dict['timestamp'],
                root_path=state_dict['root_path'],
                completed_rebases=state_dict.get('completed_rebases', {}),
                active_rebases=state_dict.get('active_rebases', [])
            )

            if self.verbose:
                print(f"📂 Loaded rebase state from {state_file}")

            return state
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Failed to load state: {e}")
            return None

    def cleanup_state_file(self, root_path: str) -> None:
        """Remove the state file after successful completion.

        Args:
            root_path: Root repository path
        """
        state_file = self.get_state_file_path(root_path)

        try:
            if os.path.exists(state_file):
                os.remove(state_file)
                if self.verbose:
                    print(f"🗑️  Cleaned up state file: {state_file}")
        except Exception as e:
            if self.verbose:
                print(f"⚠️  Failed to cleanup state file: {e}")

    def timestamp(self) -> str:
        """Generate a timestamp string.

        Returns:
            Formatted timestamp string
        """
        return time.strftime('%Y%m%d%H%M%S')
