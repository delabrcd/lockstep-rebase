# Changelog

All notable changes to the Git Submodule Rebase Tool will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2025-08-18

### Added
- Force-push offer after successful rebase via `--offer-force-push`. Requires typing a confirmation phrase and shows ahead/behind info before pushing.
- Backup management commands:
  - `lockstep-rebase backups list` — list backups across the hierarchy with session/original-branch filters.
  - `lockstep-rebase backups delete` — delete by branch, all in repo, or by session (hierarchy-wide).
  - `lockstep-rebase backups restore` — restore original branches across the hierarchy from a chosen session.
- Structured repository hierarchy output and Rich table rendering in `hierarchy` command.
- Selective submodule rebasing: `--include`, `--exclude`, and per-repo `--branch-map repo=SRC[:TGT]`.

### Changed
- Rebase planning improvements:
  - Handle remote-only branches by offering to create local branches from `origin` when missing.
  - Auto-discovery considers a submodule “updated” if its pointer changed, regardless of parent changes.
  - Treat branch suggestion as exact only if branch/remote tip equals the submodule commit (short-hash equality).
  - Auto-discovery fallback prefers existing local/default branches to avoid failures.
- Architecture: `RepoInfo` now holds an optional `GitManager`; orchestrator prefers per-repo managers.
- Logging behavior: console logging disabled by default; logs always go to a rotating file at `~/.lockstep-rebase/lockstep-rebase.log` (override with `LOCKSTEP_REBASE_LOG`). Added `--log-level` and `-v`, plus a startup notice indicating log file and how to enable console logs.

### Fixed
- CLI exception handlers now log `logger.debug(..., exc_info=True)` to capture full stack traces even when console logs are disabled.
- Improved Windows console robustness by sanitizing unencodable characters to avoid `UnicodeEncodeError` when printing emojis/special characters.

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
