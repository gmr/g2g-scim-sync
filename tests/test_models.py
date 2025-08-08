"""Tests for data models."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from g2g_scim_sync.models import (
    GitHubTeam,
    GoogleGroup,
    GoogleUser,
    ScimUser,
    SyncOperation,
    SyncResult,
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


class TestGoogleGroup:
    """Tests for GoogleGroup model."""

    def test_create_google_group(self) -> None:
        """Test creating a Google group."""
        group = GoogleGroup(
            id='group123',
            name='Engineering',
            email='engineering@company.com',
            description='Engineering team',
            direct_members_count=5,
            member_emails=['john@company.com', 'jane@company.com'],
        )

        assert group.id == 'group123'
        assert group.name == 'Engineering'
        assert group.email == 'engineering@company.com'
        assert group.description == 'Engineering team'
        assert group.direct_members_count == 5
        assert len(group.member_emails) == 2

    def test_google_group_defaults(self) -> None:
        """Test Google group with default values."""
        group = GoogleGroup(
            id='group123',
            name='Engineering',
            email='engineering@company.com',
        )

        assert group.description is None
        assert group.direct_members_count == 0
        assert group.member_emails == []

    def test_google_group_invalid_email(self) -> None:
        """Test Google group with invalid email."""
        with pytest.raises(
            ValidationError, match='value is not a valid email address'
        ):
            GoogleGroup(
                id='group123',
                name='Engineering',
                email='invalid-email',
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
        assert scim_user.external_id == 'google123'

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


class TestGitHubTeam:
    """Tests for GitHubTeam model."""

    def test_create_github_team(self) -> None:
        """Test creating a GitHub team."""
        team = GitHubTeam(
            id=123,
            name='Engineering',
            slug='engineering',
            description='Engineering team',
            privacy='closed',
            members=['john', 'jane'],
        )

        assert team.id == 123
        assert team.name == 'Engineering'
        assert team.slug == 'engineering'
        assert team.description == 'Engineering team'
        assert team.privacy == 'closed'
        assert len(team.members) == 2

    def test_github_team_from_google_group(self) -> None:
        """Test creating GitHub team from Google group."""
        google_group = GoogleGroup(
            id='group123',
            name='Engineering Team',
            email='engineering@company.com',
            description='Engineering team members',
        )

        team = GitHubTeam.from_google_group(google_group)

        assert team.name == 'Engineering Team'
        assert team.slug == 'engineering-team'
        assert team.description == 'Engineering team members'
        assert team.members == []
        assert team.privacy == 'closed'
        assert team.id is None

    def test_github_team_slug_generation(self) -> None:
        """Test GitHub team slug generation from group name."""
        google_group = GoogleGroup(
            id='group123',
            name='Test_Group Name',
            email='test@company.com',
        )

        team = GitHubTeam.from_google_group(google_group)

        assert team.slug == 'test-group-name'

    def test_github_team_defaults(self) -> None:
        """Test GitHub team with default values."""
        team = GitHubTeam(name='Engineering', slug='engineering')

        assert team.id is None
        assert team.description is None
        assert team.privacy == 'closed'
        assert team.members == []


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
        operation = SyncOperation(
            operation_type='create',
            resource_type='user',
            resource_id='john.doe',
        )

        result = SyncResult(
            operation=operation,
            success=True,
            error=None,
        )

        assert result.operation == operation
        assert result.success is True
        assert result.error is None
        assert isinstance(result.timestamp, datetime)

    def test_sync_result_with_error(self) -> None:
        """Test sync result with error."""
        operation = SyncOperation(
            operation_type='create',
            resource_type='user',
            resource_id='john.doe',
        )

        result = SyncResult(
            operation=operation,
            success=False,
            error='User already exists',
        )

        assert result.success is False
        assert result.error == 'User already exists'


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
            teams_processed=2,
            dry_run=False,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=30.5,
        )

        assert summary.total_operations == 10
        assert summary.successful_operations == 8
        assert summary.failed_operations == 2
        assert summary.users_processed == 5
        assert summary.teams_processed == 2
        assert summary.dry_run is False
        assert summary.success_rate == 80.0

    def test_sync_summary_success_rate_zero_operations(self) -> None:
        """Test sync summary success rate with zero operations."""
        summary = SyncSummary(
            total_operations=0,
            successful_operations=0,
            failed_operations=0,
            users_processed=0,
            teams_processed=0,
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
            teams_processed=2,
            dry_run=False,
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_seconds=15.0,
        )

        assert summary.success_rate == 100.0
