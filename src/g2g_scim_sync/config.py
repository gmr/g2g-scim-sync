"""Configuration management for g2g-scim-bridge."""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class GoogleConfig(BaseModel):
    """Google Workspace configuration."""

    service_account_file: Path = Field(
        ..., description='Path to Google service account JSON file'
    )
    domain: str = Field(
        ..., description='Google Workspace domain (e.g., company.com)'
    )
    organizational_units: list[str] = Field(
        ...,
        description='List of Google Workspace OU paths to sync',
    )
    individual_users: list[str] = Field(
        default_factory=list,
        description='List of individual user emails to sync outside of OUs',
    )
    subject_email: str = Field(
        ...,
        description='Admin user email to impersonate for domain delegation',
    )

    @field_validator('service_account_file')
    @classmethod
    def validate_service_account_file(
        cls: type['GoogleConfig'], v: Path
    ) -> Path:
        """Validate that service account file exists."""
        if not v.exists():
            raise ValueError(f'Service account file not found: {v}')
        if not v.is_file():
            raise ValueError(f'Service account path is not a file: {v}')
        return v


class GitHubConfig(BaseModel):
    """GitHub Enterprise configuration."""

    hostname: str = Field(..., description='GitHub Enterprise hostname')
    scim_token: str = Field(..., description='GitHub SCIM API token')
    enterprise_account: str = Field(
        ..., description='GitHub enterprise account name'
    )
    enterprise_owners: list[str] = Field(
        default_factory=list,
        description='List of user emails who should be enterprise owners',
    )
    billing_managers: list[str] = Field(
        default_factory=list,
        description='List of user emails who should be billing managers',
    )
    guest_collaborators: list[str] = Field(
        default_factory=list,
        description='List of user emails who should be guest collaborators',
    )
    emu_username_suffix: str | None = Field(
        default=None,
        description='EMU suffix to append to usernames (e.g., "companyname")',
    )

    @field_validator('hostname')
    @classmethod
    def validate_hostname(cls: type['GitHubConfig'], v: str) -> str:
        """Validate GitHub hostname format."""
        # Remove protocol if provided
        if v.startswith(('http://', 'https://')):
            v = v.split('://', 1)[1]
        # Remove trailing slash
        return v.rstrip('/')


class SyncConfig(BaseModel):
    """Synchronization behavior configuration."""

    delete_suspended: bool = Field(
        default=False,
        description='Delete suspended users instead of deactivating',
    )
    create_groups: bool = Field(
        default=True,
        description='Automatically create missing GitHub idP Groups (teams)',
    )
    flatten_ous: bool = Field(
        default=True,
        description='Flatten nested Google OUs into GitHub teams',
    )


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = Field(
        default='INFO',
        description='Logging level (DEBUG, INFO, WARNING, ERROR)',
    )
    file: str | None = Field(
        default=None, description='Optional log file path'
    )

    @field_validator('level')
    @classmethod
    def validate_level(cls: type['LoggingConfig'], v: str) -> str:
        """Validate logging level."""
        valid_levels = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        level_upper = v.upper()
        if level_upper not in valid_levels:
            raise ValueError(
                f'Invalid logging level: {v}. Must be one of {valid_levels}'
            )
        return level_upper


class Config(BaseModel):
    """Main configuration model."""

    google: GoogleConfig
    github: GitHubConfig
    sync: SyncConfig = Field(default_factory=SyncConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @classmethod
    def from_file(cls: type['Config'], path: Path) -> 'Config':
        """Load configuration from TOML file."""
        if not path.exists():
            raise FileNotFoundError(f'Configuration file not found: {path}')

        with open(path, 'rb') as f:
            data = tomllib.load(f)

        return cls.model_validate(data)

    @classmethod
    def from_dict(cls: type['Config'], data: dict[str, Any]) -> 'Config':
        """Create configuration from dictionary."""
        return cls.model_validate(data)
