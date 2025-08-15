"""
Tests for the CLI interface.
"""

from unittest.mock import Mock, patch
from click.testing import CliRunner

from lockstep_rebase.cli import cli
from lockstep_rebase.models import RebaseError


class TestCLI:
    """Test CLI commands."""
    
    def setup_method(self):
        """Setup test environment."""
        self.runner = CliRunner()
    
    def test_cli_help(self):
        """Test CLI help command."""
        result = self.runner.invoke(cli, ['--help'])
        assert result.exit_code == 0
        assert 'Git Submodule Rebase Tool' in result.output
    
    def test_cli_version_option(self):
        """Test that CLI accepts version-related options."""
        result = self.runner.invoke(cli, ['--verbose', '--help'])
        assert result.exit_code == 0
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_status_command(self, mock_orchestrator_class):
        """Test status command."""
        # Mock orchestrator
        mock_orchestrator = Mock()
        mock_orchestrator.get_repository_status.return_value = {
            'root': {
                'path': '.',
                'current_branch': 'main',
                'is_rebasing': 'False',
                'is_submodule': 'False',
                'depth': '0'
            }
        }
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['status'])
        assert result.exit_code == 0
        assert 'Repository Status' in result.output
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_hierarchy_command(self, mock_orchestrator_class):
        """Test hierarchy command."""
        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['hierarchy'])
        assert result.exit_code == 0
        mock_orchestrator.print_repository_hierarchy.assert_called_once()
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_validate_command_success(self, mock_orchestrator_class):
        """Test validate command with successful validation."""
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = []
        mock_operation = Mock()
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['validate', 'feature/test', 'main'])
        assert result.exit_code == 0
        assert 'All validations passed' in result.output
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_validate_command_failure(self, mock_orchestrator_class):
        """Test validate command with validation failures."""
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = ['Test error']
        mock_orchestrator.plan_rebase.side_effect = RebaseError("Branch missing")
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['validate', 'feature/test', 'main'])
        assert result.exit_code == 1
        assert 'Repository State Issues' in result.output
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_rebase_dry_run(self, mock_orchestrator_class):
        """Test rebase command with dry run."""
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = []
        mock_operation = Mock()
        mock_operation.repo_states = []
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['rebase', 'feature/test', 'main', '--dry-run'])
        assert result.exit_code == 0
        assert 'Dry Run Complete' in result.output
        mock_orchestrator.execute_rebase.assert_not_called()
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    @patch('click.confirm')
    def test_rebase_command_success(self, mock_confirm, mock_orchestrator_class):
        """Test successful rebase command."""
        mock_confirm.return_value = True
        
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = []
        mock_operation = Mock()
        mock_operation.repo_states = []
        mock_operation.global_commit_mapping = {}
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator.execute_rebase.return_value = True
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['rebase', 'feature/test', 'main'])
        assert result.exit_code == 0
        assert 'Rebase completed successfully' in result.output
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    @patch('click.confirm')
    def test_rebase_command_cancelled(self, mock_confirm, mock_orchestrator_class):
        """Test cancelled rebase command."""
        mock_confirm.return_value = False
        
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = []
        mock_operation = Mock()
        mock_operation.repo_states = []
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['rebase', 'feature/test', 'main'])
        assert result.exit_code == 0
        assert 'Operation cancelled' in result.output
        mock_orchestrator.execute_rebase.assert_not_called()
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_rebase_command_with_validation_errors_force(self, mock_orchestrator_class):
        """Test rebase command with validation errors and force flag."""
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = ['Test warning']
        mock_operation = Mock()
        mock_operation.repo_states = []
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator_class.return_value = mock_orchestrator
        
        result = self.runner.invoke(cli, ['rebase', 'feature/test', 'main', '--force', '--dry-run'])
        assert result.exit_code == 0
        assert 'Validation Warnings' in result.output
    
    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_rebase_command_error_handling(self, mock_orchestrator_class):
        """Test rebase command error handling."""
        mock_orchestrator_class.side_effect = RebaseError("Test error")
        
        result = self.runner.invoke(cli, ['rebase', 'feature/test', 'main'])
        assert result.exit_code == 1
        assert 'Rebase Error' in result.output
    
    def test_invalid_command(self):
        """Test invalid command handling."""
        result = self.runner.invoke(cli, ['invalid-command'])
        assert result.exit_code != 0

    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_rebase_with_include_exclude_forwarded(self, mock_orchestrator_class):
        """Ensure include/exclude are parsed and sent to plan_rebase."""
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = []
        mock_operation = Mock()
        mock_operation.repo_states = []
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator_class.return_value = mock_orchestrator

        result = self.runner.invoke(
            cli,
            ['rebase', 'src', 'tgt', '--dry-run', '--include', 'libA', '--exclude', 'libB']
        )
        assert result.exit_code == 0

        # Check call kwargs
        assert mock_orchestrator.plan_rebase.called
        _, kwargs = mock_orchestrator.plan_rebase.call_args
        assert kwargs.get('include') == {'libA'}
        assert kwargs.get('exclude') == {'libB'}
        # branch_map omitted -> None
        assert kwargs.get('branch_map') is None

    @patch('lockstep_rebase.cli.RebaseOrchestrator')
    def test_rebase_with_branch_map_forwarded(self, mock_orchestrator_class):
        """Ensure branch_map items are parsed and sent to plan_rebase."""
        mock_orchestrator = Mock()
        mock_orchestrator.validate_repository_state.return_value = []
        mock_operation = Mock()
        mock_operation.repo_states = []
        mock_orchestrator.plan_rebase.return_value = mock_operation
        mock_orchestrator_class.return_value = mock_orchestrator

        result = self.runner.invoke(
            cli,
            [
                'rebase', 'src', 'tgt', '--dry-run',
                '--branch-map', 'libA=feat/x:main',
                '--branch-map', 'libs/libB=feat/y'
            ]
        )
        assert result.exit_code == 0

        _, kwargs = mock_orchestrator.plan_rebase.call_args
        expected = {
            'libA': ('feat/x', 'main'),
            'libs/libB': ('feat/y', None),
        }
        assert kwargs.get('branch_map') == expected
