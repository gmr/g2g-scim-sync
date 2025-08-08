"""Core sync engine for Google Workspace to GitHub Enterprise SCIM."""

from __future__ import annotations

import logging
from typing import Optional

from g2g_scim_sync.github_client import GitHubScimClient
from g2g_scim_sync.google_client import GoogleWorkspaceClient
from g2g_scim_sync.models import (
    GitHubTeam,
    GoogleGroup,
    GoogleUser,
    ScimUser,
    SyncConfig,
    SyncResult,
    SyncStats,
    UserDiff,
    TeamDiff,
)

logger = logging.getLogger(__name__)


class SyncEngine:
    """Core synchronization engine for Google to GitHub SCIM sync."""

    def __init__(
        self: SyncEngine,
        google_client: GoogleWorkspaceClient,
        github_client: GitHubScimClient,
        config: SyncConfig,
    ) -> None:
        """Initialize the synchronization engine.

        Args:
            google_client: Google Workspace Admin SDK client
            github_client: GitHub Enterprise SCIM API client
            config: Synchronization configuration
        """
        self.google_client = google_client
        self.github_client = github_client
        self.config = config
        self._stats = SyncStats()

    async def synchronize(
        self: SyncEngine,
        group_emails: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> SyncResult:
        """Perform full synchronization from Google Workspace to GitHub.

        Args:
            group_emails: Google Groups to sync (defaults to config groups)
            dry_run: Preview changes without applying them

        Returns:
            Synchronization results and statistics
        """
        logger.info('Starting synchronization process')
        self._stats = SyncStats()

        try:
            # Use configured groups if none specified
            sync_groups = group_emails or self.config.groups
            if not sync_groups:
                raise ValueError('No groups specified for synchronization')
            # Fetch data from both systems
            google_users = await self._get_google_users(sync_groups)
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

            # Handle team synchronization if enabled
            team_diffs: list[TeamDiff] = []
            if self.config.sync_teams:
                google_groups = await self._get_google_groups(sync_groups)
                github_teams = await self._get_github_teams()

                team_diffs = await self._calculate_team_diffs(
                    google_groups, github_teams, google_users
                )

                if not dry_run:
                    await self._apply_team_changes(team_diffs)
                else:
                    self._preview_team_changes(team_diffs)

            logger.info(f'Synchronization completed: {self._stats}')
            return SyncResult(
                success=True,
                user_diffs=user_diffs,
                team_diffs=team_diffs,
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
        self: SyncEngine, group_emails: list[str]
    ) -> list[GoogleUser]:
        """Get all users from specified Google Groups (including nested)."""
        logger.info(f'Fetching users from {len(group_emails)} Google groups')

        all_users = await self.google_client.get_all_users_in_groups(
            group_emails
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

    async def _get_github_users(self: SyncEngine) -> list[ScimUser]:
        """Get all existing SCIM users from GitHub Enterprise."""
        logger.info('Fetching existing GitHub SCIM users')

        users = await self.github_client.get_users()
        logger.info(f'Found {len(users)} existing GitHub users')
        return users

    async def _get_google_groups(
        self: SyncEngine, group_emails: list[str]
    ) -> list[GoogleGroup]:
        """Get Google Groups for team synchronization."""
        logger.info(f'Fetching {len(group_emails)} Google groups')

        groups = []
        for group_email in group_emails:
            try:
                group = await self.google_client.get_group(group_email)
                groups.append(group)
            except ValueError as e:
                logger.warning(f'Skipping group {group_email}: {e}')
                continue

        # Get nested groups and flatten them
        all_groups = []
        for group in groups:
            all_groups.append(group)

            # Get nested groups
            nested_groups = await self.google_client.get_nested_groups(
                group.email
            )
            all_groups.extend(nested_groups)

        logger.info(f'Found {len(all_groups)} total groups (including nested)')
        return all_groups

    async def _get_github_teams(self: SyncEngine) -> list[GitHubTeam]:
        """Get all existing GitHub teams."""
        logger.info('Fetching existing GitHub teams')

        teams = await self.github_client.get_groups()
        logger.info(f'Found {len(teams)} existing GitHub teams')
        return teams

    async def _calculate_user_diffs(
        self: SyncEngine,
        google_users: list[GoogleUser],
        github_users: list[ScimUser],
    ) -> list[UserDiff]:
        """Calculate differences between Google and GitHub users."""
        logger.info('Calculating user differences')

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

        logger.info(f'Found {len(user_diffs)} user differences')
        return user_diffs

    async def _calculate_team_diffs(
        self: SyncEngine,
        google_groups: list[GoogleGroup],
        github_teams: list[GitHubTeam],
        google_users: list[GoogleUser],
    ) -> list[TeamDiff]:
        """Calculate differences between Google Groups and GitHub teams."""
        logger.info('Calculating team differences')

        # Create lookup maps
        github_teams_by_slug = {team.slug: team for team in github_teams}
        user_email_to_username = {
            user.primary_email: self._email_to_username(user.primary_email)
            for user in google_users
        }

        team_diffs = []

        for google_group in google_groups:
            team_slug = self._group_to_team_slug(google_group)
            existing_team = github_teams_by_slug.get(team_slug)

            # Convert member emails to GitHub usernames
            github_members = []
            for email in google_group.member_emails:
                username = user_email_to_username.get(email)
                if username:
                    github_members.append(username)
                else:
                    logger.debug(f'No GitHub user for group member {email}')

            target_team = GitHubTeam(
                name=google_group.name,
                slug=team_slug,
                description=google_group.description,
                members=github_members,
            )

            if existing_team is None:
                # Team needs to be created
                team_diffs.append(
                    TeamDiff(
                        action='create',
                        google_group=google_group,
                        target_team=target_team,
                    )
                )
                self._stats.teams_to_create += 1

            else:
                # Check if team needs to be updated
                if self._teams_differ(existing_team, target_team):
                    team_diffs.append(
                        TeamDiff(
                            action='update',
                            google_group=google_group,
                            existing_team=existing_team,
                            target_team=target_team,
                        )
                    )
                    self._stats.teams_to_update += 1
                else:
                    logger.debug(f'Team {team_slug} is up to date')
                    self._stats.teams_up_to_date += 1

        logger.info(f'Found {len(team_diffs)} team differences')
        return team_diffs

    async def _apply_user_changes(
        self: SyncEngine, user_diffs: list[UserDiff]
    ) -> None:
        """Apply user changes to GitHub Enterprise."""
        logger.info(f'Applying {len(user_diffs)} user changes')

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

    async def _apply_team_changes(
        self: SyncEngine, team_diffs: list[TeamDiff]
    ) -> None:
        """Apply team changes to GitHub Enterprise."""
        logger.info(f'Applying {len(team_diffs)} team changes')

        for diff in team_diffs:
            try:
                if diff.action == 'create' and diff.target_team:
                    created_team = await self.github_client.create_group(
                        diff.target_team
                    )
                    logger.info(f'Created team: {created_team.name}')
                    self._stats.teams_created += 1

                elif (
                    diff.action == 'update'
                    and diff.existing_team
                    and diff.target_team
                ):
                    updated_team = await self.github_client.update_group(
                        str(diff.existing_team.id), diff.target_team
                    )
                    logger.info(f'Updated team: {updated_team.name}')
                    self._stats.teams_updated += 1

            except Exception as e:
                logger.error(f'Failed to apply team change {diff.action}: {e}')
                self._stats.teams_failed += 1

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

    def _preview_team_changes(
        self: SyncEngine, team_diffs: list[TeamDiff]
    ) -> None:
        """Preview team changes for dry-run mode."""
        logger.info(f'DRY RUN: Would apply {len(team_diffs)} team changes:')

        for diff in team_diffs:
            if diff.action == 'create' and diff.google_group:
                logger.info(f'  CREATE TEAM: {diff.google_group.name}')
            elif diff.action == 'update' and diff.google_group:
                logger.info(f'  UPDATE TEAM: {diff.google_group.name}')

    def _should_sync_user(self: SyncEngine, user: GoogleUser) -> bool:
        """Check if user should be synchronized."""
        # Skip suspended users unless explicitly enabled
        if user.suspended and not self.config.include_suspended:
            return False

        # Check organizational unit filters
        if self.config.org_unit_filters:
            if user.org_unit_path not in self.config.org_unit_filters:
                return False

        return True

    def _google_user_to_scim(self: SyncEngine, user: GoogleUser) -> ScimUser:
        """Convert Google User to SCIM User format."""
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
        )

    def _teams_differ(
        self: SyncEngine, existing: GitHubTeam, target: GitHubTeam
    ) -> bool:
        """Check if two GitHub teams have meaningful differences."""
        return (
            existing.name != target.name
            or existing.description != target.description
            or set(existing.members) != set(target.members)
        )

    def _get_primary_email(self: SyncEngine, user: ScimUser) -> str:
        """Extract primary email from SCIM user."""
        for email in user.emails:
            if email.get('primary'):
                return email['value']
        # Fallback to first email if no primary marked
        return user.emails[0]['value'] if user.emails else ''

    def _email_to_username(self: SyncEngine, email: str) -> str:
        """Convert email to GitHub username."""
        # Use local part of email as username
        return email.split('@')[0].replace('.', '-')

    def _group_to_team_slug(self: SyncEngine, group: GoogleGroup) -> str:
        """Convert Google Group to GitHub team slug."""
        # Use group name, convert to lowercase and replace spaces
        return group.name.lower().replace(' ', '-').replace('_', '-')
