"""Tests for CLI functionality."""

import logging
import sys
from pathlib import Path
from unittest import mock

import pytest

from g2g_scim_sync import cli
from g2g_scim_sync.config import Config


class TestParseArgs:
    """Tests for command line argument parsing."""

    def test_required_config_argument(self) -> None:
        """Test that config argument is required."""
        with pytest.raises(SystemExit):
            cli.parse_args()

    def test_basic_config_argument(self) -> None:
        """Test parsing basic config argument."""
        args = cli.parse_args(['--config', 'config.toml'])
        assert args.config == Path('config.toml')
        assert args.dry_run is False
        assert args.delete_suspended is False
        assert args.organizational_units is None
        assert args.verbose is False

    def test_all_arguments(self) -> None:
        """Test parsing all command line arguments."""
        args = cli.parse_args(
            [
                '--config',
                'config.toml',
                '--dry-run',
                '--delete-suspended',
                '--organizational-units',
                '/Engineering,/Sales',
                '--verbose',
            ]
        )

        assert args.config == Path('config.toml')
        assert args.dry_run is True
        assert args.delete_suspended is True
        assert args.organizational_units == '/Engineering,/Sales'
        assert args.verbose is True

    def test_short_verbose_flag(self) -> None:
        """Test short verbose flag."""
        args = cli.parse_args(['--config', 'config.toml', '-v'])
        assert args.verbose is True


class TestSetupLogging:
    """Tests for logging configuration."""

    def test_console_logging_only(self, tmp_path: Path) -> None:
        """Test logging setup with console only."""
        service_file = tmp_path / 'service.json'
        service_file.write_text('{}')

        config = Config.from_dict(
            {
                'google': {
                    'service_account_file': str(service_file),
                    'domain': 'test.com',
                    'organizational_units': ['/Engineering'],
                    'subject_email': 'admin@test.com',
                },
                'github': {
                    'hostname': 'github.test.com',
                    'scim_token': 'token',
                    'enterprise_account': 'test',
                },
                'logging': {'level': 'DEBUG'},
            }
        )

        # Clear any existing handlers
        logger = logging.getLogger()
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        cli.setup_logging(config)

        assert logger.level == logging.DEBUG
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_file_and_console_logging(self, tmp_path: Path) -> None:
        """Test logging setup with both file and console."""
        service_file = tmp_path / 'service.json'
        service_file.write_text('{}')
        log_file = tmp_path / 'test.log'

        config = Config.from_dict(
            {
                'google': {
                    'service_account_file': str(service_file),
                    'domain': 'test.com',
                    'organizational_units': ['/Engineering'],
                    'subject_email': 'admin@test.com',
                },
                'github': {
                    'hostname': 'github.test.com',
                    'scim_token': 'token',
                    'enterprise_account': 'test',
                },
                'logging': {'level': 'INFO', 'file': str(log_file)},
            }
        )

        # Clear any existing handlers
        logger = logging.getLogger()
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        cli.setup_logging(config)

        assert logger.level == logging.INFO
        assert len(logger.handlers) == 2

        # Check handler types
        handler_types = [type(handler) for handler in logger.handlers]
        assert logging.StreamHandler in handler_types
        assert logging.FileHandler in handler_types


class TestMain:
    """Tests for main CLI function."""

    def create_test_config_file(self, tmp_path: Path) -> Path:
        """Create a test configuration file."""
        service_file = tmp_path / 'service.json'
        service_file.write_text('{}')

        config_file = tmp_path / 'config.toml'
        config_content = f"""
[google]
service_account_file = "{service_file}"
domain = "test.com"
organizational_units = ["/Engineering"]
subject_email = "admin@test.com"

[github]
hostname = "github.test.com"
scim_token = "token"
enterprise_account = "test"
"""
        config_file.write_text(config_content)
        return config_file

    @mock.patch('sys.argv')
    @mock.patch('g2g_scim_sync.cli.setup_logging')
    def test_main_success(
        self,
        mock_setup_logging: mock.Mock,
        mock_argv: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful main execution."""
        config_file = self.create_test_config_file(tmp_path)
        mock_argv.__getitem__ = mock.Mock(
            side_effect=lambda x: [
                'g2g-scim-sync',
                '--config',
                str(config_file),
            ][x]
        )
        mock_argv.__len__ = mock.Mock(return_value=3)

        with (
            mock.patch('sys.exit') as mock_exit,
            mock.patch('g2g_scim_sync.cli.run_sync') as mock_run_sync,
        ):
            cli.main()
            mock_exit.assert_called_once_with(0)
            mock_setup_logging.assert_called_once()
            mock_run_sync.assert_called_once()

    @mock.patch('g2g_scim_sync.cli.parse_args')
    def test_main_keyboard_interrupt(self, mock_parse_args: mock.Mock) -> None:
        """Test main handles KeyboardInterrupt."""
        mock_parse_args.side_effect = KeyboardInterrupt()

        with (
            mock.patch('sys.exit', side_effect=SystemExit) as mock_exit,
            mock.patch('builtins.print') as mock_print,
        ):
            with pytest.raises(SystemExit):
                cli.main()
            mock_exit.assert_called_with(130)
            mock_print.assert_called_once_with(
                'Interrupted by user', file=sys.stderr
            )

    @mock.patch('g2g_scim_sync.cli.parse_args')
    def test_main_config_not_found(self, mock_parse_args: mock.Mock) -> None:
        """Test main handles missing config file."""
        # Mock parse_args to return args with nonexistent config file
        mock_args = mock.Mock()
        mock_args.config = Path('/nonexistent/config.toml')
        mock_parse_args.return_value = mock_args

        with (
            mock.patch('sys.exit', side_effect=SystemExit) as mock_exit,
            mock.patch('builtins.print') as mock_print,
        ):
            with pytest.raises(SystemExit):
                cli.main()
            mock_exit.assert_called_with(1)

            # Check error message contains file not found
            call_args = mock_print.call_args[0]
            assert 'Configuration file not found' in call_args[0]

    @mock.patch('g2g_scim_sync.cli.parse_args')
    @mock.patch('g2g_scim_sync.cli.setup_logging')
    def test_main_with_cli_overrides(
        self,
        mock_setup_logging: mock.Mock,
        mock_parse_args: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test main with CLI argument overrides."""
        config_file = self.create_test_config_file(tmp_path)

        # Mock parse_args to return args with overrides
        mock_args = mock.Mock()
        mock_args.config = config_file
        mock_args.verbose = True
        mock_args.delete_suspended = True
        mock_args.organizational_units = '/Sales,/Marketing'
        mock_args.individual_users = None
        mock_args.dry_run = False
        mock_parse_args.return_value = mock_args

        with mock.patch('sys.exit') as mock_exit:
            cli.main()
            mock_exit.assert_called_with(0)

            # Verify setup_logging was called with modified config
            config_arg = mock_setup_logging.call_args[0][0]
            assert config_arg.logging.level == 'DEBUG'  # verbose override
            assert config_arg.sync.delete_suspended is True  # CLI override
            assert config_arg.google.organizational_units == [
                '/Sales',
                '/Marketing',
            ]  # CLI override
