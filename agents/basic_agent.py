# Copyright (c) Microsoft. All rights reserved.

"""Basic agent with custom tools.

Creates a single Agent instance backed by FoundryChatClient with four
local tools: weather lookup, knowledge base search, time retrieval,
and cost calculation. The agent is ready to be wrapped by ResponsesHostServer.
"""

from typing import Any, Mapping

from agent_framework import Agent

from agents.azure_clients import get_foundry_chat_client
from agents.prompt_templates import NO_SOURCE_REFERENCES_RULE, render_prompt_template
from agents.tools import calculate_cost, get_current_time, get_weather, search_knowledge_base

INSTRUCTIONS = (
    "You are a helpful AI assistant with access to several tools. "
    "Use them when the user's question requires real-time data, calculations, "
    "or knowledge base lookups. Keep your answers concise and informative.\n\n"
    "Available capabilities:\n"
    "- Weather: Look up current weather for any city.\n"
    "- Knowledge Base: Search internal documentation for relevant information.\n"
    "- Time: Get the current date and time in any timezone.\n"
    "- Cost Calculator: Calculate totals for a list of items with quantities and prices."
)


def create_basic_agent(parameters: Mapping[str, Any] | None = None) -> Agent:
    """Create and return a single agent with local tool functions.

    Environment variables required:
        FOUNDRY_PROJECT_ENDPOINT — Azure AI Foundry project endpoint.
        AZURE_AI_MODEL_DEPLOYMENT_NAME — Model deployment name (e.g., gpt-4.1-mini).
    """
    client = get_foundry_chat_client()

    agent = Agent(
        client=client,
        instructions=render_prompt_template(INSTRUCTIONS, parameters) + NO_SOURCE_REFERENCES_RULE,
        tools=[get_weather, search_knowledge_base, get_current_time, calculate_cost],
        # History is managed by the hosting infrastructure (ResponsesHostServer),
        # so disable server-side storage.
        # https://developers.openai.com/api/reference/resources/responses/methods/create
        default_options={"store": False},
    )

    return agent
