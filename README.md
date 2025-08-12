# Lockstep Rebase

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub](https://img.shields.io/badge/GitHub-delabrcd%2Flockstep--rebase-blue.svg)](https://github.com/delabrcd/lockstep-rebase)

Automated nested Git submodule rebasing tool with intelligent conflict resolution and bash-style interactive UI.

> **⚠️ AI-Generated Code Notice**  
> This project was primarily developed using AI assistance (Claude by Anthropic). While thoroughly designed and tested, users should review the code and test in non-production environments before use in critical workflows.

## Overview

Lockstep Rebase is a powerful Python tool designed to handle the complex task of rebasing Git repositories with nested submodules. It features:

- **🎯 Proactive Conflict Resolution** - Pre-calculates submodule pointer mappings for deterministic conflict resolution
- **🔍 Bash-Style Autocomplete** - Real-time fuzzy search with inline completion for branch selection
- **🔄 Automatic Root Discovery** - Works from any directory within a Git repository
- **📦 Professional Architecture** - Modular, extensible design with comprehensive error handling
- **💾 State Management** - Persistent state with resume capability for interrupted operations

## Features

🚀 **Fully Automated Lockstep Rebasing**
- Recursively discovers and rebases nested submodules in dependency order
- Automatically resolves submodule pointer conflicts using commit mappings
- Handles complex multi-level submodule hierarchies

🤖 **Intelligent Conflict Resolution**
- Auto-resolves submodule pointer conflicts throughout entire rebase sequence
- Falls back to interactive resolution for genuine code conflicts
- Recursive auto-resolution on every `git rebase --continue`

🛡️ **Safety & Recovery**
- Creates timestamped backup branches before rebasing
- Persistent state management for resuming interrupted operations
- Graceful cleanup of active rebases on cancellation or errors

🗂️ **Backup Management**
- Interactive backup branch management (`--manage-backups`)
- Optional cleanup of backup branches after successful push
- Bulk operations for managing multiple repositories

⚙️ **Professional Features**
- No editor popups - completely hands-off operation
- Comprehensive logging and progress indicators
- Dry-run mode for previewing changes
- Cross-platform compatibility (Windows, macOS, Linux)

## Installation

### From Source

```bash
# Clone the repository
git clone https://github.com/delabrcd/lockstep-rebase.git
cd lockstep-rebase

# Install in development mode
pip install -e .
```

### Direct Installation from GitHub

```bash
# Install directly from GitHub
pip install git+https://github.com/delabrcd/lockstep-rebase.git
```

## Usage

### Basic Rebase Operation

```bash
# Interactive lockstep rebase
lockstep-rebase

# Dry run to preview changes
lockstep-rebase --dry-run

# Verbose output for debugging
lockstep-rebase --verbose

# Specify different root directory
lockstep-rebase --root /path/to/repo
```

### Backup Management

```bash
# Manage existing backup branches
lockstep-rebase --manage-backups
```

## How It Works

1. **Discovery**: Recursively discovers all nested submodules
2. **Configuration**: Interactive prompts for branch selection per repository
3. **Dependency Order**: Rebases submodules first, then parent repositories
4. **Conflict Resolution**: Automatically resolves submodule pointer conflicts using commit mappings
5. **Safety**: Creates backup branches and maintains persistent state
6. **Push**: Optional force-push with confirmation and backup cleanup

## Example Workflow

```bash
$ lockstep-rebase --verbose

🔍 Discovering repository structure...

🌳 Repository structure:
  📁 my-project
    📁 lib/common
      📁 lib/common/shared
    📁 tools/build-scripts

📁 Repository: shared
   Current branch: main
   Available branches: main, feature/updates
Do you want to rebase shared? (y/n): y
Enter branch to rebase (current: main): feature/updates
Enter base branch/commit for feature/updates: main

🚀 Starting nested rebase...

🔄 Rebasing shared (feature/updates onto main)
📦 Created backup branch: feature/updates-backup-20250812170354
✅ Rebase completed successfully!

🔄 Rebasing common (feature/integration onto main)
⚠️  Rebase conflicts detected
🤖 Attempting automatic submodule conflict resolution...
✅ Found mapping (short hash): 8bb089ae -> 239baba8
✅ Updated shared to rebased commit 239baba8
✅ All submodule conflicts resolved automatically!

📋 REBASE SUMMARY
✅ Successful rebases (3):
  📁 shared: 5 commits rebased
     Backup: feature/updates-backup-20250812170354
  📁 common: 12 commits rebased
     Backup: feature/integration-backup-20250812170354
  📁 my-project: 8 commits rebased
     Backup: main-backup-20250812170354

🚀 Ready to push 3 repositories:
  📁 shared
  📁 common  
  📁 my-project

Proceed with force push to all repositories? (yes/no): yes

✅ Nested rebase completed successfully!

🗂️  Found 3 backup branches created during this rebase:
Remove these backup branches? (y/N): n
📦 Backup branches preserved.
```

## Architecture

The tool is organized into modular components:

- **Core**: Main manager, data models, and Git utilities
- **Conflict Resolution**: Specialized handlers for different conflict types
- **Backup Management**: Backup branch creation and cleanup
- **Utils**: State persistence and repository discovery
- **CLI**: Command-line interface and argument parsing

## Requirements

- Python 3.8+
- Git 2.0+
- No external Python dependencies (uses only standard library)

## Safety Features

- **Backup Branches**: Automatic creation before any destructive operations
- **State Persistence**: Resume interrupted operations without losing progress
- **Dry Run Mode**: Preview all changes before execution
- **Force-with-lease**: Safer force pushes that respect remote changes
- **Graceful Cleanup**: Automatic abort of active rebases on cancellation
- Enable `--verbose` mode for detailed debugging output
