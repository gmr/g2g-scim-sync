"""Tests for the synchronization engine."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

from g2g_scim_sync.config import SyncConfig, GitHubConfig
from g2g_scim_sync.models import (
    GitHubGroup,
    GoogleOU,
    GoogleUser,
    ScimUser,
    SyncStats,
    UserDiff,
    GroupDiff,
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
            create_groups=True,
            flatten_ous=False,
        )
        self.github_config = GitHubConfig(
            hostname='github.company.com',
            scim_token='token',  # noqa: S106
            enterprise_account='org',
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
            user_name=email,  # Use full email as username
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

    def create_github_team(self, name: str, slug: str) -> GitHubGroup:
        """Create a test GitHub team."""
        return GitHubGroup(
            id='team-uuid-123',
            name=name,
            slug=slug,
            description=f'{name} team',
            members=['john.doe@test.com', 'jane.smith@test.com'],
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
        assert len(result.group_diffs) == 1  # One team to create
        assert result.user_diffs[0].action == 'create'
        assert result.group_diffs[0].action == 'create'

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
        assert diffs[0].existing_scim_user.user_name == 'orphan.user@test.com'

    @pytest.mark.asyncio
    async def test_calculate_group_diffs_create(self) -> None:
        """Test team diff calculation for creation."""
        google_ous = [self.create_google_ou('New Team', '/NewTeam')]
        github_teams = []
        google_users = [self.create_google_user('john.doe@test.com')]

        diffs = await self.engine._calculate_group_diffs(
            google_ous, github_teams, google_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'create'
        assert diffs[0].google_ou.name == 'New Team'
        assert diffs[0].target_group is not None

    @pytest.mark.asyncio
    async def test_calculate_group_diffs_update(self) -> None:
        """Test team diff calculation for updates."""
        google_ou = self.create_google_ou('Engineering', '/Engineering')

        # Existing team with different members
        existing_group = self.create_github_team('Engineering', 'engineering')
        existing_group.members = ['old-member']

        github_teams = [existing_group]
        google_ous = [google_ou]
        google_users = [self.create_google_user('john.doe@test.com')]

        diffs = await self.engine._calculate_group_diffs(
            google_ous, github_teams, google_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'update'
        assert diffs[0].existing_group == existing_group
        assert diffs[0].target_group is not None

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

        assert scim_user.user_name == 'john.doe@test.com'
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

    def test_groups_differ(self) -> None:
        """Test team difference detection."""
        team1 = self.create_github_team('Engineering', 'engineering')
        team2 = self.create_github_team('Engineering', 'engineering')

        # Same teams should not differ
        assert not self.engine._groups_differ(team1, team2)

        # Different names should differ
        team2.name = 'Marketing'
        assert self.engine._groups_differ(team1, team2)

        # Different members should differ
        team2.name = team1.name
        team2.members = ['different-user']
        assert self.engine._groups_differ(team1, team2)

    def test_get_primary_email(self) -> None:
        """Test primary email extraction."""
        user = self.create_scim_user('test.user')
        email = self.engine._get_primary_email(user)
        assert email == 'test.user@test.com'

    def test_email_to_username(self) -> None:
        """Test email to username conversion."""
        username = self.engine._email_to_username('john.doe@test.com')
        assert username == 'john.doe@test.com'

    def test_email_to_username_with_emu_suffix(self) -> None:
        """Test email to username conversion with EMU suffix."""
        # Configure EMU suffix
        self.github_config.emu_username_suffix = 'companyname'

        username = self.engine._email_to_username('john.doe@test.com')
        assert username == 'john.doe@test.com_companyname'

        # Test with different email
        username = self.engine._email_to_username('jane.smith@test.com')
        assert username == 'jane.smith@test.com_companyname'

    def test_ou_to_group_slug(self) -> None:
        """Test OU to team slug conversion."""
        ou = self.create_google_ou('Engineering Team', '/Engineering Team')
        slug = self.engine._ou_to_group_slug(ou)
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
    async def test_apply_group_changes_create(self) -> None:
        """Test applying team creation changes."""
        target_group = self.create_github_team('New Team', 'new-team')
        diff = GroupDiff(
            action='create',
            target_group=target_group,
        )

        created_team = target_group
        created_team.id = 456
        self.mock_github_client.create_group.return_value = created_team

        await self.engine._apply_group_changes([diff])

        self.mock_github_client.create_group.assert_called_once_with(
            target_group
        )
        assert self.engine._stats.groups_created == 1

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
        group_diff = GroupDiff(
            action='create',
            google_ou=self.create_google_ou('New Team', '/New Team'),
            target_group=self.create_github_team('New Team', 'new-team'),
        )

        # These should not raise exceptions
        self.engine._preview_user_changes([user_diff])
        self.engine._preview_group_changes([group_diff])

    @pytest.mark.asyncio
    async def test_synchronize_with_flattened_ous(self) -> None:
        """Test synchronization with OU flattening enabled."""
        # Update config to enable flattening
        self.config.flatten_ous = True
        self.config.create_groups = True

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
            self.create_github_team('AWeber', 'aweber'),
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
        assert len(result.group_diffs) == 5  # 5 flattened groups created

        # Verify all diffs are creation actions
        assert all(diff.action == 'create' for diff in result.user_diffs)
        assert all(diff.action == 'create' for diff in result.group_diffs)

        # Verify API calls
        self.mock_google_client.get_all_users.assert_called_once()
        # get_users is called twice in flattened mode: once for sync, once for
        # team mapping
        assert self.mock_github_client.get_users.call_count == 2
        assert self.mock_github_client.create_user.call_count == 2
        assert self.mock_github_client.create_group.call_count == 5

    @pytest.mark.asyncio
    async def test_synchronize_with_groups_disabled(self) -> None:
        """Test synchronization with group creation disabled."""
        # Update config to disable team creation
        self.config.create_groups = False

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
        assert len(result.group_diffs) == 0  # No teams when disabled

        # Verify API calls
        self.mock_github_client.create_user.assert_called_once()
        # Should not fetch groups
        self.mock_github_client.get_groups.assert_not_called()
        # Should not create groups
        self.mock_github_client.create_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_calculate_flattened_group_diffs(self) -> None:
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
        diffs = await self.engine._calculate_flattened_group_diffs(
            google_users, github_teams
        )

        # Should create teams: aweber, engineering, backend, frontend,
        # marketing
        assert len(diffs) == 5
        team_slugs = {diff.target_group.slug for diff in diffs}
        assert team_slugs == {
            'aweber',
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
            diff for diff in diffs if diff.target_group.slug == 'engineering'
        )
        assert 'john.doe@test.com' in engineering_diff.target_group.members
        assert 'jane.smith@test.com' in engineering_diff.target_group.members
        assert (
            'bob.johnson@test.com' not in engineering_diff.target_group.members
        )

        # Backend team should have only john.doe
        backend_diff = next(
            diff for diff in diffs if diff.target_group.slug == 'backend'
        )
        assert 'john.doe@test.com' in backend_diff.target_group.members
        assert 'jane.smith@test.com' not in backend_diff.target_group.members

        # Marketing team should have only bob.johnson
        marketing_diff = next(
            diff for diff in diffs if diff.target_group.slug == 'marketing'
        )
        assert 'bob.johnson@test.com' in marketing_diff.target_group.members
        assert 'john.doe@test.com' not in marketing_diff.target_group.members

    @pytest.mark.asyncio
    async def test_apply_group_changes_scim_not_supported(self) -> None:
        """Test applying team changes when SCIM Groups API is not supported."""
        from g2g_scim_sync.models import GitHubScimNotSupportedException

        # Create a team diff that would need to be created
        group_diff = GroupDiff(
            action='create',
            google_ou=self.create_google_ou(
                'Engineering', '/AWeber/Engineering'
            ),
            target_group=self.create_github_team('Engineering', 'engineering'),
        )

        # Mock the GitHub client to raise the exception
        self.mock_github_client.create_group.side_effect = (
            GitHubScimNotSupportedException('SCIM Groups API not supported')
        )

        # Apply team changes - should handle the exception gracefully
        await self.engine._apply_group_changes([group_diff])

        # Verify stats show failed team creation
        assert self.engine._stats.groups_failed == 1
        assert self.engine._stats.groups_created == 0

    @pytest.mark.asyncio
    async def test_apply_group_changes_general_error(self) -> None:
        """Test applying team changes with general exception handling."""
        # Create a team diff for update
        existing_group = self.create_github_team('Engineering', 'engineering')
        existing_group.id = 'team123'

        group_diff = GroupDiff(
            action='update',
            google_ou=self.create_google_ou(
                'Engineering', '/AWeber/Engineering'
            ),
            existing_group=existing_group,
            target_group=self.create_github_team(
                'Engineering Updated', 'engineering'
            ),
        )

        # Mock the GitHub client to raise a general exception
        self.mock_github_client.update_group.side_effect = Exception(
            'Network error'
        )

        # Apply team changes - should handle the exception gracefully
        await self.engine._apply_group_changes([group_diff])

        # Verify stats show failed team update
        assert self.engine._stats.groups_failed == 1
        assert self.engine._stats.groups_updated == 0

    @pytest.mark.asyncio
    async def test_synchronize_fetch_error_handling(self) -> None:
        """Test synchronization with errors in fetching data."""
        # Mock error when fetching Google users
        self.mock_google_client.get_all_users.side_effect = Exception(
            'Google API error'
        )

        # Synchronization should handle the error and not crash
        result = await self.engine.synchronize(
            ou_paths=['/AWeber/Engineering'], dry_run=True
        )

        # Result should indicate failure
        assert result.success is False

    @pytest.mark.asyncio
    async def test_calculate_flattened_group_diffs_with_existing_group(
        self,
    ) -> None:
        """Test calculating flattened group diffs with existing groups to
        update."""
        google_users = [
            self.create_google_user('john.doe@test.com'),
            self.create_google_user('jane.smith@test.com'),
        ]
        google_users[0].org_unit_path = '/AWeber/Engineering'
        google_users[1].org_unit_path = '/AWeber/Engineering'

        # Create existing team with different members
        existing_group = self.create_github_team('Engineering', 'engineering')
        existing_group.id = 'team123'
        existing_group.members = ['old.user']  # Different from Google users
        github_teams = [existing_group]

        # Mock GitHub users for SCIM ID mapping
        github_users = [
            self.create_scim_user('old.user'),
        ]
        self.mock_github_client.get_users.return_value = github_users

        diffs = await self.engine._calculate_flattened_group_diffs(
            google_users, github_teams
        )

        # Should generate 1 create (aweber) and 1 update (engineering) diff
        assert len(diffs) == 2

        # Find the update diff for engineering team
        update_diffs = [d for d in diffs if d.action == 'update']
        create_diffs = [d for d in diffs if d.action == 'create']

        assert len(update_diffs) == 1
        assert len(create_diffs) == 1
        assert update_diffs[0].existing_group is not None
        assert update_diffs[0].existing_group.id == 'team123'
