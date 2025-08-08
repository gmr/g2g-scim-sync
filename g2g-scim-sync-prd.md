# g2g-scim-sync Product Requirements Document

## Overview
A Python CLI tool that synchronizes Google Workspace users and groups to GitHub Enterprise using SCIM provisioning. Designed for scheduled batch execution via cron.

## Core Requirements

### Authentication
- **Google Admin SDK**: Service account JSON credentials
- **GitHub SCIM API**: Service token provided by GitHub Enterprise
- **Configuration**: TOML format for all settings

### User Provisioning
- **Scope**: Sync users filtered by Google Group membership only
- **Direction**: One-way sync (Google Workspace → GitHub Enterprise)
- **Operations**: Create, update, suspend, delete users
- **Attributes**: Map standard SCIM user attributes (userName, emails, name, active)

### Group/Team Management
- **Strategy**: Flatten nested Google Groups into individual GitHub Teams
- **Naming**: Use group names as-is (e.g., "Engineering" → "engineering")
- **Creation**: Automatically create missing GitHub Teams
- **Membership**: Cascade removals (removing from parent removes from all child teams)

### User Lifecycle
- **New Users**: Provision on next sync run
- **Updates**: Sync attribute changes on each run
- **Suspensions**: Suspended Google users become inactive in GitHub
- **Deletions**: Immediate deprovisioning with optional `--delete-suspended` flag

## Technical Specifications

- This should be a modern Python application targeting Python 3.12+.
- Test coverage should include unit tests and target 90% or greater coverage

### CLI Interface
```bash
# Basic sync
g2g-scim-sync --config config.toml

# Dry run mode
g2g-scim-sync --config config.toml --dry-run

# Force delete suspended users
g2g-scim-sync --config config.toml --delete-suspended

# Sync specific groups only
g2g-scim-sync --config config.toml --groups "Engineering,Sales"
```

### Configuration Format (TOML)
```toml
[google]
service_account_file = "path/to/service-account.json"
domain = "company.com"
groups = ["Engineering", "Sales", "Marketing"]

[github]
enterprise_url = "https://github.company.com"
scim_token = "ghes_token_here"
organization = "company-org"

[sync]
delete_suspended = false
create_teams = true
flatten_groups = true

[logging]
level = "INFO"
file = "g2g-scim-sync.log"
```

### Key Features
- **Dry Run Mode**: Preview changes without applying
- **Detailed Logging**: Audit trail for all operations
- **Error Handling**: Graceful handling of API rate limits and failures
- **Idempotent**: Safe to run multiple times
- **Single Organization**: Focus on one GitHub Enterprise org

### Data Flow
1. **Fetch**: Get users from specified Google Groups via Admin SDK
2. **Flatten**: Process nested group memberships into flat team list
3. **Compare**: Diff current GitHub users/teams via SCIM API
4. **Provision**: Apply changes (users and teams) via SCIM API
5. **Log**: Record all operations for audit

### Dependencies
- **Google Admin SDK**: User and group management
- **GitHub REST API**: SCIM endpoints for enterprise
- **Standard Libraries**: `logging`, `configparser`, `argparse`
- **HTTP Client**: `httpx`

## Success Criteria
- Users in specified Google Groups appear in GitHub Enterprise
- Google Group hierarchy flattened to GitHub Teams
- Suspended Google users become inactive in GitHub
- Tool runs reliably on cron schedule
- Comprehensive logging for troubleshooting
- Safe dry-run mode for testing changes

## Out of Scope (V1)
- Bidirectional sync
- Multiple GitHub organizations
- Real-time webhooks
- Custom attribute mapping
- Group hierarchy preservation
- SAML configuration management
