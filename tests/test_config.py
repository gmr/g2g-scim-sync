"""Tests for configuration management."""

from pathlib import Path
from typing import Any

import pytest

from g2g_scim_sync.config import (
    Config,
    GitHubConfig,
    GoogleConfig,
    LoggingConfig,
    SyncConfig,
)


class TestGoogleConfig:
    """Tests for GoogleConfig model."""

    def test_valid_config(self, tmp_path: Path) -> None:
        """Test valid Google configuration."""
        # Create temporary service account file
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{}')

        config = GoogleConfig(
            service_account_file=service_file,
            domain='company.com',
            organizational_units=['/Engineering', '/Sales'],
            subject_email='admin@company.com',
        )

        assert config.service_account_file == service_file
        assert config.domain == 'company.com'
        assert config.organizational_units == ['/Engineering', '/Sales']
        assert config.individual_users == []

    def test_config_with_individual_users(self, tmp_path: Path) -> None:
        """Test Google configuration with individual users."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{}')

        config = GoogleConfig(
            service_account_file=service_file,
            domain='company.com',
            organizational_units=['/Engineering'],
            individual_users=['john@company.com', 'jane@company.com'],
            subject_email='admin@company.com',
        )

        assert config.individual_users == [
            'john@company.com',
            'jane@company.com',
        ]

    def test_nonexistent_service_account_file(self) -> None:
        """Test validation error for nonexistent service account file."""
        with pytest.raises(ValueError, match='Service account file not found'):
            GoogleConfig(
                service_account_file=Path('/nonexistent/file.json'),
                domain='company.com',
                organizational_units=['/Engineering'],
                subject_email='admin@company.com',
            )

    def test_service_account_file_is_directory(self, tmp_path: Path) -> None:
        """Test validation error when service account path is directory."""
        directory = tmp_path / 'service-account'
        directory.mkdir()

        with pytest.raises(
            ValueError, match='Service account path is not a file'
        ):
            GoogleConfig(
                service_account_file=directory,
                domain='company.com',
                organizational_units=['/Engineering'],
                subject_email='admin@company.com',
            )


class TestGitHubConfig:
    """Tests for GitHubConfig model."""

    def test_valid_config(self) -> None:
        """Test valid GitHub configuration."""
        config = GitHubConfig(
            hostname='github.company.com',
            scim_token='ghes_token_here',  # noqa: S106
            enterprise_account='company-org',
        )

        assert config.hostname == 'github.company.com'
        assert config.scim_token == 'ghes_token_here'  # noqa: S105
        assert config.enterprise_account == 'company-org'

    def test_hostname_trailing_slash_removed(self) -> None:
        """Test that trailing slash is removed from hostname."""
        config = GitHubConfig(
            hostname='github.company.com/',
            scim_token='token',  # noqa: S106
            enterprise_account='org',
        )

        assert config.hostname == 'github.company.com'

    def test_hostname_protocol_stripping(self) -> None:
        """Test that protocol is stripped from hostname."""
        config = GitHubConfig(
            hostname='https://github.company.com',
            scim_token='token',  # noqa: S106
            enterprise_account='org',
        )
        assert config.hostname == 'github.company.com'

        config = GitHubConfig(
            hostname='http://github.company.com',
            scim_token='token',  # noqa: S106
            enterprise_account='org',
        )
        assert config.hostname == 'github.company.com'

    def test_config_with_emu_suffix(self) -> None:
        """Test GitHub configuration with EMU username suffix."""
        config = GitHubConfig(
            hostname='github.company.com',
            scim_token='ghes_token_here',  # noqa: S106
            enterprise_account='company-org',
            emu_username_suffix='companyname',
        )

        assert config.emu_username_suffix == 'companyname'

    def test_config_without_emu_suffix(self) -> None:
        """Test GitHub configuration without EMU username suffix (default)."""
        config = GitHubConfig(
            hostname='github.company.com',
            scim_token='ghes_token_here',  # noqa: S106
            enterprise_account='company-org',
        )

        assert config.emu_username_suffix is None


class TestSyncConfig:
    """Tests for SyncConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SyncConfig()

        assert config.delete_suspended is False
        assert config.create_groups is True
        assert config.flatten_ous is True

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = SyncConfig(
            delete_suspended=True, create_groups=False, flatten_ous=False
        )

        assert config.delete_suspended is True
        assert config.create_groups is False
        assert config.flatten_ous is False


class TestLoggingConfig:
    """Tests for LoggingConfig model."""

    def test_default_values(self) -> None:
        """Test default logging configuration."""
        config = LoggingConfig()

        assert config.level == 'INFO'
        assert config.file is None

    def test_custom_values(self) -> None:
        """Test custom logging configuration."""
        config = LoggingConfig(level='DEBUG', file='app.log')

        assert config.level == 'DEBUG'
        assert config.file == 'app.log'

    def test_level_case_insensitive(self) -> None:
        """Test that logging level is case-insensitive."""
        config = LoggingConfig(level='debug')
        assert config.level == 'DEBUG'

    def test_invalid_level(self) -> None:
        """Test validation error for invalid logging level."""
        with pytest.raises(ValueError, match='Invalid logging level'):
            LoggingConfig(level='INVALID')


class TestConfig:
    """Tests for main Config model."""

    def create_valid_config_dict(self, tmp_path: Path) -> dict[str, Any]:
        """Create a valid configuration dictionary."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{}')

        return {
            'google': {
                'service_account_file': str(service_file),
                'domain': 'company.com',
                'organizational_units': ['/Engineering', '/Sales'],
                'subject_email': 'admin@company.com',
            },
            'github': {
                'hostname': 'github.company.com',
                'scim_token': 'token',  # noqa: S106
                'enterprise_account': 'org',
            },
            'sync': {
                'delete_suspended': False,
                'create_groups': True,
                'flatten_ous': True,
            },
            'logging': {'level': 'INFO', 'file': 'app.log'},
        }

    def test_from_dict(self, tmp_path: Path) -> None:
        """Test creating config from dictionary."""
        config_dict = self.create_valid_config_dict(tmp_path)
        config = Config.from_dict(config_dict)

        assert config.google.domain == 'company.com'
        assert config.github.enterprise_account == 'org'
        assert config.sync.create_groups is True
        assert config.logging.level == 'INFO'

    def test_from_file(self, tmp_path: Path) -> None:
        """Test loading config from TOML file."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{}')

        # Create TOML config file
        config_file = tmp_path / 'config.toml'
        config_content = f"""
[google]
service_account_file = "{service_file}"
domain = "company.com"
organizational_units = ["/Engineering", "/Sales"]
subject_email = "admin@company.com"

[github]
hostname = "github.company.com"
scim_token = "token"
enterprise_account = "org"

[sync]
delete_suspended = false
create_groups = true
flatten_ous = true

[logging]
level = "INFO"
file = "app.log"
"""
        config_file.write_text(config_content)

        config = Config.from_file(config_file)

        assert config.google.domain == 'company.com'
        assert config.github.enterprise_account == 'org'
        assert config.sync.create_groups is True
        assert config.logging.level == 'INFO'

    def test_from_file_not_found(self) -> None:
        """Test error when config file doesn't exist."""
        with pytest.raises(
            FileNotFoundError, match='Configuration file not found'
        ):
            Config.from_file(Path('/nonexistent/config.toml'))

    def test_default_sections(self, tmp_path: Path) -> None:
        """Test that sync and logging sections use defaults when missing."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{}')

        minimal_config = {
            'google': {
                'service_account_file': str(service_file),
                'domain': 'company.com',
                'organizational_units': ['/Engineering'],
                'subject_email': 'admin@company.com',
            },
            'github': {
                'hostname': 'github.company.com',
                'scim_token': 'token',  # noqa: S106
                'enterprise_account': 'org',
            },
        }

        config = Config.from_dict(minimal_config)

        # Check defaults are applied
        assert config.sync.delete_suspended is False
        assert config.sync.create_groups is True
        assert config.sync.flatten_ous is True
        assert config.logging.level == 'INFO'
        assert config.logging.file is None
