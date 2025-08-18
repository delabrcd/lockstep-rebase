"""
Main rebase orchestration logic for multi-repository operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple

from lockstep_rebase.conflict_resolver import ConflictResolver

from .models import (
    RebaseOperation,
    RebaseState,
    RepoInfo,
    RebaseError,
    HierarchyEntry,
    BackupEntry,
    ResolutionSummary,
)
from .git_manager import GitManager  # Expose for tests patching rebase_orchestrator.GitManager
from .submodule_mapper import SubmoduleMapper
from .commit_tracker import GlobalCommitTracker, CommitTracker
from .prompt_interface import UserPrompt, NoOpPrompt, BranchSyncAction
from .conflict_prompt_interface import ConflictPrompt
from .backup_manager import BACKUP_PREFIX


logger = logging.getLogger(__name__)


class RebaseOrchestrator:
    """Orchestrates rebase operations across multiple repositories with submodules."""

    def __init__(
        self, root_path: Optional[Path] = None, conflict_prompt: ConflictPrompt = None
    ) -> None:
        """Initialize the rebase orchestrator."""
        # Normalize provided path (or cwd) to absolute to avoid relative path issues
        self.root_path = (root_path or Path.cwd()).resolve()
        logger.debug(
            f"RebaseOrchestrator initialized with root_path={self.root_path} cwd={Path.cwd()}"
        )
        self.submodule_mapper = SubmoduleMapper(self.root_path)
        self.global_tracker = GlobalCommitTracker()

        # Support both new and legacy signatures for discover_repository_hierarchy.
        # New: discover_repository_hierarchy(global_tracker, conflict_prompt)
        # Legacy (used by some tests/mocks): discover_repository_hierarchy()
        try:
            self.root_repo_info = self.submodule_mapper.discover_repository_hierarchy(
                self.global_tracker, conflict_prompt
            )
        except TypeError:
            # Backward compatibility with mocks providing no-arg method
            self.root_repo_info = self.submodule_mapper.discover_repository_hierarchy()

        logger.info(f"Initialized rebase orchestrator for {self.root_repo_info.name}")

    def plan_rebase(
        self,
        source_branch: str,
        target_branch: str,
        prompt: UserPrompt = None,
        *,
        include: Optional[set[str]] = None,
        exclude: Optional[set[str]] = None,
        branch_map: Optional[dict[str, tuple[str, Optional[str]]]] = None,
        do_sync_prompt: bool = True,
    ) -> RebaseOperation:
        """
        Plan a rebase operation across all repositories.

        Args:
            source_branch: The branch to rebase (e.g., 'feature/my-feature')
            target_branch: The branch to rebase onto (e.g., 'main')

        Returns:
            RebaseOperation with planned states for all repositories
        """
        logger.info(f"Planning rebase from {source_branch} to {target_branch}")

        if prompt is None:
            prompt = NoOpPrompt()

        # Create rebase operation (global defaults)
        operation = RebaseOperation(
            root_repo=self.root_repo_info, source_branch=source_branch, target_branch=target_branch
        )

        # Compute repositories in rebase order (deepest first)
        full_order = self.submodule_mapper.get_rebase_order(self.root_repo_info)

        # Filter include/exclude
        def _matches(repo: RepoInfo, token: str) -> bool:
            rel = (
                str(repo.path.relative_to(self.root_path))
                if self.root_path in repo.path.parents or repo.path == self.root_path
                else str(repo.path)
            )
            return token == repo.name or token == rel or token == str(repo.path)

        if include:
            selected = [r for r in full_order if any(_matches(r, t) for t in include)]
            if not selected:
                raise RebaseError("No repositories matched --include filters")
        else:
            selected = list(full_order)

        if exclude:
            selected = [r for r in selected if not any(_matches(r, t) for t in exclude)]
            if not selected:
                raise RebaseError("All repositories were excluded by --exclude filters")

        # Fetch remotes for all selected repositories up front (including submodules)
        for repo_info in selected:
            try:
                gm = repo_info.git_manager
                remotes = [r.name for r in gm.repo.remotes]
                for rn in remotes:
                    try:
                        gm.fetch_remote(rn)
                    except Exception as fe:
                        logger.warning(f"Failed to fetch {rn} for {repo_info.name}: {fe}")
            except Exception as e:
                logger.warning(f"Failed to list/fetch remotes for {repo_info.name}: {e}")

        # Per-repo branch resolve using branch_map overrides
        def _resolve_branches(repo: RepoInfo) -> tuple[str, str]:
            if not branch_map:
                return source_branch, target_branch
            # Priority: name, relative path, absolute path
            rel = (
                str(repo.path.relative_to(self.root_path))
                if self.root_path in repo.path.parents or repo.path == self.root_path
                else str(repo.path)
            )
            keys = [repo.name, rel, str(repo.path)]
            for k in keys:
                if k in branch_map:
                    src, tgt = branch_map[k]
                    return src or source_branch, (tgt if tgt is not None else target_branch)
            return source_branch, target_branch

        # Validate branches per repo and build states
        missing_src: list[str] = []
        missing_tgt: list[str] = []

        for repo_info in selected:
            gm = repo_info.git_manager
            src_br, tgt_br = _resolve_branches(repo_info)

            # Ensure source branch exists locally; if only remote exists, offer to create
            if not gm.branch_exists(src_br):
                chosen_remote = None
                try:
                    remotes = [r.name for r in gm.repo.remotes]
                except Exception:
                    remotes = []
                for rn in sorted(remotes, key=lambda n: (n != "origin", n)):
                    if gm.remote_branch_exists(src_br, rn):
                        chosen_remote = rn
                        break
                if chosen_remote:
                    try:
                        if prompt.confirm_create_local_branch(
                            repo_info.name, src_br, chosen_remote
                        ):
                            gm.create_local_branch_from_remote(src_br, chosen_remote)
                        else:
                            missing_src.append(f"{repo_info.name} ({src_br})")
                    except Exception:
                        missing_src.append(f"{repo_info.name} ({src_br})")
                else:
                    missing_src.append(f"{repo_info.name} ({src_br})")

            # Ensure target branch exists locally; if only remote exists, offer to create
            if not gm.branch_exists(tgt_br):
                chosen_remote = None
                try:
                    remotes = [r.name for r in gm.repo.remotes]
                except Exception:
                    remotes = []
                for rn in sorted(remotes, key=lambda n: (n != "origin", n)):
                    if gm.remote_branch_exists(tgt_br, rn):
                        chosen_remote = rn
                        break
                if chosen_remote:
                    try:
                        if prompt.confirm_create_local_branch(
                            repo_info.name, tgt_br, chosen_remote
                        ):
                            gm.create_local_branch_from_remote(tgt_br, chosen_remote)
                        else:
                            missing_tgt.append(f"{repo_info.name} ({tgt_br})")
                    except Exception:
                        missing_tgt.append(f"{repo_info.name} ({tgt_br})")
                else:
                    missing_tgt.append(f"{repo_info.name} ({tgt_br})")

            # Remote sync: prompt user instead of auto fast-forwarding (only if enabled here)
            if do_sync_prompt:
                try:

                    def _maybe_prompt_sync(branch: str) -> None:
                        # Only consider if local exists and there is some remote with the branch
                        if not gm.branch_exists(branch):
                            return
                        try:
                            remotes = [r.name for r in gm.repo.remotes]
                        except Exception:
                            remotes = []
                        chosen_remote = None
                        for rn in sorted(remotes, key=lambda n: (n != "origin", n)):
                            if gm.remote_branch_exists(branch, rn):
                                chosen_remote = rn
                                break
                        if not chosen_remote:
                            return
                        ahead, behind = gm.branch_ahead_behind(branch, chosen_remote)
                        if ahead == 0 and behind == 0:
                            return
                        local_commit = gm.get_short_commit_for_ref(branch) or ""
                        remote_commit = (
                            gm.get_short_commit_for_ref(f"{chosen_remote}/{branch}") or ""
                        )
                        action = prompt.confirm_sync_branch(
                            repo_info.name,
                            branch,
                            local_commit,
                            remote_commit,
                            behind,
                            ahead,
                        )
                        if action == BranchSyncAction.SYNC_LOCAL:
                            if behind > 0 and ahead == 0:
                                logger.info(
                                    f"User approved fast-forward of {repo_info.name}:{branch} from {chosen_remote} (behind {behind})"
                                )
                                gm.fast_forward_branch_to_remote(branch, chosen_remote)
                            else:
                                logger.warning(
                                    f"Cannot fast-forward {repo_info.name}:{branch} due to divergence (ahead {ahead}, behind {behind}); skipping"
                                )
                        elif action == BranchSyncAction.USE_REMOTE:
                            logger.info(
                                f"User chose to reset {repo_info.name}:{branch} to {chosen_remote}/{branch} ({remote_commit})"
                            )
                            # Force update local branch to remote tip
                            gm.create_local_branch_from_remote(branch, chosen_remote)
                        elif action == BranchSyncAction.SKIP:
                            logger.info(f"User skipped syncing {repo_info.name}:{branch}")
                        elif action == BranchSyncAction.ABORT:
                            raise RebaseError(
                                f"User aborted during sync of {repo_info.name}:{branch}"
                            )
                        # CREATE_LOCAL is not applicable here since the branch exists locally

                    _maybe_prompt_sync(src_br)
                    _maybe_prompt_sync(tgt_br)
                except Exception as e:
                    logger.warning(
                        f"Failed remote sync prompt for {repo_info.name} ({src_br}->{tgt_br}): {e}"
                    )

        if missing_src:
            raise RebaseError("Source branch missing in: " + ", ".join(missing_src))
        if missing_tgt:
            raise RebaseError("Target branch missing in: " + ", ".join(missing_tgt))

        # Build rebase states
        for repo_info in selected:
            gm = repo_info.git_manager
            if not gm:
                raise RebaseError(f"Missing GitManager for {repo_info.name} ({repo_info.path})")
            src_br, tgt_br = _resolve_branches(repo_info)

            original_commits = gm.get_commits_between(tgt_br, src_br)

            state = RebaseState(
                repo=repo_info,
                source_branch=src_br,
                target_branch=tgt_br,
                original_commits=original_commits,
            )

            operation.repo_states.append(state)
            logger.debug(
                f"Planned rebase for {repo_info.name}: {len(original_commits)} commits ({src_br} -> {tgt_br})"
            )

        logger.info(f"Planned rebase operation for {len(operation.repo_states)} repositories")
        return operation

    def plan_rebase_auto(
        self,
        source_branch: str,
        target_branch: str,
        prompt: UserPrompt = None,
        *,
        include: Optional[Set[str]] = None,
        exclude: Optional[Set[str]] = None,
        branch_map_overrides: Optional[Dict[str, Tuple[str, Optional[str]]]] = None,
    ) -> RebaseOperation:
        """
        Auto-discover updated submodules within the commit range, prompt for inclusion,
        infer or allow branch selection per included submodule, recurse into nested submodules,
        then delegate to plan_rebase with the discovered include set and branch_map.

        Args:
            source_branch: Parent/root source branch
            target_branch: Parent/root target branch
            prompt: User prompt implementation for interactions
            include: Optional user include filters (name/relative/absolute)
            exclude: Optional user exclude filters (name/relative/absolute)
            branch_map_overrides: Optional per-repo overrides to apply on top of discovery
        """
        logger.info(f"Planning auto-discovery rebase from {source_branch} to {target_branch}")

        if prompt is None:
            prompt = NoOpPrompt()

        discovered_includes: Set[str] = set()
        discovered_branch_map: Dict[str, Tuple[str, Optional[str]]] = {}

        def repo_key_variants(repo_path: Path) -> Tuple[str, str, str]:
            """Return (name-like placeholder not available here, rel, abs) keys we may use."""
            abs_key = str(repo_path)
            try:
                rel_key = str(repo_path.relative_to(self.root_path))
            except Exception:
                rel_key = abs_key
            # Name matching will be handled by plan_rebase; we provide rel/abs keys here
            return "", rel_key, abs_key

        def record_repo(repo_info: RepoInfo) -> None:
            _, rel_key, abs_key = repo_key_variants(repo_info.path)
            # Prefer including by absolute and relative for robust matching
            discovered_includes.add(abs_key)
            discovered_includes.add(rel_key)

        def infer_branches_for_submodule(
            sub_repo: RepoInfo,
            src_sha: Optional[str],
            tgt_sha: Optional[str],
            parent_src: str,
            parent_tgt: str,
        ) -> Tuple[str, str]:
            """Infer default (src, tgt) branches inside submodule using ONLY exact tip matches.

            If no exact match exists for a pointer, return an empty string to force manual input.
            Preference: if the parent's branch name exists in the submodule and is an exact match, use it.
            Otherwise, pick any branch (local or remote) whose tip equals the pointer commit.
            """
            gm_sub = sub_repo.git_manager

            def pick(commit_sha: Optional[str], prefer: str) -> str:
                if not commit_sha:
                    return ""

                short_commit = gm_sub.get_short_commit_for_ref(commit_sha)
                if not short_commit:
                    return ""

                # Prefer the hinted parent branch name if it exactly matches the pointer
                try:
                    if gm_sub.branch_exists(prefer):
                        head = gm_sub.get_short_commit_for_ref(prefer)
                        if head == short_commit:
                            return prefer
                    # Check across any remote
                    try:
                        for r in gm_sub.repo.remotes:
                            if gm_sub.remote_branch_exists(prefer, r.name):
                                head = gm_sub.get_short_commit_for_ref(f"{r.name}/{prefer}")
                                if head == short_commit:
                                    return prefer
                    except Exception:
                        pass
                except Exception:
                    pass

                # Discover other exact matches via branches_containing_commit, but filter by exact tip equality
                try:
                    locals_, remotes_ = gm_sub.branches_containing_commit(commit_sha)
                except Exception:
                    locals_, remotes_ = ([], [])

                def _sanitize_local(names: List[str]) -> List[str]:
                    out: List[str] = []
                    for n in names:
                        if not n:
                            continue
                        low = n.lower()
                        if (
                            n.startswith("(")
                            or "detached" in low
                            or low.startswith("head")
                            or "->" in n
                        ):
                            continue
                        out.append(n)
                    try:
                        return [b for b in out if gm_sub.branch_exists(b)]
                    except Exception:
                        return out

                def _sanitize_remote(names: List[str]) -> List[str]:
                    out: List[str] = []
                    for n in names:
                        if not n:
                            continue
                        if "->" in n:
                            continue
                        out.append(n)
                    return out

                for cand in _sanitize_local(locals_):
                    try:
                        head = gm_sub.get_short_commit_for_ref(cand)
                        if head == short_commit:
                            return cand
                    except Exception:
                        continue

                for cand in _sanitize_remote(remotes_):
                    # cand is like 'remote/name'; compare using full ref and return short branch name
                    name = cand.split("/", 1)[1] if "/" in cand else cand
                    try:
                        head = gm_sub.get_short_commit_for_ref(cand)
                        if head == short_commit:
                            return name
                    except Exception:
                        continue

                # No exact matches found
                return ""

            default_src = pick(src_sha, parent_src)
            default_tgt = pick(tgt_sha, parent_tgt)
            return default_src, default_tgt

        def process_parent(parent_info: RepoInfo, parent_src: str, parent_tgt: str) -> None:
            # Always include the parent repo itself
            gm_parent = parent_info.git_manager

            # Always fetch before checking sync or reading pointers
            try:
                # Fetch all remotes to ensure up-to-date pointers for comparison
                remotes = [r.name for r in gm_parent.repo.remotes]
                for rn in remotes:
                    try:
                        gm_parent.fetch_remote(rn)
                    except Exception as fe:
                        logger.warning(f"Failed to fetch {rn} for {parent_info.name}: {fe}")
            except Exception as e:
                logger.warning(f"Failed to fetch origin for {parent_info.name}: {e}")

            # Optionally prompt to sync parent's branches
            def _maybe_prompt_sync(branch: str) -> None:
                if not gm_parent.branch_exists(branch):
                    return
                if not gm_parent.remote_branch_exists(branch, "origin"):
                    return
                ahead, behind = gm_parent.branch_ahead_behind(branch, "origin")
                if ahead == 0 and behind == 0:
                    return
                local_commit = gm_parent.get_short_commit_for_ref(branch) or ""
                remote_commit = gm_parent.get_short_commit_for_ref(f"origin/{branch}") or ""
                action = prompt.confirm_sync_branch(
                    parent_info.name, branch, local_commit, remote_commit, behind, ahead
                )
                if action == BranchSyncAction.SYNC_LOCAL:
                    if behind > 0 and ahead == 0:
                        gm_parent.fast_forward_branch_to_remote(branch, "origin")
                    else:
                        logger.warning(
                            f"Cannot fast-forward {parent_info.name}:{branch} due to divergence (ahead {ahead}, behind {behind}); skipping"
                        )
                elif action == BranchSyncAction.USE_REMOTE:
                    gm_parent.create_local_branch_from_remote(branch, "origin")
                elif action == BranchSyncAction.SKIP:
                    pass
                elif action == BranchSyncAction.ABORT:
                    raise RebaseError(f"User aborted during sync of {parent_info.name}:{branch}")

            try:
                _maybe_prompt_sync(parent_src)
                _maybe_prompt_sync(parent_tgt)
            except Exception as e:
                logger.warning(
                    f"Remote sync prompt in auto-planning failed for {parent_info.name}: {e}"
                )

            # Resolve refs for reading pointers (prefer a remote ref if local is missing or behind)
            def _ref_for_reading(branch: str) -> str:
                try:
                    remotes = [r.name for r in gm_parent.repo.remotes]
                except Exception:
                    remotes = []

                # Prefer 'origin' order
                sorted_remotes = sorted(remotes, key=lambda n: (n != "origin", n))

                local_exists = gm_parent.branch_exists(branch)

                # If local exists, but is behind a remote, use the remote ref for read-only comparisons
                if local_exists:
                    for rn in sorted_remotes:
                        if gm_parent.remote_branch_exists(branch, rn):
                            ahead, behind = gm_parent.branch_ahead_behind(branch, rn)
                            if behind > 0 and ahead == 0:
                                return f"{rn}/{branch}"
                            break  # We checked the preferred remote; fall back to local
                    return branch

                # No local branch: if any remote has it, use that remote ref
                for rn in sorted_remotes:
                    if gm_parent.remote_branch_exists(branch, rn):
                        return f"{rn}/{branch}"
                # Fallback: return branch as-is (may be a detached or tag ref)
                return branch

            src_ref = _ref_for_reading(parent_src)
            tgt_ref = _ref_for_reading(parent_tgt)
            logger.debug(
                f"Parent {parent_info.name}: using refs src_ref={src_ref}, tgt_ref={tgt_ref} for submodule pointer comparison"
            )

            for sm in parent_info.submodules:
                # Compute the submodule path relative to the parent's repo root (POSIX).
                # Prefer GitManager normalization when available; fall back to manual logic for test mocks.
                rel_path: str
                used_gm_normalization = False
                try:
                    # Use GitManager's normalization if present (real implementation)
                    maybe_rel = gm_parent._to_repo_relative_str(sm.path)  # type: ignore[attr-defined]
                    if isinstance(maybe_rel, str) and maybe_rel:
                        rel_path = maybe_rel
                        used_gm_normalization = True
                    else:
                        raise TypeError("to_repo_relative_str did not return str")
                except Exception:
                    # Manual fallback compatible with MagicMock GitManager in tests
                    try:
                        base_root = Path(gm_parent.repo.working_dir)
                    except Exception:
                        base_root = parent_info.path

                    try:
                        rel_path = str(Path(sm.path).resolve().relative_to(base_root)).replace("\\", "/")
                    except Exception:
                        # Fallback: try relative to parent_info.path (may be same as base_root)
                        try:
                            rel_path = (
                                str(Path(sm.path).resolve().relative_to(parent_info.path)).replace("\\", "/")
                            )
                        except Exception:
                            # Final fallback to submodule name
                            rel_path = sm.name

                if used_gm_normalization:
                    logger.debug(
                        f"Parent {parent_info.name}: computed submodule rel_path='{rel_path}' via GitManager normalization (sm.path='{sm.path}')"
                    )
                else:
                    logger.debug(
                        f"Parent {parent_info.name}: computed submodule rel_path='{rel_path}' from base_root='{base_root}' (sm.path='{sm.path}')"
                    )

                # Read the submodule pointers at each end
                src_sha = gm_parent.get_submodule_pointer_at(src_ref, rel_path)
                tgt_sha = gm_parent.get_submodule_pointer_at(tgt_ref, rel_path)
                logger.debug(
                    f"Parent {parent_info.name}: submodule {rel_path} pointers src({src_ref})={src_sha} tgt({tgt_ref})={tgt_sha}"
                )

                # Determine if the submodule pointer differs between source and target
                # Include when the pointers are not equal (including None vs SHA differences)
                if src_sha == tgt_sha:
                    # No update for this submodule in parent between the two refs
                    continue

                # Detect if submodule changed on both branches (relative to merge-base) to annotate suggestions.
                # This is informational only (do not gate inclusion on this).
                both_changed = False
                base_sha = gm_parent.repo.git.merge_base(src_ref, tgt_ref)
                if base_sha:
                    both_changed = bool(
                        gm_parent.submodule_changed_between(base_sha, src_ref, rel_path)
                        and gm_parent.submodule_changed_between(base_sha, tgt_ref, rel_path)
                    )
                logger.debug(
                    f"Parent {parent_info.name}: submodule {rel_path} merge-base={base_sha}, both_changed={both_changed}"
                )

                # Include this parent since it has a changed submodule pointer
                record_repo(parent_info)

                # Infer suggested branches for the submodule
                sugg_src, sugg_tgt = infer_branches_for_submodule(
                    sm, src_sha, tgt_sha, parent_src, parent_tgt
                )

                # Git manager for this submodule (used by helpers below)
                gm_sub = sm.git_manager

                # Compute display variants; prefer local branch names, fall back to remote-qualified
                def _to_display(branch_name: str) -> str:
                    try:
                        # Prefer local branch if it exists
                        if gm_sub.branch_exists(branch_name):
                            return branch_name
                        # Otherwise, show remote-qualified (prefer 'origin') if available
                        remotes = [r.name for r in gm_sub.repo.remotes]
                        for rn in sorted(remotes, key=lambda n: (n != "origin", n)):
                            if gm_sub.remote_branch_exists(branch_name, rn):
                                return f"{rn}/{branch_name}"
                    except Exception:
                        pass
                    return branch_name

                def _is_exact(branch_name: str, commit_sha: Optional[str]) -> bool:
                    if not commit_sha:
                        return False
                    try:
                        short_commit = gm_sub.get_short_commit_for_ref(commit_sha)
                        if not short_commit:
                            return False
                        if gm_sub.branch_exists(branch_name):
                            head_short = gm_sub.get_short_commit_for_ref(branch_name)
                            if head_short == short_commit:
                                return True
                        remotes = [r.name for r in gm_sub.repo.remotes]
                        for rn in remotes:
                            if gm_sub.remote_branch_exists(branch_name, rn):
                                head_short = gm_sub.get_short_commit_for_ref(f"{rn}/{branch_name}")
                                if head_short == short_commit:
                                    return True
                        return False
                    except Exception:
                        return False

                src_exact = _is_exact(sugg_src, src_sha)
                tgt_exact = _is_exact(sugg_tgt, tgt_sha)
                display_src = _to_display(sugg_src) if src_exact else "no exact tracking branch"
                display_tgt = _to_display(sugg_tgt) if tgt_exact else "no exact tracking branch"

                # Prompt for inclusion (present display suggestions with remote prefixes preserved)
                include_sm = prompt.confirm_include_updated_submodule(
                    parent_info.name,
                    rel_path,
                    src_sha or "",
                    tgt_sha or "",
                    display_src,
                    display_tgt,
                )

                if not include_sm:
                    continue

                # Allow override of inferred branches.
                # Only suggest defaults when there is an exact tracking branch; otherwise force manual input.
                default_src_for_input = sugg_src if src_exact else ""
                default_tgt_for_input = sugg_tgt if tgt_exact else ""
                chosen_src, chosen_tgt = prompt.choose_submodule_branches(
                    sm.name, default_src_for_input, default_tgt_for_input
                )

                # Ensure local branches exist (tool operates on local branches). If only remote exists, offer to create local.
                try:
                    for chosen in (chosen_src, chosen_tgt):
                        if gm_sub.branch_exists(chosen):
                            continue
                        # Find a remote that has this branch (prefer 'origin')
                        chosen_remote: Optional[str] = None
                        try:
                            remotes = [r.name for r in gm_sub.repo.remotes]
                        except Exception:
                            remotes = []
                        for rn in sorted(remotes, key=lambda n: (n != "origin", n)):
                            if gm_sub.remote_branch_exists(chosen, rn):
                                chosen_remote = rn
                                break
                        if chosen_remote:
                            if prompt.confirm_create_local_branch(sm.name, chosen, chosen_remote):
                                gm_sub.create_local_branch_from_remote(chosen, chosen_remote)
                except Exception as e:
                    logger.warning(f"Failed ensuring local branch exists for {sm.name}: {e}")

                # Record mapping and inclusion using robust key (relative to overall root)
                _, rel_key, abs_key = repo_key_variants(sm.path)
                discovered_branch_map[rel_key] = (chosen_src, chosen_tgt)
                discovered_includes.add(rel_key)
                discovered_includes.add(abs_key)

                # Recurse into nested submodules using chosen branches for this submodule
                process_parent(sm, chosen_src, chosen_tgt)

        # Kick off discovery from the root
        record_repo(self.root_repo_info)
        process_parent(self.root_repo_info, source_branch, target_branch)

        # Merge user overrides for branches (overrides take precedence)
        if branch_map_overrides:
            for k, v in branch_map_overrides.items():
                discovered_branch_map[k] = v

        # Determine the include filter to pass to planner
        # If user provided explicit includes, prefer that; otherwise use discovered set
        include_filter: Optional[Set[str]] = (
            include
            if (include and len(include) > 0)
            else (discovered_includes if discovered_includes else None)
        )

        # Apply excludes by passing through to planner (it will apply matching)
        operation = self.plan_rebase(
            source_branch,
            target_branch,
            prompt,
            include=include_filter,
            exclude=exclude,
            branch_map=discovered_branch_map or None,
            do_sync_prompt=False,
        )

        logger.info(f"Auto-discovery planned {len(operation.repo_states)} repositories for rebase")
        return operation

    def execute_rebase(self, operation: RebaseOperation) -> bool:
        """
        Execute the planned rebase operation.

        Returns:
            True if rebase completed successfully, False if aborted
        """
        logger.info("Starting rebase execution")

        try:
            # Ensure backups exist before any mutations if not already prepared
            if not operation.backup_session_id:
                self.create_backups(operation)

            for state in operation.repo_states:
                if not self._execute_repository_rebase(state, operation):
                    logger.error(f"Rebase failed for {state.repo.name}")
                    self._cleanup_failed_rebase(operation)
                    return False

            logger.info("✅ Rebase operation completed successfully!")
            return True

        except Exception as e:
            logger.error(f"Rebase execution failed: {e}")
            self._cleanup_failed_rebase(operation)
            raise RebaseError(f"Rebase execution failed: {e}")

    def create_backups(self, operation: RebaseOperation) -> None:
        """Create backup branches for all repositories' source branches.

        This should be called after planning and before execution. Idempotent if called twice in the same session.
        """
        # Initialize session id if not present
        if not operation.backup_session_id:
            operation.backup_session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

        created = 0
        for state in operation.repo_states:
            repo = state.repo
            key = str(repo.path)
            if key in operation.backup_branches:
                continue
            if not repo.backup_manager:
                raise RebaseError(f"Missing BackupManager for {repo.name} ({repo.path})")
            try:
                backup_name = repo.backup_manager.create_backup_branch(
                    state.source_branch, session_id=operation.backup_session_id
                )
                operation.backup_branches[key] = backup_name
                created += 1
            except Exception as e:
                logger.error(
                    f"Failed to create backup for {repo.name} ({state.source_branch}): {e}"
                )
                raise RebaseError(f"Failed to create backup branch in {repo.name}: {e}")
        logger.info(f"Created {created} backup branches for session {operation.backup_session_id}")

    def delete_backups(self, operation: RebaseOperation) -> int:
        """Delete backup branches for this operation.

        If a backup session id is present, delete all backups across the hierarchy for that session.
        Otherwise, fall back to deleting only the operation-recorded backups.

        Returns number of deleted backups.
        """
        # Prefer session-based deletion to ensure hierarchy-wide cleanup
        if operation.backup_session_id:
            deleted = self.delete_backups_by_session(operation.backup_session_id)
            # Clear recorded branches to avoid double-deletion attempts
            operation.backup_branches.clear()
            return deleted

        # Fallback: delete only the branches recorded on the operation
        deleted = 0
        for path_str, backup_name in list(operation.backup_branches.items()):
            try:
                repo_info = self._get_repo_by_path_str(path_str)
                if repo_info and repo_info.backup_manager:
                    repo_info.backup_manager.delete_backup_branch(backup_name)
                    deleted += 1
                    del operation.backup_branches[path_str]
                else:
                    logger.warning(f"No repo/backup manager found for {path_str}; skipping delete")
            except Exception as e:
                logger.error(f"Failed to delete backup {backup_name} in {path_str}: {e}")
        return deleted

    def list_backups_in_repo(self, repo_path: Optional[Path] = None) -> List[str]:
        """List backup branches in the specified or root repository."""
        repo = self._repo_for_path_or_root(repo_path)
        if not repo.backup_manager:
            return []
        return repo.backup_manager.list_backup_branches()

    def list_parsed_backups_in_repo(
        self, repo_path: Optional[Path] = None, original_branch: Optional[str] = None
    ) -> List[BackupEntry]:
        """List structured backup entries in the specified or root repository."""
        repo = self._repo_for_path_or_root(repo_path)
        if not repo.backup_manager:
            return []
        return repo.backup_manager.list_parsed_backups(original_branch=original_branch)

    def list_backups_across_hierarchy(
        self, original_branch: Optional[str] = None
    ) -> List[BackupEntry]:
        """Aggregate structured backup entries across the repository hierarchy."""
        entries: List[BackupEntry] = []
        for repo_info in self._get_all_repositories(self.root_repo_info):
            try:
                if repo_info.backup_manager:
                    entries.extend(
                        repo_info.backup_manager.list_parsed_backups(
                            original_branch=original_branch
                        )
                    )
            except Exception:
                # Ignore repos that error on listing
                continue
        return entries

    def delete_backups_by_session(
        self, session_id: str, original_branch: Optional[str] = None
    ) -> int:
        """Delete backups across the hierarchy filtered by session id (and optional original branch).

        Returns number of deleted backups.
        """
        entries = self.list_backups_across_hierarchy(original_branch=original_branch)
        targets = [e for e in entries if e.session == session_id]
        deleted = 0
        for e in targets:
            if self.delete_backup_in_repo(e.backup_branch, e.repo_path):
                deleted += 1
        return deleted

    def delete_backup_in_repo(self, backup_branch: str, repo_path: Optional[Path] = None) -> bool:
        """Delete a specific backup branch in the given repository."""
        repo = self._repo_for_path_or_root(repo_path)
        if not repo.backup_manager:
            return False
        try:
            repo.backup_manager.delete_backup_branch(backup_branch)
            return True
        except Exception:
            return False

    def restore_original_branch_in_repo(
        self,
        original_branch: str,
        repo_path: Optional[Path] = None,
        session_id: Optional[str] = None,
    ) -> Optional[str]:
        """Restore original branch from a backup in the given repo.

        If session_id is provided, uses that exact backup name. Otherwise picks the latest backup.

        Returns the backup branch name used on success, or None if no suitable backup found.
        """
        repo = self._repo_for_path_or_root(repo_path)
        if not repo.backup_manager:
            return None
        backup_name: Optional[str] = None
        if session_id:
            candidate = f"{BACKUP_PREFIX}/{original_branch}/{session_id}"
            backups = repo.backup_manager.list_backup_branches()
            if candidate in backups:
                backup_name = candidate
        else:
            backup_name = repo.backup_manager.get_latest_backup_for_original_branch(original_branch)

        if not backup_name:
            return None

        repo.backup_manager.restore_branch_from_backup(original_branch, backup_name)
        # Ensure the restored branch is checked out to leave the repo in a clean state
        try:
            repo.git_manager.checkout_branch(original_branch)
        except Exception as e:
            logger.warning(f"Checked out restored branch failed in {repo.name} ({repo.path}): {e}")
        return backup_name

    def restore_original_branches_across_hierarchy(
        self, original_branch: str, session_id: Optional[str] = None
    ) -> int:
        """Restore the original branch from backups across all repositories in the hierarchy.

        Returns number of repositories restored.
        """
        restored = 0
        # Restore bottom-up: lowest-level submodules first, then parents/root
        for repo_info in self.submodule_mapper.get_rebase_order(self.root_repo_info):
            used = self.restore_original_branch_in_repo(
                original_branch, repo_info.path, session_id=session_id
            )
            if used:
                restored += 1
        return restored

    def _execute_repository_rebase(self, state: RebaseState, operation: RebaseOperation) -> bool:
        """Execute rebase for a single repository."""
        logger.info(f"🔄 Rebasing {state.repo.name} ({state.repo.relative_path})")

        git_manager = state.repo.git_manager
        repo_tracker = self.global_tracker.get_tracker(state.repo.name)

        try:
            # Checkout source branch
            git_manager.checkout_branch(state.source_branch)

            # Start rebase
            success, conflict_files = git_manager.start_rebase(state.target_branch)

            if success:
                # Rebase completed without conflicts
                return self._handle_successful_rebase(state, repo_tracker)

            if conflict_files:
                # Handle conflicts
                return self._handle_rebase_conflicts(
                    state,
                    repo_tracker,
                )

            # Other error
            logger.error(f"Failed to start rebase for {state.repo.name}")
            return False

        except Exception as e:
            logger.error(f"Error during rebase of {state.repo.name}: {e}")
            return False

    def _handle_successful_rebase(self, state: RebaseState, repo_tracker: CommitTracker) -> bool:
        """Handle a rebase that completed without conflicts."""
        try:
            # Get updated commits
            new_commits = state.repo.git_manager.get_updated_commits(state.original_commits)

            # Map old commits to new commits
            commit_mappings = repo_tracker.map_commits(state.original_commits, new_commits)

            # Update state
            state.new_commits = new_commits
            state.commit_mapping = commit_mappings
            state.is_completed = True

            logger.info(f"✅ Successfully rebased {state.repo.name}")
            return True

        except Exception as e:
            logger.error(f"Error handling successful rebase: {e}")
            return False

    def _handle_rebase_conflicts(
        self,
        state: RebaseState,
        repo_tracker: CommitTracker,
    ) -> bool:
        """Handle rebase conflicts through resolution loop."""
        state.has_conflicts = True

        while True:
            # Analyze conflicts

            file_conflicts, submodule_conflicts = state.repo.conflict_resolver.analyze_conflicts()

            if not file_conflicts and not submodule_conflicts:
                # No more conflicts, try to continue
                success, new_conflicts = state.repo.git_manager.continue_rebase()

                if success:
                    return self._handle_successful_rebase(state, repo_tracker)

                if new_conflicts:
                    continue

                # Other error
                logger.error(f"Failed to continue rebase for {state.repo.name}")
                return False

            # Try to auto-resolve submodule conflicts
            resolved_submodules, unresolved_submodules = [], []
            if submodule_conflicts:
                # Map conflicted submodule paths to RepoInfo instances.
                # Conflicts are reported as filesystem paths; prefer exact path match and
                # fall back to direct child name matching. Filter out any Nones to avoid
                # NoneType errors in the resolver, but keep track of unmapped paths so
                # the user can resolve them manually.
                mapped_sub_repos = []
                unmapped_conflicts = []
                for conflict in submodule_conflicts:
                    try:
                        path_str = str(conflict)
                    except Exception:
                        path_str = f"{conflict}"

                    ri = self._get_repo_by_path_str(path_str)
                    if ri is None:
                        # Fallback: try name match against direct child submodule
                        try:
                            name = Path(path_str).name
                        except Exception:
                            name = path_str
                        ri = state.repo.get_submodule(name)

                    if ri is not None:
                        mapped_sub_repos.append(ri)
                    else:
                        unmapped_conflicts.append(path_str)

                resolved_submodules, unresolved_submodules = (
                    state.repo.conflict_resolver.auto_resolve_submodule_conflicts(mapped_sub_repos)
                )

                # Ensure unmapped paths are surfaced for manual resolution
                if unmapped_conflicts:
                    unresolved_submodules.extend(unmapped_conflicts)
                    logger.warning(
                        "Encountered %d submodule conflict(s) that could not be mapped to known submodules; "
                        "left for manual resolution: %s",
                        len(unmapped_conflicts),
                        unmapped_conflicts,
                    )

                logger.debug(
                    f"Auto-resolved {len(resolved_submodules)} submodules and "
                    f"{len(unresolved_submodules)} unresolved submodules"
                )

            # Check if we still have unresolved conflicts
            remaining_conflicts = file_conflicts + unresolved_submodules

            if remaining_conflicts:
                # Prompt user for manual resolution
                if not state.repo.conflict_resolver.prompt_user_for_conflict_resolution(
                    state.repo, file_conflicts, unresolved_submodules
                ):
                    # User chose to abort
                    logger.info("User aborted rebase operation")
                    return False

            # Continue the loop to check for more conflicts

    def _cleanup_failed_rebase(self, operation: RebaseOperation) -> None:
        """Clean up after a failed rebase operation."""
        logger.info("Cleaning up failed rebase operation")

        for state in operation.repo_states:
            try:
                if state.repo.git_manager.is_rebase_in_progress():
                    state.repo.git_manager.abort_rebase()
                    logger.info(f"Aborted rebase for {state.repo.name}")
            except Exception as e:
                logger.error(f"Error cleaning up {state.repo.name}: {e}")

    def get_repository_status(self) -> Dict[str, Dict[str, str]]:
        """Get status information for all repositories."""
        status = {}

        all_repos = self._get_all_repositories(self.root_repo_info)

        for repo_info in all_repos:
            try:
                git_manager = repo_info.git_manager
                current_branch = git_manager.get_current_branch()
                is_rebasing = git_manager.is_rebase_in_progress()

                status[repo_info.name] = {
                    "path": str(repo_info.relative_path),
                    "current_branch": current_branch,
                    "is_rebasing": str(is_rebasing),
                    "is_submodule": str(repo_info.is_submodule),
                    "depth": str(repo_info.depth),
                }
            except Exception as e:
                status[repo_info.name] = {"path": str(repo_info.relative_path), "error": str(e)}

        return status

    def _get_all_repositories(self, root_info: RepoInfo) -> List[RepoInfo]:
        """Get a flat list of all repositories."""
        all_repos = [root_info]
        for submodule in root_info.submodules:
            all_repos.extend(self._get_all_repositories(submodule))
        return all_repos

    def _repo_for_path_or_root(self, repo_path: Optional[Path]) -> RepoInfo:
        """Resolve a RepoInfo for the given path, or return root if None.

        Raises RebaseError if no matching repository is found.
        """
        if repo_path is None:
            return self.root_repo_info
        target = Path(repo_path).resolve()
        for ri in self._get_all_repositories(self.root_repo_info):
            if ri.path == target:
                return ri
        raise RebaseError(f"Repository not found for path: {target}")

    def _get_repo_by_path_str(self, path_str: str) -> Optional[RepoInfo]:
        """Best-effort lookup of RepoInfo by a stringified path."""
        try:
            target = Path(path_str).resolve()
        except Exception:
            return None
        for ri in self._get_all_repositories(self.root_repo_info):
            if ri.path == target:
                return ri
        return None

    def get_repo_heirarchy(self) -> List[str]:
        """Return the discovered repository hierarchy as lines for CLI display."""
        return self.submodule_mapper.get_hierarchy_lines(self.root_repo_info)

    def get_hierarchy_entries(self) -> List[HierarchyEntry]:
        """Return structured hierarchy entries for UI formatting."""
        return self.submodule_mapper.get_hierarchy_entries(self.root_repo_info)

    def get_root_repo(self) -> RepoInfo:
        return self.root_repo_info

    def collect_resolution_summary(self) -> Dict[str, ResolutionSummary]:
        all_repos = self._get_all_repositories(self.root_repo_info)
        summaries = {}
        for repo in all_repos:
            summaries[repo.name] = repo.conflict_resolver.get_resolution_summary()
        return summaries

    def validate_repository_state(self, prompt: UserPrompt = None) -> List[str]:
        """
        Validate that all repositories are in a clean state for rebase.

        Args:
            prompt: Optional prompt interface for user interactions

        Returns:
            List of validation errors (empty if all good)
        """
        if prompt is None:
            prompt = NoOpPrompt()

        errors = []
        all_repos = self._get_all_repositories(self.root_repo_info)

        for repo_info in all_repos:
            try:
                git_manager = repo_info.git_manager

                # Check for ongoing rebase
                if git_manager.is_rebase_in_progress():
                    errors.append(f"{repo_info.name}: Rebase already in progress")

                # Check for unstaged changes
                if repo_info.conflict_resolver.has_unstaged_changes(repo_info.path):
                    errors.append(f"{repo_info.name}: Has unstaged changes")

            except Exception as e:
                errors.append(f"{repo_info.name}: Error validating state - {e}")

        return errors
