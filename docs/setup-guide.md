# Complete Setup Guide for g2g-scim-sync

This guide provides step-by-step instructions to set up g2g-scim-sync for synchronizing Google Workspace users to GitHub Enterprise Cloud organizations using SCIM provisioning.

## Overview

g2g-scim-sync enables automated user provisioning from Google Workspace to GitHub Enterprise Cloud organizations. The setup involves:

1. Google Workspace service account configuration
2. GitHub Enterprise Cloud SCIM personal access token setup
3. SAML SSO configuration
4. Tool configuration and testing

## Prerequisites

- **Google Workspace**: Super Admin access
- **GitHub Enterprise Cloud**: Organization owner permissions
- **Technical Requirements**: Python 3.12+, access to command line
- **SAML SSO**: Must be configured for your GitHub organization

## Part 1: Google Workspace Setup

### 1.1 Create Google Cloud Project and Service Account

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create new project or select existing project
3. Navigate to **APIs & Services > Library**
4. Enable **Admin SDK API**
5. Go to **IAM & Admin > Service Accounts**
6. Click **Create Service Account**
7. Enter name and description
8. Click **Create and Continue**
9. Skip role assignment (will use domain-wide delegation)
10. Click **Done**
11. Click on the created service account
12. Go to **Keys** tab
13. Click **Add Key > Create new key**
14. Select **JSON** format
15. Download and securely store the JSON file

### 1.2 Configure Domain-Wide Delegation

1. In the service account details, copy the **Client ID** (not email address)
2. Go to [Google Admin Console](https://admin.google.com)
3. Navigate to **Security > Access and data control > API controls**
4. Click **Manage Domain Wide Delegation**
5. Click **Add new**
6. Enter the **Client ID** from step 1
7. In **OAuth scopes**, enter:
   ```
   https://www.googleapis.com/auth/admin.directory.user.readonly,https://www.googleapis.com/auth/admin.directory.orgunit.readonly
   ```
8. Click **Authorize**

### 1.3 Admin User Requirements

The service account will impersonate an admin user who must have:
- **Users** → **Read** permission
- **Organizational units** → **Read** permission

## Part 2: GitHub Enterprise Cloud Setup

### 2.1 Verify SAML SSO Configuration

SCIM for GitHub Enterprise Cloud organizations requires SAML SSO to be configured first:

1. Go to your GitHub organization settings
2. Navigate to **Security > Authentication security**
3. Ensure SAML SSO is enabled and working
4. Verify users can authenticate via SAML

### 2.2 Enable SCIM Provisioning

1. In your GitHub organization, go to **Settings > Security > Authentication security**
2. Under **SCIM provisioning**, click **Enable SCIM provisioning**
3. **Critical**: Enable **"Open SCIM Configuration"** - this is required for external SCIM providers

### 2.3 Create Personal Access Token

**Important**: SCIM for GitHub Enterprise Cloud requires a classic personal access token, not OAuth.

1. Sign in as your admin setup user
2. Go to **Settings > Developer settings > Personal access tokens > Tokens (classic)**
3. Click **Generate new token (classic)**
4. Select **scim:enterprise** scope only
5. Set no expiration date
6. Generate and securely store the token

### 2.4 Test SCIM Access

Test the personal access token using your configured endpoint (g2g-scim-sync handles the correct API URLs automatically based on your `hostname` setting).

## Part 3: SAML Configuration Requirements

### 3.1 Google Workspace SAML Configuration

Configure SAML in Google Workspace Admin Console:

1. Go to **Apps > Web and mobile apps > Add app > Add custom SAML app**
2. Configure your GitHub SAML app with your organization's details
3. **Critical**: In **Attribute mapping** section:
   - **Name ID format**: **Email**
   - **Name ID value**: **Primary email**
4. Ensure additional attribute mappings for first name, last name, etc.

### 3.2 User Identifier Matching

- GitHub SCIM identifies users by email address in the `userName` field
- SAML `NameID` must also be the user's email address
- Both must match for proper user linking between SAML authentication and SCIM provisioning

## Part 4: Tool Installation and Configuration

### 4.1 Install g2g-scim-sync

```bash
git clone https://github.com/gmr/g2g-scim-sync
cd g2g-scim-sync
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4.2 Create Configuration File

```bash
cp config.example.toml config.toml
```

### 4.3 Configure Settings

Edit `config.toml`:

```toml
[google]
# Path to your Google service account JSON file
service_account_file = "/secure/path/to/service-account.json"
domain = "yourcompany.com"
subject_email = "admin@yourcompany.com"

# Organizational Units to sync (use full paths)
organizational_units = [
    "/Engineering",
    "/Sales",
    "/Marketing"
]

# Individual users to sync (optional)
individual_users = [
    "contractor@yourcompany.com"
]

[github]
# GitHub Enterprise hostname (handles API URLs automatically)
hostname = "company-slug.ghe.com"  # or "github.com" for standard

# GitHub enterprise account name
enterprise_account = "your-org-name"

# Personal access token with scim:enterprise scope
scim_token = "your_scim_token_here"

[sync]
# Create missing idP groups automatically
create_groups = true

# Flatten nested OUs into individual groups
flatten_ous = true

# Delete suspended users (use with caution)
delete_suspended = false
```

## Part 5: Testing and Validation

### 5.1 Test Google Workspace Connection

```bash
g2g-scim-sync --config config.toml --dry-run --verbose
```

Expected output:
- Successful Google Workspace authentication
- List of users in specified OUs
- No GitHub operations executed (dry-run mode)

### 5.2 Test GitHub SCIM Connection

The dry-run should show:
- Successful GitHub SCIM API connection using personal access token
- Current GitHub organization users and teams
- Planned sync operations (not executed)

### 5.3 Validate User Mapping

Verify:
- Google Workspace users have email addresses matching their GitHub accounts
- SAML SSO users can authenticate with email as NameID
- Email addresses are consistent across Google, SAML, and GitHub

## Part 6: Production Deployment

### 6.1 Initial Sync

Review planned changes:
```bash
g2g-scim-sync --config config.toml --dry-run --verbose > sync-plan.log
```

Execute first sync:
```bash
g2g-scim-sync --config config.toml --verbose
```

### 6.2 Schedule Regular Syncs

```bash
# Hourly sync via cron
0 * * * * /path/to/.venv/bin/g2g-scim-sync --config /path/to/config.toml
```

### 6.3 Monitoring

- Review sync logs regularly
- Monitor SCIM API rate limits
- Track user provisioning success rates
- Set up alerts for sync failures

## Common Issues and Solutions

### Google Workspace Authentication Errors

**"Insufficient Permission"**:
- Verify domain-wide delegation uses **Client ID**, not service account email
- Check subject email has Users and OU read permissions
- Ensure OAuth scopes match exactly

**"Domain-wide delegation not configured"**:
- Confirm Client ID was entered correctly in Admin Console
- Wait up to 10 minutes for delegation changes to propagate

### GitHub SCIM Errors

**"Unauthorized" or "Token invalid"**:
- Verify you're using a classic personal access token with `scim:enterprise` scope
- Check enterprise account name in configuration is correct
- Ensure token was created by admin setup user

**"SCIM not enabled"**:
- Confirm SAML SSO is properly configured first
- Verify SCIM provisioning was enabled in organization settings

### User Sync Issues

**Users not appearing in GitHub**:
- Verify users exist in specified Google OUs
- Check email addresses match between systems
- Ensure SAML NameID is configured as email address

**SAML authentication failures**:
- Confirm NameID format is "Email" in Google Workspace
- Verify SAML attribute mappings include email as NameID
- Check user has access to GitHub SAML application

### idP Group Management Issues

**idP Groups not created**:
- Ensure `create_groups = true` in configuration
- Verify personal access token has group creation permissions
- Check OU paths are case-sensitive and correct

## Security Considerations

- **Credential Storage**: Store service account JSON and personal access tokens securely
- **Scope Limitation**: Use minimum required OAuth scopes
- **Access Control**: Limit admin account permissions to required roles only
- **Monitoring**: Log all sync operations and review regularly
- **Token Rotation**: Rotate personal access tokens and service account keys regularly

## API Rate Limits

GitHub SCIM has rate limits:
- **Primary rate limit**: 5,000 requests per hour for organization SCIM
- **Secondary rate limits**: Based on CPU/memory usage
- Plan sync operations to stay within limits
- Implement exponential backoff for rate limit errors

## Troubleshooting

Enable verbose logging:
```bash
g2g-scim-sync --config config.toml --dry-run --verbose --debug
```

Check specific error patterns:
- Google API errors: Usually permission or delegation issues
- GitHub SCIM errors: Often personal access token or rate limiting issues
- User matching errors: Email address mismatches between systems
