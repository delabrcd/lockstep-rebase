# Lockstep Rebase

A professional-grade Python tool for rebasing Git repositories with tightly coupled submodules in lockstep. This tool handles complex multi-level submodule hierarchies, automatically tracks commit hash changes, and provides intelligent conflict resolution.

## Features

- **🔍 Automatic Repository Discovery**: Detects Git repositories and maps submodule hierarchies
- **📋 Smart Rebase Planning**: Plans rebase operations across all repositories in dependency order
- **🔄 Commit Tracking**: Tracks commit hash changes during rebases for submodule resolution
- **⚡ Intelligent Conflict Resolution**: Auto-resolves submodule conflicts using commit mappings
- **🛡️ Safe Operations**: Validates repository state before operations and provides rollback
- **📊 Rich CLI Interface**: Beautiful command-line interface with progress tracking
- **🔧 Cross-Platform**: Works on Windows, macOS, and Linux

## Installation

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

Notes:
- Identifiers for `--include`, `--exclude`, and `--branch-map` keys can be repo name, relative path from root, or absolute path.
- `--branch-map` format is `repo=SRC[:TGT]`. If `:TGT` is omitted, the global target branch is used for that repo.

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

### Project Structure
```
src/lockstep_rebase/
├── __init__.py              # Package initialization
├── cli.py                   # Command-line interface
├── models.py                # Data models and exceptions
├── git_manager.py           # Git operations wrapper
├── submodule_mapper.py      # Repository hierarchy discovery
├── commit_tracker.py        # Commit hash tracking
├── conflict_resolver.py     # Conflict resolution logic
└── rebase_orchestrator.py   # Main orchestration logic
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

## License

MIT License - see LICENSE file for details.

## Support

For issues, feature requests, or questions:
- Create an issue on GitHub
- Check existing issues for solutions
- Use verbose mode for detailed error information
