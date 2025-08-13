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


class GoogleOU(BaseModel):
    """Google Workspace Organizational Unit model from Admin SDK."""

    org_unit_path: str = Field(..., description='Organizational unit path')
    name: str = Field(..., description='OU name (last component of path)')
    description: Optional[str] = Field(
        default=None, description='OU description'
    )
    parent_org_unit_path: Optional[str] = Field(
        default=None, description='Parent OU path'
    )
    user_count: int = Field(
        default=0, description='Number of users in this OU'
    )
    user_emails: list[EmailStr] = Field(
        default_factory=list, description='User email addresses in this OU'
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
    roles: list[dict] = Field(
        default_factory=lambda: [{'value': 'user', 'primary': True}],
        description='User roles in enterprise',
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
            external_id=google_user.primary_email.split('@')[0],
        )


class GitHubGroup(BaseModel):
    """GitHub idP Group (team) model."""

    id: Optional[str] = Field(default=None, description='GitHub idP Group ID')
    name: str = Field(..., description='idP Group name')
    slug: str = Field(..., description='idP Group slug')
    description: Optional[str] = Field(
        default=None, description='idP Group description'
    )
    privacy: str = Field(
        default='closed', description='idP Group privacy level'
    )
    members: list[str] = Field(
        default_factory=list, description='idP Group member usernames'
    )

    @classmethod
    def from_google_ou(
        cls: type[GitHubGroup], google_ou: GoogleOU
    ) -> GitHubGroup:
        """Create GitHub idP Group from Google OU."""
        # Convert OU name to valid group slug
        slug = google_ou.name.lower().replace(' ', '-').replace('_', '-')

        return cls(
            name=google_ou.name,
            slug=slug,
            description=google_ou.description,
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
    groups_processed: int = Field(..., description='idP Groups processed')
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


class SyncStats(BaseModel):
    """Statistics tracking for synchronization operations."""

    users_skipped: int = Field(
        default=0, description='Users skipped by filters'
    )
    users_to_create: int = Field(default=0, description='Users to be created')
    users_to_update: int = Field(default=0, description='Users to be updated')
    users_to_suspend: int = Field(
        default=0, description='Users to be suspended'
    )
    users_up_to_date: int = Field(
        default=0, description='Users already current'
    )
    users_created: int = Field(
        default=0, description='Users successfully created'
    )
    users_updated: int = Field(
        default=0, description='Users successfully updated'
    )
    users_suspended: int = Field(
        default=0, description='Users successfully suspended'
    )
    users_failed: int = Field(default=0, description='User operations failed')

    groups_to_create: int = Field(
        default=0, description='idP Groups to be created'
    )
    groups_to_update: int = Field(
        default=0, description='idP Groups to be updated'
    )
    groups_up_to_date: int = Field(
        default=0, description='idP Groups already current'
    )
    groups_created: int = Field(
        default=0, description='idP Groups successfully created'
    )
    groups_updated: int = Field(
        default=0, description='idP Groups successfully updated'
    )
    groups_failed: int = Field(
        default=0, description='idP Group operations failed'
    )

    def __str__(self: SyncStats) -> str:
        """String representation of sync statistics."""
        return (
            f'Users: {self.users_created} created, '
            f'{self.users_updated} updated, '
            f'{self.users_suspended} suspended, {self.users_failed} failed | '
            f'idP Groups: {self.groups_created} created, '
            f'{self.groups_updated} updated, {self.groups_failed} failed'
        )


class UserDiff(BaseModel):
    """Represents differences for a user sync operation."""

    action: str = Field(
        ..., description='Action to perform (create/update/suspend)'
    )
    google_user: Optional[GoogleUser] = Field(
        default=None, description='Source Google user'
    )
    existing_scim_user: Optional[ScimUser] = Field(
        default=None, description='Existing GitHub SCIM user'
    )
    target_scim_user: Optional[ScimUser] = Field(
        default=None, description='Target SCIM user state'
    )


class GroupDiff(BaseModel):
    """Represents differences for an idP Group sync operation."""

    action: str = Field(..., description='Action to perform (create/update)')
    google_ou: Optional[GoogleOU] = Field(
        default=None, description='Source Google OU'
    )
    existing_group: Optional[GitHubGroup] = Field(
        default=None, description='Existing GitHub idP Group'
    )
    target_group: Optional[GitHubGroup] = Field(
        default=None, description='Target idP Group state'
    )


class SyncResult(BaseModel):
    """Enhanced sync result with detailed diff information."""

    success: bool = Field(..., description='Overall success status')
    user_diffs: list[UserDiff] = Field(
        default_factory=list, description='User differences found'
    )
    group_diffs: list[GroupDiff] = Field(
        default_factory=list, description='idP Group differences found'
    )
    stats: SyncStats = Field(
        default_factory=SyncStats, description='Sync statistics'
    )
    error: Optional[str] = Field(
        default=None, description='Error message if failed'
    )
    dry_run: bool = Field(default=False, description='Was this a dry run')
    timestamp: datetime = Field(
        default_factory=datetime.now, description='Sync completion timestamp'
    )


class GitHubScimNotSupportedException(Exception):
    """Exception when GitHub Enterprise Server doesn't support SCIM Groups."""

    pass
