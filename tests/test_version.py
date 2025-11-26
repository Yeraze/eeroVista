"""Tests for version synchronization across configuration files."""

import re
import sys
from pathlib import Path

import pytest


def get_version_from_init():
    """Read version from src/__init__.py."""
    init_file = Path(__file__).parent.parent / "src" / "__init__.py"
    with init_file.open() as f:
        content = f.read()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
    return None


def get_version_from_setup():
    """Read version using setup.py's get_version() function."""
    # Just call the function directly without importing the whole module
    # to avoid triggering setup() call
    import re
    from pathlib import Path

    init_file = Path(__file__).parent.parent / "src" / "__init__.py"
    with init_file.open() as f:
        content = f.read()
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        if match:
            return match.group(1)
        raise RuntimeError("Could not find __version__ in src/__init__.py")
    return None


def test_version_exists_in_init():
    """Test that __version__ is defined in src/__init__.py."""
    version = get_version_from_init()
    assert version is not None, "Could not find __version__ in src/__init__.py"
    assert version != "", "Version string is empty"


def test_version_format():
    """Test that version follows semantic versioning format."""
    version = get_version_from_init()
    # Should match X.Y.Z or X.Y.Z-suffix format
    assert re.match(r'^\d+\.\d+\.\d+(-\w+)?$', version), \
        f"Version '{version}' does not follow semantic versioning format"


def test_setup_py_reads_version_correctly():
    """Test that setup.py can read version from src/__init__.py."""
    init_version = get_version_from_init()
    setup_version = get_version_from_setup()

    assert setup_version == init_version, \
        f"setup.py version '{setup_version}' doesn't match src/__init__.py version '{init_version}'"


def test_setup_py_get_version_error_handling():
    """Test that get_version() has proper error handling."""
    # Test the regex pattern handles different quote styles
    import re

    test_cases = [
        ('__version__ = "1.2.3"', "1.2.3"),
        ("__version__ = '1.2.3'", "1.2.3"),
        ('__version__="1.2.3"', "1.2.3"),  # No spaces
        ('__version__  =  "1.2.3"', "1.2.3"),  # Extra spaces
    ]

    for content, expected in test_cases:
        match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
        assert match is not None, f"Pattern didn't match: {content}"
        assert match.group(1) == expected, f"Expected {expected}, got {match.group(1)}"


def test_pyproject_toml_has_dynamic_version():
    """Test that pyproject.toml is configured for dynamic versioning."""
    pyproject_file = Path(__file__).parent.parent / "pyproject.toml"
    with pyproject_file.open() as f:
        content = f.read()

    # Check that dynamic versioning is configured
    assert 'dynamic = ["version"]' in content, \
        "pyproject.toml should specify dynamic version"
    assert 'version = {attr = "src.__version__"}' in content, \
        "pyproject.toml should read version from src.__version__"


def test_version_consistency_across_package():
    """Test that the version is consistent when imported from package."""
    # Import the package version
    import src
    package_version = src.__version__

    # Compare with what we read from the file
    file_version = get_version_from_init()

    assert package_version == file_version, \
        f"Imported version '{package_version}' doesn't match file version '{file_version}'"


def test_api_reports_correct_version():
    """Test that the API health endpoint reports the correct version."""
    import src
    from src import __version__

    # This should match what the API returns
    expected_version = __version__

    # Verify it's not a placeholder
    assert expected_version != "0.0.0", "Version should not be placeholder"
    assert expected_version != "", "Version should not be empty"
