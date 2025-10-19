# Development Guide

Guide for setting up a development environment and contributing to eeroVista.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose
- Git
- An Eero mesh network for testing

## Local Development Setup

### 1. Clone Repository

```bash
git clone https://github.com/yeraze/eerovista.git
cd eerovista
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt  # Development dependencies
```

### 4. Set Up Database

```bash
mkdir data
python -m src.models.database  # Initialize schema
```

### 5. Run Development Server

```bash
# Set environment variables
export DATABASE_PATH=./data/eerovista.db
export LOG_LEVEL=DEBUG
export COLLECTION_INTERVAL_DEVICES=30
export COLLECTION_INTERVAL_NETWORK=60

# Run FastAPI with auto-reload
uvicorn src.main:app --reload --host 0.0.0.0 --port 8080
```

Access the development server at `http://localhost:8080`

## Project Structure

```
eerovista/
├── src/                        # Source code
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # Configuration
│   ├── models/                 # Database models
│   ├── collectors/             # Data collectors
│   ├── eero_client/            # Eero API wrapper
│   ├── api/                    # API endpoints
│   ├── scheduler/              # Background jobs
│   ├── utils/                  # Utilities
│   └── templates/              # HTML templates
├── static/                     # Static assets
│   ├── css/
│   ├── js/
│   └── img/
├── docs/                       # Documentation
├── tests/                      # Test suite
├── Dockerfile                  # Container definition
├── docker-compose.yml          # Docker composition
├── requirements.txt            # Python dependencies
└── requirements-dev.txt        # Dev dependencies
```

## Development Dependencies

The `requirements-dev.txt` includes:

```
# Testing
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
httpx>=0.24.0  # For testing FastAPI

# Code quality
black>=23.7.0  # Code formatter
ruff>=0.0.280  # Fast linter
mypy>=1.4.0    # Type checker

# Development tools
ipython>=8.14.0
```

Install with:
```bash
pip install -r requirements-dev.txt
```

## Code Style

### Formatting with Black

```bash
# Format all Python files
black src/ tests/

# Check without modifying
black --check src/ tests/
```

Configuration in `pyproject.toml`:
```toml
[tool.black]
line-length = 100
target-version = ['py311']
```

### Linting with Ruff

```bash
# Lint all files
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/
```

### Type Checking with mypy

```bash
# Type check
mypy src/
```

## Running Tests

### Run All Tests

```bash
pytest
```

### Run with Coverage

```bash
pytest --cov=src --cov-report=html
open htmlcov/index.html  # View coverage report
```

### Run Specific Tests

```bash
# Single test file
pytest tests/test_collectors.py

# Single test function
pytest tests/test_collectors.py::test_device_collector

# Tests matching pattern
pytest -k "device"
```

### Test Structure

```
tests/
├── conftest.py               # Pytest fixtures
├── test_collectors.py        # Collector tests
├── test_eero_client.py       # Eero client tests
├── test_api.py               # API endpoint tests
├── test_database.py          # Database model tests
└── test_scheduler.py         # Scheduler tests
```

## Writing Tests

### Example Test

```python
import pytest
from httpx import AsyncClient
from src.main import app

@pytest.mark.asyncio
async def test_health_endpoint():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
```

### Fixtures

Common fixtures in `conftest.py`:

```python
import pytest
from sqlalchemy import create_engine
from src.models.database import Base

@pytest.fixture
def db_session():
    """Create test database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # ... return session

@pytest.fixture
def mock_eero_client():
    """Mock Eero API client."""
    # ... return mock
```

## Database Migrations

### Create Migration

When modifying database models, create a migration:

```bash
# Generate migration
alembic revision --autogenerate -m "Add new table"

# Apply migration
alembic upgrade head
```

### Migration Files

Located in `alembic/versions/`:
```
alembic/
├── env.py
├── script.py.mako
└── versions/
    └── 001_initial_schema.py
```

## Docker Development

### Build Image

```bash
docker build -t eerovista:dev .
```

### Run Development Container

```bash
docker compose -f docker-compose.dev.yml up
```

**docker-compose.dev.yml**:
```yaml
version: '3.8'

services:
  eerovista:
    build: .
    volumes:
      - ./src:/app/src  # Mount source for live reload
      - ./data:/data
    environment:
      - LOG_LEVEL=DEBUG
    command: uvicorn src.main:app --reload --host 0.0.0.0 --port 8080
```

## Debugging

### VS Code Launch Configuration

`.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "FastAPI",
      "type": "python",
      "request": "launch",
      "module": "uvicorn",
      "args": [
        "src.main:app",
        "--reload",
        "--host", "0.0.0.0",
        "--port", "8080"
      ],
      "jinja": true,
      "env": {
        "DATABASE_PATH": "./data/eerovista.db",
        "LOG_LEVEL": "DEBUG"
      }
    }
  ]
}
```

### Logging

Use structured logging:

```python
import logging

logger = logging.getLogger(__name__)

logger.debug("Device collected", extra={"mac": device.mac, "connected": True})
logger.info("Collector started", extra={"interval": 30})
logger.warning("API rate limited", extra={"retry_after": 60})
logger.error("Database error", exc_info=True)
```

## Contributing

### Workflow

1. **Fork** the repository
2. **Create branch**: `git checkout -b feature/my-feature`
3. **Make changes** and commit
4. **Run tests**: `pytest`
5. **Format code**: `black src/ && ruff check src/`
6. **Push**: `git push origin feature/my-feature`
7. **Create Pull Request**

### Commit Messages

Follow conventional commits:

```
feat: Add device filtering to API
fix: Correct signal strength calculation
docs: Update installation guide
test: Add collector unit tests
refactor: Simplify database queries
```

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing completed
- [ ] All tests pass

## Checklist
- [ ] Code follows style guidelines (black, ruff)
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings
```

## Release Process

### Version Numbering

Follow Semantic Versioning (SemVer):
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes

### Creating a Release

1. **Update version** in `src/__init__.py`:
   ```python
   __version__ = "1.2.0"
   ```

2. **Update CHANGELOG.md**:
   ```markdown
   ## [1.2.0] - 2025-10-19
   ### Added
   - New speedtest visualization
   ### Fixed
   - Signal strength calculation
   ```

3. **Commit and tag**:
   ```bash
   git add src/__init__.py CHANGELOG.md
   git commit -m "chore: Release v1.2.0"
   git tag -a v1.2.0 -m "Release v1.2.0"
   git push origin main --tags
   ```

4. **GitHub Actions** will:
   - Run tests
   - Build Docker image
   - Publish to Docker Hub
   - Create GitHub release

## Development Tools

### Database Browser

View SQLite database:
```bash
sqlite3 data/eerovista.db
.tables
SELECT * FROM devices LIMIT 10;
```

Or use [DB Browser for SQLite](https://sqlitebrowser.org/).

### API Testing

Use the auto-generated docs:
- Swagger UI: `http://localhost:8080/docs`
- ReDoc: `http://localhost:8080/redoc`

Or use curl:
```bash
curl -X GET http://localhost:8080/api/devices | jq
```

### Performance Profiling

```python
# Add to endpoint for profiling
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# ... code to profile ...

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

## Common Development Tasks

### Add New Collector

1. Create file in `src/collectors/my_collector.py`
2. Inherit from `BaseCollector`
3. Implement `collect()` method
4. Register in `src/scheduler/jobs.py`
5. Add tests in `tests/test_collectors.py`

### Add New API Endpoint

1. Add route in `src/api/my_routes.py`
2. Register router in `src/main.py`
3. Add OpenAPI documentation
4. Add tests in `tests/test_api.py`
5. Update API documentation in `docs/api-reference.md`

### Add New Database Table

1. Define model in `src/models/database.py`
2. Create migration: `alembic revision --autogenerate`
3. Test migration: `alembic upgrade head`
4. Add model tests in `tests/test_database.py`

## Troubleshooting Development

### Import Errors

Ensure you're in the virtual environment:
```bash
which python  # Should show venv path
pip list | grep fastapi
```

### Database Lock Errors

SQLite doesn't handle concurrent writes well:
```bash
# Kill any running instances
pkill -f uvicorn

# Remove lock
rm data/eerovista.db-journal
```

### Port Already in Use

```bash
# Find process using port 8080
lsof -i :8080

# Kill it
kill -9 <PID>
```

## Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
- [Catppuccin Style Guide](https://github.com/catppuccin/catppuccin)

## Support

For development questions:
- GitHub Discussions: https://github.com/yeraze/eerovista/discussions
- Issues: https://github.com/yeraze/eerovista/issues
