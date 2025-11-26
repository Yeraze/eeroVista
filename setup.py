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
    """Read version from src/__init__.py."""
    init_file = Path(__file__).parent / "src" / "__init__.py"
    with init_file.open() as f:
        for line in f:
            if line.startswith("__version__"):
                return line.split('"')[1]
    return "0.0.0"


setup(
    name="eerovista",
    version=get_version(),
    description="Read-only monitoring for Eero mesh networks",
    author="eeroVista Contributors",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=read_requirements(),
)
