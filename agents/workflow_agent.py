# Copyright (c) Microsoft. All rights reserved.

"""Multi-agent workflow pipeline.

Creates a 3-agent pipeline using WorkflowBuilder:
  Researcher  →  Analyst  →  Report Formatter

Each agent is wrapped in an AgentExecutor with context_mode="last_agent"
so it only sees the output of the previous agent. The workflow is exposed
as a single composite agent via .as_agent().
"""

from typing import Any, Mapping

from agent_framework import Agent, AgentExecutor, WorkflowBuilder

from agents.azure_clients import build_model_options, get_foundry_chat_client
from agents.prompt_templates import NO_SOURCE_REFERENCES_RULE, render_prompt_template
from agents.tools import get_weather, search_knowledge_base, get_current_time

RESEARCHER_INSTRUCTIONS = (
    "You are a research specialist. Your job is to gather comprehensive information "
    "about the topic the user asks about. Use the available tools to collect data:\n"
    "- Search the knowledge base for relevant documentation and guides.\n"
    "- Look up weather data if the topic is location-related.\n"
    "- Check the current time if temporal context is needed.\n\n"
    "Compile all findings into a structured research brief with clear sections."
)

ANALYST_INSTRUCTIONS = (
    "You are a senior analyst. You receive a research brief from the research team. "
    "Your job is to:\n"
    "1. Evaluate the quality and relevance of the gathered information.\n"
    "2. Identify key insights, trends, and patterns.\n"
    "3. Draw actionable conclusions.\n"
    "4. Flag any gaps or areas that need further investigation.\n\n"
    "Produce a concise analysis with numbered key findings and a recommendation section."
)

FORMATTER_INSTRUCTIONS = (
    "You are a professional report formatter. You receive an analysis document "
    "and your job is to format it into a polished, reader-friendly report.\n\n"
    "Follow this structure:\n"
    "## Executive Summary\n"
    "A 2-3 sentence overview of the key findings.\n\n"
    "## Key Findings\n"
    "Numbered list of the most important insights.\n\n"
    "## Recommendations\n"
    "Actionable next steps based on the analysis.\n\n"
    "## Conclusion\n"
    "A brief closing statement.\n\n"
    "Use clear headings, bullet points, and concise language. "
    "Do not add information that was not in the analysis."
)


def create_workflow_agent(parameters: Mapping[str, Any] | None = None) -> Agent:
    """Create and return a multi-agent workflow pipeline.

    The pipeline chains three agents:
      1. Researcher — gathers information using tools
      2. Analyst — evaluates findings and draws conclusions
      3. Formatter — produces a polished final report

    Environment variables required:
        FOUNDRY_PROJECT_ENDPOINT — Azure AI Foundry project endpoint.
        AZURE_AI_MODEL_DEPLOYMENT_NAME — Model deployment name.
    """
    client = get_foundry_chat_client()

    # --- Agent definitions ---
    researcher = Agent(
        client=client,
        instructions=render_prompt_template(RESEARCHER_INSTRUCTIONS, parameters) + NO_SOURCE_REFERENCES_RULE,
        name="researcher",
        tools=[get_weather, search_knowledge_base, get_current_time],
        default_options=build_model_options(),
    )

    analyst = Agent(
        client=client,
        instructions=render_prompt_template(ANALYST_INSTRUCTIONS, parameters) + NO_SOURCE_REFERENCES_RULE,
        name="analyst",
        default_options=build_model_options(),
    )

    formatter = Agent(
        client=client,
        instructions=render_prompt_template(FORMATTER_INSTRUCTIONS, parameters) + NO_SOURCE_REFERENCES_RULE,
        name="formatter",
        default_options=build_model_options(),
    )

    # --- Workflow wiring ---
    # Each executor uses context_mode="last_agent" so the agent only sees
    # the output from the immediately preceding agent, not the full history.
    researcher_executor = AgentExecutor(researcher, context_mode="last_agent")
    analyst_executor = AgentExecutor(analyst, context_mode="last_agent")
    formatter_executor = AgentExecutor(formatter, context_mode="last_agent")

    workflow_agent = (
        WorkflowBuilder(
            start_executor=researcher_executor,
            # Only emit the formatter's output to the caller.
            output_executors=[formatter_executor],
        )
        .add_edge(researcher_executor, analyst_executor)
        .add_edge(analyst_executor, formatter_executor)
        .build()
        .as_agent()
    )

    return workflow_agent
