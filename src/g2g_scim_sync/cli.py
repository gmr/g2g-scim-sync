"""Command-line interface for g2g-scim-sync."""

import argparse
import logging
import sys
from pathlib import Path
from typing import NoReturn

from g2g_scim_sync.config import Config


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
        '--groups',
        help='Comma-separated list of groups to sync (overrides config)',
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
        if args.groups:
            config.google.groups = [g.strip() for g in args.groups.split(',')]

        # Setup logging
        setup_logging(config)
        logger = logging.getLogger(__name__)

        if args.dry_run:
            logger.info('Running in DRY RUN mode - no changes will be made')

        logger.info(f'Starting sync with config: {args.config}')
        logger.info(f'Target groups: {config.google.groups}')

        # TODO: Implement sync logic
        logger.info('Sync completed successfully')

    except KeyboardInterrupt:
        print('Interrupted by user', file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)

    sys.exit(0)


if __name__ == '__main__':
    main()
