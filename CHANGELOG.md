# Changelog

All notable changes to the Git Submodule Rebase Tool will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2024-01-15

### Added
- Initial release of Git Submodule Rebase Tool
- Automatic repository hierarchy discovery
- Smart rebase planning across multiple repository levels
- Commit hash tracking and mapping during rebases
- Intelligent conflict resolution for submodule conflicts
- Interactive conflict resolution for file conflicts
- Rich CLI interface with progress tracking
- Cross-platform support (Windows, macOS, Linux)
- Comprehensive test suite
- Professional documentation

### Features
- `git-submodule-rebase rebase` - Main rebase command
- `git-submodule-rebase status` - Repository status display
- `git-submodule-rebase hierarchy` - Repository structure visualization
- `git-submodule-rebase validate` - Pre-rebase validation
- `--dry-run` option for safe operation preview
- `--force` option to bypass validation warnings
- `--verbose` option for detailed logging

### Core Components
- **RebaseOrchestrator** - Main orchestration logic
- **GitManager** - Git operations wrapper
- **SubmoduleMapper** - Repository hierarchy discovery
- **CommitTracker** - Commit hash tracking and mapping
- **ConflictResolver** - Intelligent conflict resolution
- **CLI Interface** - Rich command-line interface

### Dependencies
- GitPython >= 3.1.40
- Click >= 8.1.0
- Rich >= 13.0.0
- Colorama >= 0.4.6

### Requirements
- Python >= 3.11
- Git >= 2.0 with submodule support
- Clean working directory for rebase operations
