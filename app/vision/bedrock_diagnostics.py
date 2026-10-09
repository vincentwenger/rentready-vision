"""Non-sensitive Bedrock request diagnostics for Detector v4."""

from __future__ import annotations

import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


class DiagnosticConverseClient:
    """Add request context without changing the underlying Bedrock client."""

    def __init__(self, client: Any, *, component: str):
        self.client = client
        self.component = component
        self.request_count = 0

    def converse(self, **kwargs):
        self.request_count += 1

        image_count = sum(
            1
            for message in kwargs.get("messages", [])
            for block in message.get("content", [])
            if isinstance(block, dict) and "image" in block
        )

        context = {
            "component": self.component,
            "request_number": self.request_count,
            "model_id": str(kwargs.get("modelId", "unknown")),
            "image_count": image_count,
        }

        try:
            return self.client.converse(**kwargs)
        except Exception as exc:
            # Preserve the original exception type for terminal-error
            # classification, and attach safe diagnostic metadata.
            try:
                exc.rentready_bedrock_context = context
            except (AttributeError, TypeError):
                pass

            LOGGER.exception(
                "Bedrock Converse failed: component=%s "
                "request=%d model=%s images=%d",
                context["component"],
                context["request_number"],
                context["model_id"],
                context["image_count"],
            )
            raise

    def __getattr__(self, name):
        return getattr(self.client, name)
