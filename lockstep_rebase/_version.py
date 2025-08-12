"""
Version information for lockstep-rebase package.

This module contains the single source of truth for version information.
Update the VERSION constant to change the version across the entire package.
"""

# Version components for programmatic access
VERSION_MAJOR = 1
VERSION_MINOR = 1
VERSION_PATCH = 1

# Single source of truth for version information
VERSION = f"{VERSION_MAJOR}.{VERSION_MINOR}.{VERSION_PATCH}"

# Build version string
def get_version() -> str:
    """Get the current version string."""
    return VERSION

def get_version_info() -> tuple[int, int, int]:
    """Get version components as a tuple."""
    return (VERSION_MAJOR, VERSION_MINOR, VERSION_PATCH)

# For backwards compatibility and convenience
__version__ = VERSION
