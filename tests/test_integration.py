"""
Integration tests for the Git submodule rebase tool.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from windsurf_project.rebase_orchestrator import RebaseOrchestrator
from windsurf_project.models import RepoInfo, CommitInfo, RebaseError


class TestRebaseOrchestratorIntegration:
    """Integration tests for RebaseOrchestrator."""
    
    @pytest.fixture
    def temp_repo_structure(self):
        """Create a temporary repository structure for testing."""
        temp_dir = Path(tempfile.mkdtemp())
        
        # Create directory structure
        root_repo = temp_dir / "root"
        submodule1 = root_repo / "submodule1"
        submodule2 = root_repo / "submodule2"
        nested_submodule = submodule1 / "nested"
        
        for path in [root_repo, submodule1, submodule2, nested_submodule]:
            path.mkdir(parents=True, exist_ok=True)
            (path / ".git").mkdir(exist_ok=True)
        
        yield {
            'temp_dir': temp_dir,
            'root_repo': root_repo,
            'submodule1': submodule1,
            'submodule2': submodule2,
            'nested_submodule': nested_submodule
        }
        
        # Cleanup
        shutil.rmtree(temp_dir, ignore_errors=True)
    
    @patch('windsurf_project.git_manager.Repo')
    def test_orchestrator_initialization(self, mock_repo_class, temp_repo_structure):
        """Test RebaseOrchestrator initialization."""
        root_path = temp_repo_structure['root_repo']
        
        # Mock the Git repository
        mock_repo = Mock()
        mock_repo.working_dir = str(root_path)
        mock_repo.submodules = []
        mock_repo_class.return_value = mock_repo
        
        orchestrator = RebaseOrchestrator(root_path)
        
        assert orchestrator.root_path == root_path
        assert orchestrator.root_repo_info.path == root_path
        assert orchestrator.root_repo_info.name == "root"
    
    @patch('windsurf_project.git_manager.Repo')
    @patch('windsurf_project.submodule_mapper.Repo')
    def test_plan_rebase_with_missing_branches(self, mock_mapper_repo, mock_git_repo, temp_repo_structure):
        """Test planning rebase with missing branches."""
        root_path = temp_repo_structure['root_repo']
        
        # Mock repositories
        mock_repo = Mock()
        mock_repo.working_dir = str(root_path)
        mock_repo.submodules = []
        mock_repo.heads = []
        mock_repo.remotes.origin.refs = []
        
        mock_git_repo.return_value = mock_repo
        mock_mapper_repo.return_value = mock_repo
        
        orchestrator = RebaseOrchestrator(root_path)
        
        # Test with missing source branch
        with pytest.raises(RebaseError) as exc_info:
            orchestrator.plan_rebase("nonexistent-feature", "main")
        
        assert "missing in" in str(exc_info.value).lower()
    
    @patch('windsurf_project.git_manager.Repo')
    @patch('windsurf_project.submodule_mapper.Repo')
    def test_plan_rebase_success(self, mock_mapper_repo, mock_git_repo, temp_repo_structure):
        """Test successful rebase planning."""
        root_path = temp_repo_structure['root_repo']
        
        # Mock repositories with branches
        mock_repo = Mock()
        mock_repo.working_dir = str(root_path)
        mock_repo.submodules = []
        
        # Mock branches
        mock_feature_branch = Mock()
        mock_feature_branch.name = "refs/heads/feature/test"
        mock_main_branch = Mock()
        mock_main_branch.name = "refs/heads/main"
        
        mock_repo.heads = [mock_feature_branch, mock_main_branch]
        mock_repo.remotes.origin.refs = [mock_feature_branch, mock_main_branch]
        
        # Mock commits
        mock_commit = Mock()
        mock_commit.hexsha = "abc123"
        mock_commit.message = "Test commit"
        mock_commit.author.name = "Test Author"
        mock_commit.author.email = "test@example.com"
        mock_commit.committed_datetime.isoformat.return_value = "2023-01-01T12:00:00"
        mock_commit.parents = []
        
        mock_repo.iter_commits.return_value = [mock_commit]
        
        mock_git_repo.return_value = mock_repo
        mock_mapper_repo.return_value = mock_repo
        
        orchestrator = RebaseOrchestrator(root_path)
        operation = orchestrator.plan_rebase("feature/test", "main")
        
        assert operation.source_branch == "feature/test"
        assert operation.target_branch == "main"
        assert len(operation.repo_states) == 1
        assert operation.repo_states[0].repo.name == "root"


class TestEndToEndWorkflow:
    """End-to-end workflow tests."""
    
    @pytest.fixture
    def mock_git_environment(self):
        """Mock a complete Git environment."""
        with patch('windsurf_project.git_manager.Repo') as mock_repo_class, \
             patch('windsurf_project.submodule_mapper.Repo') as mock_mapper_repo_class, \
             patch('subprocess.run') as mock_subprocess:
            
            # Setup mock repository
            mock_repo = Mock()
            mock_repo.working_dir = "/test/repo"
            mock_repo.git_dir = "/test/repo/.git"
            mock_repo.submodules = []
            
            # Mock branches
            mock_feature_branch = Mock()
            mock_feature_branch.name = "refs/heads/feature/test"
            mock_main_branch = Mock()
            mock_main_branch.name = "refs/heads/main"
            
            mock_repo.heads = [mock_feature_branch, mock_main_branch]
            mock_repo.remotes.origin.refs = [mock_feature_branch, mock_main_branch]
            mock_repo.active_branch.name = "feature/test"
            
            # Mock commits
            mock_commit = Mock()
            mock_commit.hexsha = "abc123def456"
            mock_commit.message = "Test commit message"
            mock_commit.author.name = "Test Author"
            mock_commit.author.email = "test@example.com"
            mock_commit.committed_datetime.isoformat.return_value = "2023-01-01T12:00:00"
            mock_commit.parents = []
            
            mock_repo.iter_commits.return_value = [mock_commit]
            
            mock_repo_class.return_value = mock_repo
            mock_mapper_repo_class.return_value = mock_repo
            
            # Mock successful subprocess calls
            mock_subprocess.return_value.returncode = 0
            mock_subprocess.return_value.stdout = ""
            mock_subprocess.return_value.stderr = ""
            
            yield {
                'mock_repo': mock_repo,
                'mock_subprocess': mock_subprocess
            }
    
    def test_successful_rebase_workflow(self, mock_git_environment):
        """Test a complete successful rebase workflow."""
        orchestrator = RebaseOrchestrator(Path("/test/repo"))
        
        # Plan the rebase
        operation = orchestrator.plan_rebase("feature/test", "main")
        assert operation is not None
        assert len(operation.repo_states) == 1
        
        # Execute the rebase
        success = orchestrator.execute_rebase(operation)
        assert success is True
    
    def test_rebase_with_conflicts_workflow(self, mock_git_environment):
        """Test rebase workflow with conflicts."""
        mock_subprocess = mock_git_environment['mock_subprocess']
        
        # Mock rebase failure with conflicts
        mock_subprocess.return_value.returncode = 1
        mock_subprocess.return_value.stdout = "conflict_file.txt"
        
        orchestrator = RebaseOrchestrator(Path("/test/repo"))
        
        # Plan the rebase
        operation = orchestrator.plan_rebase("feature/test", "main")
        
        # Mock user input for conflict resolution
        with patch('builtins.input', return_value='abort'):
            success = orchestrator.execute_rebase(operation)
            assert success is False


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_invalid_repository_path(self):
        """Test handling of invalid repository paths."""
        with pytest.raises(RebaseError):
            RebaseOrchestrator(Path("/nonexistent/path"))
    
    @patch('windsurf_project.git_manager.Repo')
    def test_git_command_failure(self, mock_repo_class):
        """Test handling of Git command failures."""
        mock_repo = Mock()
        mock_repo.working_dir = "/test/repo"
        mock_repo.submodules = []
        mock_repo_class.return_value = mock_repo
        
        # Mock Git command failure
        mock_repo.git.checkout.side_effect = Exception("Git command failed")
        
        orchestrator = RebaseOrchestrator(Path("/test/repo"))
        
        with pytest.raises(RebaseError):
            # This should fail when trying to checkout
            operation = orchestrator.plan_rebase("feature/test", "main")
            orchestrator.execute_rebase(operation)


class TestRepositoryValidation:
    """Test repository validation functionality."""
    
    @patch('windsurf_project.git_manager.Repo')
    @patch('windsurf_project.submodule_mapper.Repo')
    @patch('subprocess.run')
    def test_validate_clean_repository(self, mock_subprocess, mock_mapper_repo, mock_git_repo):
        """Test validation of clean repository state."""
        # Setup mocks
        mock_repo = Mock()
        mock_repo.working_dir = "/test/repo"
        mock_repo.git_dir = "/test/repo/.git"
        mock_repo.submodules = []
        
        mock_git_repo.return_value = mock_repo
        mock_mapper_repo.return_value = mock_repo
        
        # Mock clean repository (no rebase in progress, no unstaged changes)
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = ""
        
        orchestrator = RebaseOrchestrator(Path("/test/repo"))
        errors = orchestrator.validate_repository_state()
        
        assert len(errors) == 0
    
    @patch('windsurf_project.git_manager.Repo')
    @patch('windsurf_project.submodule_mapper.Repo')
    @patch('subprocess.run')
    def test_validate_dirty_repository(self, mock_subprocess, mock_mapper_repo, mock_git_repo):
        """Test validation of repository with unstaged changes."""
        # Setup mocks
        mock_repo = Mock()
        mock_repo.working_dir = "/test/repo"
        mock_repo.git_dir = "/test/repo/.git"
        mock_repo.submodules = []
        
        mock_git_repo.return_value = mock_repo
        mock_mapper_repo.return_value = mock_repo
        
        # Mock repository with unstaged changes
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "modified_file.txt"
        
        orchestrator = RebaseOrchestrator(Path("/test/repo"))
        errors = orchestrator.validate_repository_state()
        
        assert len(errors) > 0
        assert any("unstaged changes" in error.lower() for error in errors)
