"""Tests for data models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from g2g_scim_sync.models import (
    GitHubGroup,
    GoogleOU,
    GoogleUser,
    ScimUser,
    SyncOperation,
    SyncResult,
    SyncStats,
    SyncSummary,
)


class TestGoogleUser:
    """Tests for GoogleUser model."""

    def test_create_google_user(self) -> None:
        """Test creating a Google user."""
        user = GoogleUser(
            id='123456789',
            primary_email='john.doe@company.com',
            given_name='John',
            family_name='Doe',
            full_name='John Doe',
            suspended=False,
            org_unit_path='/Engineering',
        )

        assert user.id == '123456789'
        assert user.primary_email == 'john.doe@company.com'
        assert user.given_name == 'John'
        assert user.family_name == 'Doe'
        assert user.full_name == 'John Doe'
        assert user.suspended is False
        assert user.org_unit_path == '/Engineering'
        assert user.last_login_time is None
        assert user.creation_time is None

    def test_google_user_with_timestamps(self) -> None:
        """Test Google user with timestamps."""
        now = datetime.now(timezone.utc)
        user = GoogleUser(
            id='123456789',
            primary_email='john.doe@company.com',
            given_name='John',
            family_name='Doe',
            full_name='John Doe',
            org_unit_path='/Engineering',
            last_login_time=now,
            creation_time=now,
        )

        assert user.last_login_time == now
        assert user.creation_time == now

    def test_google_user_suspended(self) -> None:
        """Test suspended Google user."""
        user = GoogleUser(
            id='123456789',
            primary_email='john.doe@company.com',
            given_name='John',
            family_name='Doe',
            full_name='John Doe',
            org_unit_path='/Engineering',
            suspended=True,
        )

        assert user.suspended is True

    def test_google_user_invalid_email(self) -> None:
        """Test Google user with invalid email."""
        with pytest.raises(
            ValidationError, match='value is not a valid email address'
        ):
            GoogleUser(
                id='123456789',
                primary_email='invalid-email',
                given_name='John',
                family_name='Doe',
                full_name='John Doe',
                org_unit_path='/Engineering',
            )


class TestGoogleOU:
    """Tests for GoogleOU model."""

    def test_create_google_ou(self) -> None:
        """Test creating a Google OU."""
        ou = GoogleOU(
            org_unit_path='/Engineering',
            name='Engineering',
            description='Engineering department',
            parent_org_unit_path='/',
            user_count=5,
            user_emails=['john@company.com', 'jane@company.com'],
        )

        assert ou.org_unit_path == '/Engineering'
        assert ou.name == 'Engineering'
        assert ou.description == 'Engineering department'
        assert ou.parent_org_unit_path == '/'
        assert ou.user_count == 5
        assert len(ou.user_emails) == 2

    def test_google_ou_defaults(self) -> None:
        """Test Google OU with default values."""
        ou = GoogleOU(
            org_unit_path='/Engineering',
            name='Engineering',
        )

        assert ou.description is None
        assert ou.parent_org_unit_path is None
        assert ou.user_count == 0
        assert ou.user_emails == []

    def test_google_ou_invalid_user_email(self) -> None:
        """Test Google OU with invalid user email."""
        with pytest.raises(
            ValidationError, match='value is not a valid email address'
        ):
            GoogleOU(
                org_unit_path='/Engineering',
                name='Engineering',
                user_emails=['invalid-email'],
            )


class TestScimUser:
    """Tests for ScimUser model."""

    def test_create_scim_user(self) -> None:
        """Test creating a SCIM user."""
        user = ScimUser(
            user_name='john.doe',
            emails=[
                {
                    'value': 'john.doe@company.com',
                    'primary': True,
                    'type': 'work',
                }
            ],
            name={
                'givenName': 'John',
                'familyName': 'Doe',
                'formatted': 'John Doe',
            },
            active=True,
            external_id='google123',
        )

        assert user.user_name == 'john.doe'
        assert len(user.emails) == 1
        assert user.emails[0]['value'] == 'john.doe@company.com'
        assert user.emails[0]['primary'] is True
        assert user.name['givenName'] == 'John'
        assert user.active is True
        assert user.external_id == 'google123'

    def test_scim_user_from_google_user(self) -> None:
        """Test creating SCIM user from Google user."""
        google_user = GoogleUser(
            id='google123',
            primary_email='john.doe@company.com',
            given_name='John',
            family_name='Doe',
            full_name='John Doe',
            org_unit_path='/Engineering',
            suspended=False,
        )

        scim_user = ScimUser.from_google_user(google_user)

        assert scim_user.user_name == 'john.doe'
        assert len(scim_user.emails) == 1
        assert scim_user.emails[0]['value'] == 'john.doe@company.com'
        assert scim_user.emails[0]['primary'] is True
        assert scim_user.name['givenName'] == 'John'
        assert scim_user.name['familyName'] == 'Doe'
        assert scim_user.name['formatted'] == 'John Doe'
        assert scim_user.active is True
        assert scim_user.external_id == 'john.doe'

    def test_scim_user_from_suspended_google_user(self) -> None:
        """Test creating SCIM user from suspended Google user."""
        google_user = GoogleUser(
            id='google123',
            primary_email='john.doe@company.com',
            given_name='John',
            family_name='Doe',
            full_name='John Doe',
            org_unit_path='/Engineering',
            suspended=True,
        )

        scim_user = ScimUser.from_google_user(google_user)

        assert scim_user.active is False

    def test_scim_user_defaults(self) -> None:
        """Test SCIM user with default values."""
        user = ScimUser(
            user_name='john.doe',
            emails=[{'value': 'john@company.com', 'primary': True}],
            name={'givenName': 'John', 'familyName': 'Doe'},
        )

        assert user.id is None
        assert user.active is True
        assert user.external_id is None


class TestGitHubGroup:
    """Tests for GitHubGroup model."""

    def test_create_github_group(self) -> None:
        """Test creating a GitHub idP Group."""
        group = GitHubGroup(
            id='team-uuid-123',
            name='Engineering',
            slug='engineering',
            description='Engineering team',
            privacy='closed',
            members=['john', 'jane'],
        )

        assert group.id == 'team-uuid-123'
        assert group.name == 'Engineering'
        assert group.slug == 'engineering'
        assert group.description == 'Engineering team'
        assert group.privacy == 'closed'
        assert len(group.members) == 2

    def test_github_group_from_google_ou(self) -> None:
        """Test creating GitHub idP Group from Google OU."""
        google_ou = GoogleOU(
            org_unit_path='/Engineering Team',
            name='Engineering Team',
            description='Engineering team members',
        )

        group = GitHubGroup.from_google_ou(google_ou)

        assert group.name == 'Engineering Team'
        assert group.slug == 'engineering-team'
        assert group.description == 'Engineering team members'
        assert group.members == []
        assert group.privacy == 'closed'
        assert group.id is None

    def test_github_group_slug_generation(self) -> None:
        """Test GitHub idP Group slug generation from OU name."""
        google_ou = GoogleOU(
            org_unit_path='/Test_OU Name',
            name='Test_OU Name',
        )

        group = GitHubGroup.from_google_ou(google_ou)

        assert group.slug == 'test-ou-name'

    def test_github_group_defaults(self) -> None:
        """Test GitHub idP Group with default values."""
        group = GitHubGroup(name='Engineering', slug='engineering')

        assert group.id is None
        assert group.description is None
        assert group.privacy == 'closed'
        assert group.members == []


class TestSyncOperation:
    """Tests for SyncOperation model."""

    def test_create_sync_operation(self) -> None:
        """Test creating a sync operation."""
        operation = SyncOperation(
            operation_type='create',
            resource_type='user',
            resource_id='john.doe',
            details={'email': 'john.doe@company.com'},
            dry_run=True,
        )

        assert operation.operation_type == 'create'
        assert operation.resource_type == 'user'
        assert operation.resource_id == 'john.doe'
        assert operation.details['email'] == 'john.doe@company.com'
        assert operation.dry_run is True

    def test_sync_operation_str(self) -> None:
        """Test sync operation string representation."""
        operation = SyncOperation(
            operation_type='create',
            resource_type='user',
            resource_id='john.doe',
        )

        assert str(operation) == 'create user: john.doe'

    def test_sync_operation_defaults(self) -> None:
        """Test sync operation with default values."""
        operation = SyncOperation(
            operation_type='create',
            resource_type='user',
            resource_id='john.doe',
        )

        assert operation.details == {}
        assert operation.dry_run is False


class TestSyncResult:
    """Tests for SyncResult model."""

    def test_create_sync_result(self) -> None:
        """Test creating a sync result."""
        result = SyncResult(
            success=True,
            error=None,
        )

        assert result.success is True
        assert result.error is None
        assert isinstance(result.timestamp, datetime)
        assert isinstance(result.user_diffs, list)
        assert isinstance(result.group_diffs, list)
        assert isinstance(result.stats, SyncStats)

    def test_sync_result_with_error(self) -> None:
        """Test sync result with error."""
        result = SyncResult(
            success=False,
            error='User already exists',
        )

        assert result.success is False
        assert result.error == 'User already exists'
        assert isinstance(result.timestamp, datetime)


class TestSyncSummary:
    """Tests for SyncSummary model."""

    def test_create_sync_summary(self) -> None:
        """Test creating a sync summary."""
        start_time = datetime.now()
        end_time = datetime.now()

        summary = SyncSummary(
            total_operations=10,
            successful_operations=8,
            failed_operations=2,
            users_processed=5,
            groups_processed=2,
            dry_run=False,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=30.5,
        )

        assert summary.total_operations == 10
        assert summary.successful_operations == 8
        assert summary.failed_operations == 2
        assert summary.users_processed == 5
        assert summary.groups_processed == 2
        assert summary.dry_run is False
        assert summary.success_rate == 80.0

    def test_sync_summary_success_rate_zero_operations(self) -> None:
        """Test sync summary success rate with zero operations."""
        summary = SyncSummary(
            total_operations=0,
            successful_operations=0,
            failed_operations=0,
            users_processed=0,
            groups_processed=0,
            dry_run=True,
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_seconds=0.0,
        )

        assert summary.success_rate == 100.0

    def test_sync_summary_perfect_success_rate(self) -> None:
        """Test sync summary with 100% success rate."""
        summary = SyncSummary(
            total_operations=5,
            successful_operations=5,
            failed_operations=0,
            users_processed=3,
            groups_processed=2,
            dry_run=False,
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_seconds=15.0,
        )

        assert summary.success_rate == 100.0
