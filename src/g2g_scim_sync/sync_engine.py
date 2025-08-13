"""Core sync engine for Google Workspace to GitHub Enterprise SCIM."""

from __future__ import annotations

import logging
from typing import Optional

from g2g_scim_sync.github_client import GitHubScimClient
from g2g_scim_sync.google_client import GoogleWorkspaceClient
from g2g_scim_sync.config import SyncConfig, GitHubConfig
from g2g_scim_sync.models import (
    GitHubGroup,
    GitHubScimNotSupportedException,
    GoogleOU,
    GoogleUser,
    ScimUser,
    SyncResult,
    SyncStats,
    UserDiff,
    GroupDiff,
)

logger = logging.getLogger(__name__)


class SyncEngine:
    """Core synchronization engine for Google to GitHub SCIM sync."""

    def __init__(
        self: SyncEngine,
        google_client: GoogleWorkspaceClient,
        github_client: GitHubScimClient,
        config: SyncConfig,
        github_config: GitHubConfig,
    ) -> None:
        """Initialize the synchronization engine.

        Args:
            google_client: Google Workspace Admin SDK client
            github_client: GitHub Enterprise SCIM API client
            config: Synchronization configuration
            github_config: GitHub configuration for role assignments
        """
        self.google_client = google_client
        self.github_client = github_client
        self.config = config
        self.github_config = github_config
        self._stats = SyncStats()

    async def synchronize(
        self: SyncEngine,
        ou_paths: Optional[list[str]] = None,
        individual_users: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Perform full synchronization from Google Workspace to GitHub.

        Args:
            ou_paths: Google Workspace OU paths to sync
            individual_users: Individual user emails to sync (outside OUs)
            dry_run: Preview changes without applying them

        Returns:
            Synchronization results and statistics
        """
        logger.info('Starting synchronization process')
        self._stats = SyncStats()

        try:
            # Use configured OUs if none specified
            sync_ous = ou_paths or []
            sync_individual = individual_users or []

            if not sync_ous and not sync_individual:
                raise ValueError(
                    'No OUs or individual users specified for synchronization'
                )

            # Fetch data from both systems
            google_users = await self._get_google_users(
                sync_ous, sync_individual
            )
            github_users = await self._get_github_users()

            # Calculate user differences
            user_diffs = await self._calculate_user_diffs(
                google_users, github_users
            )

            # Apply user changes
            if not dry_run:
                await self._apply_user_changes(user_diffs)
            else:
                self._preview_user_changes(user_diffs)

            # Handle idP Group synchronization if enabled
            group_diffs: list[GroupDiff] = []
            if self.config.create_groups:
                try:
                    github_groups = await self._get_github_groups()

                    if self.config.flatten_ous:
                        group_diffs = (
                            await self._calculate_flattened_group_diffs(
                                google_users, github_groups
                            )
                        )
                    else:
                        google_ous = await self._get_google_ous(sync_ous)
                        group_diffs = await self._calculate_group_diffs(
                            google_ous, github_groups, google_users
                        )

                    if not dry_run:
                        await self._apply_group_changes(group_diffs)
                    else:
                        self._preview_group_changes(group_diffs)

                except GitHubScimNotSupportedException as e:
                    logger.warning(f'Team operations disabled: {e}')
                    logger.info('Continuing with user provisioning only')
                    logger.info(
                        'Consider setting create_groups=false in '
                        'configuration '
                        'to skip idP Group operations'
                    )

            logger.info(f'Synchronization completed: {self._stats}')
            return SyncResult(
                success=True,
                user_diffs=user_diffs,
                group_diffs=group_diffs,
                stats=self._stats,
                dry_run=dry_run,
            )

        except Exception as e:
            logger.error(f'Synchronization failed: {e}')
            return SyncResult(
                success=False,
                error=str(e),
                stats=self._stats,
                dry_run=dry_run,
            )

    async def _get_google_users(
        self: SyncEngine, ou_paths: list[str], individual_users: list[str]
    ) -> list[GoogleUser]:
        """Get all users from specified Google OUs and individual user list."""
        logger.info(
            f'Fetching users from {len(ou_paths)} Google OUs '
            f'and {len(individual_users)} individual users'
        )

        all_users = await self.google_client.get_all_users(
            ou_paths, individual_users
        )

        # Apply user filters if configured
        filtered_users = []
        for user in all_users:
            if self._should_sync_user(user):
                filtered_users.append(user)
            else:
                logger.debug(f'Skipping user {user.primary_email} (filtered)')
                self._stats.users_skipped += 1

        logger.info(f'Found {len(filtered_users)} users to sync')
        return filtered_users

    async def _get_google_ous(
        self: SyncEngine, ou_paths: list[str]
    ) -> list[GoogleOU]:
        """Get all Google OUs from specified paths."""
        logger.info(f'Fetching {len(ou_paths)} Google OUs')

        all_ous = []
        for ou_path in ou_paths:
            try:
                ou = await self.google_client.get_ou(ou_path)
                all_ous.append(ou)
            except ValueError as e:
                logger.warning(f'Skipping OU {ou_path}: {e}')
                continue

        logger.info(f'Found {len(all_ous)} OUs')
        return all_ous

    async def _calculate_flattened_group_diffs(
        self: SyncEngine,
        google_users: list[GoogleUser],
        github_groups: list[GitHubGroup],
    ) -> list[GroupDiff]:
        """Calculate idP Group differences with OU hierarchy flattening.

        For users in nested OUs like '/Engineering/DBA',
        create idP Groups for each segment and add users to all groups.
        User in '/Engineering/DBA' gets added to both 'engineering' and 'dba'
        groups.
        """
        logger.debug('Calculating flattened team differences from OU paths')

        # Get GitHub users to create SCIM ID -> username mapping
        github_users = await self._get_github_users()
        scim_id_to_username = {
            user.id: user.user_name for user in github_users if user.id
        }

        # Create lookup maps
        github_groups_by_slug = {group.slug: group for group in github_groups}

        # Extract all unique group names from user OU paths
        group_memberships = {}  # group_slug -> set of usernames

        for user in google_users:
            # Parse OU path like '/AWeber/Engineering/DBA'
            path_segments = user.org_unit_path.strip('/').split('/')
            username = self._email_to_username(user.primary_email)

            # Create groups for all segments in the OU path
            for i in range(0, len(path_segments)):
                segment = path_segments[i]
                group_slug = (
                    segment.lower().replace(' ', '-').replace('_', '-')
                )

                if group_slug not in group_memberships:
                    group_memberships[group_slug] = set()
                group_memberships[group_slug].add(username)

        # Generate group diffs
        group_diffs = []

        for group_slug, member_usernames in group_memberships.items():
            existing_group = github_groups_by_slug.get(group_slug)

            # Create target group with hierarchical name
            target_group = GitHubGroup(
                name=group_slug,
                slug=group_slug,
                description=(
                    f'idP Group for {group_slug.replace("-", " ")} OU'
                ),
                members=list(member_usernames),
            )

            if existing_group is None:
                # Team needs to be created
                if self.config.create_groups:
                    group_diffs.append(
                        GroupDiff(
                            action='create',
                            google_ou=None,  # No single OU for flattened
                            target_group=target_group,
                        )
                    )
                    self._stats.groups_to_create += 1
            else:
                # Convert existing team member IDs to usernames for comparison
                existing_group_usernames = []
                for member_id in existing_group.members:
                    username = scim_id_to_username.get(member_id, member_id)
                    existing_group_usernames.append(username)

                # Create normalized existing team for comparison
                normalized_existing = GitHubGroup(
                    id=existing_group.id,
                    name=existing_group.name,
                    slug=existing_group.slug,
                    description=existing_group.description
                    or target_group.description,
                    members=existing_group_usernames,
                )

                # Check if team needs to be updated
                if self._groups_differ(normalized_existing, target_group):
                    group_diffs.append(
                        GroupDiff(
                            action='update',
                            google_ou=None,  # No single OU for flattened
                            existing_group=existing_group,
                            target_group=target_group,
                        )
                    )
                    self._stats.groups_to_update += 1

        logger.debug(f'Found {len(group_diffs)} flattened team differences')
        return group_diffs

    async def _get_github_users(self: SyncEngine) -> list[ScimUser]:
        """Get all existing SCIM users from GitHub Enterprise."""
        logger.debug('Fetching existing GitHub SCIM users')

        users = await self.github_client.get_users()
        logger.debug(f'Found {len(users)} existing GitHub users')
        return users

    async def _get_github_groups(self: SyncEngine) -> list[GitHubGroup]:
        """Get all existing GitHub idP Groups."""
        logger.debug('Fetching existing GitHub idP Groups')

        groups = await self.github_client.get_groups()
        logger.debug(f'Found {len(groups)} existing GitHub idP Groups')
        return groups

    async def _calculate_user_diffs(
        self: SyncEngine,
        google_users: list[GoogleUser],
        github_users: list[ScimUser],
    ) -> list[UserDiff]:
        """Calculate differences between Google and GitHub users."""
        logger.debug('Calculating user differences')

        # Create lookup maps for efficient comparison
        github_users_by_email = {
            self._get_primary_email(user): user for user in github_users
        }

        user_diffs = []

        # Check each Google user
        for google_user in google_users:
            email = google_user.primary_email
            existing_user = github_users_by_email.get(email)

            if existing_user is None:
                # User needs to be created
                scim_user = self._google_user_to_scim(google_user)
                user_diffs.append(
                    UserDiff(
                        action='create',
                        google_user=google_user,
                        target_scim_user=scim_user,
                    )
                )
                self._stats.users_to_create += 1

            else:
                # Check if user needs to be updated
                target_scim_user = self._google_user_to_scim(google_user)

                if self._users_differ(existing_user, target_scim_user):
                    user_diffs.append(
                        UserDiff(
                            action='update',
                            google_user=google_user,
                            existing_scim_user=existing_user,
                            target_scim_user=target_scim_user,
                        )
                    )
                    self._stats.users_to_update += 1
                else:
                    logger.debug(f'User {email} is up to date')
                    self._stats.users_up_to_date += 1

        # Check for suspended/deleted users
        google_emails = {user.primary_email for user in google_users}

        for github_user in github_users:
            email = self._get_primary_email(github_user)

            if email not in google_emails and github_user.active:
                # User should be suspended
                user_diffs.append(
                    UserDiff(
                        action='suspend',
                        existing_scim_user=github_user,
                    )
                )
                self._stats.users_to_suspend += 1

        logger.debug(f'Found {len(user_diffs)} user differences')
        return user_diffs

    async def _calculate_group_diffs(
        self: SyncEngine,
        google_ous: list[GoogleOU],
        github_groups: list[GitHubGroup],
        google_users: list[GoogleUser],
    ) -> list[GroupDiff]:
        """Calculate differences between Google OUs and GitHub idP Groups."""
        logger.info('Calculating idP Group differences')

        # Create lookup maps
        github_groups_by_slug = {group.slug: group for group in github_groups}
        user_email_to_username = {
            user.primary_email: self._email_to_username(user.primary_email)
            for user in google_users
        }

        group_diffs = []

        for google_ou in google_ous:
            group_slug = self._ou_to_group_slug(google_ou)
            existing_group = github_groups_by_slug.get(group_slug)

            # Convert OU user emails to GitHub usernames
            github_members = []
            for email in google_ou.user_emails:
                username = user_email_to_username.get(email)
                if username:
                    github_members.append(username)
                else:
                    logger.debug(f'No GitHub user for OU user {email}')

            target_group = GitHubGroup(
                name=group_slug,
                slug=group_slug,
                description=google_ou.description,
                members=github_members,
            )

            if existing_group is None:
                # Team needs to be created
                if self.config.create_groups:
                    group_diffs.append(
                        GroupDiff(
                            action='create',
                            google_ou=google_ou,
                            target_group=target_group,
                        )
                    )
                    self._stats.groups_to_create += 1
                else:
                    logger.info(
                        f'Skipping idP Group creation for {group_slug} '
                        '(create_teams=False)'
                    )

            else:
                # Check if team needs to be updated
                if self._groups_differ(existing_group, target_group):
                    group_diffs.append(
                        GroupDiff(
                            action='update',
                            google_ou=google_ou,
                            existing_group=existing_group,
                            target_group=target_group,
                        )
                    )
                    self._stats.groups_to_update += 1
                else:
                    logger.debug(f'idP Group {group_slug} is up to date')
                    self._stats.groups_up_to_date += 1

        logger.info(f'Found {len(group_diffs)} team differences')
        return group_diffs

    async def _apply_user_changes(
        self: SyncEngine, user_diffs: list[UserDiff]
    ) -> None:
        """Apply user changes to GitHub Enterprise."""
        logger.debug(f'Applying {len(user_diffs)} user changes')

        for diff in user_diffs:
            try:
                if diff.action == 'create' and diff.target_scim_user:
                    created_user = await self.github_client.create_user(
                        diff.target_scim_user
                    )
                    logger.info(f'Created user: {created_user.user_name}')
                    self._stats.users_created += 1

                elif (
                    diff.action == 'update'
                    and diff.existing_scim_user
                    and diff.target_scim_user
                ):
                    updated_user = await self.github_client.update_user(
                        diff.existing_scim_user.id, diff.target_scim_user
                    )
                    logger.info(f'Updated user: {updated_user.user_name}')
                    self._stats.users_updated += 1

                elif diff.action == 'suspend' and diff.existing_scim_user:
                    suspended_user = await self.github_client.suspend_user(
                        diff.existing_scim_user.id
                    )
                    logger.info(f'Suspended user: {suspended_user.user_name}')
                    self._stats.users_suspended += 1

            except Exception as e:
                logger.error(f'Failed to apply user change {diff.action}: {e}')
                self._stats.users_failed += 1

    async def _apply_group_changes(
        self: SyncEngine, group_diffs: list[GroupDiff]
    ) -> None:
        """Apply idP Group changes to GitHub Enterprise."""
        logger.info(f'Applying {len(group_diffs)} idP Group changes')

        for diff in group_diffs:
            try:
                if diff.action == 'create' and diff.target_group:
                    created_team = await self.github_client.create_group(
                        diff.target_group
                    )
                    logger.info(f'Created team: {created_team.name}')
                    self._stats.groups_created += 1

                elif (
                    diff.action == 'update'
                    and diff.existing_group
                    and diff.target_group
                ):
                    updated_team = await self.github_client.update_group(
                        str(diff.existing_group.id), diff.target_group
                    )
                    logger.info(f'Updated team: {updated_team.name}')
                    self._stats.groups_updated += 1

            except GitHubScimNotSupportedException as e:
                logger.warning(f'Team operation {diff.action} skipped: {e}')
                self._stats.groups_failed += 1
            except Exception as e:
                logger.error(f'Failed to apply team change {diff.action}: {e}')
                self._stats.groups_failed += 1

    def _preview_user_changes(
        self: SyncEngine, user_diffs: list[UserDiff]
    ) -> None:
        """Preview user changes for dry-run mode."""
        logger.info(f'DRY RUN: Would apply {len(user_diffs)} user changes:')

        for diff in user_diffs:
            if diff.action == 'create' and diff.google_user:
                logger.info(f'  CREATE: {diff.google_user.primary_email}')
            elif diff.action == 'update' and diff.google_user:
                logger.info(f'  UPDATE: {diff.google_user.primary_email}')
            elif diff.action == 'suspend' and diff.existing_scim_user:
                logger.info(f'  SUSPEND: {diff.existing_scim_user.user_name}')

    def _preview_group_changes(
        self: SyncEngine, group_diffs: list[GroupDiff]
    ) -> None:
        """Preview idP Group changes for dry-run mode."""
        logger.info(
            f'DRY RUN: Would apply {len(group_diffs)} idP Group changes:'
        )

        for diff in group_diffs:
            if diff.action == 'create' and diff.target_group:
                logger.info(f'  CREATE GROUP: {diff.target_group.name}')
            elif diff.action == 'update' and diff.target_group:
                logger.info(f'  UPDATE GROUP: {diff.target_group.name}')

    def _should_sync_user(self: SyncEngine, user: GoogleUser) -> bool:
        """Check if user should be synchronized."""
        # Always sync users, action logic handles suspended state
        return True

    def _determine_user_roles(self: SyncEngine, email: str) -> list[dict]:
        """Determine GitHub Enterprise roles for a user based on their email.

        Args:
            email: User's email address

        Returns:
            List of role dictionaries for SCIM API
        """
        if email in self.github_config.enterprise_owners:
            return [{'value': 'enterprise_owner', 'primary': True}]
        elif email in self.github_config.billing_managers:
            return [{'value': 'billing_manager', 'primary': True}]
        elif email in self.github_config.guest_collaborators:
            return [{'value': 'guest_collaborator', 'primary': True}]
        else:
            return [{'value': 'user', 'primary': True}]

    def _google_user_to_scim(self: SyncEngine, user: GoogleUser) -> ScimUser:
        """Convert Google User to SCIM User format."""
        # Determine user role based on email
        roles = self._determine_user_roles(user.primary_email)

        return ScimUser(
            user_name=self._email_to_username(user.primary_email),
            emails=[{'value': user.primary_email, 'primary': True}],
            name={
                'givenName': user.given_name,
                'familyName': user.family_name,
                'formatted': user.full_name,
            },
            active=not user.suspended,
            external_id=user.id,
            roles=roles,
        )

    def _users_differ(
        self: SyncEngine, existing: ScimUser, target: ScimUser
    ) -> bool:
        """Check if two SCIM users have meaningful differences."""
        return (
            existing.user_name != target.user_name
            or existing.emails != target.emails
            or existing.name != target.name
            or existing.active != target.active
            or existing.roles != target.roles
        )

    def _groups_differ(
        self: SyncEngine, existing: GitHubGroup, target: GitHubGroup
    ) -> bool:
        """Check if two GitHub idP Groups have meaningful differences."""
        name_differs = existing.name != target.name
        description_differs = existing.description != target.description
        members_differ = set(existing.members) != set(target.members)

        if name_differs or description_differs or members_differ:
            logger.debug(
                f'Team {existing.slug} differs: '
                f'name={name_differs} ({existing.name!r} vs {target.name!r}), '
                f'description={description_differs} '
                f'({existing.description!r} vs {target.description!r}), '
                f'members={members_differ} '
                f'(existing={existing.members!r}, target={target.members!r})'
            )
            return True
        return False

    def _get_primary_email(self: SyncEngine, user: ScimUser) -> str:
        """Extract primary email from SCIM user."""
        for email in user.emails:
            if email.get('primary'):
                return email['value']
        # Fallback to first email if no primary marked
        return user.emails[0]['value'] if user.emails else ''

    def _email_to_username(self: SyncEngine, email: str) -> str:
        """Convert email to GitHub username with optional EMU suffix."""
        # Use full email address as username
        username = email

        # Add EMU suffix if configured
        if self.github_config.emu_username_suffix:
            username = f'{username}_{self.github_config.emu_username_suffix}'

        return username

    def _ou_to_group_slug(self: SyncEngine, ou: GoogleOU) -> str:
        """Convert Google OU to GitHub idP Group slug."""
        # Use OU name, convert to lowercase and replace spaces
        return ou.name.lower().replace(' ', '-').replace('_', '-')
