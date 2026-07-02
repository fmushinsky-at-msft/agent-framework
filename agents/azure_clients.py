# Copyright (c) Microsoft. All rights reserved.

"""Shared, cached Azure clients.

Creating a new ``DefaultAzureCredential`` and ``FoundryChatClient`` on every
request adds latency (a fresh token acquisition each time), and a new HTTP
client per request opens a new connection/socket pool that can exhaust
ephemeral ports under load. Both surface as intermittent ``502 Bad Gateway``
errors behind API Management / App Service.

Reusing a single credential (its token cache is shared) and a single chat
client (its connection pool is reused) removes that per-request cost and the
associated flakiness. The endpoint and model come from environment variables
and are constant for the process lifetime, so a single client is correct.
"""

import os
from functools import lru_cache
from typing import Any

from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential


@lru_cache(maxsize=1)
def get_credential() -> DefaultAzureCredential:
    """Return a process-wide, reusable ``DefaultAzureCredential``.

    The credential caches acquired tokens internally, so reusing one instance
    avoids re-running the credential provider chain on every request.
    """
    return DefaultAzureCredential()


@lru_cache(maxsize=1)
def get_foundry_chat_client() -> FoundryChatClient:
    """Return a process-wide, reusable ``FoundryChatClient``.

    Created lazily on first use (inside the running event loop) so the shared
    connection pool is reused across requests instead of being rebuilt each time.
    The same model is used for both intent classification and grounded answers.

    Environment variables required:
        FOUNDRY_PROJECT_ENDPOINT - Azure AI Foundry project endpoint.
        AZURE_AI_MODEL_DEPLOYMENT_NAME - Model deployment name.
    """
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        credential=get_credential(),
    )


# Process-wide flag: flipped to False by ``disable_reasoning_options`` if the model
# or framework rejects the optional reasoning/verbosity parameters, so we stop
# sending them and self-heal instead of failing every request.
_reasoning_options_enabled = True


def reasoning_options_configured() -> bool:
    """True if a reasoning/verbosity env var is set (the feature was requested)."""
    return bool(
        os.environ.get("AZURE_AI_REASONING_EFFORT")
        or os.environ.get("AZURE_AI_VERBOSITY")
    )


def reasoning_options_active() -> bool:
    """True if reasoning options are configured and have not been auto-disabled."""
    return _reasoning_options_enabled and reasoning_options_configured()


def disable_reasoning_options() -> None:
    """Stop sending reasoning/verbosity options for the rest of this process."""
    global _reasoning_options_enabled
    _reasoning_options_enabled = False


def build_model_options(store: bool = False) -> dict[str, Any]:
    """Build per-request model options, adding optional reasoning controls.

    Reasoning effort and verbosity are ONLY included when their env vars are set
    (and not auto-disabled), so the default behaviour is unchanged and non-reasoning
    models (which reject these parameters) are unaffected. They apply to
    reasoning-capable models (e.g. the GPT-5 family) and lower values reduce latency:
        AZURE_AI_REASONING_EFFORT  - "minimal" | "low" | "medium" | "high"
        AZURE_AI_VERBOSITY         - "low" | "medium" | "high"

    The nested ``reasoning``/``text`` shape matches the Responses API request body
    (the same channel as ``store``). If the model/framework rejects that shape,
    ``disable_reasoning_options`` is called (see main.py) and only ``store`` is
    returned on subsequent calls.
    """
    options: dict[str, Any] = {"store": store}
    if not _reasoning_options_enabled:
        return options

    effort = os.environ.get("AZURE_AI_REASONING_EFFORT")
    if effort:
        options["reasoning"] = {"effort": effort}

    verbosity = os.environ.get("AZURE_AI_VERBOSITY")
    if verbosity:
        options["text"] = {"verbosity": verbosity}

    return options
