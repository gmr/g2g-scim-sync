"""Tests for Google Workspace client."""

from __future__ import annotations

import pytest
from pathlib import Path
from unittest import mock

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from g2g_scim_sync.google_client import GoogleWorkspaceClient
from g2g_scim_sync.models import GoogleGroup, GoogleUser


class TestGoogleWorkspaceClient:
    """Tests for GoogleWorkspaceClient."""

    def create_client(self, tmp_path: Path) -> GoogleWorkspaceClient:
        """Create a test client with mock service account file."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{"type": "service_account"}')

        return GoogleWorkspaceClient(
            service_account_file=service_file, domain='test.com'
        )

    def test_init(self, tmp_path: Path) -> None:
        """Test client initialization."""
        client = self.create_client(tmp_path)

        assert client.domain == 'test.com'
        assert (
            'https://www.googleapis.com/auth/admin.directory.user.readonly'
            in client.scopes
        )
        assert (
            'https://www.googleapis.com/auth/admin.directory.group.readonly'
            in client.scopes
        )
        assert client._admin_service is None

    def test_init_custom_scopes(self, tmp_path: Path) -> None:
        """Test client initialization with custom scopes."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{"type": "service_account"}')

        custom_scopes = ['https://example.com/scope']
        client = GoogleWorkspaceClient(
            service_account_file=service_file,
            domain='test.com',
            scopes=custom_scopes,
        )

        assert client.scopes == custom_scopes

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    def test_create_admin_service_success(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful admin service creation."""
        # Mock credentials
        mock_creds = mock.Mock()
        mock_creds.valid = True
        mock_credentials.from_service_account_file.return_value = mock_creds

        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        client = self.create_client(tmp_path)
        service = client.admin_service

        assert service == mock_service
        mock_credentials.from_service_account_file.assert_called_once()
        mock_build.assert_called_once_with(
            'admin', 'directory_v1', credentials=mock_creds
        )

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    def test_create_admin_service_invalid_credentials(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test admin service creation with invalid credentials."""
        # Mock credentials that need refresh
        mock_creds = mock.Mock()
        mock_creds.valid = False
        mock_credentials.from_service_account_file.return_value = mock_creds

        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        client = self.create_client(tmp_path)
        service = client.admin_service

        assert service == mock_service
        mock_creds.refresh.assert_called_once()

    @mock.patch('g2g_scim_sync.google_client.Credentials')
    def test_create_admin_service_auth_error(
        self, mock_credentials: mock.Mock, tmp_path: Path
    ) -> None:
        """Test admin service creation with auth error."""
        mock_credentials.from_service_account_file.side_effect = (
            GoogleAuthError('Auth failed')
        )

        client = self.create_client(tmp_path)

        with pytest.raises(GoogleAuthError, match='Auth failed'):
            _ = client.admin_service

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_user_success(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful user retrieval."""
        # Mock service and user data
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        user_data = {
            'id': '123456',
            'primaryEmail': 'john.doe@test.com',
            'name': {
                'givenName': 'John',
                'familyName': 'Doe',
                'fullName': 'John Doe',
            },
            'suspended': False,
            'orgUnitPath': '/Engineering',
        }

        mock_service.users().get().execute.return_value = user_data

        client = self.create_client(tmp_path)
        user = await client.get_user('john.doe@test.com')

        assert isinstance(user, GoogleUser)
        assert user.id == '123456'
        assert user.primary_email == 'john.doe@test.com'
        assert user.given_name == 'John'
        assert user.family_name == 'Doe'
        assert user.full_name == 'John Doe'
        assert user.suspended is False
        assert user.org_unit_path == '/Engineering'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_user_not_found(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test user retrieval when user not found."""
        # Mock 404 error
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        error_resp = mock.Mock()
        error_resp.status = 404
        http_error = HttpError(resp=error_resp, content=b'Not found')
        mock_service.users().get().execute.side_effect = http_error

        client = self.create_client(tmp_path)

        with pytest.raises(
            ValueError, match='User not found: nonexistent@test.com'
        ):
            await client.get_user('nonexistent@test.com')

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_users_in_group_success(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful retrieval of users in a group."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock group members response
        members_data = {
            'members': [
                {'email': 'john.doe@test.com', 'type': 'USER'},
                {'email': 'jane.smith@test.com', 'type': 'USER'},
                {
                    'email': 'subgroup@test.com',
                    'type': 'GROUP',
                },  # Should be ignored
            ]
        }
        mock_service.members().list().execute.return_value = members_data

        # Mock user data responses
        john_data = {
            'id': '123',
            'primaryEmail': 'john.doe@test.com',
            'name': {
                'givenName': 'John',
                'familyName': 'Doe',
                'fullName': 'John Doe',
            },
            'suspended': False,
        }
        jane_data = {
            'id': '456',
            'primaryEmail': 'jane.smith@test.com',
            'name': {
                'givenName': 'Jane',
                'familyName': 'Smith',
                'fullName': 'Jane Smith',
            },
            'suspended': False,
        }

        mock_service.users().get().execute.side_effect = [john_data, jane_data]

        client = self.create_client(tmp_path)
        users = await client.get_users_in_group('engineering@test.com')

        assert len(users) == 2
        assert users[0].primary_email == 'john.doe@test.com'
        assert users[1].primary_email == 'jane.smith@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_group_success(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful group retrieval."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock group data
        group_data = {
            'id': 'group123',
            'name': 'Engineering',
            'email': 'engineering@test.com',
            'description': 'Engineering team',
            'directMembersCount': 5,
        }
        mock_service.groups().get().execute.return_value = group_data

        # Mock member emails
        members_data = {
            'members': [{'email': 'john@test.com'}, {'email': 'jane@test.com'}]
        }
        mock_service.members().list().execute.return_value = members_data

        client = self.create_client(tmp_path)
        group = await client.get_group('engineering@test.com')

        assert isinstance(group, GoogleGroup)
        assert group.id == 'group123'
        assert group.name == 'Engineering'
        assert group.email == 'engineering@test.com'
        assert group.description == 'Engineering team'
        assert group.direct_members_count == 5
        assert len(group.member_emails) == 2

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_nested_groups(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test retrieval of nested groups."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock parent group members (contains a nested group)
        parent_members = {
            'members': [
                {'email': 'user@test.com', 'type': 'USER'},
                {'email': 'nested@test.com', 'type': 'GROUP'},
            ]
        }

        # Mock nested group data
        nested_group_data = {
            'id': 'nested123',
            'name': 'Nested Group',
            'email': 'nested@test.com',
            'directMembersCount': 2,
        }

        # Mock nested group members (no further nesting)
        nested_members = {
            'members': [{'email': 'nested_user@test.com', 'type': 'USER'}]
        }

        # Set up mock responses
        mock_service.members().list().execute.side_effect = [
            parent_members,  # Parent group members
            {
                'members': []
            },  # Nested group has no group members (for recursion)
            nested_members,  # Nested group member emails
        ]
        mock_service.groups().get().execute.return_value = nested_group_data

        client = self.create_client(tmp_path)
        nested_groups = await client.get_nested_groups('parent@test.com')

        assert len(nested_groups) == 1
        assert nested_groups[0].name == 'Nested Group'
        assert nested_groups[0].email == 'nested@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_all_users_in_groups(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test getting all unique users across multiple groups."""
        client = self.create_client(tmp_path)

        # Mock the methods this function calls
        with (
            mock.patch.object(client, 'get_users_in_group') as mock_get_users,
            mock.patch.object(client, 'get_nested_groups') as mock_get_nested,
        ):
            # Setup mock data
            user1 = GoogleUser(
                id='1',
                primary_email='user1@test.com',
                given_name='User',
                family_name='One',
                full_name='User One',
                org_unit_path='/',
            )
            user2 = GoogleUser(
                id='2',
                primary_email='user2@test.com',
                given_name='User',
                family_name='Two',
                full_name='User Two',
                org_unit_path='/',
            )

            mock_get_users.side_effect = [
                [user1, user2],  # First group
                [user2],  # Second group (duplicate user2)
                [user1],  # Nested group (duplicate user1)
            ]

            nested_group = GoogleGroup(
                id='nested',
                name='Nested',
                email='nested@test.com',
                member_emails=[],
            )
            mock_get_nested.side_effect = [
                [nested_group],  # First group has nested group
                [],  # Second group has no nested groups
            ]

            users = await client.get_all_users_in_groups(
                ['group1@test.com', 'group2@test.com']
            )

            # Should have 2 unique users (duplicates removed)
            assert len(users) == 2
            user_emails = {user.primary_email for user in users}
            assert user_emails == {'user1@test.com', 'user2@test.com'}

    def test_parse_user_minimal(self, tmp_path: Path) -> None:
        """Test parsing user data with minimal fields."""
        client = self.create_client(tmp_path)

        user_data = {
            'id': '123',
            'primaryEmail': 'test@test.com',
            'name': {
                'givenName': 'Test',
                'familyName': 'User',
                'fullName': 'Test User',
            },
        }

        user = client._parse_user(user_data)

        assert user.id == '123'
        assert user.primary_email == 'test@test.com'
        assert user.given_name == 'Test'
        assert user.family_name == 'User'
        assert user.full_name == 'Test User'
        assert user.suspended is False
        assert user.org_unit_path == '/'
        assert user.last_login_time is None
        assert user.creation_time is None

    def test_parse_user_complete(self, tmp_path: Path) -> None:
        """Test parsing user data with all fields."""
        from datetime import datetime, timezone

        client = self.create_client(tmp_path)

        user_data = {
            'id': '123',
            'primaryEmail': 'test@test.com',
            'name': {
                'givenName': 'Test',
                'familyName': 'User',
                'fullName': 'Test User',
            },
            'suspended': True,
            'orgUnitPath': '/Engineering/Backend',
            'lastLoginTime': '2024-01-15T10:30:00Z',
            'creationTime': '2024-01-01T00:00:00Z',
        }

        user = client._parse_user(user_data)

        assert user.suspended is True
        assert user.org_unit_path == '/Engineering/Backend'
        assert user.last_login_time == datetime(
            2024, 1, 15, 10, 30, tzinfo=timezone.utc
        )
        assert user.creation_time == datetime(
            2024, 1, 1, 0, 0, tzinfo=timezone.utc
        )
