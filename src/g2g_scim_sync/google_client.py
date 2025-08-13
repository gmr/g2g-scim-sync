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

from g2g_scim_sync.models import GoogleOU, GoogleUser

logger = logging.getLogger(__name__)


class GoogleWorkspaceClient:
    """Google Workspace Admin SDK client for users and OUs."""

    def __init__(
        self: GoogleWorkspaceClient,
        service_account_file: Path,
        domain: str,
        subject_email: str,
        scopes: Optional[list[str]] = None,
    ) -> None:
        """Initialize the Google Workspace client.

        Args:
            service_account_file: Path to service account JSON file
            domain: Google Workspace domain (e.g., company.com)
            subject_email: Admin user email to impersonate
            scopes: OAuth scopes (defaults to read-only admin scopes)
        """
        self.service_account_file = service_account_file
        self.domain = domain
        self.subject_email = subject_email
        self.scopes = scopes or [
            'https://www.googleapis.com/auth/admin.directory.user',
            'https://www.googleapis.com/auth/admin.directory.orgunit.readonly',
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

            # Impersonate the admin user for domain-wide delegation
            delegated_credentials = credentials.with_subject(
                self.subject_email
            )

            # Refresh credentials if needed
            if not delegated_credentials.valid:
                delegated_credentials.refresh(Request())

            service = build(
                'admin', 'directory_v1', credentials=delegated_credentials
            )
            logger.debug(
                f'Google Admin SDK client initialized with subject: '
                f'{self.subject_email}'
            )
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

    async def get_users_in_ou(
        self: GoogleWorkspaceClient, ou_path: str
    ) -> list[GoogleUser]:
        """Get all users in a specific Organizational Unit."""
        users = []
        page_token = None

        try:
            while True:
                # Build request parameters for users in the OU
                request_params = {
                    'domain': self.domain,
                    'maxResults': 500,
                    'query': f"orgUnitPath='{ou_path}'",
                }
                if page_token:
                    request_params['pageToken'] = page_token

                result = (
                    self.admin_service.users().list(**request_params).execute()
                )

                user_list = result.get('users', [])

                # Parse user data directly
                for user_data in user_list:
                    try:
                        user = self._parse_user(user_data)
                        users.append(user)
                    except (ValueError, KeyError) as e:
                        logger.warning(f'Skipping invalid user: {e}')
                        continue

                page_token = result.get('nextPageToken')
                if not page_token:
                    break

            logger.debug(f'Found {len(users)} users in OU {ou_path}')
            return users

        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f'OU not found: {ou_path}') from e
            logger.error(f'Error fetching users in OU {ou_path}: {e}')
            raise

    async def get_ou(self: GoogleWorkspaceClient, ou_path: str) -> GoogleOU:
        """Get a single Organizational Unit by path."""
        try:
            result = (
                self.admin_service.orgunits()
                .get(customerId='my_customer', orgUnitPath=ou_path)
                .execute()
            )

            # Get user emails in this OU
            users = await self.get_users_in_ou(ou_path)
            user_emails = [user.primary_email for user in users]

            # Extract name from path (last component)
            name = (
                ou_path.rstrip('/').split('/')[-1]
                if ou_path != '/'
                else 'Root'
            )

            return GoogleOU(
                org_unit_path=result['orgUnitPath'],
                name=name,
                description=result.get('description'),
                parent_org_unit_path=result.get('parentOrgUnitPath'),
                user_count=len(user_emails),
                user_emails=user_emails,
            )
        except HttpError as e:
            if e.resp.status == 404:
                raise ValueError(f'OU not found: {ou_path}') from e
            logger.error(f'Error fetching OU {ou_path}: {e}')
            raise

    async def get_child_ous(
        self: GoogleWorkspaceClient, parent_ou_path: str
    ) -> list[GoogleOU]:
        """Get all child OUs within a parent OU."""
        try:
            result = (
                self.admin_service.orgunits()
                .list(customerId='my_customer', orgUnitPath=parent_ou_path)
                .execute()
            )

            child_ous = []
            org_units = result.get('organizationUnits', [])

            for ou_data in org_units:
                # Skip the parent OU itself
                if ou_data['orgUnitPath'] != parent_ou_path:
                    ou = await self.get_ou(ou_data['orgUnitPath'])
                    child_ous.append(ou)

            logger.debug(
                f'Found {len(child_ous)} child OUs in {parent_ou_path}'
            )
            return child_ous

        except HttpError as e:
            logger.error(f'Error fetching child OUs for {parent_ou_path}: {e}')
            raise

    async def get_individual_users(
        self: GoogleWorkspaceClient, user_emails: list[str]
    ) -> list[GoogleUser]:
        """Get specific individual users by email addresses."""
        users = []

        for email in user_emails:
            try:
                user = await self.get_user(email)
                users.append(user)
                logger.debug(f'Retrieved individual user: {email}')
            except ValueError as e:
                logger.warning(f'Skipping individual user {email}: {e}')
                continue

        logger.debug(f'Found {len(users)} individual users')
        return users

    async def get_all_users_in_ous(
        self: GoogleWorkspaceClient, ou_paths: list[str]
    ) -> list[GoogleUser]:
        """Get all users across multiple OUs (including child OUs)."""
        all_users = []
        seen_emails = set()

        for ou_path in ou_paths:
            try:
                # Get direct users in this OU
                users = await self.get_users_in_ou(ou_path)
                for user in users:
                    if user.primary_email not in seen_emails:
                        all_users.append(user)
                        seen_emails.add(user.primary_email)

                # Get users in child OUs
                child_ous = await self.get_child_ous(ou_path)
                for child_ou in child_ous:
                    users = await self.get_users_in_ou(child_ou.org_unit_path)
                    for user in users:
                        if user.primary_email not in seen_emails:
                            all_users.append(user)
                            seen_emails.add(user.primary_email)

            except ValueError as e:
                logger.warning(f'Skipping OU {ou_path}: {e}')
                continue

        logger.debug(f'Found {len(all_users)} unique users across all OUs')
        return all_users

    async def get_all_users(
        self: GoogleWorkspaceClient,
        ou_paths: list[str],
        individual_user_emails: list[str],
    ) -> list[GoogleUser]:
        """Get all users from OUs and individual user list combined."""
        all_users = []
        seen_emails = set()

        # Get users from OUs
        ou_users = await self.get_all_users_in_ous(ou_paths)
        for user in ou_users:
            if user.primary_email not in seen_emails:
                all_users.append(user)
                seen_emails.add(user.primary_email)

        # Get individual users (not in OUs)
        individual_users = await self.get_individual_users(
            individual_user_emails
        )
        for user in individual_users:
            if user.primary_email not in seen_emails:
                all_users.append(user)
                seen_emails.add(user.primary_email)
            else:
                logger.debug(
                    f'Individual user {user.primary_email} already in OU, '
                    'skipping'
                )

        logger.debug(
            f'Found {len(all_users)} total unique users '
            f'({len(ou_users)} from OUs, {len(individual_users)} individual)'
        )
        return all_users

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
