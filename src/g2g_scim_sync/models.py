"""Data models for g2g-scim-sync."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class GoogleUser(BaseModel):
    """Google Workspace user model from Admin SDK."""

    id: str = Field(..., description='Google user ID')
    primary_email: EmailStr = Field(..., description='Primary email address')
    given_name: str = Field(..., description='First name')
    family_name: str = Field(..., description='Last name')
    full_name: str = Field(..., description='Full display name')
    suspended: bool = Field(
        default=False, description='User suspension status'
    )
    org_unit_path: str = Field(..., description='Organizational unit path')
    last_login_time: Optional[datetime] = Field(
        default=None, description='Last login timestamp'
    )
    creation_time: Optional[datetime] = Field(
        default=None, description='Account creation timestamp'
    )


class GoogleGroup(BaseModel):
    """Google Workspace group model from Admin SDK."""

    id: str = Field(..., description='Google group ID')
    name: str = Field(..., description='Group name')
    email: EmailStr = Field(..., description='Group email address')
    description: Optional[str] = Field(
        default=None, description='Group description'
    )
    direct_members_count: int = Field(
        default=0, description='Direct member count'
    )
    member_emails: list[EmailStr] = Field(
        default_factory=list, description='Member email addresses'
    )


class ScimUser(BaseModel):
    """SCIM user model for GitHub Enterprise."""

    id: Optional[str] = Field(default=None, description='SCIM user ID')
    user_name: str = Field(..., description='Username')
    emails: list[dict] = Field(..., description='Email addresses')
    name: dict = Field(..., description='Name components')
    active: bool = Field(default=True, description='Active status')
    external_id: Optional[str] = Field(
        default=None, description='External identity reference'
    )

    @classmethod
    def from_google_user(
        cls: type[ScimUser], google_user: GoogleUser
    ) -> ScimUser:
        """Create SCIM user from Google user."""
        return cls(
            user_name=google_user.primary_email.split('@')[0],
            emails=[
                {
                    'value': str(google_user.primary_email),
                    'primary': True,
                    'type': 'work',
                }
            ],
            name={
                'givenName': google_user.given_name,
                'familyName': google_user.family_name,
                'formatted': google_user.full_name,
            },
            active=not google_user.suspended,
            external_id=google_user.id,
        )


class GitHubTeam(BaseModel):
    """GitHub team model."""

    id: Optional[int] = Field(default=None, description='GitHub team ID')
    name: str = Field(..., description='Team name')
    slug: str = Field(..., description='Team slug')
    description: Optional[str] = Field(
        default=None, description='Team description'
    )
    privacy: str = Field(default='closed', description='Team privacy level')
    members: list[str] = Field(
        default_factory=list, description='Team member usernames'
    )

    @classmethod
    def from_google_group(
        cls: type[GitHubTeam], google_group: GoogleGroup
    ) -> GitHubTeam:
        """Create GitHub team from Google group."""
        # Convert group name to valid team slug
        slug = google_group.name.lower().replace(' ', '-').replace('_', '-')

        return cls(
            name=google_group.name,
            slug=slug,
            description=google_group.description,
            members=[],  # Will be populated during sync
        )


class SyncOperation(BaseModel):
    """Represents a sync operation to be performed."""

    operation_type: str = Field(..., description='Type of operation')
    resource_type: str = Field(..., description='Resource type (user/team)')
    resource_id: str = Field(..., description='Resource identifier')
    details: dict = Field(
        default_factory=dict, description='Operation details'
    )
    dry_run: bool = Field(default=False, description='Dry run mode')

    def __str__(self: SyncOperation) -> str:
        """String representation of sync operation."""
        return (
            f'{self.operation_type} {self.resource_type}: {self.resource_id}'
        )


class SyncResult(BaseModel):
    """Result of a sync operation."""

    operation: SyncOperation = Field(
        ..., description='The operation performed'
    )
    success: bool = Field(..., description='Success status')
    error: Optional[str] = Field(
        default=None, description='Error message if failed'
    )
    timestamp: datetime = Field(
        default_factory=datetime.now, description='Operation timestamp'
    )


class SyncSummary(BaseModel):
    """Summary of a complete sync run."""

    total_operations: int = Field(
        ..., description='Total operations attempted'
    )
    successful_operations: int = Field(
        ..., description='Successful operations'
    )
    failed_operations: int = Field(..., description='Failed operations')
    users_processed: int = Field(..., description='Users processed')
    teams_processed: int = Field(..., description='Teams processed')
    dry_run: bool = Field(..., description='Was this a dry run')
    start_time: datetime = Field(..., description='Sync start time')
    end_time: datetime = Field(..., description='Sync end time')
    duration_seconds: float = Field(
        ..., description='Total duration in seconds'
    )

    @property
    def success_rate(self: SyncSummary) -> float:
        """Calculate success rate percentage."""
        if self.total_operations == 0:
            return 100.0
        return (self.successful_operations / self.total_operations) * 100.0
