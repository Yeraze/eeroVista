# Tests

This directory contains the test suite for eeroVista.

## Running Tests Locally

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-asyncio

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_example.py

# Run tests matching a pattern
pytest -k "test_version"
```

## Test Organization

- `test_*.py` - Test files (auto-discovered by pytest)
- `conftest.py` - Shared fixtures and configuration
- `__init__.py` - Package marker

## Writing Tests

### Basic Test

```python
def test_something():
    result = function_under_test()
    assert result == expected_value
```

### Async Test

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result is not None
```

### Using Fixtures

```python
@pytest.fixture
def sample_device():
    return {
        "mac_address": "00:11:22:33:44:55",
        "name": "Test Device",
    }

def test_with_fixture(sample_device):
    assert sample_device["mac_address"] is not None
```

## Coverage

After running tests with coverage, open `htmlcov/index.html` to view detailed coverage reports.

Target: >80% code coverage
