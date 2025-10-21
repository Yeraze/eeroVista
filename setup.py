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


setup(
    name="eerovista",
    version="0.8.0",
    description="Read-only monitoring for Eero mesh networks",
    author="eeroVista Contributors",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=read_requirements(),
)
