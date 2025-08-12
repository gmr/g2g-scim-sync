"""Configuration management for g2g-scim-bridge."""

import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


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

    enterprise_url: str = Field(..., description='GitHub Enterprise base URL')
    scim_token: str = Field(..., description='GitHub SCIM API token')
    organization: str = Field(..., description='GitHub organization name')

    @field_validator('enterprise_url')
    @classmethod
    def validate_enterprise_url(cls: type['GitHubConfig'], v: str) -> str:
        """Validate GitHub Enterprise URL format."""
        if not v.startswith(('http://', 'https://')):
            raise ValueError(
                'GitHub Enterprise URL must start with http:// or https://'
            )
        return v.rstrip('/')


class SyncConfig(BaseModel):
    """Synchronization behavior configuration."""

    delete_suspended: bool = Field(
        default=False,
        description='Delete suspended users instead of deactivating',
    )
    create_teams: bool = Field(
        default=True, description='Automatically create missing GitHub teams'
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
