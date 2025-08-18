# Lockstep Rebase

[![CI](https://github.com/delabrcd/lockstep-rebase/actions/workflows/ci.yml/badge.svg)](https://github.com/delabrcd/lockstep-rebase/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)
![OS](https://img.shields.io/badge/os-linux%20%7C%20macOS%20%7C%20windows-lightgrey)
[![License: MIT](https://img.shields.io/github/license/delabrcd/lockstep-rebase)](LICENSE)

A Python CLI tool for rebasing Git repositories with tightly coupled submodules in lockstep. It handles multi-level submodule hierarchies, tracks commit hash changes, and provides conflict resolution helpers.

## Features

- **🔍 Automatic Repository Discovery**: Detects Git repositories and maps submodule hierarchies
- **📋 Smart Rebase Planning**: Plans rebase operations across all repositories in dependency order
- **🔄 Commit Tracking**: Tracks commit hash changes during rebases for submodule resolution
- **⚡ Conflict Resolution Aids**: Auto-resolves submodule conflicts using commit mappings; prompts for file conflicts
- **🧹 Session-Based Backups (Hierarchy-Wide)**: Create, list, delete, and restore backup branches across all repos in a session. Interactive session picker and optional filtering by original branch.
- **📊 CLI UX**: Helpful output with structured hierarchy views and progress messages
- **🔧 Cross-Platform**: Works on Windows, macOS, and Linux

## Installation

### Directly from GitHub (source install)
```bash
pip install --upgrade pip
pip install git+https://github.com/delabrcd/lockstep-rebase.git
```

Tip (Linux/macOS): pip may place console scripts in `~/.local/bin`.
Add to PATH if needed:
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### From Source
```bash
git clone https://github.com/delabrcd/lockstep-rebase.git
cd lockstep-rebase
pip install -e .
```

### For Development
```bash
git clone https://github.com/delabrcd/lockstep-rebase.git
cd lockstep-rebase
pip install -e ".[dev]"
```

## Quick Start

1. **Navigate to your repository** (can be at any level - root or submodule)
2. **Check repository status**:
   ```bash
   lockstep-rebase status
   ```

3. **Validate branches exist**:
   ```bash
   lockstep-rebase validate feature/my-branch main
   ```

4. **Perform the rebase**:
   ```bash
   lockstep-rebase rebase feature/my-branch main
   ```

## Usage Examples

### Basic Rebase Operation
```bash
# Rebase feature branch onto main across all submodules
lockstep-rebase rebase feature/awesome-feature main
```

### Dry Run (See What Would Happen)
```bash
# Preview the rebase operation without making changes
lockstep-rebase rebase feature/awesome-feature main --dry-run
```

### Force Rebase (Skip Validation Warnings)
```bash
# Proceed even if there are validation warnings
lockstep-rebase rebase feature/awesome-feature main --force
```

### Check Repository Hierarchy
```bash
# Display the discovered repository structure
lockstep-rebase hierarchy
```

### Verbose Output
```bash
# Enable detailed logging
lockstep-rebase --verbose rebase feature/awesome-feature main
```

### Selective Rebasing (Include/Exclude)
```bash
# Rebase only specific repos by name or relative path (repeat --include)
lockstep-rebase rebase feature/awesome-feature main \
  --include shared-lib \
  --include libs/core

# Exclude specific repos (repeat --exclude)
lockstep-rebase rebase feature/awesome-feature main \
  --exclude experimental-lib
```

### Per-Repo Branch Overrides
```bash
# Override source branch for a repo; target inherits global target
lockstep-rebase rebase feature/top main \
  --branch-map libs/core=feature/core-top

# Override both source and target for a repo
lockstep-rebase rebase feature/top main \
  --branch-map shared-lib=feature/shared-new:release/1.2

# Multiple mappings
lockstep-rebase rebase feature/top main \
  --branch-map shared-lib=feature/shared-new:main \
  --branch-map tools/formatter=feature/fmt:dev
```

### Auto-Discovery of Updated Submodules
```bash
# Detect submodules whose pointers changed between target..source
lockstep-rebase rebase feature/top main --auto-select-submodules
```

- Automatically detects submodules updated in the parent repo between branches.
- Infers per-submodule source/target branches from submodule commit pointers.
- Prompts you to include each updated submodule and allows branch overrides.

#### Combine with filters and branch-map
```bash
# Include/exclude still apply
lockstep-rebase rebase feature/top main \
  --auto-select-submodules \
  --include libs/core \
  --exclude experimental-lib
  
# Branch overrides are respected
lockstep-rebase rebase feature/top main \
  --auto-select-submodules \
  --branch-map libs/core=feature/core-top:release/1.2
```

Tip: Use --dry-run to preview the discovered plan.

Notes:
- Identifiers for `--include`, `--exclude`, and `--branch-map` keys can be repo name, relative path from root, or absolute path.
- `--branch-map` format is `repo=SRC[:TGT]`. If `:TGT` is omitted, the global target branch is used for that repo.

## Logging

- Console logging is disabled by default. Enable with `-v/--verbose` or `--log-level {debug,info,warning,error}`.
- Logs are always written to a rotating file (default: `~/.lockstep-rebase/lockstep-rebase.log`). Override with `LOCKSTEP_REBASE_LOG`.
- On startup, the CLI prints a short notice indicating where logs are written and how to enable console logs.

## Backups: list, delete, restore

Backup branches are created per rebase session with names like `lockstep/backup/{original_branch}/{session_id}`.

- **List backups across the hierarchy**
  ```bash
  lockstep-rebase backups list [--original-branch BR] [--session-id S] [--latest] [--repo-path PATH]
  ```

- **Delete backups across the hierarchy**
  - Interactive picker (default):
    ```bash
    lockstep-rebase backups delete
    ```
  - Latest session:
    ```bash
    lockstep-rebase backups delete --latest
    ```
  - Specific session:
    ```bash
    lockstep-rebase backups delete --session-id S
    ```
  - Filter by original branch: add `--original-branch BR`
  - Per-repo deletion: add `--repo-path PATH` and use `--all` or `--branch <name>` to target branches in that repo

- **Restore backups**
  - Restore all backups from a session:
    ```bash
    lockstep-rebase backups restore --session-id S
    lockstep-rebase backups restore --latest
    ```
  - Restore a single original branch:
    ```bash
    lockstep-rebase backups restore <original-branch> [--session-id S | --latest]
    ```

## How It Works

### 1. Repository Discovery
The tool automatically discovers your repository hierarchy:
- Finds the root Git repository
- Maps all submodules recursively
- Determines rebase order (deepest submodules first)

### 2. Branch Validation
Before starting, it validates:
- Source and target branches exist in all repositories
- Repositories are in a clean state
- No ongoing rebase operations

### 3. Rebase Execution
Executes rebases in dependency order:
- Starts with deepest submodules
- Tracks commit hash changes
- Works up to the root repository

### 4. Conflict Resolution
When conflicts occur:
- **Submodule conflicts**: Auto-resolves using tracked commit mappings
- **File conflicts**: Prompts user for manual resolution
- **Mixed conflicts**: Handles both automatically and manually

## Common Use Cases

### Scenario 1: Feature Branch Rebase
You're working on `feature/user-auth` but `main` has advanced:
```bash
lockstep-rebase rebase feature/user-auth main
```

### Scenario 2: Multi-Developer Coordination
Your coworker merged their feature first, now you need to rebase:
```bash
# First, fetch latest changes
git fetch --recurse-submodules

# Then rebase your feature branch
lockstep-rebase rebase feature/my-feature main
```

### Scenario 3: Complex Submodule Dependencies
Working with nested submodules where changes span multiple levels:
```bash
# The tool handles the complexity automatically
lockstep-rebase rebase feature/cross-module-changes main
```

## Conflict Resolution

### Automatic Submodule Resolution
When submodule conflicts occur, the tool:
1. Identifies the conflicting submodule commit
2. Looks up the new commit hash from its tracking data
3. Automatically updates the submodule reference
4. Continues the rebase

### Manual File Resolution
For file conflicts, the tool:
1. Lists all conflicted files
2. Pauses execution
3. Waits for you to resolve conflicts
4. Validates resolution before continuing

Example conflict resolution workflow:
```bash
# Tool detects conflicts and pauses
🔥 MERGE CONFLICTS DETECTED in my-submodule
📄 File Conflicts (2):
  - src/config.py
  - tests/test_config.py

# You resolve conflicts manually:
# 1. Edit the files to resolve conflicts
# 2. Stage the resolved files: git add src/config.py tests/test_config.py

# Then continue:
Type 'resolved' when conflicts are fixed: resolved
✅ Conflicts verified as resolved. Continuing rebase...
```

## Configuration

### Environment Variables
- `GIT_SUBMODULE_REBASE_LOG_LEVEL`: Set logging level (DEBUG, INFO, WARNING, ERROR)
- `GIT_SUBMODULE_REBASE_NO_COLOR`: Disable colored output

### Repository Requirements
- Git 2.0+ with submodule support
- All submodules must be initialized and up-to-date
- Clean working directory (no uncommitted changes)

## Development

### Setup Development Environment
```bash
# Clone and setup
git clone <repository-url>
cd lockstep-rebase
python -m venv venv
source venv/bin/activate  # Windows: .\venv\Scripts\activate
pip install -e ".[dev]"
```

### Running Tests
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=lockstep_rebase

# Run specific test file
pytest tests/test_models.py -v
```

### Code Quality
```bash
# Format code
black .

# Lint code
flake8

# Type checking (if using mypy)
mypy src/lockstep_rebase
```

## Troubleshooting

### Common Issues

**"No Git repository found"**
- Ensure you're running the command from within a Git repository
- Check that `.git` directory exists

**"Branch missing in repositories"**
- Verify the branch exists in all submodules
- Use `lockstep-rebase validate` to check

**"Repository has unstaged changes"**
- Commit or stash your changes before rebasing
- Use `git status` to check repository state

**"Rebase already in progress"**
- Complete or abort the existing rebase first
- Use `git rebase --abort` if needed

### Getting Help
```bash
# General help
lockstep-rebase --help

# Command-specific help
lockstep-rebase rebase --help

# Enable verbose logging for debugging
lockstep-rebase --verbose <command>
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Ensure all tests pass
6. Submit a pull request

## Safety and Disclaimer

This project is largely AI-generated and not thoroughly tested. Rebasing and submodule operations can be destructive. Use at your own risk.

Recommendations:
- Work on disposable clones or branches.
- Commit or stash your changes before running.
- Use `--dry-run` to preview plans.
- Verify results and keep your own backups.

## License

MIT License - see LICENSE file for details.
