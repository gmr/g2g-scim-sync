"""Tests for the synchronization engine."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest import mock

import pytest

from g2g_scim_sync.models import (
    GitHubTeam,
    GoogleGroup,
    GoogleUser,
    ScimUser,
    SyncConfig,
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
            groups=['engineering@test.com', 'marketing@test.com'],
            sync_teams=True,
            include_suspended=False,
        )
        self.engine = SyncEngine(
            google_client=self.mock_google_client,
            github_client=self.mock_github_client,
            config=self.config,
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

    def create_google_group(self, name: str, email: str) -> GoogleGroup:
        """Create a test Google group."""
        return GoogleGroup(
            id=f'group_{name.replace(" ", "_")}',
            name=name,
            email=email,
            description=f'{name} team group',
            direct_members_count=2,
            member_emails=['john.doe@test.com', 'jane.smith@test.com'],
        )

    def create_github_team(self, name: str, slug: str) -> GitHubTeam:
        """Create a test GitHub team."""
        return GitHubTeam(
            id=123,
            name=name,
            slug=slug,
            description=f'{name} team',
            members=['john-doe', 'jane-smith'],
        )

    @pytest.mark.asyncio
    async def test_synchronize_success(self) -> None:
        """Test successful synchronization."""
        # Setup mock data
        google_users = [
            self.create_google_user('john.doe@test.com'),
            self.create_google_user('jane.smith@test.com'),
        ]
        github_users = [self.create_scim_user('john.doe')]

        google_groups = [
            self.create_google_group('Engineering', 'engineering@test.com')
        ]
        github_teams = []

        # Setup mock responses
        self.mock_google_client.get_all_users_in_groups.return_value = (
            google_users
        )
        self.mock_github_client.get_users.return_value = github_users

        # Mock get_group to return different groups for each call
        def mock_get_group(email: str) -> GoogleGroup:
            if 'engineering' in email:
                return google_groups[0]
            else:
                # Return a marketing group for the second call
                return self.create_google_group(
                    'Marketing', 'marketing@test.com'
                )

        self.mock_google_client.get_group.side_effect = mock_get_group
        self.mock_google_client.get_nested_groups.return_value = []
        self.mock_github_client.get_groups.return_value = github_teams

        # Mock GitHub operations
        created_user = self.create_scim_user('jane.smith')
        created_user.id = 'scim_jane_smith'
        self.mock_github_client.create_user.return_value = created_user

        created_team = self.create_github_team('Engineering', 'engineering')
        self.mock_github_client.create_group.return_value = created_team

        # Execute synchronization
        result = await self.engine.synchronize()

        # Verify results
        assert result.success is True
        assert result.dry_run is False
        assert len(result.user_diffs) == 1  # One user to create
        # Should have 2 teams since we have 2 groups configured but only mock 1
        assert (
            len(result.team_diffs) == 2
        )  # One team to create from each group
        assert result.user_diffs[0].action == 'create'
        assert result.team_diffs[0].action == 'create'

        # Verify API calls
        self.mock_google_client.get_all_users_in_groups.assert_called_once()
        self.mock_github_client.get_users.assert_called_once()
        self.mock_github_client.create_user.assert_called_once()
        # Should be called twice - once for each group
        assert self.mock_github_client.create_group.call_count == 2

    @pytest.mark.asyncio
    async def test_synchronize_dry_run(self) -> None:
        """Test dry run mode."""
        # Setup mock data
        google_users = [self.create_google_user('john.doe@test.com')]
        github_users = []

        self.mock_google_client.get_all_users_in_groups.return_value = (
            google_users
        )
        self.mock_github_client.get_users.return_value = github_users
        self.mock_google_client.get_group.return_value = (
            self.create_google_group('Engineering', 'engineering@test.com')
        )
        self.mock_google_client.get_nested_groups.return_value = []
        self.mock_github_client.get_groups.return_value = []

        # Execute dry run
        result = await self.engine.synchronize(dry_run=True)

        # Verify results
        assert result.success is True
        assert result.dry_run is True
        assert len(result.user_diffs) == 1

        # Verify no GitHub operations were called
        self.mock_github_client.create_user.assert_not_called()
        self.mock_github_client.create_group.assert_not_called()

    @pytest.mark.asyncio
    async def test_synchronize_with_custom_groups(self) -> None:
        """Test synchronization with custom group list."""
        custom_groups = ['custom@test.com']

        self.mock_google_client.get_all_users_in_groups.return_value = []
        self.mock_github_client.get_users.return_value = []

        await self.engine.synchronize(group_emails=custom_groups)

        # Verify custom groups were used
        self.mock_google_client.get_all_users_in_groups.assert_called_once_with(
            custom_groups
        )

    @pytest.mark.asyncio
    async def test_synchronize_error_handling(self) -> None:
        """Test error handling during synchronization."""
        # Setup mock to raise exception
        self.mock_google_client.get_all_users_in_groups.side_effect = (
            Exception('Google API error')
        )

        # Execute synchronization
        result = await self.engine.synchronize()

        # Verify error handling
        assert result.success is False
        assert result.error == 'Google API error'
        assert isinstance(result.stats, SyncStats)

    @pytest.mark.asyncio
    async def test_no_groups_specified(self) -> None:
        """Test error when no groups specified."""
        # Create engine with empty config
        config = SyncConfig(groups=[])
        engine = SyncEngine(
            google_client=self.mock_google_client,
            github_client=self.mock_github_client,
            config=config,
        )

        # Execute synchronization
        result = await engine.synchronize()

        # Verify error
        assert result.success is False
        assert 'No groups specified for synchronization' in result.error

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
        google_groups = [
            self.create_google_group('New Team', 'newteam@test.com')
        ]
        github_teams = []
        google_users = [self.create_google_user('john.doe@test.com')]

        diffs = await self.engine._calculate_team_diffs(
            google_groups, github_teams, google_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'create'
        assert diffs[0].google_group.name == 'New Team'
        assert diffs[0].target_team is not None

    @pytest.mark.asyncio
    async def test_calculate_team_diffs_update(self) -> None:
        """Test team diff calculation for updates."""
        google_group = self.create_google_group('Engineering', 'eng@test.com')

        # Existing team with different members
        existing_team = self.create_github_team('Engineering', 'engineering')
        existing_team.members = ['old-member']

        github_teams = [existing_team]
        google_groups = [google_group]
        google_users = [self.create_google_user('john.doe@test.com')]

        diffs = await self.engine._calculate_team_diffs(
            google_groups, github_teams, google_users
        )

        assert len(diffs) == 1
        assert diffs[0].action == 'update'
        assert diffs[0].existing_team == existing_team
        assert diffs[0].target_team is not None

    def test_should_sync_user_suspended(self) -> None:
        """Test user filtering for suspended users."""
        suspended_user = self.create_google_user(
            'suspended@test.com', suspended=True
        )

        # Default config excludes suspended users
        assert not self.engine._should_sync_user(suspended_user)

        # Config with include_suspended=True
        self.engine.config.include_suspended = True
        assert self.engine._should_sync_user(suspended_user)

    def test_should_sync_user_org_unit(self) -> None:
        """Test user filtering by organizational unit."""
        user = self.create_google_user('user@test.com')
        user.org_unit_path = '/Engineering/Backend'

        # No filters - should sync
        assert self.engine._should_sync_user(user)

        # With matching filter - should sync
        self.engine.config.org_unit_filters = ['/Engineering/Backend']
        assert self.engine._should_sync_user(user)

        # With non-matching filter - should not sync
        self.engine.config.org_unit_filters = ['/Sales']
        assert not self.engine._should_sync_user(user)

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

    def test_group_to_team_slug(self) -> None:
        """Test group to team slug conversion."""
        group = self.create_google_group('Engineering Team', 'eng@test.com')
        slug = self.engine._group_to_team_slug(group)
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
            google_group=self.create_google_group('New Team', 'new@test.com'),
        )

        # These should not raise exceptions
        self.engine._preview_user_changes([user_diff])
        self.engine._preview_team_changes([team_diff])
