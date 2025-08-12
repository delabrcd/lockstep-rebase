# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- **Python Version Requirement**: Dropped Python 3.8 support, now requires Python 3.9+
  - Updated to use modern type hint syntax (e.g., `tuple[int, int, int]`)
  - Improved compatibility with latest packaging tools
  - Updated CI/CD pipeline to test Python 3.9-3.12

## [1.1.1] - 2025-01-12

### Added
- **Bash-Style Inline Autocomplete**: Real-time branch selection with cursor-based completion
  - Character-by-character input capture on Windows
  - Inline gray text completion preview
  - Tab to accept, Enter to confirm, Ctrl+C to cancel
  - Cross-platform support with Unix fallback
- **Enhanced User Experience**: Professional CLI interface with visual feedback
- **Comprehensive .gitignore**: Complete Python/GitHub deployment configuration
- **AI Attribution**: Clear documentation of AI-assisted development

### Improved
- **Branch Selection UX**: Lightning-fast branch selection with fuzzy matching
- **Input Validation**: Robust validation with helpful error messages
- **Documentation**: Enhanced README with GitHub deployment information
- **Package Structure**: Professional open-source project layout

### Technical
- Added `InlineAutocomplete` class with platform-specific implementations
- Enhanced `BranchSelector` with `select_branch_inline()` method
- Improved terminal control with ANSI escape sequences
- Cross-platform keyboard input handling

## [1.1.0] - 2025-01-12

### Added
- **Proactive Conflict Resolution**: Revolutionary pre-calculated submodule mapping system
  - `RebasePlanner` class for analyzing commits before rebase
  - `PlannedSubmoduleResolver` for deterministic conflict resolution
  - Commit-by-commit submodule target calculation
- **Fuzzy Search Branch Selection**: Interactive branch selection with intelligent matching
  - `FuzzyMatcher` with scoring algorithm
  - `BranchSelector` with real-time filtering
  - `InteractivePrompt` for enhanced user interactions
- **Automatic Git Root Discovery**: Works from any directory within repository
  - `find_git_root()` method using `git rev-parse --show-toplevel`
  - Intelligent path resolution and validation
- **Centralized Version Management**: Single source of truth for version information
  - `_version.py` module with programmatic access
  - Automatic version propagation to all package files

### Changed
- **Architecture**: Complete refactor from monolithic script to modular package
  - `core/` - Main rebase logic and Git utilities
  - `conflict_resolution/` - Conflict handling strategies
  - `utils/` - State management, discovery, and UI utilities
  - `backup/` - Backup branch management
- **Conflict Resolution**: Replaced reactive with proactive approach
  - Pre-analysis of rebase commits and submodule dependencies
  - Deterministic submodule pointer updates
  - Reduced manual intervention requirements

### Improved
- **User Experience**: Professional CLI with enhanced prompts and validation
- **Error Handling**: Comprehensive error recovery and user guidance
- **State Management**: Persistent rebase state with resume capability
- **Performance**: Faster conflict resolution through pre-calculation

### Technical
- Migrated from single script to installable Python package
- Added comprehensive type hints and documentation
- Implemented modern Python packaging standards
- Enhanced Git command abstraction layer

## [1.0.0] - 2025-01-11

### Added
- **Initial Release**: Core lockstep rebase functionality
- **Nested Submodule Support**: Recursive repository discovery and rebasing
- **Interactive Configuration**: User-driven branch and base selection
- **Backup Management**: Automatic backup branch creation and cleanup
- **State Persistence**: Resume interrupted rebase operations
- **Conflict Detection**: Automatic detection of submodule vs. regular conflicts

### Features
- Recursive submodule traversal and dependency-order rebasing
- Commit mapping storage and retrieval
- Interactive merge conflict handling
- Force-push with lease for safer remote updates
- Comprehensive logging and verbose output modes
- Dry-run mode for preview without changes

### Technical
- Python 3.8+ compatibility
- Git command-line interface integration
- JSON-based state file management
- Cross-platform path handling
- Subprocess-based Git command execution

---

## Development Notes

### AI-Generated Code
This project was primarily developed using AI assistance (Claude by Anthropic). The development process involved:

- **Architectural Design**: AI-assisted system design and component planning
- **Implementation**: AI-generated code with human oversight and testing
- **Refactoring**: Multiple iterations to improve code quality and user experience
- **Documentation**: AI-generated documentation with human review

### Version Strategy
- **Major versions** (x.0.0): Breaking changes or major architectural shifts
- **Minor versions** (x.y.0): New features, significant improvements
- **Patch versions** (x.y.z): Bug fixes, minor improvements, documentation updates

### Contribution Guidelines
When contributing to this project:
1. Update this CHANGELOG.md with your changes
2. Follow the existing format and categorization
3. Include both user-facing and technical details
4. Reference issue numbers where applicable
