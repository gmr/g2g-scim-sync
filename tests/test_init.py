"""Tests for package initialization."""

import g2g_scim_sync


def test_version_exists() -> None:
    """Test that package version is available."""
    assert hasattr(g2g_scim_sync, '__version__')
    assert isinstance(g2g_scim_sync.__version__, str)
    assert len(g2g_scim_sync.__version__) > 0


def test_author_exists() -> None:
    """Test that package author is available."""
    assert hasattr(g2g_scim_sync, '__author__')
    assert isinstance(g2g_scim_sync.__author__, str)
    assert 'Gavin M. Roy' in g2g_scim_sync.__author__


def test_package_not_found_fallback() -> None:
    """Test fallback version when package not installed."""
    from unittest import mock
    from importlib import metadata
    import g2g_scim_sync

    # Mock metadata.version to raise PackageNotFoundError
    with mock.patch.object(metadata, 'version') as mock_version:
        mock_version.side_effect = metadata.PackageNotFoundError(
            'g2g-scim-sync'
        )

        # Force reload of the module to trigger the exception handling
        import importlib

        importlib.reload(g2g_scim_sync)

        # Should fall back to development version
        assert g2g_scim_sync.__version__ == '0.0.0-dev'
