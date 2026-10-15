# Copyright 2026 Google LLC
# Custom ADK services registration
import os
import urllib.parse
from typing import Any

from google.adk.cli.service_registry import get_service_registry
from google.adk.memory import VertexAiMemoryBankService


def agentengine_memory_factory(uri: str, **kwargs: Any) -> VertexAiMemoryBankService:
    """Factory for agentengine:// memory URIs with us-east1 support for short-form IDs."""
    parsed = urllib.parse.urlsplit(uri)
    uri_part = parsed.netloc + parsed.path
    if "/" not in uri_part:
        return VertexAiMemoryBankService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT", "qwiklabs-gcp-03-f6ec19d098cc"),
            location=os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_LOCATION", "us-east1"),
            agent_engine_id=uri_part,
        )
    parts = uri_part.split("/")
    return VertexAiMemoryBankService(
        project=parts[1],
        location=parts[3],
        agent_engine_id=parts[5],
    )


registry = get_service_registry()
registry.register_memory_service("agentengine", agentengine_memory_factory)
