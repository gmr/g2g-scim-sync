"""Google Workspace to GitHub Enterprise SCIM synchronization tool."""

from importlib import metadata

try:
    __version__ = metadata.version('g2g-scim-sync')
except metadata.PackageNotFoundError:
    # Fallback when running from source without installation
    __version__ = '0.0.0-dev'

__author__ = 'Gavin M. Roy <gavinr@aweber.com>'
