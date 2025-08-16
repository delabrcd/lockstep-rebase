"""
Tests for auto-discovery submodule rebase planning and CLI flow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Set, Tuple
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from lockstep_rebase.models import RepoInfo
from lockstep_rebase.rebase_orchestrator import RebaseOrchestrator
from lockstep_rebase.cli import cli


# --- Test utilities ---
class StubPrompt:
    def __init__(self, override_src: Optional[str] = None, override_tgt: Optional[str] = None) -> None:
        self.override_src = override_src
        self.override_tgt = override_tgt

    def confirm_include_updated_submodule(
        self,
        parent_name: str,
        rel_path: str,
        src_sha: str,
        tgt_sha: str,
        sugg_src: str,
        sugg_tgt: str,
    ) -> bool:
        # Always include in these tests
        return True

    def choose_submodule_branches(self, name: str, sugg_src: str, sugg_tgt: str) -> Tuple[str, str]:
        return (
            self.override_src if self.override_src is not None else sugg_src,
            self.override_tgt if self.override_tgt is not None else sugg_tgt,
        )


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
        # Deepest-first order is expected by orchestrator.plan_rebase
        return list(self._order)

    def get_hierarchy_lines(self, _root):
        return []

    def get_hierarchy_entries(self, _root):
        return []


# GitManager factory with per-repo behavior needed by auto-discovery
class GitManagerFactory:
    def __init__(
        self,
        branches_by_repo: Dict[Path, Set[str]],
        changed_by_parent: Dict[Path, Set[str]],
        pointers: Dict[Tuple[Path, str, str], Optional[str]],
        branches_containing: Dict[Tuple[Path, str], Tuple[list[str], list[str]]],
    ) -> None:
        self.branches_by_repo = branches_by_repo
        self.changed_by_parent = changed_by_parent
        self.pointers = pointers
        self.branches_containing = branches_containing
        self._mocks: Dict[Path, MagicMock] = {}

    def __call__(self, repo_path: Path):
        repo_path = Path(repo_path)
        if repo_path in self._mocks:
            return self._mocks[repo_path]

        m = MagicMock()

        def branch_exists(name: str, _path: Optional[Path] = None) -> bool:
            return name in self.branches_by_repo.get(repo_path, set())

        def get_commits_between(base: str, feature: str, _path: Optional[Path] = None):
            return []

        def submodule_changed_between(base: str, feature: str, rel_path: str, _path: Optional[Path] = None) -> bool:
            changed = self.changed_by_parent.get(repo_path, set())
            return rel_path in changed

        def get_submodule_pointer_at(branch: str, rel_path: str, _path: Optional[Path] = None) -> Optional[str]:
            return self.pointers.get((repo_path, branch, rel_path))

        def branches_containing_commit(commit_sha: str, _path: Optional[Path] = None, include_remotes: bool = True):
            return self.branches_containing.get((repo_path, commit_sha), ([], []))

        m.branch_exists.side_effect = branch_exists
        m.get_commits_between.side_effect = get_commits_between
        m.submodule_changed_between.side_effect = submodule_changed_between
        m.get_submodule_pointer_at.side_effect = get_submodule_pointer_at
        m.branches_containing_commit.side_effect = branches_containing_commit

        self._mocks[repo_path] = m
        return m


# --- Fixtures ---
@pytest.fixture()
def simple_hierarchy(tmp_path: Path):
    root_path = tmp_path / "root"
    liba_path = root_path / "libA"
    libb_path = root_path / "libB"
    root_path.mkdir(parents=True)
    liba_path.mkdir(parents=True)
    libb_path.mkdir(parents=True)

    root = RepoInfo(path=root_path, name="root", is_submodule=False, depth=0)
    libA = RepoInfo(path=liba_path, name="libA", is_submodule=True, parent_repo=root, depth=1)
    libB = RepoInfo(path=libb_path, name="libB", is_submodule=True, parent_repo=root, depth=1)
    root.submodules = [libA, libB]

    # Deepest-first order as expected by plan_rebase
    order = [libA, libB, root]
    return root, order


@pytest.fixture()
def nested_hierarchy(tmp_path: Path):
    root_path = tmp_path / "root"
    liba_path = root_path / "libA"
    subx_path = liba_path / "subX"
    root_path.mkdir(parents=True)
    liba_path.mkdir(parents=True)
    subx_path.mkdir(parents=True)

    root = RepoInfo(path=root_path, name="root", is_submodule=False, depth=0)
    libA = RepoInfo(path=liba_path, name="libA", is_submodule=True, parent_repo=root, depth=1)
    subX = RepoInfo(path=subx_path, name="subX", is_submodule=True, parent_repo=libA, depth=2)
    root.submodules = [libA]
    libA.submodules = [subX]

    order = [subX, libA, root]
    return root, order


# --- Tests ---

def test_auto_plan_includes_changed_and_infers_branches(simple_hierarchy):
    root, order = simple_hierarchy

    # Only libA changed in parent root between target..source
    changed_by_parent = {root.path: {"libA"}}
    # Pointers (repo_path, branch, rel_path) -> sha
    pointers = {
        (root.path, "feature/x", "libA"): "aaa",
        (root.path, "main", "libA"): "bbb",
    }
    # libA branch inference from SHAs
    branches_containing = {
        (order[0].path, "aaa"): (["feature/x"], ["origin/feature/x"]),
        (order[0].path, "bbb"): (["main"], []),
    }
    branches_by_repo = {
        order[0].path: {"feature/x", "main"},  # libA
        order[1].path: {"feature/x", "main"},  # libB (unused)
        order[2].path: {"feature/x", "main"},  # root
    }

    gm_factory = GitManagerFactory(branches_by_repo, changed_by_parent, pointers, branches_containing)

    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)
    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper), patch(
        "lockstep_rebase.rebase_orchestrator.GitManager", side_effect=gm_factory
    ):
        orch = RebaseOrchestrator(root_path=root.path)
        prompt = StubPrompt()
        op = orch.plan_rebase_auto("feature/x", "main", prompt)

    names = {s.repo.name for s in op.repo_states}
    assert names == {"libA", "root"}, "Should include changed submodule and root only"

    states = {s.repo.name: s for s in op.repo_states}
    assert states["libA"].source_branch == "feature/x"
    assert states["libA"].target_branch == "main"
    assert states["root"].source_branch == "feature/x"
    assert states["root"].target_branch == "main"


def test_auto_plan_respects_prompt_overrides(simple_hierarchy):
    root, order = simple_hierarchy

    changed_by_parent = {root.path: {"libA"}}
    pointers = {
        (root.path, "src", "libA"): "c1",
        (root.path, "tgt", "libA"): "c2",
    }
    branches_containing = {
        (order[0].path, "c1"): ([], ["origin/src"]),
        (order[0].path, "c2"): ([], ["origin/tgt"]),
    }
    branches_by_repo = {
        order[0].path: {"ov/src", "ov/tgt"},
        order[2].path: {"src", "tgt"},
    }

    gm_factory = GitManagerFactory(branches_by_repo, changed_by_parent, pointers, branches_containing)

    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)
    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper), patch(
        "lockstep_rebase.rebase_orchestrator.GitManager", side_effect=gm_factory
    ):
        orch = RebaseOrchestrator(root_path=root.path)
        # Override suggested branches
        prompt = StubPrompt(override_src="ov/src", override_tgt="ov/tgt")
        op = orch.plan_rebase_auto("src", "tgt", prompt)

    states = {s.repo.name: s for s in op.repo_states}
    assert {"libA", "root"} == set(states.keys())
    assert states["libA"].source_branch == "ov/src"
    assert states["libA"].target_branch == "ov/tgt"


def test_auto_plan_applies_exclude_after_discovery(simple_hierarchy):
    root, order = simple_hierarchy

    changed_by_parent = {root.path: {"libA"}}
    pointers = {
        (root.path, "s", "libA"): "h1",
        (root.path, "t", "libA"): "h2",
    }
    branches_containing = {
        (order[0].path, "h1"): (["s"], []),
        (order[0].path, "h2"): (["t"], []),
    }
    branches_by_repo = {
        order[0].path: {"s", "t"},
        order[2].path: {"s", "t"},
    }

    gm_factory = GitManagerFactory(branches_by_repo, changed_by_parent, pointers, branches_containing)

    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)
    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper), patch(
        "lockstep_rebase.rebase_orchestrator.GitManager", side_effect=gm_factory
    ):
        orch = RebaseOrchestrator(root_path=root.path)
        prompt = StubPrompt()
        op = orch.plan_rebase_auto("s", "t", prompt, exclude={"libA"})

    names = [s.repo.name for s in op.repo_states]
    assert names == ["root"], "Exclude should remove discovered submodule from final plan"


def test_auto_plan_recurses_into_nested(nested_hierarchy):
    root, order = nested_hierarchy
    subX, libA, _root = order  # order: [subX, libA, root]

    # root changed libA; within libA, subX also changed
    changed_by_parent = {
        root.path: {"libA"},
        libA.path: {"subX"},
    }
    pointers = {
        (root.path, "fsrc", "libA"): "shaA1",
        (root.path, "tgt", "libA"): "shaA0",
        (libA.path, "fsrc", "subX"): "shaX1",
        (libA.path, "tgt", "subX"): "shaX0",
    }
    branches_containing = {
        (libA.path, "shaA1"): (["fsrc"], []),
        (libA.path, "shaA0"): (["tgt"], []),
        (subX.path, "shaX1"): (["fsrc"], []),
        (subX.path, "shaX0"): (["tgt"], []),
    }
    branches_by_repo = {
        root.path: {"fsrc", "tgt"},
        libA.path: {"fsrc", "tgt"},
        subX.path: {"fsrc", "tgt"},
    }

    gm_factory = GitManagerFactory(branches_by_repo, changed_by_parent, pointers, branches_containing)

    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)
    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper), patch(
        "lockstep_rebase.rebase_orchestrator.GitManager", side_effect=gm_factory
    ):
        orch = RebaseOrchestrator(root_path=root.path)
        prompt = StubPrompt()
        op = orch.plan_rebase_auto("fsrc", "tgt", prompt)

    names = {s.repo.name for s in op.repo_states}
    assert names == {"root", "libA", "subX"}, "Should include nested updated submodule as well"


def test_branch_inference_ignores_detached_head(simple_hierarchy):
    root, order = simple_hierarchy
    libA = order[0]

    changed_by_parent = {root.path: {"libA"}}
    pointers = {
        (root.path, "feature/x", "libA"): "sha1",
        (root.path, "main", "libA"): "sha0",
    }
    # Local output includes a detached HEAD annotation which should be ignored by filtering
    branches_containing = {
        (libA.path, "sha1"): (["(HEAD detached at 1234abcd)"], []),
        (libA.path, "sha0"): (["(HEAD detached at 5678efgh)"], []),
    }
    branches_by_repo = {
        libA.path: {"feature/x", "main"},
        root.path: {"feature/x", "main"},
    }

    gm_factory = GitManagerFactory(branches_by_repo, changed_by_parent, pointers, branches_containing)

    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)
    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper), patch(
        "lockstep_rebase.rebase_orchestrator.GitManager", side_effect=gm_factory
    ):
        orch = RebaseOrchestrator(root_path=root.path)
        prompt = StubPrompt()
        op = orch.plan_rebase_auto("feature/x", "main", prompt)

    states = {s.repo.name: s for s in op.repo_states}
    assert states["libA"].source_branch == "feature/x"
    assert states["libA"].target_branch == "main"


def test_branch_inference_skips_symbolic_remote_head(simple_hierarchy):
    root, order = simple_hierarchy
    libA = order[0]

    changed_by_parent = {root.path: {"libA"}}
    pointers = {
        (root.path, "src", "libA"): "c1",
        (root.path, "tgt", "libA"): "c2",
    }
    branches_containing = {
        # No locals, remotes include a symbolic HEAD ref and a real branch
        (libA.path, "c1"): ([], ["origin/HEAD -> origin/src", "origin/src"]),
        (libA.path, "c2"): ([], ["origin/HEAD -> origin/tgt", "origin/tgt"]),
    }
    branches_by_repo = {
        libA.path: {"src", "tgt"},
        root.path: {"src", "tgt"},
    }

    gm_factory = GitManagerFactory(branches_by_repo, changed_by_parent, pointers, branches_containing)

    mapper = FakeSubmoduleMapper().with_hierarchy(root, order)
    with patch("lockstep_rebase.rebase_orchestrator.SubmoduleMapper", return_value=mapper), patch(
        "lockstep_rebase.rebase_orchestrator.GitManager", side_effect=gm_factory
    ):
        orch = RebaseOrchestrator(root_path=root.path)
        prompt = StubPrompt()
        op = orch.plan_rebase_auto("src", "tgt", prompt)

    states = {s.repo.name: s for s in op.repo_states}
    assert states["libA"].source_branch == "src"
    assert states["libA"].target_branch == "tgt"


# --- CLI tests for auto mode ---
@patch("lockstep_rebase.cli.RebaseOrchestrator")
@patch("lockstep_rebase.cli.CliPrompt")
@patch("lockstep_rebase.cli.CliConflictPrompt")
def test_cli_rebase_auto_flag_forwarded(mock_conflict_prompt_cls, mock_prompt_cls, mock_orch_cls):
    runner = CliRunner()

    mock_prompt_cls.return_value = MagicMock()

    mock_orch = MagicMock()
    mock_orch.validate_repository_state.return_value = []
    mock_operation = MagicMock()
    mock_operation.repo_states = []
    mock_operation.global_commit_mapping = {}
    mock_orch.plan_rebase_auto.return_value = mock_operation
    mock_orch_cls.return_value = mock_orch

    result = runner.invoke(
        cli,
        [
            "rebase",
            "src",
            "tgt",
            "--dry-run",
            "--auto-select-submodules",
            "--include",
            "libA",
            "--exclude",
            "libB",
            "--branch-map",
            "libC=feat/x:main",
        ],
    )

    assert result.exit_code == 0
    assert mock_orch.plan_rebase_auto.called
    _, args, kwargs = mock_orch.plan_rebase_auto.mock_calls[0]
    # args: (source, target, prompt)
    assert args[0] == "src"
    assert args[1] == "tgt"
    assert "include" in kwargs and kwargs["include"] == {"libA"}
    assert "exclude" in kwargs and kwargs["exclude"] == {"libB"}
    assert "branch_map_overrides" in kwargs and kwargs["branch_map_overrides"] == {"libC": ("feat/x", "main")}
