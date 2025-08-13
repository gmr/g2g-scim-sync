"""Tests for the synchronization engine."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

from g2g_scim_sync.config import SyncConfig, GitHubConfig
from g2g_scim_sync.models import (
    GitHubTeam,
    GoogleOU,
    GoogleUser,
    ScimUser,
    SyncStats,
    UserDiff,
    TeamDiff,
)
from g2g_scim_sync.sync_engine import SyncEngine


class TestSyncEngine:
    """Tests for SyncEngine."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_google_client = mock.AsyncMock()
        self.mock_github_client = mock.AsyncMock()
        self.config = SyncConfig(
            delete_suspended=False,
            create_teams=True,
            flatten_ous=False,
        )
        self.github_config = GitHubConfig(
            enterprise_url='https://github.company.com',
            scim_token='token',  # noqa: S106
            organization='org',
            enterprise_owners=['owner@test.com'],
            billing_managers=['billing@test.com'],
            guest_collaborators=['guest@test.com'],
        )
        self.engine = SyncEngine(
            google_client=self.mock_google_client,
            github_client=self.mock_github_client,
            config=self.config,
            github_config=self.github_config,
        )

    def create_google_user(
        self, email: str, suspended: bool = False
    ) -> GoogleUser:
        """Create a test Google user."""
        name_parts = email.split('@')[0].split('.')
        given_name = name_parts[0].title()
        family_name = name_parts[1].title() if len(name_parts) > 1 else 'User'

        return GoogleUser(
            id=f'user_{email.replace("@", "_").replace(".", "_")}',
            primary_email=email,
            given_name=given_name,
            family_name=family_name,
            full_name=f'{given_name} {family_name}',
            suspended=suspended,
            org_unit_path='/Engineering',
            last_login_time=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
            creation_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

    def create_scim_user(self, username: str, active: bool = True) -> ScimUser:
        """Create a test SCIM user."""
        email = f'{username}@test.com'
        name_parts = username.split('.')
        given_name = name_parts[0].title()
        family_name = name_parts[1].title() if len(name_parts) > 1 else 'User'

        return ScimUser(
            id=f'scim_{username}',
            user_name=username.replace('.', '-'),
            emails=[{'value': email, 'primary': True}],
            name={
                'givenName': given_name,
                'familyName': family_name,
                'formatted': f'{given_name} {family_name}',
            },
            active=active,
            external_id=f'google_user_{username}',
        )

    def create_google_ou(self, name: str, path: str) -> GoogleOU:
        """Create a test Google OU."""
        return GoogleOU(
            org_unit_path=path,
            name=name,
            description=f'{name} organizational unit',
            user_count=2,
            user_emails=['john.doe@test.com', 'jane.smith@test.com'],
        )

    def create_github_team(self, name: str, slug: str) -> GitHubTeam:
        """Create a test GitHub team."""
        return GitHubTeam(
            id='team-uuid-123',
            name=name,
            slug=slug,
            description=f'{name} team',
            members=['john-doe', 'jane-smith'],
        )

    @pytest.mark.asyncio
    async def test_synchronize_success(self) -> None:
        """Test successful synchronization with OU-based sync."""
        # Setup mock data
        google_users = [
            self.create_google_user('john.doe@test.com'),
            self.create_google_user('jane.smith@test.com'),
        ]
        github_users = [self.create_scim_user('john.doe')]

        google_ous = [self.create_google_ou('Engineering', '/Engineering')]
        github_teams = []

        # Setup mock responses
        self.mock_google_client.get_all_users.return_value = google_users
        self.mock_github_client.get_users.return_value = github_users
        self.mock_google_client.get_ou.return_value = google_ous[0]
        self.mock_github_client.get_groups.return_value = github_teams

        # Mock GitHub operations
        created_user = self.create_scim_user('jane.smith')
        created_user.id = 'scim_jane_smith'
        self.mock_github_client.create_user.return_value = created_user

        created_team = self.create_github_team('Engineering', 'engineering')
        self.mock_github_client.create_group.return_value = created_team

        # Execute synchronization with OU paths
        result = await self.engine.synchronize(ou_paths=['/Engineering'])

        # Verify results
        assert result.success is True
        assert result.dry_run is False
        assert len(result.user_diffs) == 1  # One user to create
        assert len(result.team_diffs) == 1  # One team to create
        assert result.user_diffs[0].action == 'create'
        assert result.team_diffs[0].action == 'create'

        # Verify API calls
        self.mock_google_client.get_all_users.assert_called_once()
        self.mock_github_client.get_users.assert_called_once()
        self.mock_github_client.create_user.assert_called_once()
        self.mock_github_client.create_group.assert_called_once()

    @pytest.mark.asyncio
    async def test_synchronize_dry_run(self) -> None:
        """Test dry run mode."""
        # Setup mock data
        google_users = [self.create_google_user('john.doe@test.com')]
        github_users = []

        self.mock_google_client.get_all_users.return_value = google_users
        self.mock_github_client.get_users.return_value = github_users
        self.mock_google_client.get_ou.return_value = self.create_google_ou(
            'Engineering', '/Engineering'
        )
        self.mock_github_client.get_groups.return_value = []

        # Execute dry run
        result = await self.engine.synchronize(
            ou_paths=['/Engineering'], dry_run=True
        )

        # Verify results
        assert result.success is True
        assert result.dry_run is True
        assert len(result.user_diffs) == 1

        # Verify no GitHub operations were called
        self.mock_github_client.create_user.assert_not_called()
        self.mock_github_client.create_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_synchronize_with_custom_ous(self) -> None:
        """Test synchronization with custom OU list."""
        custom_ous = ['/Custom/Department']

        self.mock_google_client.get_all_users.return_value = []
        self.mock_github_client.get_users.return_value = []
        self.mock_github_client.get_groups.return_value = []
        self.mock_google_client.get_ou.return_value = self.create_google_ou(
            'Custom Department', '/Custom/Department'
        )

        await self.engine.synchronize(ou_paths=custom_ous)

        # Verify custom OUs were used
        self.mock_google_client.get_all_users.assert_called_once_with(
            custom_ous, []
        )

    @pytest.mark.asyncio
    async def test_synchronize_error_handling(self) -> None:
        """Test error handling during synchronization."""
        # Setup mock to raise exception
        self.mock_google_client.get_all_users.side_effect = Exception(
            'Google API error'
        )

        # Execute synchronization
        result = await self.engine.synchronize(ou_paths=['/Engineering'])

        # Verify error handling
        assert result.success is False
        assert result.error == 'Google API error'
        assert isinstance(result.stats, SyncStats)

    @pytest.mark.asyncio
    async def test_no_ous_specified(self) -> None:
        """Test error when no OUs specified."""
        # Execute synchronization without OU paths
        result = await self.engine.synchronize()

        # Verify error
        assert result.success is False
        assert (
            'No OUs or individual users specified for synchronization'
            in result.error
        )

    @pytest.mark.asyncio
    async def test_calculate_user_diffs_create(self) -> None:
        """Test user diff calculation for creation."""
        google_users = [self.create_google_user('new.user@test.com')]
        github_users = []

        diffs = await self.engine._calculate_user_diffs(
            google_users, github_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'create'
        assert diffs[0].google_user.primary_email == 'new.user@test.com'
        assert diffs[0].target_scim_user is not None

    @pytest.mark.asyncio
    async def test_calculate_user_diffs_update(self) -> None:
        """Test user diff calculation for updates."""
        google_user = self.create_google_user('john.doe@test.com')

        # Create existing user with different name
        existing_user = self.create_scim_user('john.doe')
        existing_user.name = {'givenName': 'OldFirst', 'familyName': 'OldLast'}

        github_users = [existing_user]
        google_users = [google_user]

        diffs = await self.engine._calculate_user_diffs(
            google_users, github_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'update'
        assert diffs[0].existing_scim_user == existing_user
        assert diffs[0].target_scim_user is not None

    @pytest.mark.asyncio
    async def test_calculate_user_diffs_suspend(self) -> None:
        """Test user diff calculation for suspension."""
        google_users = []  # No Google users
        github_users = [
            self.create_scim_user('orphan.user')
        ]  # Active GitHub user

        diffs = await self.engine._calculate_user_diffs(
            google_users, github_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'suspend'
        assert diffs[0].existing_scim_user.user_name == 'orphan-user'

    @pytest.mark.asyncio
    async def test_calculate_team_diffs_create(self) -> None:
        """Test team diff calculation for creation."""
        google_ous = [self.create_google_ou('New Team', '/NewTeam')]
        github_teams = []
        google_users = [self.create_google_user('john.doe@test.com')]

        diffs = await self.engine._calculate_team_diffs(
            google_ous, github_teams, google_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'create'
        assert diffs[0].google_ou.name == 'New Team'
        assert diffs[0].target_team is not None

    @pytest.mark.asyncio
    async def test_calculate_team_diffs_update(self) -> None:
        """Test team diff calculation for updates."""
        google_ou = self.create_google_ou('Engineering', '/Engineering')

        # Existing team with different members
        existing_team = self.create_github_team('Engineering', 'engineering')
        existing_team.members = ['old-member']

        github_teams = [existing_team]
        google_ous = [google_ou]
        google_users = [self.create_google_user('john.doe@test.com')]

        diffs = await self.engine._calculate_team_diffs(
            google_ous, github_teams, google_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'update'
        assert diffs[0].existing_team == existing_team
        assert diffs[0].target_team is not None

    def test_should_sync_user(self) -> None:
        """Test user filtering - now always returns True."""
        user = self.create_google_user('user@test.com')
        suspended_user = self.create_google_user(
            'suspended@test.com', suspended=True
        )

        # All users should be synced - filtering is handled by action logic
        assert self.engine._should_sync_user(user)
        assert self.engine._should_sync_user(suspended_user)

    def test_google_user_to_scim(self) -> None:
        """Test Google user to SCIM conversion."""
        google_user = self.create_google_user('john.doe@test.com')
        scim_user = self.engine._google_user_to_scim(google_user)

        assert scim_user.user_name == 'john-doe'
        assert scim_user.emails[0]['value'] == 'john.doe@test.com'
        assert scim_user.name['givenName'] == 'John'
        assert scim_user.name['familyName'] == 'Doe'
        assert scim_user.active is True
        assert scim_user.external_id == google_user.id
        assert scim_user.roles == [{'value': 'user', 'primary': True}]

    def test_determine_user_roles(self) -> None:
        """Test role assignment based on email configuration."""
        # Test enterprise owner
        roles = self.engine._determine_user_roles('owner@test.com')
        assert roles == [{'value': 'enterprise_owner', 'primary': True}]

        # Test billing manager
        roles = self.engine._determine_user_roles('billing@test.com')
        assert roles == [{'value': 'billing_manager', 'primary': True}]

        # Test guest collaborator
        roles = self.engine._determine_user_roles('guest@test.com')
        assert roles == [{'value': 'guest_collaborator', 'primary': True}]

        # Test default user role
        roles = self.engine._determine_user_roles('regular@test.com')
        assert roles == [{'value': 'user', 'primary': True}]

    def test_google_user_to_scim_with_roles(self) -> None:
        """Test Google user to SCIM conversion with different roles."""
        # Test enterprise owner
        google_user = self.create_google_user('owner@test.com')
        scim_user = self.engine._google_user_to_scim(google_user)
        assert scim_user.roles == [
            {'value': 'enterprise_owner', 'primary': True}
        ]

        # Test billing manager
        google_user = self.create_google_user('billing@test.com')
        scim_user = self.engine._google_user_to_scim(google_user)
        assert scim_user.roles == [
            {'value': 'billing_manager', 'primary': True}
        ]

        # Test guest collaborator
        google_user = self.create_google_user('guest@test.com')
        scim_user = self.engine._google_user_to_scim(google_user)
        assert scim_user.roles == [
            {'value': 'guest_collaborator', 'primary': True}
        ]

    def test_users_differ(self) -> None:
        """Test user difference detection."""
        user1 = self.create_scim_user('john.doe')
        user2 = self.create_scim_user('john.doe')

        # Same users should not differ
        assert not self.engine._users_differ(user1, user2)

        # Different usernames should differ
        user2.user_name = 'john-smith'
        assert self.engine._users_differ(user1, user2)

        # Different active status should differ
        user2.user_name = user1.user_name
        user2.active = False
        assert self.engine._users_differ(user1, user2)

    def test_teams_differ(self) -> None:
        """Test team difference detection."""
        team1 = self.create_github_team('Engineering', 'engineering')
        team2 = self.create_github_team('Engineering', 'engineering')

        # Same teams should not differ
        assert not self.engine._teams_differ(team1, team2)

        # Different names should differ
        team2.name = 'Marketing'
        assert self.engine._teams_differ(team1, team2)

        # Different members should differ
        team2.name = team1.name
        team2.members = ['different-user']
        assert self.engine._teams_differ(team1, team2)

    def test_get_primary_email(self) -> None:
        """Test primary email extraction."""
        user = self.create_scim_user('test.user')
        email = self.engine._get_primary_email(user)
        assert email == 'test.user@test.com'

    def test_email_to_username(self) -> None:
        """Test email to username conversion."""
        username = self.engine._email_to_username('john.doe@test.com')
        assert username == 'john-doe'

    def test_ou_to_team_slug(self) -> None:
        """Test OU to team slug conversion."""
        ou = self.create_google_ou('Engineering Team', '/Engineering Team')
        slug = self.engine._ou_to_team_slug(ou)
        assert slug == 'engineering-team'

    @pytest.mark.asyncio
    async def test_apply_user_changes_create(self) -> None:
        """Test applying user creation changes."""
        target_user = self.create_scim_user('new.user')
        diff = UserDiff(
            action='create',
            target_scim_user=target_user,
        )

        created_user = self.create_scim_user('new.user')
        created_user.id = 'scim_new_user'
        self.mock_github_client.create_user.return_value = created_user

        await self.engine._apply_user_changes([diff])

        self.mock_github_client.create_user.assert_called_once_with(
            target_user
        )
        assert self.engine._stats.users_created == 1

    @pytest.mark.asyncio
    async def test_apply_user_changes_update(self) -> None:
        """Test applying user update changes."""
        existing_user = self.create_scim_user('existing.user')
        target_user = self.create_scim_user('existing.user')
        target_user.name = {'givenName': 'Updated', 'familyName': 'Name'}

        diff = UserDiff(
            action='update',
            existing_scim_user=existing_user,
            target_scim_user=target_user,
        )

        updated_user = target_user
        updated_user.id = existing_user.id
        self.mock_github_client.update_user.return_value = updated_user

        await self.engine._apply_user_changes([diff])

        self.mock_github_client.update_user.assert_called_once_with(
            existing_user.id, target_user
        )
        assert self.engine._stats.users_updated == 1

    @pytest.mark.asyncio
    async def test_apply_user_changes_suspend(self) -> None:
        """Test applying user suspension changes."""
        existing_user = self.create_scim_user('suspend.user')
        diff = UserDiff(
            action='suspend',
            existing_scim_user=existing_user,
        )

        suspended_user = existing_user
        suspended_user.active = False
        self.mock_github_client.suspend_user.return_value = suspended_user

        await self.engine._apply_user_changes([diff])

        self.mock_github_client.suspend_user.assert_called_once_with(
            existing_user.id
        )
        assert self.engine._stats.users_suspended == 1

    @pytest.mark.asyncio
    async def test_apply_team_changes_create(self) -> None:
        """Test applying team creation changes."""
        target_team = self.create_github_team('New Team', 'new-team')
        diff = TeamDiff(
            action='create',
            target_team=target_team,
        )

        created_team = target_team
        created_team.id = 456
        self.mock_github_client.create_group.return_value = created_team

        await self.engine._apply_team_changes([diff])

        self.mock_github_client.create_group.assert_called_once_with(
            target_team
        )
        assert self.engine._stats.teams_created == 1

    @pytest.mark.asyncio
    async def test_apply_changes_error_handling(self) -> None:
        """Test error handling during change application."""
        diff = UserDiff(
            action='create',
            target_scim_user=self.create_scim_user('error.user'),
        )

        self.mock_github_client.create_user.side_effect = Exception(
            'API Error'
        )

        await self.engine._apply_user_changes([diff])

        assert self.engine._stats.users_failed == 1
        assert self.engine._stats.users_created == 0

    def test_preview_changes(self) -> None:
        """Test change preview for dry run mode."""
        user_diff = UserDiff(
            action='create',
            google_user=self.create_google_user('new.user@test.com'),
        )
        team_diff = TeamDiff(
            action='create',
            google_ou=self.create_google_ou('New Team', '/New Team'),
            target_team=self.create_github_team('New Team', 'new-team'),
        )

        # These should not raise exceptions
        self.engine._preview_user_changes([user_diff])
        self.engine._preview_team_changes([team_diff])

    @pytest.mark.asyncio
    async def test_synchronize_with_flattened_ous(self) -> None:
        """Test synchronization with OU flattening enabled."""
        # Update config to enable flattening
        self.config.flatten_ous = True
        self.config.create_teams = True

        # Setup mock data
        google_users = [
            self.create_google_user('john.doe@test.com'),
            self.create_google_user('jane.smith@test.com'),
        ]
        # Update users to be in nested OUs for flattening
        google_users[0].org_unit_path = '/AWeber/Engineering/Backend'
        google_users[1].org_unit_path = '/AWeber/Marketing/Digital'

        github_users = []
        github_teams = []

        # Setup mock responses
        self.mock_google_client.get_all_users.return_value = google_users
        self.mock_github_client.get_users.return_value = github_users
        self.mock_github_client.get_groups.return_value = github_teams

        # Mock GitHub operations
        created_user1 = self.create_scim_user('john.doe')
        created_user2 = self.create_scim_user('jane.smith')
        self.mock_github_client.create_user.side_effect = [
            created_user1,
            created_user2,
        ]

        created_teams = [
            self.create_github_team('Engineering', 'engineering'),
            self.create_github_team('Backend', 'backend'),
            self.create_github_team('Marketing', 'marketing'),
            self.create_github_team('Digital', 'digital'),
        ]
        self.mock_github_client.create_group.side_effect = created_teams

        # Execute synchronization with flattened OUs
        result = await self.engine.synchronize(
            ou_paths=[
                '/AWeber/Engineering/Backend',
                '/AWeber/Marketing/Digital',
            ]
        )

        # Verify results
        assert result.success is True
        assert result.dry_run is False
        assert len(result.user_diffs) == 2  # Two users to create
        assert len(result.team_diffs) == 4  # Four teams to create (flattened)

        # Verify all diffs are creation actions
        assert all(diff.action == 'create' for diff in result.user_diffs)
        assert all(diff.action == 'create' for diff in result.team_diffs)

        # Verify API calls
        self.mock_google_client.get_all_users.assert_called_once()
        self.mock_github_client.get_users.assert_called_once()
        assert self.mock_github_client.create_user.call_count == 2
        assert self.mock_github_client.create_group.call_count == 4

    @pytest.mark.asyncio
    async def test_synchronize_with_teams_disabled(self) -> None:
        """Test synchronization with team creation disabled."""
        # Update config to disable team creation
        self.config.create_teams = False

        # Setup mock data
        google_users = [self.create_google_user('john.doe@test.com')]
        github_users = []

        # Setup mock responses
        self.mock_google_client.get_all_users.return_value = google_users
        self.mock_github_client.get_users.return_value = github_users

        # Mock GitHub operations
        created_user = self.create_scim_user('john.doe')
        self.mock_github_client.create_user.return_value = created_user

        # Execute synchronization with teams disabled
        result = await self.engine.synchronize(ou_paths=['/Engineering'])

        # Verify results
        assert result.success is True
        assert len(result.user_diffs) == 1  # One user to create
        assert len(result.team_diffs) == 0  # No teams when disabled

        # Verify API calls
        self.mock_github_client.create_user.assert_called_once()
        # Should not fetch groups
        self.mock_github_client.get_groups.assert_not_called()
        # Should not create groups
        self.mock_github_client.create_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_calculate_flattened_team_diffs(self) -> None:
        """Test flattened team diff calculation."""
        # Setup users in nested OUs
        google_users = [
            self.create_google_user('john.doe@test.com'),
            self.create_google_user('jane.smith@test.com'),
            self.create_google_user('bob.johnson@test.com'),
        ]
        # Set up nested OU paths for flattening
        google_users[0].org_unit_path = '/AWeber/Engineering/Backend'
        google_users[1].org_unit_path = '/AWeber/Engineering/Frontend'
        google_users[2].org_unit_path = '/AWeber/Marketing'

        github_teams = []  # No existing teams

        # Test the flattened team diff calculation
        diffs = await self.engine._calculate_flattened_team_diffs(
            google_users, github_teams
        )

        # Should create teams: engineering, backend, frontend, marketing
        assert len(diffs) == 4
        team_slugs = {diff.target_team.slug for diff in diffs}
        assert team_slugs == {
            'engineering',
            'backend',
            'frontend',
            'marketing',
        }

        # Verify all are creation actions
        assert all(diff.action == 'create' for diff in diffs)

        # Verify team memberships
        # Engineering team should have both john.doe and jane.smith
        engineering_diff = next(
            diff for diff in diffs if diff.target_team.slug == 'engineering'
        )
        assert 'john-doe' in engineering_diff.target_team.members
        assert 'jane-smith' in engineering_diff.target_team.members
        assert 'bob-johnson' not in engineering_diff.target_team.members

        # Backend team should have only john.doe
        backend_diff = next(
            diff for diff in diffs if diff.target_team.slug == 'backend'
        )
        assert 'john-doe' in backend_diff.target_team.members
        assert 'jane-smith' not in backend_diff.target_team.members

        # Marketing team should have only bob.johnson
        marketing_diff = next(
            diff for diff in diffs if diff.target_team.slug == 'marketing'
        )
        assert 'bob-johnson' in marketing_diff.target_team.members
        assert 'john-doe' not in marketing_diff.target_team.members
