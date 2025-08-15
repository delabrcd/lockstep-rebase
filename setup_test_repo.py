import subprocess
from pathlib import Path

def run(cmd, cwd=None):
    print(f"[{cwd or '.'}]$ {cmd}")
    subprocess.check_call(cmd, shell=True, cwd=cwd)

def git_init(path, name):
    path.mkdir(parents=True, exist_ok=True)
    run("git init", cwd=path)
    (path / "README.md").write_text(f"# {name}\n")
    run("git add README.md", cwd=path)
    run(f'git commit -m "Initial commit in {name}"', cwd=path)

def git_commit_change(path, filename, message):
    file_path = path / filename
    with open(file_path, "a") as f:
        f.write(message + "\n")
    run(f"git add {filename}", cwd=path)
    run(f'git commit -m "{message}"', cwd=path)

def update_submodule_pointer(child_repo_path, parent_repo_path, submodule_relpath, message):
    """Update parent's submodule pointer to latest commit in child."""
    new_commit = subprocess.check_output(
        ["git", "-C", str(child_repo_path), "rev-parse", "HEAD"], text=True
    ).strip()
    submodule_abs_path = parent_repo_path / submodule_relpath
    run("git fetch", cwd=submodule_abs_path)
    run(f"git checkout {new_commit}", cwd=submodule_abs_path)
    run(f"git add {submodule_relpath}", cwd=parent_repo_path)
    run(f'git commit -m "{message}"', cwd=parent_repo_path)

def lockstep_commit(shared_repo, common_repo, main_repo, commit_num, branch_label):
    """Make one lockstep commit across all repos with proper retargeting."""
    # 1. Change in shared-header
    git_commit_change(shared_repo, "shared.txt", f"shared-header: {branch_label} change {commit_num}")
    update_submodule_pointer(shared_repo, common_repo, "shared-header", f"Update shared-header submodule ({branch_label} {commit_num})")

    # 2. Change in common-src
    git_commit_change(common_repo, "common.txt", f"common-src: {branch_label} change {commit_num}")
    update_submodule_pointer(common_repo, main_repo, "common-src", f"Update common-src submodule ({branch_label} {commit_num})")

    # 3. Change in main-repo
    git_commit_change(main_repo, "main.txt", f"main-repo: {branch_label} change {commit_num}")

# --- Setup base paths ---
base = Path("nested-git-playground").absolute()
if base.exists():
    run("rm -rf nested-git-playground", cwd=base.parent)

base.mkdir()

shared_header = base / "shared-header"
common_src = base / "common-src"
main_repo = base / "main-repo"

# --- Initialize repos and submodules ---
git_init(shared_header, "shared-header")
git_commit_change(shared_header, "shared.txt", "shared-header: initial data")

git_init(common_src, "common-src")
run(f"git submodule add ../shared-header shared-header", cwd=common_src)
run('git commit -m "Add shared-header submodule"', cwd=common_src)
git_commit_change(common_src, "common.txt", "common-src: initial data")

git_init(main_repo, "main-repo")
run(f"git submodule add ../common-src common-src", cwd=main_repo)
run('git commit -m "Add common-src submodule"', cwd=main_repo)
git_commit_change(main_repo, "main.txt", "main-repo: initial data")

# --- Create feature branches ---
for repo in [shared_header, common_src, main_repo]:
    run("git checkout -b feature/test", cwd=repo)

# --- Lockstep feature commits (at least 2) ---
for i in range(1, 3):  # Change range(1, N+1) for more commits
    lockstep_commit(shared_header, common_src, main_repo, i, "feature")

# --- Switch back to main/master ---
for repo in [shared_header, common_src, main_repo]:
    try:
        run("git checkout main", cwd=repo)
    except subprocess.CalledProcessError:
        run("git checkout master", cwd=repo)

# --- Divergent commits on main branch ---
for i in range(1, 3):
    lockstep_commit(shared_header, common_src, main_repo, i, "main branch")

print(f"\nPlayground created at {base}")
print("Repo structure:\n - main-repo\n   - common-src\n     - shared-header")
# --- Visual representation of the git trees ---
def print_git_tree(path, name):
    print(f"\n=== {name} ===")
    run("git log --oneline --graph --decorate --all --abbrev-commit", cwd=path)

print_git_tree(main_repo, "MAIN REPO")
print_git_tree(common_src, "COMMON-SRC SUBMODULE")
print_git_tree(shared_header, "SHARED-HEADER SUBMODULE")

# run git submodule update --init --recursive
run("git submodule update --init --recursive", cwd=main_repo)

