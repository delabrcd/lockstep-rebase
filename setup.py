"""
Setup script for lockstep-rebase package.
"""

from setuptools import setup, find_packages
import os
import sys

# Add the package directory to the path to import version
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lockstep_rebase'))
from _version import VERSION

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="lockstep-rebase",
    version=VERSION,
    author="Caleb DeLaBruere",
    author_email="caleb.delabruere@inficon.com",
    description="Automated nested Git submodule rebasing tool with intelligent conflict resolution",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/delabrcd/lockstep-rebase",
    project_urls={
        "Bug Tracker": "https://github.com/delabrcd/lockstep-rebase/issues",
        "Documentation": "https://github.com/delabrcd/lockstep-rebase#readme",
        "Source Code": "https://github.com/delabrcd/lockstep-rebase",
        "Changelog": "https://github.com/delabrcd/lockstep-rebase/blob/main/CHANGELOG.md",
    },
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control :: Git",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=[
        # No external dependencies - uses only standard library
    ],
    entry_points={
        "console_scripts": [
            "lockstep-rebase=lockstep_rebase.cli:main",
        ],
    },
    keywords="git rebase submodule automation lockstep",
    project_urls={
        "Bug Reports": "https://github.com/delabrcd/lockstep-rebase/issues",
        "Source": "https://github.com/delabrcd/lockstep-rebase",
    },
)
