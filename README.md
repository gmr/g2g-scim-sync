# g2g-scim-sync

A Python CLI tool that synchronizes Google Workspace users and groups to GitHub Enterprise using SCIM provisioning. Designed for scheduled batch execution via cron.

## Features

- **One-way sync** from Google Workspace to GitHub Enterprise
- **Group-filtered provisioning** - sync only users in specified Google Groups
- **Automatic team creation** - creates missing GitHub teams from Google Groups
- **Group flattening** - converts nested Google Groups into individual GitHub teams
- **User lifecycle management** - handles create, update, suspend, and delete operations
- **Dry run mode** - preview changes without applying them
- **Comprehensive logging** - detailed audit trail for all operations
- **Idempotent operations** - safe to run multiple times

## Requirements

- Python 3.12+
- Google Workspace admin access with service account
- GitHub Enterprise with SCIM API access
- GitHub organization admin permissions

## Installation

```bash
# Clone the repository
git clone https://github.com/gmr/g2g-scim-sync
cd g2g-scim-sync

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package
pip install -e .
```

## Configuration

1. Copy the example configuration:
   ```bash
   cp config.example.toml config.toml
   ```

2. Update `config.toml` with your settings:
   - Google service account JSON file path
   - Google Workspace domain and groups to sync
   - GitHub Enterprise URL, SCIM token, and organization
   - Sync and logging preferences

3. Ensure your Google service account has the following scopes:
   - `https://www.googleapis.com/auth/admin.directory.user.readonly`
   - `https://www.googleapis.com/auth/admin.directory.group.readonly`

## Usage

### Basic Sync
```bash
g2g-scim-sync --config config.toml
```

### Dry Run (Preview Changes)
```bash
g2g-scim-sync --config config.toml --dry-run
```

### Force Delete Suspended Users
```bash
g2g-scim-sync --config config.toml --delete-suspended
```

### Sync Specific Groups Only
```bash
g2g-scim-sync --config config.toml --groups "Engineering,Sales"
```

### Verbose Logging
```bash
g2g-scim-sync --config config.toml --verbose
```

## How It Works

1. **Fetch**: Retrieves users from specified Google Groups via Admin SDK
2. **Flatten**: Processes nested group memberships into flat team structure
3. **Compare**: Diffs current GitHub users/teams via SCIM API
4. **Provision**: Applies changes (users and teams) via SCIM API
5. **Log**: Records all operations for audit trail

## User Lifecycle

- **New Users**: Provisioned on next sync run
- **Updates**: Attribute changes synchronized each run
- **Suspensions**: Suspended Google users become inactive in GitHub
- **Deletions**: Immediate deprovisioning (requires `--delete-suspended`)

## Group Management

- Google Groups are flattened into individual GitHub teams
- Team names use group names as-is (e.g., "Engineering" → "engineering")
- Missing GitHub teams are created automatically
- Nested group memberships cascade (removing from parent removes from children)

## Development

```bash
# Install development dependencies
pip install -e .[dev]

# Set up pre-commit hooks
pre-commit install

# Run tests
pytest

# Run tests with coverage
pytest --cov=g2g_scim_bridge --cov-report=html

# Format code
ruff format

# Lint code
ruff check
```

## License

BSD-3-Clause License. See [LICENSE](LICENSE) file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Ensure tests pass and coverage is maintained
5. Submit a pull request

## Support

- Create an issue on GitHub for bugs or feature requests
- Check existing issues before creating new ones
- Provide detailed information including logs and configuration (sanitized)