"""Example test file - replace with actual tests."""

import pytest


def test_example():
    """Example test that always passes."""
    assert True


def test_version():
    """Test that version is defined."""
    from src import __version__
    assert __version__ is not None
    assert isinstance(__version__, str)


@pytest.mark.asyncio
async def test_async_example():
    """Example async test."""
    result = await async_function()
    assert result is True


async def async_function():
    """Example async function."""
    return True
