"""
Lockstep Rebase - Automated nested Git submodule rebasing tool.

A powerful tool for rebasing Git repositories with nested submodules in lockstep,
automatically resolving submodule pointer conflicts using commit mappings.
"""

from ._version import VERSION, get_version, get_version_info
from .core.manager import NestedRebaseManager
from .core.models import RepoInfo, RebaseResult, RebaseState

# Package metadata
__version__ = VERSION
__author__ = "Caleb DeLaBruere"
__email__ = "caleb.delabruere@inficon.com"

__all__ = [
    'NestedRebaseManager',
    'RepoInfo',
    'RebaseResult',
    'RebaseState',
    '__version__',
    'get_version',
    'get_version_info'
]
