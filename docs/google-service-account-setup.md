# Google Workspace Service Account Setup Guide

This document explains how to set up service account credentials for Google Workspace to use with g2g-scim-sync.

## Prerequisites

- Google Workspace admin access
- Access to Google Cloud Console
- Permissions to enable APIs and create service accounts

## Step-by-Step Setup

### 1. Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Click **Select a project** at the top of the page
3. Click **New Project**
4. Enter a project name (e.g., "g2g-scim-sync")
5. Select your organization if applicable
6. Click **Create**

### 2. Enable Required APIs

1. In the Google Cloud Console, go to **APIs & Services** > **Library**
2. Search for and enable:
   - **Admin SDK API** (provides user and organizational unit directory access)

### 3. Create a Service Account

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **Service account**
3. Fill in the service account details:
   - **Name**: `g2g-scim-sync` (or your preferred name)
   - **Description**: `Service account for g2g-scim-sync tool`
4. Click **Create and Continue**
5. Skip the optional steps by clicking **Done**

### 4. Generate Service Account Key

1. In the **Credentials** page, find your service account under **Service Accounts**
2. Click on the service account email
3. Go to the **Keys** tab
4. Click **Add Key** > **Create new key**
5. Select **JSON** format
6. Click **Create**
7. The JSON key file will download automatically
8. **Secure this file** - it contains sensitive credentials

### 5. Configure Domain-Wide Delegation

This step is crucial for accessing Google Workspace data:

1. In the service account details page, copy the **Client ID** (numeric value)
2. Go to the [Google Admin Console](https://admin.google.com)
3. Navigate to **Security** > **API Controls** > **Manage Domain-wide Delegation**
4. Click **Add new**
5. Enter the **Client ID** from step 1
6. Add the following OAuth scopes (comma-separated):
   ```
   https://www.googleapis.com/auth/admin.directory.user.readonly,https://www.googleapis.com/auth/admin.directory.orgunit.readonly
   ```
7. Click **Authorize**

### 6. Enable Subject Impersonation (Optional but Recommended)

To use a specific admin user for API calls:

1. In your service account configuration, note that you may need to impersonate an admin user
2. Ensure the admin user has the following roles:
   - **Users Reader** (to read user data)
   - **Organizational Units Reader** (to read OU structure and data)

## Security Best Practices

### File Storage
- Store the JSON key file in a secure location outside your project repository
- Set restrictive file permissions (600 on Unix systems):
  ```bash
  chmod 600 /path/to/service-account.json
  ```
- Never commit the key file to version control

### Access Control
- Use the principle of least privilege
- Only grant the minimum required scopes:
  - `https://www.googleapis.com/auth/admin.directory.user.readonly`
  - `https://www.googleapis.com/auth/admin.directory.orgunit.readonly`
- Consider creating a dedicated admin user for API access

### Key Rotation
- Regularly rotate service account keys (recommended: every 90 days)
- Monitor key usage through Google Cloud Console
- Delete unused or old keys

## Understanding Organizational Units

Google Workspace Organizational Units (OUs) are hierarchical containers that organize users by department, location, or role. Unlike groups, OUs represent the organizational structure and users are directly assigned to them.

### Finding OU Paths

1. Go to the [Google Admin Console](https://admin.google.com)
2. Navigate to **Directory** > **Organizational units**
3. The path shown in the breadcrumb is what you'll use in configuration
4. Examples:
   - Root organization: `/`
   - Engineering department: `/Engineering`
   - Sub-departments: `/Engineering/Backend` or `/Engineering/Frontend`

### OU vs Groups Differences

- **OUs**: Hierarchical structure, users directly belong to them, used for policies and organization
- **Groups**: Flat collections, users can belong to multiple groups, used for collaboration and permissions

## Configuration

After creating the service account, update your `config.toml` file:

```toml
[google]
# Path to your Google service account JSON file
service_account_file = "/secure/path/to/service-account.json"

# Your Google Workspace domain
domain = "yourcompany.com"

# List of Google Workspace Organizational Unit paths to synchronize
organizational_units = ["/Engineering", "/Sales", "/Marketing"]
```

## Testing Your Setup

You can test your service account configuration by running a dry run:

```bash
g2g-scim-sync --config config.toml --dry-run --verbose
```

This will attempt to connect to Google Workspace and list the users/organizational units without making any changes.

## Troubleshooting

### Common Errors

**Error: "Insufficient Permission"**
- Verify domain-wide delegation is configured correctly
- Check that the service account has the required OAuth scopes
- Ensure the JSON key file path is correct

**Error: "API not enabled"**
- Verify that Admin SDK API is enabled in Google Cloud Console
- Wait a few minutes after enabling APIs for them to propagate

**Error: "Subject not found"**
- If using subject impersonation, verify the admin user email is correct
- Ensure the admin user has sufficient permissions

**Error: "Access denied"**
- Check that the service account client ID is authorized in Admin Console
- Verify the OAuth scopes are entered correctly (no extra spaces)

### Debugging Steps

1. **Verify API Access**:
   - Go to Google Cloud Console > APIs & Services > Dashboard
   - Confirm Admin SDK API shows recent activity

2. **Check Service Account**:
   - Verify the service account exists and has the JSON key
   - Confirm domain-wide delegation is enabled

3. **Test Minimal Access**:
   - Try accessing a single organizational unit first (e.g., "/Engineering")
   - Use verbose logging to see detailed error messages

## References

- [Google Workspace Admin SDK Documentation](https://developers.google.com/admin-sdk)
- [Service Account Authentication](https://cloud.google.com/docs/authentication/production)
- [Domain-wide Delegation](https://developers.google.com/identity/protocols/oauth2/service-account#delegatingauthority)
- [OAuth 2.0 Scopes for Google APIs](https://developers.google.com/identity/protocols/oauth2/scopes#admin-sdk)

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Review the application logs for detailed error messages
3. Verify your Google Workspace admin permissions
4. Create an issue on the project repository with sanitized logs
