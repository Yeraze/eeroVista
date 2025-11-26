"""Setup configuration for eeroVista."""

from pathlib import Path

from setuptools import find_packages, setup


def read_requirements():
    """Read requirements from requirements.txt."""
    requirements_file = Path(__file__).parent / "requirements.txt"
    with requirements_file.open() as f:
        return [
            line.strip()
            for line in f
            if line.strip() and not line.startswith("#")
        ]


def get_version():
    """Read version from src/__init__.py.

    This is the single source of truth for version numbers.
    Returns:
        str: Version string (e.g., "2.4.6")
    Raises:
        RuntimeError: If version cannot be read from __init__.py
    """
    import re

    init_file = Path(__file__).parent / "src" / "__init__.py"

    try:
        with init_file.open() as f:
            content = f.read()
            # Match __version__ = "x.y.z" or __version__ = 'x.y.z'
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1)
            raise RuntimeError("Could not find __version__ in src/__init__.py")
    except FileNotFoundError:
        raise RuntimeError(
            f"Could not find {init_file}. Ensure src/__init__.py exists."
        )
    except Exception as e:
        raise RuntimeError(f"Error reading version from {init_file}: {e}")


setup(
    name="eerovista",
    version=get_version(),
    description="Read-only monitoring for Eero mesh networks",
    author="eeroVista Contributors",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=read_requirements(),
)
