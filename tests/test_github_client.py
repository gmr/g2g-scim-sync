"""Tests for GitHub SCIM client."""

from __future__ import annotations

import pytest
from unittest import mock


from g2g_scim_sync.github_client import GitHubScimClient
from g2g_scim_sync.models import GitHubGroup, ScimUser


class TestGitHubScimClient:
    """Tests for GitHubScimClient."""

    def create_client(self) -> GitHubScimClient:
        """Create a test client."""
        return GitHubScimClient(
            hostname='github.company.com',
            scim_token='ghes_test_token',  # noqa: S106
            enterprise_account='test-org',
        )

    def create_cloud_client(self) -> GitHubScimClient:
        """Create a GitHub Enterprise Cloud test client."""
        return GitHubScimClient(
            hostname='github.com',
            scim_token='ghe_test_token',  # noqa: S106
            enterprise_account='test-org',
        )

    def test_init_enterprise_server(self) -> None:
        """Test client initialization for GitHub Enterprise Server."""
        client = self.create_client()

        assert client.hostname == 'github.company.com'
        assert client.scim_token == 'ghes_test_token'  # noqa: S105
        assert client.enterprise_account == 'test-org'
        assert client.timeout == 30.0
        assert (
            client.base_url
            == 'https://github.company.com/api/v3/scim/v2/enterprises'
        )
        assert client.enterprise_name == 'test-org'

    def test_init_enterprise_cloud(self) -> None:
        """Test client initialization for GitHub Enterprise Cloud."""
        client = self.create_cloud_client()

        assert client.hostname == 'github.com'
        assert client.base_url == 'https://api.github.com/scim/v2/enterprises'
        assert client.enterprise_name == 'test-org'

    def test_init_custom_timeout(self) -> None:
        """Test client initialization with custom timeout."""
        client = GitHubScimClient(
            hostname='github.company.com',
            scim_token='token',  # noqa: S106
            enterprise_account='org',
            timeout=60.0,
        )

        assert client.timeout == 60.0

    @mock.patch('httpx.AsyncClient')
    def test_create_client(self, mock_async_client: mock.Mock) -> None:
        """Test HTTP client creation."""
        client = self.create_client()

        # Access get_client method to trigger creation
        _ = client.get_client()

        mock_async_client.assert_called_once_with(
            base_url='https://github.company.com/api/v3/scim/v2/enterprises/test-org',
            headers={
                'Authorization': 'Bearer ghes_test_token',
                'Content-Type': 'application/scim+json',
                'Accept': 'application/scim+json',
                'User-Agent': 'g2g-scim-sync/1.0.0',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            timeout=30.0,
        )

    @pytest.mark.asyncio
    async def test_close(self) -> None:
        """Test client cleanup."""
        client = self.create_client()

        # Create mock client
        mock_client = mock.AsyncMock()
        client._client = mock_client

        await client.close()

        mock_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        """Test async context manager."""
        client = self.create_client()

        with mock.patch.object(client, 'close') as mock_close:
            async with client as ctx_client:
                assert ctx_client is client

            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_users_single_page(self) -> None:
        """Test getting users with single page response."""
        client = self.create_client()

        # Mock response data
        response_data = {
            'totalResults': 2,
            'Resources': [
                {
                    'id': 'user1',
                    'userName': 'john.doe',
                    'emails': [
                        {'value': 'john.doe@test.com', 'primary': True}
                    ],
                    'name': {'givenName': 'John', 'familyName': 'Doe'},
                    'active': True,
                },
                {
                    'id': 'user2',
                    'userName': 'jane.smith',
                    'emails': [
                        {'value': 'jane.smith@test.com', 'primary': True}
                    ],
                    'name': {'givenName': 'Jane', 'familyName': 'Smith'},
                    'active': False,
                },
            ],
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get.return_value = mock_response

            users = await client.get_users()

        assert len(users) == 2
        assert users[0].user_name == 'john.doe'
        assert users[0].active is True
        assert users[1].user_name == 'jane.smith'
        assert users[1].active is False

    @pytest.mark.asyncio
    async def test_get_users_multiple_pages(self) -> None:
        """Test getting users with pagination."""
        client = self.create_client()

        # Mock first page response
        page1_data = {
            'totalResults': 3,
            'Resources': [
                {
                    'id': 'user1',
                    'userName': 'user1',
                    'emails': [{'value': 'user1@test.com'}],
                    'name': {'givenName': 'User', 'familyName': 'One'},
                    'active': True,
                },
                {
                    'id': 'user2',
                    'userName': 'user2',
                    'emails': [{'value': 'user2@test.com'}],
                    'name': {'givenName': 'User', 'familyName': 'Two'},
                    'active': True,
                },
            ],
        }

        # Mock second page response
        page2_data = {
            'totalResults': 3,
            'Resources': [
                {
                    'id': 'user3',
                    'userName': 'user3',
                    'emails': [{'value': 'user3@test.com'}],
                    'name': {'givenName': 'User', 'familyName': 'Three'},
                    'active': True,
                }
            ],
        }

        mock_response1 = mock.Mock()
        mock_response1.json.return_value = page1_data
        mock_response1.raise_for_status.return_value = None

        mock_response2 = mock.Mock()
        mock_response2.json.return_value = page2_data
        mock_response2.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get.side_effect = [mock_response1, mock_response2]

            users = await client.get_users(count=2)

        assert len(users) == 3
        assert users[0].user_name == 'user1'
        assert users[1].user_name == 'user2'
        assert users[2].user_name == 'user3'

    @pytest.mark.asyncio
    async def test_get_user(self) -> None:
        """Test getting a specific user."""
        client = self.create_client()

        response_data = {
            'id': 'user123',
            'userName': 'test.user',
            'emails': [{'value': 'test.user@test.com', 'primary': True}],
            'name': {'givenName': 'Test', 'familyName': 'User'},
            'active': True,
            'externalId': 'ext123',
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get.return_value = mock_response

            user = await client.get_user('user123')

        assert user.id == 'user123'
        assert user.user_name == 'test.user'
        assert user.external_id == 'ext123'
        mock_client.get.assert_called_once_with('/Users/user123')

    @pytest.mark.asyncio
    async def test_create_user(self) -> None:
        """Test creating a new user."""
        client = self.create_client()

        # Input user
        new_user = ScimUser(
            user_name='new.user',
            emails=[{'value': 'new.user@test.com', 'primary': True}],
            name={'givenName': 'New', 'familyName': 'User'},
            active=True,
            external_id='ext456',
        )

        # Mock response
        response_data = {
            'id': 'created123',
            'userName': 'new.user',
            'emails': [{'value': 'new.user@test.com', 'primary': True}],
            'name': {'givenName': 'New', 'familyName': 'User'},
            'active': True,
            'externalId': 'ext456',
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.post.return_value = mock_response

            created_user = await client.create_user(new_user)

        assert created_user.id == 'created123'
        assert created_user.user_name == 'new.user'

        # Check that POST was called with correct data
        mock_client.post.assert_called_once_with(
            '/Users',
            json={
                'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
                'userName': 'new.user',
                'emails': [{'value': 'new.user@test.com', 'primary': True}],
                'name': {'givenName': 'New', 'familyName': 'User'},
                'active': True,
                'roles': [{'value': 'user', 'primary': True}],
                'externalId': 'ext456',
            },
        )

    @pytest.mark.asyncio
    async def test_update_user(self) -> None:
        """Test updating an existing user."""
        client = self.create_client()

        # Updated user data
        updated_user = ScimUser(
            id='user123',
            user_name='updated.user',
            emails=[{'value': 'updated.user@test.com', 'primary': True}],
            name={'givenName': 'Updated', 'familyName': 'User'},
            active=False,
        )

        # Mock response
        response_data = {
            'id': 'user123',
            'userName': 'updated.user',
            'emails': [{'value': 'updated.user@test.com', 'primary': True}],
            'name': {'givenName': 'Updated', 'familyName': 'User'},
            'active': False,
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.put.return_value = mock_response

            result_user = await client.update_user('user123', updated_user)

        assert result_user.user_name == 'updated.user'
        assert result_user.active is False

        mock_client.put.assert_called_once_with(
            '/Users/user123',
            json={
                'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
                'userName': 'updated.user',
                'emails': [
                    {'value': 'updated.user@test.com', 'primary': True}
                ],
                'name': {'givenName': 'Updated', 'familyName': 'User'},
                'active': False,
                'roles': [{'value': 'user', 'primary': True}],
            },
        )

    @pytest.mark.asyncio
    async def test_delete_user(self) -> None:
        """Test deleting a user."""
        client = self.create_client()

        mock_response = mock.Mock()
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.delete.return_value = mock_response

            await client.delete_user('user123')

        mock_client.delete.assert_called_once_with('/Users/user123')

    @pytest.mark.asyncio
    async def test_suspend_user(self) -> None:
        """Test suspending a user."""
        client = self.create_client()

        # Mock response
        response_data = {
            'id': 'user123',
            'userName': 'test.user',
            'emails': [{'value': 'test.user@test.com', 'primary': True}],
            'name': {'givenName': 'Test', 'familyName': 'User'},
            'active': False,
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.patch.return_value = mock_response

            suspended_user = await client.suspend_user('user123')

        assert suspended_user.active is False

        mock_client.patch.assert_called_once_with(
            '/Users/user123',
            json={
                'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
                'Operations': [
                    {
                        'op': 'replace',
                        'path': 'active',
                        'value': False,
                    }
                ],
            },
        )

    @pytest.mark.asyncio
    async def test_get_groups(self) -> None:
        """Test getting all groups."""
        client = self.create_client()

        response_data = {
            'totalResults': 2,
            'Resources': [
                {
                    'id': '1',
                    'displayName': 'Engineering',
                    'externalId': 'engineering',
                    'members': [
                        {'value': 'john.doe', 'display': 'john.doe'},
                        {'value': 'jane.smith', 'display': 'jane.smith'},
                    ],
                },
                {
                    'id': '2',
                    'displayName': 'Sales',
                    'externalId': 'sales',
                    'members': [
                        {'value': 'bob.wilson', 'display': 'bob.wilson'}
                    ],
                },
            ],
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with mock.patch.object(client, 'get_client') as mock_get_client:
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.get.return_value = mock_response

            teams = await client.get_groups()

        assert len(teams) == 2
        assert teams[0].name == 'Engineering'
        assert teams[0].slug == 'engineering'
        assert teams[0].members == ['john.doe', 'jane.smith']
        assert teams[1].name == 'Sales'
        assert teams[1].members == ['bob.wilson']

    @pytest.mark.asyncio
    async def test_create_group(self) -> None:
        """Test creating a new group."""
        client = self.create_client()

        # Input team
        new_team = GitHubGroup(
            name='Marketing',
            slug='marketing',
            members=['alice.brown', 'charlie.davis'],
        )

        # Mock response
        response_data = {
            'id': '3',
            'displayName': 'Marketing',
            'externalId': 'marketing',
            'members': [
                {'value': 'alice.brown', 'display': 'alice.brown'},
                {'value': 'charlie.davis', 'display': 'charlie.davis'},
            ],
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with (
            mock.patch.object(client, 'get_client') as mock_get_client,
            mock.patch.object(
                client, '_get_member_scim_data'
            ) as mock_get_member_scim_data,
        ):
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.post.return_value = mock_response
            mock_get_member_scim_data.return_value = [
                {
                    'value': 'alice-scim-id',
                    '$ref': 'ref-alice',
                    'displayName': 'alice.brown',
                },
                {
                    'value': 'charlie-scim-id',
                    '$ref': 'ref-charlie',
                    'displayName': 'charlie.davis',
                },
            ]

            created_team = await client.create_group(new_team)

        assert created_team.id == '3'
        assert created_team.name == 'Marketing'
        assert created_team.slug == 'marketing'

        mock_client.post.assert_called_once_with(
            '/Groups',
            json={
                'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group'],
                'displayName': 'Marketing',
                'externalId': 'marketing',
                'members': [
                    {
                        'value': 'alice-scim-id',
                        '$ref': 'ref-alice',
                        'displayName': 'alice.brown',
                    },
                    {
                        'value': 'charlie-scim-id',
                        '$ref': 'ref-charlie',
                        'displayName': 'charlie.davis',
                    },
                ],
            },
        )

    @pytest.mark.asyncio
    async def test_update_group(self) -> None:
        """Test updating an existing group."""
        client = self.create_client()

        # Updated team
        updated_team = GitHubGroup(
            id='3',
            name='Marketing Team',
            slug='marketing-team',
            members=['alice.brown'],
        )

        # Mock response
        response_data = {
            'id': '3',
            'displayName': 'Marketing Team',
            'externalId': 'marketing-team',
            'members': [{'value': 'alice.brown', 'display': 'alice.brown'}],
        }

        mock_response = mock.Mock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status.return_value = None

        with (
            mock.patch.object(client, 'get_client') as mock_get_client,
            mock.patch.object(
                client, '_get_member_scim_data'
            ) as mock_get_member_scim_data,
        ):
            mock_client = mock.AsyncMock()
            mock_get_client.return_value = mock_client
            mock_client.put.return_value = mock_response
            mock_get_member_scim_data.return_value = [
                {
                    'value': 'alice-scim-id',
                    '$ref': 'ref-alice',
                    'displayName': 'alice.brown',
                },
            ]

            result_team = await client.update_group('3', updated_team)

        assert result_team.name == 'Marketing Team'
        assert result_team.slug == 'marketing-team'
        assert result_team.members == ['alice.brown']

        mock_client.put.assert_called_once_with(
            '/Groups/3',
            json={
                'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group'],
                'displayName': 'Marketing Team',
                'externalId': 'marketing-team',
                'members': [
                    {
                        'value': 'alice-scim-id',
                        '$ref': 'ref-alice',
                        'displayName': 'alice.brown',
                    },
                ],
            },
        )

    def test_parse_scim_user(self) -> None:
        """Test parsing SCIM user data."""
        client = self.create_client()

        user_data = {
            'id': 'user123',
            'userName': 'test.user',
            'emails': [{'value': 'test.user@test.com', 'primary': True}],
            'name': {'givenName': 'Test', 'familyName': 'User'},
            'active': True,
            'externalId': 'ext123',
        }

        user = client._parse_scim_user(user_data)

        assert user.id == 'user123'
        assert user.user_name == 'test.user'
        assert user.emails == [
            {'value': 'test.user@test.com', 'primary': True}
        ]
        assert user.name == {'givenName': 'Test', 'familyName': 'User'}
        assert user.active is True
        assert user.external_id == 'ext123'

    def test_parse_scim_user_minimal(self) -> None:
        """Test parsing SCIM user data with minimal fields."""
        client = self.create_client()

        user_data = {
            'userName': 'minimal.user',
            'emails': [{'value': 'minimal.user@test.com'}],
            'name': {'givenName': 'Minimal', 'familyName': 'User'},
        }

        user = client._parse_scim_user(user_data)

        assert user.id is None
        assert user.user_name == 'minimal.user'
        assert user.active is True  # default value
        assert user.external_id is None

    def test_scim_user_to_dict(self) -> None:
        """Test converting ScimUser to dict."""
        client = self.create_client()

        user = ScimUser(
            user_name='test.user',
            emails=[{'value': 'test.user@test.com', 'primary': True}],
            name={'givenName': 'Test', 'familyName': 'User'},
            active=False,
            external_id='ext123',
        )

        user_dict = client._scim_user_to_dict(user)

        expected = {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
            'userName': 'test.user',
            'emails': [{'value': 'test.user@test.com', 'primary': True}],
            'name': {'givenName': 'Test', 'familyName': 'User'},
            'active': False,
            'roles': [{'value': 'user', 'primary': True}],
            'externalId': 'ext123',
        }

        assert user_dict == expected

    def test_scim_user_to_dict_no_external_id(self) -> None:
        """Test converting ScimUser to dict without external ID."""
        client = self.create_client()

        user = ScimUser(
            user_name='test.user',
            emails=[{'value': 'test.user@test.com'}],
            name={'givenName': 'Test', 'familyName': 'User'},
            active=True,
        )

        user_dict = client._scim_user_to_dict(user)

        assert 'externalId' not in user_dict
        assert user_dict['active'] is True

    def test_parse_scim_group(self) -> None:
        """Test parsing SCIM group data."""
        client = self.create_client()

        group_data = {
            'id': '123',
            'displayName': 'Test Team',
            'externalId': 'test-team',
            'description': 'A test team',
            'members': [
                {'value': 'user1', 'display': 'user1'},
                {'value': 'user2', 'display': 'user2'},
            ],
        }

        team = client._parse_scim_group(group_data)

        assert team.id == '123'
        assert team.name == 'Test Team'
        assert team.slug == 'test-team'
        assert team.description == 'A test team'
        assert team.members == ['user1', 'user2']

    def test_parse_scim_group_no_external_id(self) -> None:
        """Test parsing SCIM group data without external ID."""
        client = self.create_client()

        group_data = {
            'id': '456',
            'displayName': 'Another Team',
            'members': [],
        }

        team = client._parse_scim_group(group_data)

        assert team.id == '456'
        assert team.name == 'Another Team'
        assert team.slug == 'another team'  # fallback from display name
        assert team.description is None
        assert team.members == []

    @pytest.mark.asyncio
    async def test_get_groups_scim_not_supported(self) -> None:
        """Test get_groups when SCIM Groups API is not supported (404)."""
        from g2g_scim_sync.models import GitHubScimNotSupportedException
        import httpx

        client = self.create_client()

        with mock.patch('httpx.AsyncClient.get') as mock_get:
            # Mock 404 response for SCIM Groups API
            mock_response = mock.MagicMock()
            mock_response.status_code = 404
            mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
                message='Not Found',
                request=mock.MagicMock(),
                response=mock_response,
            )
            mock_get.return_value = mock_response

            with pytest.raises(GitHubScimNotSupportedException) as exc_info:
                await client.get_groups()

            assert 'SCIM Groups API is not available' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_groups_empty_resources(self) -> None:
        """Test get_groups when no groups are found."""
        client = self.create_client()

        with mock.patch('httpx.AsyncClient.get') as mock_get:
            # Mock empty response
            mock_response = mock.MagicMock()
            mock_response.json.return_value = {
                'Resources': [],
                'totalResults': 0,
                'startIndex': 1,
                'itemsPerPage': 20,
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            teams = await client.get_groups()
            assert teams == []

    @pytest.mark.asyncio
    async def test_create_group_scim_not_supported(self) -> None:
        """Test create_group when SCIM Groups API is not supported (404)."""
        from g2g_scim_sync.models import GitHubScimNotSupportedException
        import httpx

        client = self.create_client()
        team = GitHubGroup(
            name='Test Team',
            slug='test-team',
            description='Test description',
            members=['user1', 'user2'],
        )

        # Mock the _get_member_scim_data method to avoid the HTTP call
        with mock.patch.object(
            client, '_get_member_scim_data'
        ) as mock_get_members:
            mock_get_members.return_value = [
                {
                    'value': 'user1',
                    '$ref': 'https://api.github.com/scim/v2/enterprises/test-org/Users/user1',
                    'displayName': 'user1',
                },
                {
                    'value': 'user2',
                    '$ref': 'https://api.github.com/scim/v2/enterprises/test-org/Users/user2',
                    'displayName': 'user2',
                },
            ]

            with mock.patch('httpx.AsyncClient.post') as mock_post:
                # Mock 404 response for SCIM Groups API
                mock_response = mock.MagicMock()
                mock_response.status_code = 404
                mock_response.raise_for_status.side_effect = (
                    httpx.HTTPStatusError(
                        message='Not Found',
                        request=mock.MagicMock(),
                        response=mock_response,
                    )
                )
                mock_post.return_value = mock_response

                with pytest.raises(
                    GitHubScimNotSupportedException
                ) as exc_info:
                    await client.create_group(team)

            assert 'SCIM Groups API is not available' in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_member_scim_data_missing_user(self) -> None:
        """Test _get_member_scim_data when username not found in SCIM users."""
        client = self.create_client()

        with mock.patch.object(client, 'get_users') as mock_get_users:
            # Mock users response with one user
            mock_user = ScimUser(
                id='user123',
                user_name='existing.user',
                emails=[{'value': 'existing.user@test.com'}],
                name={'givenName': 'Existing', 'familyName': 'User'},
            )
            mock_get_users.return_value = [mock_user]

            # Test with missing username
            result = await client._get_member_scim_data(['missing.user'])

            # Should return empty list and log warning for missing user
            assert result == []
