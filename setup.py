"""Setup configuration for eeroVista."""

from setuptools import find_packages, setup

setup(
    name="eerovista",
    version="0.1.0",
    description="Read-only monitoring for Eero mesh networks",
    author="eeroVista Contributors",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        line.strip()
        for line in open("requirements.txt")
        if line.strip() and not line.startswith("#")
    ],
)
