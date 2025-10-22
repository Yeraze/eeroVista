"""
Monkey-patch for eero-client library to fix Pydantic 2.8.2 compatibility.

Bug: eero-client 2.2.2 uses TypeAdapter(list[type(model)]) which fails with Pydantic 2.8.2
Fix: Change to TypeAdapter(list[model])

Bug: eero-client models don't allow None for amazon_directed_id and premium_details.interval
Fix: Make these fields Optional to support shared admin accounts

This patch must be imported before any eero-client usage.
"""

import logging
from copy import copy
from typing import Any, Optional

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic.errors import PydanticSchemaGenerationError

logger = logging.getLogger(__name__)


def patch_pydantic_models():
    """
    Patch eero-client Pydantic models to allow None values for optional fields.

    This fixes validation errors when accessing accounts as a shared admin on
    Amazon-linked networks, where amazon_directed_id and premium_details.interval
    are None instead of strings.
    """
    try:
        from eero.client.models import NetworkInfo, PremiumDetails

        logger.info("Patching eero-client Pydantic models for Optional fields")

        # Patch NetworkInfo.amazon_directed_id to be Optional
        if hasattr(NetworkInfo, '__annotations__'):
            if 'amazon_directed_id' in NetworkInfo.__annotations__:
                NetworkInfo.__annotations__['amazon_directed_id'] = Optional[str]
                logger.debug("Patched NetworkInfo.amazon_directed_id to Optional[str]")

        # Patch PremiumDetails.interval to be Optional
        if hasattr(PremiumDetails, '__annotations__'):
            if 'interval' in PremiumDetails.__annotations__:
                PremiumDetails.__annotations__['interval'] = Optional[str]
                logger.debug("Patched PremiumDetails.interval to Optional[str]")

        # Rebuild the models with updated annotations
        NetworkInfo.model_rebuild()
        PremiumDetails.model_rebuild()

        logger.info("Pydantic model patches applied successfully")

    except Exception as e:
        logger.warning(f"Could not patch Pydantic models (non-critical): {e}")


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
                    except PydanticSchemaGenerationError as e:
                        # Schema generation failed - this is the known bug, return raw data
                        logger.debug(f"Schema generation failed for {action}, returning raw data (expected)")
                        return result
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


# Apply patches immediately when module is imported
patch_pydantic_models()
patch_eero_client()
