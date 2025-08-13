"""Tests for Google Workspace client."""

from __future__ import annotations

import pytest
import tempfile
from pathlib import Path
from unittest import mock

from google.auth.exceptions import GoogleAuthError
from googleapiclient.errors import HttpError

from g2g_scim_sync.google_client import GoogleWorkspaceClient
from g2g_scim_sync.models import GoogleOU, GoogleUser


class TestGoogleWorkspaceClient:
    """Tests for GoogleWorkspaceClient."""

    def create_client(self, tmp_path: Path) -> GoogleWorkspaceClient:
        """Create a test client with mock service account file."""
        service_file = tmp_path / 'service-account.json'
        service_file.write_text('{"type": "service_account"}')

        return GoogleWorkspaceClient(
            service_account_file=service_file,
            domain='test.com',
            subject_email='admin@test.com',
        )

    def test_init(self, tmp_path: Path) -> None:
        """Test client initialization."""
        client = self.create_client(tmp_path)

        assert client.domain == 'test.com'
        assert (
            'https://www.googleapis.com/auth/admin.directory.user'
            in client.scopes
        )
        assert (
            'https://www.googleapis.com/auth/admin.directory.orgunit.readonly'
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
            subject_email='admin@test.com',
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
        mock_delegated_creds = mock.Mock()
        mock_delegated_creds.valid = True
        mock_creds.with_subject.return_value = mock_delegated_creds
        mock_credentials.from_service_account_file.return_value = mock_creds

        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        client = self.create_client(tmp_path)
        service = client.admin_service

        assert service == mock_service
        mock_credentials.from_service_account_file.assert_called_once()
        mock_creds.with_subject.assert_called_once_with('admin@test.com')
        mock_build.assert_called_once_with(
            'admin', 'directory_v1', credentials=mock_delegated_creds
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
        mock_delegated_creds = mock.Mock()
        mock_delegated_creds.valid = False
        mock_creds.with_subject.return_value = mock_delegated_creds
        mock_credentials.from_service_account_file.return_value = mock_creds

        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        client = self.create_client(tmp_path)
        service = client.admin_service

        assert service == mock_service
        mock_delegated_creds.refresh.assert_called_once()

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
    async def test_get_user_http_error(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test user retrieval with HTTP error other than 404."""
        # Mock 500 error
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        error_resp = mock.Mock()
        error_resp.status = 500
        http_error = HttpError(resp=error_resp, content=b'Server error')
        mock_service.users().get().execute.side_effect = http_error

        client = self.create_client(tmp_path)

        with pytest.raises(HttpError):
            await client.get_user('test@test.com')

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_users_in_ou_success(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful retrieval of users in an OU."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock users list response for OU
        users_data = {
            'users': [
                {
                    'id': '123',
                    'primaryEmail': 'john.doe@test.com',
                    'name': {
                        'givenName': 'John',
                        'familyName': 'Doe',
                        'fullName': 'John Doe',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
                {
                    'id': '456',
                    'primaryEmail': 'jane.smith@test.com',
                    'name': {
                        'givenName': 'Jane',
                        'familyName': 'Smith',
                        'fullName': 'Jane Smith',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
            ]
        }
        mock_service.users().list().execute.return_value = users_data

        client = self.create_client(tmp_path)
        users = await client.get_users_in_ou('/Engineering')

        assert len(users) == 2
        assert users[0].primary_email == 'john.doe@test.com'
        assert users[1].primary_email == 'jane.smith@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_users_in_ou_invalid_user(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test get_users_in_ou with invalid user data."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock users list with invalid user data
        users_data = {
            'users': [
                {
                    'id': '123',
                    'primaryEmail': 'valid.user@test.com',
                    'name': {
                        'givenName': 'Valid',
                        'familyName': 'User',
                        'fullName': 'Valid User',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
                {
                    # Missing required 'id' field - will cause ValueError
                    'primaryEmail': 'invalid.user@test.com',
                    'name': {
                        'givenName': 'Invalid',
                        'familyName': 'User',
                        'fullName': 'Invalid User',
                    },
                },
            ]
        }
        mock_service.users().list().execute.return_value = users_data

        client = self.create_client(tmp_path)
        users = await client.get_users_in_ou('/Engineering')

        # Should only return the valid user
        assert len(users) == 1
        assert users[0].primary_email == 'valid.user@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_users_in_ou_not_found(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test get_users_in_ou when OU not found."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock 404 error
        error_resp = mock.Mock()
        error_resp.status = 404
        http_error = HttpError(resp=error_resp, content=b'OU not found')
        mock_service.users().list().execute.side_effect = http_error

        client = self.create_client(tmp_path)

        with pytest.raises(ValueError, match='OU not found: /NonExistent'):
            await client.get_users_in_ou('/NonExistent')

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_users_in_ou_http_error(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test get_users_in_ou with HTTP error other than 404."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock 500 error
        error_resp = mock.Mock()
        error_resp.status = 500
        http_error = HttpError(resp=error_resp, content=b'Server error')
        mock_service.users().list().execute.side_effect = http_error

        client = self.create_client(tmp_path)

        with pytest.raises(HttpError):
            await client.get_users_in_ou('/Engineering')

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_users_in_ou_pagination(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test get_users_in_ou with pagination."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock paginated response
        page1_data = {
            'users': [
                {
                    'id': '123',
                    'primaryEmail': 'user1@test.com',
                    'name': {
                        'givenName': 'User',
                        'familyName': 'One',
                        'fullName': 'User One',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
            ],
            'nextPageToken': 'next_page_token',
        }
        page2_data = {
            'users': [
                {
                    'id': '456',
                    'primaryEmail': 'user2@test.com',
                    'name': {
                        'givenName': 'User',
                        'familyName': 'Two',
                        'fullName': 'User Two',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
            ],
        }

        mock_service.users().list().execute.side_effect = [
            page1_data,
            page2_data,
        ]

        client = self.create_client(tmp_path)
        users = await client.get_users_in_ou('/Engineering')

        # Should have users from both pages
        assert len(users) == 2
        assert users[0].primary_email == 'user1@test.com'
        assert users[1].primary_email == 'user2@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_ou_success(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test successful OU retrieval."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock OU data
        ou_data = {
            'name': 'Engineering',
            'orgUnitPath': '/Engineering',
            'description': 'Engineering department',
            'parentOrgUnitPath': '/',
        }
        mock_service.orgunits().get().execute.return_value = ou_data

        # Mock users in OU
        users_data = {
            'users': [
                {
                    'id': '123',
                    'primaryEmail': 'john@test.com',
                    'name': {
                        'givenName': 'John',
                        'familyName': 'Doe',
                        'fullName': 'John Doe',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
                {
                    'id': '456',
                    'primaryEmail': 'jane@test.com',
                    'name': {
                        'givenName': 'Jane',
                        'familyName': 'Smith',
                        'fullName': 'Jane Smith',
                    },
                    'suspended': False,
                    'orgUnitPath': '/Engineering',
                },
            ]
        }
        mock_service.users().list().execute.return_value = users_data

        client = self.create_client(tmp_path)
        ou = await client.get_ou('/Engineering')

        assert isinstance(ou, GoogleOU)
        assert ou.name == 'Engineering'
        assert ou.org_unit_path == '/Engineering'
        assert ou.description == 'Engineering department'
        assert ou.parent_org_unit_path == '/'
        assert ou.user_count == 2
        assert len(ou.user_emails) == 2

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_child_ous(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test retrieval of child OUs."""
        # Mock service
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock child OUs data
        child_ous_data = {
            'organizationUnits': [
                {
                    'name': 'Frontend',
                    'orgUnitPath': '/Engineering/Frontend',
                    'description': 'Frontend team',
                    'parentOrgUnitPath': '/Engineering',
                },
                {
                    'name': 'Backend',
                    'orgUnitPath': '/Engineering/Backend',
                    'description': 'Backend team',
                    'parentOrgUnitPath': '/Engineering',
                },
            ]
        }
        mock_service.orgunits().list().execute.return_value = child_ous_data

        client = self.create_client(tmp_path)

        # Mock get_ou method for each child OU
        with mock.patch.object(client, 'get_ou') as mock_get_ou:
            mock_get_ou.side_effect = [
                GoogleOU(
                    org_unit_path='/Engineering/Frontend',
                    name='Frontend',
                    description='Frontend team',
                    parent_org_unit_path='/Engineering',
                    user_count=0,
                    user_emails=[],
                ),
                GoogleOU(
                    org_unit_path='/Engineering/Backend',
                    name='Backend',
                    description='Backend team',
                    parent_org_unit_path='/Engineering',
                    user_count=0,
                    user_emails=[],
                ),
            ]
            child_ous = await client.get_child_ous('/Engineering')

            assert len(child_ous) == 2
            assert child_ous[0].name == 'Frontend'
            assert child_ous[0].org_unit_path == '/Engineering/Frontend'
            assert child_ous[1].name == 'Backend'
            assert child_ous[1].org_unit_path == '/Engineering/Backend'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_all_users_in_ous(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test getting all unique users across multiple OUs."""
        client = self.create_client(tmp_path)

        # Mock the methods this function calls
        with mock.patch.object(client, 'get_users_in_ou') as mock_get_users:
            # Setup mock data
            user1 = GoogleUser(
                id='1',
                primary_email='user1@test.com',
                given_name='User',
                family_name='One',
                full_name='User One',
                org_unit_path='/Engineering',
            )
            user2 = GoogleUser(
                id='2',
                primary_email='user2@test.com',
                given_name='User',
                family_name='Two',
                full_name='User Two',
                org_unit_path='/Marketing',
            )
            user3 = GoogleUser(
                id='1',  # Same user in different OU (duplicate)
                primary_email='user1@test.com',
                given_name='User',
                family_name='One',
                full_name='User One',
                org_unit_path='/Engineering/Backend',
            )

            mock_get_users.side_effect = [
                [user1],  # First OU
                [user2],  # Second OU
                [user3],  # Third OU (duplicate user1)
            ]

            users = await client.get_all_users_in_ous(
                ['/Engineering', '/Marketing', '/Engineering/Backend']
            )

            # Should have 2 unique users (duplicates removed by email)
            assert len(users) == 2
            user_emails = {user.primary_email for user in users}
            assert user_emails == {'user1@test.com', 'user2@test.com'}

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_individual_users(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test getting individual users by email."""
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock get user responses
        def mock_get_user(userKey: str) -> mock.Mock:
            if userKey == 'john@test.com':
                return mock.Mock(
                    execute=mock.Mock(
                        return_value={
                            'id': '123',
                            'primaryEmail': 'john@test.com',
                            'name': {
                                'givenName': 'John',
                                'familyName': 'Doe',
                                'fullName': 'John Doe',
                            },
                            'orgUnitPath': '/',
                        }
                    )
                )
            elif userKey == 'jane@test.com':
                return mock.Mock(
                    execute=mock.Mock(
                        return_value={
                            'id': '456',
                            'primaryEmail': 'jane@test.com',
                            'name': {
                                'givenName': 'Jane',
                                'familyName': 'Smith',
                                'fullName': 'Jane Smith',
                            },
                            'orgUnitPath': '/Sales',
                        }
                    )
                )
            else:
                error_resp = mock.Mock()
                error_resp.status = 404
                raise HttpError(resp=error_resp, content=b'Not found')

        mock_service.users().get.side_effect = mock_get_user

        client = self.create_client(tmp_path)

        # Test successful retrieval
        users = await client.get_individual_users(
            ['john@test.com', 'jane@test.com']
        )

        assert len(users) == 2
        assert users[0].primary_email == 'john@test.com'
        assert users[1].primary_email == 'jane@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_individual_users_with_not_found(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test getting individual users when some don't exist."""
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        def mock_get_user(userKey: str) -> mock.Mock:
            if userKey == 'john@test.com':
                return mock.Mock(
                    execute=mock.Mock(
                        return_value={
                            'id': '123',
                            'primaryEmail': 'john@test.com',
                            'name': {
                                'givenName': 'John',
                                'familyName': 'Doe',
                                'fullName': 'John Doe',
                            },
                        }
                    )
                )
            else:
                error_resp = mock.Mock()
                error_resp.status = 404
                raise HttpError(resp=error_resp, content=b'Not found')

        mock_service.users().get.side_effect = mock_get_user

        client = self.create_client(tmp_path)

        # Should skip missing users and return only found ones
        users = await client.get_individual_users(
            ['john@test.com', 'missing@test.com']
        )

        assert len(users) == 1
        assert users[0].primary_email == 'john@test.com'

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_all_users(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test getting all users from OUs and individual list combined."""
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock OU users list response
        ou_users_data = {
            'users': [
                {
                    'id': '123',
                    'primaryEmail': 'ou.user@test.com',
                    'name': {
                        'givenName': 'OU',
                        'familyName': 'User',
                        'fullName': 'OU User',
                    },
                    'orgUnitPath': '/Engineering',
                }
            ]
        }

        # Mock individual user get response
        def mock_get_user(userKey: str) -> mock.Mock:
            if userKey == 'individual@test.com':
                return mock.Mock(
                    execute=mock.Mock(
                        return_value={
                            'id': '456',
                            'primaryEmail': 'individual@test.com',
                            'name': {
                                'givenName': 'Individual',
                                'familyName': 'User',
                                'fullName': 'Individual User',
                            },
                            'orgUnitPath': '/',
                        }
                    )
                )
            else:
                error_resp = mock.Mock()
                error_resp.status = 404
                raise HttpError(resp=error_resp, content=b'Not found')

        mock_service.users().list().execute.return_value = ou_users_data
        mock_service.users().get.side_effect = mock_get_user
        mock_service.orgunits().list().execute.return_value = {
            'organizationUnits': []
        }

        client = self.create_client(tmp_path)

        users = await client.get_all_users(
            ['/Engineering'], ['individual@test.com']
        )

        assert len(users) == 2
        user_emails = {user.primary_email for user in users}
        assert user_emails == {'ou.user@test.com', 'individual@test.com'}

    @mock.patch('g2g_scim_sync.google_client.build')
    @mock.patch('g2g_scim_sync.google_client.Credentials')
    @pytest.mark.asyncio
    async def test_get_all_users_deduplication(
        self,
        mock_credentials: mock.Mock,
        mock_build: mock.Mock,
        tmp_path: Path,
    ) -> None:
        """Test deduplication between OUs and individual list."""
        mock_service = mock.Mock()
        mock_build.return_value = mock_service

        # Mock OU users list response with duplicate user
        ou_users_data = {
            'users': [
                {
                    'id': '123',
                    'primaryEmail': 'duplicate@test.com',
                    'name': {
                        'givenName': 'Duplicate',
                        'familyName': 'User',
                        'fullName': 'Duplicate User',
                    },
                    'orgUnitPath': '/Engineering',
                }
            ]
        }

        # Mock individual user get response with same user
        def mock_get_user(userKey: str) -> mock.Mock:
            if userKey == 'duplicate@test.com':
                return mock.Mock(
                    execute=mock.Mock(
                        return_value={
                            'id': '123',
                            'primaryEmail': 'duplicate@test.com',
                            'name': {
                                'givenName': 'Duplicate',
                                'familyName': 'User',
                                'fullName': 'Duplicate User',
                            },
                            'orgUnitPath': '/Engineering',
                        }
                    )
                )
            else:
                error_resp = mock.Mock()
                error_resp.status = 404
                raise HttpError(resp=error_resp, content=b'Not found')

        mock_service.users().list().execute.return_value = ou_users_data
        mock_service.users().get.side_effect = mock_get_user
        mock_service.orgunits().list().execute.return_value = {
            'organizationUnits': []
        }

        client = self.create_client(tmp_path)

        users = await client.get_all_users(
            ['/Engineering'], ['duplicate@test.com']
        )

        # Should only have 1 user even though it appears in both lists
        assert len(users) == 1
        assert users[0].primary_email == 'duplicate@test.com'

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

    def test_parse_datetime_complete(self) -> None:
        """Test parsing complete datetime string."""
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as tmp_dir:
            client = self.create_client(Path(tmp_dir))
            result = client._parse_datetime('2024-01-15T10:30:45.123Z')

            assert result == datetime(
                2024, 1, 15, 10, 30, 45, 123000, timezone.utc
            )

    def test_parse_datetime_none(self) -> None:
        """Test parsing None datetime."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            client = self.create_client(Path(tmp_dir))
            result = client._parse_datetime(None)
            assert result is None
