"""Command-line interface for g2g-scim-sync."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import NoReturn

from g2g_scim_sync.config import Config
from g2g_scim_sync.github_client import GitHubScimClient
from g2g_scim_sync.google_client import GoogleWorkspaceClient
from g2g_scim_sync.sync_engine import SyncEngine


def setup_logging(config: Config) -> None:
    """Configure logging based on configuration settings."""
    level = getattr(logging, config.logging.level.upper())

    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Setup root logger
    logger = logging.getLogger()
    logger.setLevel(level)

    for name in {'googleapiclient', 'httpcore', 'httpx', 'urllib3'}:
        logging.getLogger(name).setLevel(logging.CRITICAL)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler if specified
    if config.logging.file:
        file_handler = logging.FileHandler(config.logging.file)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)


async def run_sync(config: Config, dry_run: bool) -> None:
    """Run the synchronization process."""
    logger = logging.getLogger(__name__)

    try:
        # Initialize clients
        google_client = GoogleWorkspaceClient(
            service_account_file=config.google.service_account_file,
            domain=config.google.domain,
            subject_email=config.google.subject_email,
        )
        github_client = GitHubScimClient(
            hostname=config.github.hostname,
            scim_token=config.github.scim_token,
            enterprise_account=config.github.enterprise_account,
        )

        # Create sync engine
        sync_engine = SyncEngine(
            google_client=google_client,
            github_client=github_client,
            config=config.sync,
            github_config=config.github,
        )

        # Run synchronization
        result = await sync_engine.synchronize(
            ou_paths=config.google.organizational_units,
            individual_users=config.google.individual_users,
            dry_run=dry_run,
        )

        if not result.success:
            raise RuntimeError(result.error)

    except Exception as e:
        logger.error(f'Synchronization failed: {e}')
        raise


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Google Workspace to GitHub Enterprise SCIM sync tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '--config',
        required=True,
        type=Path,
        help='Path to TOML configuration file',
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without applying them',
    )

    parser.add_argument(
        '--delete-suspended',
        action='store_true',
        help='Delete suspended users instead of just deactivating',
    )

    parser.add_argument(
        '-ou',
        '--organizational-units',
        help='Comma-separated list of OU paths to sync (overrides config)',
    )

    parser.add_argument(
        '--individual-users',
        help='Comma-separated list of user emails to sync (overrides config)',
    )

    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='Enable verbose logging (DEBUG level)',
    )

    return parser.parse_args(args)


def main() -> NoReturn:
    """Main entry point for the CLI."""
    try:
        args = parse_args()

        # Load configuration
        config = Config.from_file(args.config)

        # Override config with CLI arguments
        if args.verbose:
            config.logging.level = 'DEBUG'
        if args.delete_suspended:
            config.sync.delete_suspended = True
        if args.organizational_units:
            config.google.organizational_units = [
                ou.strip() for ou in args.organizational_units.split(',')
            ]
        if args.individual_users:
            config.google.individual_users = [
                user.strip() for user in args.individual_users.split(',')
            ]

        # Setup logging
        setup_logging(config)
        logger = logging.getLogger(__name__)

        if args.dry_run:
            logger.info('Running in DRY RUN mode - no changes will be made')

        logger.debug(f'Starting sync with config: {args.config}')
        logger.debug(f'Target OUs: {config.google.organizational_units}')
        if config.google.individual_users:
            logger.debug(f'Individual users: {config.google.individual_users}')

        # Run synchronization
        asyncio.run(run_sync(config, args.dry_run))
        logger.debug('Sync completed successfully')

    except KeyboardInterrupt:
        print('Interrupted by user', file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
