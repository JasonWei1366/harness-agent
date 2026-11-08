"""Model streaming framework.

``engine`` is the stable pipeline. A new vendor encodes one turn into a request
and parses that vendor's response lines. HTTP, retries, and assistant events
stay in the engine.
"""

from agent.types import CancellationToken
from model.catalog import RuntimeModel, RuntimeModelCatalog, RuntimeModelLimits
from model.client import (
    FakeProvider,
    ModelProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    bind_client,
    stream_response,
    use_client,
)
from model.engine import EncodedRequest, ModelTurn, StreamParser, VendorCodec, VendorProvider

__all__ = [
    "CancellationToken",
    "EncodedRequest",
    "FakeProvider",
    "ModelProvider",
    "ModelTurn",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "bind_client",
    "stream_response",
    "use_client",
    "RuntimeModel",
    "RuntimeModelCatalog",
    "RuntimeModelLimits",
    "StreamParser",
    "VendorCodec",
    "VendorProvider",
]
