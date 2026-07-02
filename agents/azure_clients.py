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

	Environment variables required:
		FOUNDRY_PROJECT_ENDPOINT — Azure AI Foundry project endpoint.
		AZURE_AI_MODEL_DEPLOYMENT_NAME — Model deployment name.
	"""
	return FoundryChatClient(
		project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
		model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
		credential=get_credential(),
	)
