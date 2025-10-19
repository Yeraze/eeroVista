"""
Monkey-patch for eero-client library to fix Pydantic 2.8.2 compatibility.

Bug: eero-client 2.2.2 uses TypeAdapter(list[type(model)]) which fails with Pydantic 2.8.2
Fix: Change to TypeAdapter(list[model])

This patch must be imported before any eero-client usage.
"""

import logging
from copy import copy
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

logger = logging.getLogger(__name__)


def patch_eero_client():
    """Apply runtime patch to fix eero-client Pydantic compatibility."""
    try:
        from eero.client.routes import method_factory
        from eero.client.routes.routes import GET_RESOURCES, POST_RESOURCES, Resource
        from eero.client.models import ErrorMeta

        logger.info("Applying eero-client Pydantic 2.8.2 compatibility patch")

        # Store reference to original make_method for debugging
        original_make_method = method_factory.make_method

        def patched_make_method(method: str, action: str, resource: Resource, **kwargs: Any):
            """Patched version of make_method with fixed TypeAdapter usage."""
            method = copy(method)
            action = copy(action)
            resource = copy(resource)

            def func(self, **kwargs: str) -> None | dict[str, Any] | BaseModel | list[BaseModel]:
                url, model = resource
                for key, value in kwargs.items():
                    url = url.replace("<{}>".format(key), str(value))

                result = self.refreshed(lambda: self.client.request(method, url))

                if model is not None:
                    try:
                        if isinstance(result, list):
                            # FIX: Use list[model] instead of list[type(model)]
                            return TypeAdapter(list[model]).validate_python(result)  # type: ignore
                        return model.model_validate(result)  # type: ignore
                    except ValidationError as e:
                        if model == ErrorMeta:
                            logger.warning(f"Not Implemented: {action} (expected error)")
                            return result
                        # Validation failed - return raw data instead of crashing
                        logger.debug(f"Validation failed for {action}, returning raw data: {e}")
                        return result
                    except Exception as e:
                        logger.error(
                            "[%s] Unexpected error: %s",
                            action,
                            e,
                            exc_info=False,
                        )
                        # Return raw data as fallback
                        return result
                return result

            return lambda self, **caller_kwargs: func(self, **kwargs, **caller_kwargs)

        # Apply the patch
        method_factory.make_method = patched_make_method

        logger.info("eero-client patch applied successfully")

    except Exception as e:
        logger.error(f"Failed to patch eero-client: {e}")
        raise


# Apply patch immediately when module is imported
patch_eero_client()
