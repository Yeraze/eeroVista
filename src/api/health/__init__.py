"""Health check and status API endpoints.

This subpackage contains:
- routes: Core health, device, node, and routing endpoints
- analytics: Bandwidth analysis, health scores, and performance metrics
- models: Shared request models and helper functions
"""

from fastapi import APIRouter

from .analytics import router as analytics_router
from .routes import router as routes_router

# Combined router that includes all health endpoints
router = APIRouter()
router.include_router(routes_router)
router.include_router(analytics_router)
