"""
Tests for RebaseOrchestrator selective planning (include/exclude and branch_map).
"""

from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from lockstep_rebase.models import RepoInfo, RebaseError
from lockstep_rebase.rebase_orchestrator import RebaseOrchestrator


@pytest.fixture()
def fake_hierarchy(tmp_path: Path):
    root_path = tmp_path / "root"
    liba_path = tmp_path / "root" / "libA"
    libb_path = tmp_path / "root" / "libB"
    root_path.mkdir(parents=True)
    liba_path.mkdir(parents=True)
    libb_path.mkdir(parents=True)

    root = RepoInfo(path=root_path, name="root", is_submodule=False, depth=0)
    libA = RepoInfo(path=liba_path, name="libA", is_submodule=True, parent_repo=root, depth=1)
    libB = RepoInfo(path=libb_path, name="libB", is_submodule=True, parent_repo=root, depth=1)
    root.submodules = [libA, libB]
    return root, [libA, libB, root]


class FakeSubmoduleMapper:
    def __init__(self, root_path: Optional[Path] = None) -> None:
        self._root_path = root_path
        self._root = None
        self._order = None

    def with_hierarchy(self, root, order):
        self._root = root
        self._order = order
        return self

    def discover_repository_hierarchy(self):
        return self._root

    def get_rebase_order(self, _root):
        return list(self._order)

    # For CLI hierarchy fallbacks (not used in these tests)
    def get_hierarchy_lines(self, _root):
        return []

    def get_hierarchy_entries(self, _root):
        return []


@pytest.fixture()
def patched_env(fake_hierarchy):
    root, order = fake_hierarchy

    # Patch SubmoduleMapper within rebase_orchestrator module
    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)

    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper):
        yield root, order


def make_git_manager_side_effect(root, order, existing_branches_by_repo):
    """Return a side_effect for GitManager(...) that yields a mock per repo path.

    existing_branches_by_repo: dict[Path, set[str]]
    """
    mocks_by_path = {}

    def factory(repo_path: Path):
        repo_path = Path(repo_path)
        if repo_path not in mocks_by_path:
            m = MagicMock()
            # branch_exists: True if branch in configured set for that repo
            def branch_exists(name, _path=None):
                return name in existing_branches_by_repo.get(repo_path, set())

            m.branch_exists.side_effect = branch_exists
            m.get_commits_between.return_value = []
            mocks_by_path[repo_path] = m
        return mocks_by_path[repo_path]

    return factory


def test_plan_rebase_include_exclude_filters(patched_env):
    root, order = patched_env

    # Allow all branches for simplicity
    existing = {ri.path: {"feat/x", "main", "dev"} for ri in order}

    with patch(
        "lockstep_rebase.rebase_orchestrator.GitManager",
        side_effect=make_git_manager_side_effect(root, order, existing),
    ) as GM:
        # Attach patched GitManager mocks to each RepoInfo to avoid lazy init
        for ri in order:
            ri.git_manager = GM(ri.path)

        orch = RebaseOrchestrator(root_path=root.path)

        # Include only libA
        op_inc = orch.plan_rebase("feat/x", "main", include={"libA"})
        assert [s.repo.name for s in op_inc.repo_states] == ["libA"], "include should limit to libA only"

        # Exclude libB
        op_exc = orch.plan_rebase("feat/x", "main", exclude={"libB"})
        assert {s.repo.name for s in op_exc.repo_states} == {"libA", "root"}, "exclude should remove libB"


def test_plan_rebase_branch_map_overrides(patched_env):
    root, order = patched_env
    libA, libB, root_repo = order  # order is [libA, libB, root]

    # Setup branches: Only custom branches exist per mapping
    existing = {
        libA.path: {"feat/altA", "trunk"},
        libB.path: {"feat/x", "main"},
        root_repo.path: {"feat/x", "main"},
    }

    with patch(
        "lockstep_rebase.rebase_orchestrator.GitManager",
        side_effect=make_git_manager_side_effect(root, order, existing),
    ) as GM:
        # Attach patched GitManager mocks to each RepoInfo to avoid lazy init
        for ri in order:
            ri.git_manager = GM(ri.path)

        orch = RebaseOrchestrator(root_path=root.path)

        # Override libA to use source feat/altA and target trunk; others default
        op = orch.plan_rebase(
            "feat/x",
            "main",
            branch_map={
                # by name
                "libA": ("feat/altA", "trunk"),
                # by relative path
                str(libB.path.relative_to(root.path)): ("feat/x", None),
            },
        )

        states = {s.repo.name: s for s in op.repo_states}
        assert states["libA"].source_branch == "feat/altA"
        assert states["libA"].target_branch == "trunk"
        # libB uses provided src and inherits global target
        assert states["libB"].source_branch == "feat/x"
        assert states["libB"].target_branch == "main"
        # root remains defaults
        assert states["root"].source_branch == "feat/x"
        assert states["root"].target_branch == "main"


def test_plan_rebase_missing_branch_raises(patched_env):
    root, order = patched_env
    libA, libB, root_repo = order

    # Only some branches exist to trigger validation errors
    existing = {
        libA.path: {"feat/x", "main"},
        libB.path: {"feat/y", "main"},  # missing source feat/x
        root_repo.path: {"feat/x", "main"},
    }

    with patch(
        "lockstep_rebase.rebase_orchestrator.GitManager",
        side_effect=make_git_manager_side_effect(root, order, existing),
    ) as GM:
        # Attach patched GitManager mocks to each RepoInfo to avoid lazy init
        for ri in order:
            ri.git_manager = GM(ri.path)

        orch = RebaseOrchestrator(root_path=root.path)
        with pytest.raises(RebaseError) as ei:
            orch.plan_rebase("feat/x", "main")
        assert "Source branch missing" in str(ei.value)
