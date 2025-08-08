"""Google Workspace Admin SDK client."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import Request
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from g2g_scim_sync.models import GoogleGroup, GoogleUser

logger = logging.getLogger(__name__)


class GoogleWorkspaceClient:
    """Google Workspace Admin SDK client for fetching users and groups."""

    def __init__(
        self: GoogleWorkspaceClient,
        service_account_file: Path,
        domain: str,
        scopes: Optional[list[str]] = None,
    ) -> None:
        """Initialize the Google Workspace client.

        Args:
            service_account_file: Path to service account JSON file
            domain: Google Workspace domain (e.g., company.com)
            scopes: OAuth scopes (defaults to read-only admin scopes)
        """
        self.service_account_file = service_account_file
        self.domain = domain
        self.scopes = scopes or [
            'https://www.googleapis.com/auth/admin.directory.user.readonly',
            'https://www.googleapis.com/auth/admin.directory.group.readonly',
        ]
        self._admin_service: Optional[Resource] = None

    @property
    def admin_service(self: GoogleWorkspaceClient) -> Resource:
        """Get or create the Admin SDK service client."""
        if self._admin_service is None:
            self._admin_service = self._create_admin_service()
        return self._admin_service

    def _create_admin_service(self: GoogleWorkspaceClient) -> Resource:
        """Create the Google Admin SDK service client."""
        try:
            credentials = Credentials.from_service_account_file(
                str(self.service_account_file), scopes=self.scopes
            )

            # Refresh credentials if needed
            if not credentials.valid:
                credentials.refresh(Request())

            service = build('admin', 'directory_v1', credentials=credentials)
            logger.info('Successfully initialized Google Admin SDK client')
            return service

        except (GoogleAuthError, FileNotFoundError, ValueError) as e:
            logger.error(f'Failed to initialize Google Admin SDK client: {e}')
            raise

    async def get_user(
        self: GoogleWorkspaceClient, user_email: str
    ) -> GoogleUser:
        """Get a single user by email address."""
        try:
            result = (
                self.admin_service.users().get(userKey=user_email).execute()
            )
            return self._parse_user(result)
        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f'User not found: {user_email}') from e
            logger.error(f'Error fetching user {user_email}: {e}')
            raise

    async def get_users_in_group(
        self: GoogleWorkspaceClient, group_email: str
    ) -> list[GoogleUser]:
        """Get all users that are members of a specific group."""
        users = []
        page_token = None

        try:
            while True:
                # Get group members
                request = self.admin_service.members().list(
                    groupKey=group_email, pageToken=page_token, maxResults=200
                )
                result = request.execute()

                members = result.get('members', [])

                # Filter to only USER members and fetch their details
                for member in members:
                    if member.get('type') == 'USER':
                        try:
                            user = await self.get_user(member['email'])
                            users.append(user)
                        except ValueError:
                            # User not found, skip
                            logger.warning(
                                f'Skipping missing user: {member["email"]}'
                            )
                            continue

                page_token = result.get('nextPageToken')
                if not page_token:
                    break

            logger.info(f'Found {len(users)} users in group {group_email}')
            return users

        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f'Group not found: {group_email}') from e
            logger.error(f'Error fetching users in group {group_email}: {e}')
            raise

    async def get_group(
        self: GoogleWorkspaceClient, group_email: str
    ) -> GoogleGroup:
        """Get a single group by email address."""
        try:
            result = (
                self.admin_service.groups().get(groupKey=group_email).execute()
            )

            # Get member emails
            member_emails = await self._get_group_member_emails(group_email)

            return GoogleGroup(
                id=result['id'],
                name=result['name'],
                email=result['email'],
                description=result.get('description'),
                direct_members_count=result.get('directMembersCount', 0),
                member_emails=member_emails,
            )
        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f'Group not found: {group_email}') from e
            logger.error(f'Error fetching group {group_email}: {e}')
            raise

    async def get_nested_groups(
        self: GoogleWorkspaceClient, group_email: str
    ) -> list[GoogleGroup]:
        """Get all nested groups within a parent group."""
        nested_groups = []
        page_token = None

        try:
            while True:
                request = self.admin_service.members().list(
                    groupKey=group_email, pageToken=page_token, maxResults=200
                )
                result = request.execute()

                members = result.get('members', [])

                # Find GROUP members and fetch their details
                for member in members:
                    if member.get('type') == 'GROUP':
                        try:
                            nested_group = await self.get_group(
                                member['email']
                            )
                            nested_groups.append(nested_group)

                            # Recursively get nested groups
                            sub_nested = await self.get_nested_groups(
                                member['email']
                            )
                            nested_groups.extend(sub_nested)
                        except ValueError:
                            # Group not found, skip
                            logger.warning(
                                f'Skipping missing group: {member["email"]}'
                            )
                            continue

                page_token = result.get('nextPageToken')
                if not page_token:
                    break

            logger.info(
                f'Found {len(nested_groups)} nested groups in {group_email}'
            )
            return nested_groups

        except HttpError as e:
            logger.error(
                f'Error fetching nested groups for {group_email}: {e}'
            )
            raise

    async def get_all_users_in_groups(
        self: GoogleWorkspaceClient, group_emails: list[str]
    ) -> list[GoogleUser]:
        """Get all users across multiple groups (including nested)."""
        all_users = []
        seen_emails = set()

        for group_email in group_emails:
            try:
                # Get direct users in this group
                users = await self.get_users_in_group(group_email)
                for user in users:
                    if user.primary_email not in seen_emails:
                        all_users.append(user)
                        seen_emails.add(user.primary_email)

                # Get users in nested groups
                nested_groups = await self.get_nested_groups(group_email)
                for nested_group in nested_groups:
                    users = await self.get_users_in_group(nested_group.email)
                    for user in users:
                        if user.primary_email not in seen_emails:
                            all_users.append(user)
                            seen_emails.add(user.primary_email)

            except ValueError as e:
                logger.warning(f'Skipping group {group_email}: {e}')
                continue

        logger.info(f'Found {len(all_users)} unique users across all groups')
        return all_users

    async def _get_group_member_emails(
        self: GoogleWorkspaceClient, group_email: str
    ) -> list[str]:
        """Get all member email addresses for a group."""
        member_emails = []
        page_token = None

        try:
            while True:
                request = self.admin_service.members().list(
                    groupKey=group_email, pageToken=page_token, maxResults=200
                )
                result = request.execute()

                members = result.get('members', [])
                member_emails.extend([member['email'] for member in members])

                page_token = result.get('nextPageToken')
                if not page_token:
                    break

            return member_emails

        except HttpError as e:
            logger.error(
                f'Error fetching member emails for {group_email}: {e}'
            )
            return []

    def _parse_user(
        self: GoogleWorkspaceClient, user_data: dict
    ) -> GoogleUser:
        """Parse Google API user data into GoogleUser model."""
        return GoogleUser(
            id=user_data['id'],
            primary_email=user_data['primaryEmail'],
            given_name=user_data['name']['givenName'],
            family_name=user_data['name']['familyName'],
            full_name=user_data['name']['fullName'],
            suspended=user_data.get('suspended', False),
            org_unit_path=user_data.get('orgUnitPath', '/'),
            last_login_time=self._parse_datetime(
                user_data.get('lastLoginTime')
            ),
            creation_time=self._parse_datetime(user_data.get('creationTime')),
        )

    def _parse_datetime(
        self: GoogleWorkspaceClient, dt_str: Optional[str]
    ) -> Optional[datetime]:
        """Parse Google API datetime string to datetime object."""
        if not dt_str:
            return None

        try:
            # Google API returns RFC3339 format: 2024-01-15T10:30:00.000Z
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            logger.warning(f'Failed to parse datetime: {dt_str}')
            return None
