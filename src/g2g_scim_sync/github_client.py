"""GitHub Enterprise SCIM API client."""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from g2g_scim_sync.models import (
    GitHubGroup,
    ScimUser,
    GitHubScimNotSupportedException,
)

logger = logging.getLogger(__name__)


class GitHubScimClient:
    """GitHub Enterprise SCIM API client for user and idP Group management."""

    def __init__(
        self: GitHubScimClient,
        hostname: str,
        scim_token: str,
        enterprise_account: str,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the GitHub SCIM client.

        Args:
            hostname: GitHub Enterprise hostname
            scim_token: SCIM API token with enterprise:scim scope
            enterprise_account: GitHub enterprise account name
            timeout: HTTP request timeout in seconds
        """
        # Ensure hostname doesn't have protocol
        if hostname.startswith(('http://', 'https://')):
            hostname = hostname.split('://', 1)[1]

        self.hostname = hostname.rstrip('/')
        self.scim_token = scim_token
        self.enterprise_account = enterprise_account
        self.timeout = timeout

        # Build URLs based on hostname
        if hostname == 'github.com':
            # GitHub Enterprise Cloud
            self.base_url = 'https://api.github.com/scim/v2/enterprises'
            self.enterprise_name = enterprise_account
        else:
            # GitHub Enterprise Server
            self.base_url = f'https://{hostname}/api/v3/scim/v2/enterprises'
            self.enterprise_name = enterprise_account

        self._client: Optional[httpx.AsyncClient] = None

    def get_client(self: GitHubScimClient) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self: GitHubScimClient) -> httpx.AsyncClient:
        """Create the HTTP client with proper headers."""
        headers = {
            'Authorization': f'Bearer {self.scim_token}',
            'Content-Type': 'application/scim+json',
            'Accept': 'application/scim+json',
            'User-Agent': 'g2g-scim-sync/1.0.0',
            'X-GitHub-Api-Version': '2022-11-28',
        }

        return httpx.AsyncClient(
            base_url=f'{self.base_url}/{self.enterprise_name}',
            headers=headers,
            timeout=self.timeout,
        )

    async def close(self: GitHubScimClient) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self: GitHubScimClient) -> GitHubScimClient:
        """Async context manager entry."""
        return self

    async def __aexit__(
        self: GitHubScimClient,
        exc_type: type,
        exc_val: Exception,
        exc_tb: object,
    ) -> None:
        """Async context manager exit."""
        await self.close()

    async def get_users(
        self: GitHubScimClient,
        start_index: int = 1,
        count: int = 100,
    ) -> list[ScimUser]:
        """Get all SCIM users from GitHub Enterprise.

        Args:
            start_index: Starting index for pagination (1-based)
            count: Number of users to retrieve per page

        Returns:
            List of SCIM users
        """
        users = []
        current_start = start_index

        while True:
            response = await self.get_client().get(
                '/Users',
                params={
                    'startIndex': current_start,
                    'count': count,
                },
            )
            response.raise_for_status()
            data = response.json()

            resources = data.get('Resources', [])
            if not resources:
                break

            for user_data in resources:
                user = self._parse_scim_user(user_data)
                users.append(user)

            # Check if there are more results
            total_results = data.get('totalResults', 0)
            if current_start + len(resources) > total_results:
                break

            current_start += len(resources)

        logger.debug(f'Retrieved {len(users)} users from GitHub Enterprise')
        return users

    async def get_user(self: GitHubScimClient, user_id: str) -> ScimUser:
        """Get a specific SCIM user by ID.

        Args:
            user_id: SCIM user ID

        Returns:
            SCIM user

        Raises:
            httpx.HTTPStatusError: If user not found or API error
        """
        response = await self.get_client().get(f'/Users/{user_id}')
        response.raise_for_status()

        user_data = response.json()
        return self._parse_scim_user(user_data)

    async def create_user(self: GitHubScimClient, user: ScimUser) -> ScimUser:
        """Create a new SCIM user.

        Args:
            user: SCIM user to create

        Returns:
            Created SCIM user with ID
        """
        user_data = self._scim_user_to_dict(user)

        response = await self.get_client().post('/Users', json=user_data)
        response.raise_for_status()

        created_data = response.json()
        created_user = self._parse_scim_user(created_data)

        logger.debug(f'Created user: {created_user.user_name}')
        return created_user

    async def update_user(
        self: GitHubScimClient,
        user_id: str,
        user: ScimUser,
    ) -> ScimUser:
        """Update an existing SCIM user.

        Args:
            user_id: SCIM user ID to update
            user: Updated SCIM user data

        Returns:
            Updated SCIM user
        """
        user_data = self._scim_user_to_dict(user)

        response = await self.get_client().put(
            f'/Users/{user_id}', json=user_data
        )
        response.raise_for_status()

        updated_data = response.json()
        updated_user = self._parse_scim_user(updated_data)

        logger.debug(f'Updated user: {updated_user.user_name}')
        return updated_user

    async def delete_user(self: GitHubScimClient, user_id: str) -> None:
        """Delete a SCIM user.

        Args:
            user_id: SCIM user ID to delete
        """
        response = await self.get_client().delete(f'/Users/{user_id}')
        response.raise_for_status()

        logger.debug(f'Deleted user ID: {user_id}')

    async def suspend_user(
        self: GitHubScimClient,
        user_id: str,
    ) -> ScimUser:
        """Suspend a SCIM user by setting active=False.

        Args:
            user_id: SCIM user ID to suspend

        Returns:
            Updated SCIM user
        """
        patch_data = {
            'schemas': ['urn:ietf:params:scim:api:messages:2.0:PatchOp'],
            'Operations': [
                {
                    'op': 'replace',
                    'path': 'active',
                    'value': False,
                }
            ],
        }

        response = await self.get_client().patch(
            f'/Users/{user_id}', json=patch_data
        )
        response.raise_for_status()

        updated_data = response.json()
        updated_user = self._parse_scim_user(updated_data)

        logger.debug(f'Suspended user: {updated_user.user_name}')
        return updated_user

    async def get_groups(
        self: GitHubScimClient,
        start_index: int = 1,
        count: int = 100,
    ) -> list[GitHubGroup]:
        """Get all SCIM groups (idP Groups) from GitHub Enterprise.

        Args:
            start_index: Starting index for pagination (1-based)
            count: Number of groups to retrieve per page

        Returns:
            List of GitHub idP Groups

        Raises:
            GitHubScimNotSupportedException: If SCIM Groups API is not
                supported
        """
        groups = []
        current_start = start_index

        while True:
            try:
                response = await self.get_client().get(
                    '/Groups',
                    params={
                        'startIndex': current_start,
                        'count': count,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    raise GitHubScimNotSupportedException(
                        'SCIM Groups API is not available for this GitHub '
                        'Enterprise instance. Groups may be managed through '
                        'your identity provider instead of the SCIM API.'
                    ) from e
                raise

            data = response.json()

            resources = data.get('Resources', [])
            if not resources:
                break

            for group_data in resources:
                group = self._parse_scim_group(group_data)
                groups.append(group)

            # Check if there are more results
            total_results = data.get('totalResults', 0)
            if current_start + len(resources) > total_results:
                break

            current_start += len(resources)

        logger.debug(
            f'Retrieved {len(groups)} idP Groups from GitHub Enterprise'
        )
        return groups

    async def create_group(
        self: GitHubScimClient, group: GitHubGroup
    ) -> GitHubGroup:
        """Create a new SCIM group (idP Group).

        Args:
            group: GitHub idP Group to create

        Returns:
            Created GitHub idP Group with ID

        Raises:
            GitHubScimNotSupportedException: If SCIM Groups API is not
                supported
        """
        # Get member SCIM user IDs by looking up usernames
        members = []
        if group.members:
            members = await self._get_member_scim_data(group.members)

        group_data = {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group'],
            'displayName': group.name,
            'externalId': group.slug,
            'members': members,
        }

        try:
            response = await self.get_client().post('/Groups', json=group_data)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise GitHubScimNotSupportedException(
                    'SCIM Groups API is not available for this GitHub '
                    'Enterprise instance. This may be because groups are '
                    'managed through your identity provider instead of the '
                    'SCIM API. User provisioning will continue without team '
                    'creation.'
                ) from e
            raise

        created_data = response.json()
        created_group = self._parse_scim_group(created_data)

        logger.debug(f'Created idP Group: {created_group.name}')
        return created_group

    async def update_group(
        self: GitHubScimClient,
        group_id: str,
        group: GitHubGroup,
    ) -> GitHubGroup:
        """Update an existing SCIM group (team).

        Args:
            group_id: SCIM group ID to update
            team: Updated GitHub team data

        Returns:
            Updated GitHub team
        """
        # Get member SCIM user IDs by looking up usernames
        members = []
        if group.members:
            members = await self._get_member_scim_data(group.members)

        group_data = {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:Group'],
            'displayName': group.name,
            'externalId': group.slug,
            'members': members,
        }

        response = await self.get_client().put(
            f'/Groups/{group_id}', json=group_data
        )
        response.raise_for_status()

        updated_data = response.json()
        updated_group = self._parse_scim_group(updated_data)

        logger.debug(f'Updated idP Group: {updated_group.name}')
        return updated_group

    async def _get_member_scim_data(
        self: GitHubScimClient, usernames: list[str]
    ) -> list[dict[str, str]]:
        """Convert usernames to SCIM member format with user IDs.

        Args:
            usernames: List of GitHub usernames

        Returns:
            List of member objects with SCIM user ID, $ref, and displayName
        """
        members = []

        # Get all users to build username -> SCIM ID mapping
        all_users = await self.get_users()
        username_to_scim_id = {
            user.user_name: user.id for user in all_users if user.id
        }

        for username in usernames:
            scim_user_id = username_to_scim_id.get(username)
            if scim_user_id:
                member = {
                    'value': scim_user_id,
                    '$ref': f'https://api.github.com/scim/v2/enterprises/{self.enterprise_name}/Users/{scim_user_id}',
                    'displayName': username,
                }
                members.append(member)
            else:
                logger.warning(
                    f'Could not find SCIM user ID for username: {username}'
                )

        return members

    def _parse_scim_user(self: GitHubScimClient, user_data: dict) -> ScimUser:
        """Parse SCIM API user data into ScimUser model."""
        return ScimUser(
            id=user_data.get('id'),
            user_name=user_data['userName'],
            emails=user_data['emails'],
            name=user_data['name'],
            active=user_data.get('active', True),
            external_id=user_data.get('externalId'),
            roles=user_data.get('roles', [{'value': 'user', 'primary': True}]),
        )

    def _scim_user_to_dict(self: GitHubScimClient, user: ScimUser) -> dict:
        """Convert ScimUser model to SCIM API format."""
        user_dict = {
            'schemas': ['urn:ietf:params:scim:schemas:core:2.0:User'],
            'userName': user.user_name,
            'emails': user.emails,
            'name': user.name,
            'active': user.active,
            'roles': user.roles,
        }

        if user.external_id:
            user_dict['externalId'] = user.external_id

        return user_dict

    def _parse_scim_group(
        self: GitHubScimClient, group_data: dict
    ) -> GitHubGroup:
        """Parse SCIM API group data into GitHubTeam model."""
        # Extract member usernames from SCIM members format
        members = []
        for member in group_data.get('members', []):
            if 'value' in member:
                members.append(member['value'])

        return GitHubGroup(
            id=group_data.get('id'),
            name=group_data['displayName'],
            slug=group_data.get(
                'externalId', group_data['displayName'].lower()
            ),
            description=group_data.get('description'),
            members=members,
        )
