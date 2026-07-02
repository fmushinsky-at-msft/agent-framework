"""Single-source multi-agent orchestrator inspired by AI Foundry wf-agent.yaml.

This module is the primary and only implementation for intent-based routing:
1. Orchestrator classifies user intent (1-7)
2. Optional User Profile enrichment for intents 1/3/4/5
3. Routes to the corresponding specialist agent
4. Returns a consolidated response
"""

import logging
import re
import time
from typing import Annotated, Any, Mapping, Optional

from agent_framework import Agent, tool
from pydantic import Field

from agents.azure_clients import get_foundry_chat_client
from agents.prompt_templates import (
    NO_SOURCE_REFERENCES_RULE,
    build_template_context,
    render_prompt_template,
)
from agents.tools import (
    fetch_hr_profile,
    get_current_time,
    hr_info_given_userid,
    search_ai_policy_knowledge_base,
    search_commuter_knowledge_base,
    search_data_classification_knowledge_base,
    search_health_benefit_knowledge_base,
    search_hr_policy_knowledge_base,
    search_retirement_knowledge_base,
    search_staff_profile_knowledge_base,
)

logger = logging.getLogger(__name__)

ORCHESTRATOR_INSTRUCTIONS = (
    "You are an assistant that determines the intent of the user question\n"
    "Rules:\n"
    "- Do not answer user question. Only determines the intent based on the below instructions.\n"
    "- User question may be follow on to previous questions in a conversation. Use the conversation context and users latest question to determine the intent and determine the best category below.\n"
    "- Evaluate all categories criteria below before responding with the best match.\n"
    " \n"
    "When users ask about HR Related content such as details about different health plans, dental plans, prescription plans.  You have access to PDF documents that contain all plan details for users to ask for comparisons or general plan details:\n"
    "- Respond with '1'. Number Only.\n"
    "When users ask about Commuter Benefit related content, such maximum contribution, Commuter Benefits Program, how to enrollment and requirement.\n"
    "- Respond with '2'. Number Only.\n"
    "For questions related Retirement Benefit such as Vision Benefits, Pension, separation payout, Medicare benefit, contribution level post retirement. Health Care Post Retirement, premium post retirement, dental post retirement, Vision post retirement. \n"
    "- Respond with '3'. Number Only.\n"
    " \n"
    "For questions related to HR policy, such as leave, ADA, remote work and employment policies. \n"
    "- Respond with '4'. Number Only.\n"
    "When users ask about HR benefits information (pay, vacation balance, health/dental/vision plans), and when users ask about HR profile information (employee id, supervisor/manager name, contact information, address, title, hire date, level/grade, job title):\n"
    "- Respond with '5'. Number Only.\n"
    "For questions related to Artificial Intelligence (AI) standard or policy, such as governance, AI Bias, employee rules for using AI systems, and violations of AI policy.\n"
    "- Respond with '6'. Number Only.\n"
    " \n"
    "For questions related to Data Classification standard or policy, such as standard four categories or sensitive label (Public, Internal, Confidential, Restricted), Data encryption, handling of electronic information/ data. Retrieve data from pa-data-classification.\n"
    "- Respond with '7'. Number Only.\n"
    " \n"
    "When the intent of user's question does not fall into above categories:\n"
    "- Respond with '0'. Number Only."
)

USER_PROFILE_INSTRUCTIONS = (
    "You are a User Profile and Benefits assistant. \n"
    "Always run the User_Profile tool for every user questions\n"
    "- Call the User_Profile tool with user_name: {user_id}\n"
    "-ALWAYS RETURN FULL PROFILE INFORMATION\n"
    "-DO NOT ANSWER THE QUESTION"
)

HEALTH_BENEFIT_INSTRUCTIONS = (
    "You are Health Benefits Assistant.\n"
    "For HR Related content, such as details about different health plans, dental plans, and prescription plans. You have access to PDF documents that contain all plan details for users to ask for comparisons or general plan details. User profile information:{User profile context} \n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

COMMUTER_INSTRUCTIONS = (
    "You are a Commuter assistant.\n"
    "For questions related Commuter Plan Benefit. \n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

RETIREMENT_INSTRUCTIONS = (
    "For questions related Retirement Benefit such as Pension. Health Care Post Retirement, premium post retirement, dental post retirement. \n"
    "User profile information:{Local.user_profile}\n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

HR_POLICY_INSTRUCTIONS = (
    "For questions related to HR policy, such as leave, ADA, remote work and employment policies. User profile information:{Local.user_profile}\n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

STAFF_PROFILE_INSTRUCTIONS = (
    "When users ask about HR benefits information (pay, vacation balance, health/dental/vision plans), and when users ask about HR profile information (employee id, supervisor/manager name, contact information, address, title, hire date, level/grade, job title)\n"
    "Use the user Profile Information:{Local.user_profile}\n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

AI_POLICY_INSTRUCTIONS = (
    "For questions related to Artificial Intelligence (AI) standard or policy, such as governance, AI Bias, employee rules for using AI systems, and violations of AI policy. \n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

DATA_CLASSIFICATION_INSTRUCTIONS = (
    "For questions related to Data Classification standard or policy, such as standard four categories or sensitive label (Public, Internal, Confidential, Restricted), Data encryption, handling of electronic information/ data.\n"
    "# Rules when answering questions\n"
    "- Be brief in your answers.\n"
    "- DO NOT USE your own general knowledge to generate answers.\n"
    "- If asking a clarifying question to the user would help, ask the question.\n"
    "- Use the user's name \"{user_full_name}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)


class MultiAgentOrchestrator:
    """Intent-based orchestrator that performs conditional routing end-to-end."""

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        self.parameters = build_template_context(parameters)
        self.client = get_foundry_chat_client()

        self.orchestrator = Agent(
            client=self.client,
            instructions=render_prompt_template(ORCHESTRATOR_INSTRUCTIONS, self.parameters),
            name="orchestrator",
            default_options={"store": False},
        )

        self.specialists = {
            "1": Agent(
                client=self.client,
                instructions=render_prompt_template(HEALTH_BENEFIT_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="health_benefit",
                tools=[search_health_benefit_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "2": Agent(
                client=self.client,
                instructions=render_prompt_template(COMMUTER_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="commuter",
                tools=[search_commuter_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "3": Agent(
                client=self.client,
                instructions=render_prompt_template(RETIREMENT_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="retirement",
                tools=[search_retirement_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "4": Agent(
                client=self.client,
                instructions=render_prompt_template(HR_POLICY_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="hr_policy",
                tools=[search_hr_policy_knowledge_base, get_current_time, hr_info_given_userid],
                default_options={"store": False},
            ),
            "5": Agent(
                client=self.client,
                instructions=render_prompt_template(STAFF_PROFILE_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="staff_profile",
                tools=[search_staff_profile_knowledge_base, get_current_time, hr_info_given_userid],
                default_options={"store": False},
            ),
            "6": Agent(
                client=self.client,
                instructions=render_prompt_template(AI_POLICY_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="ai_policy",
                tools=[search_ai_policy_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "7": Agent(
                client=self.client,
                instructions=render_prompt_template(DATA_CLASSIFICATION_INSTRUCTIONS, self.parameters) + NO_SOURCE_REFERENCES_RULE,
                name="data_classification",
                tools=[search_data_classification_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
        }

    async def route(self, user_message: str) -> str:
        """Run full orchestration: classify, branch, and answer.

        Per-hop wall-clock timings are logged at INFO so you can see exactly how
        many seconds each stage burns and compare the total against the upstream
        (~15s bot / Copilot Studio) timeout.
        """
        turn_start = time.perf_counter()

        classify_start = time.perf_counter()
        intent_response = await self.orchestrator.run(user_message)
        classify_elapsed = time.perf_counter() - classify_start

        intent = self._extract_intent(str(intent_response))
        specialist_input = user_message

        if not intent:
            logger.info(
                "route timing | intent=none | classify=%.2fs | total=%.2fs",
                classify_elapsed,
                time.perf_counter() - turn_start,
            )
            return "I am not able to answer your question. Please rephrase your question."

        profile_elapsed = 0.0
        if intent in {"1", "3", "4", "5"}:
            # Fetch the user profile with a direct, deterministic HTTP call instead
            # of spending a full extra LLM round-trip on an agent whose only job was
            # to invoke this tool. Removing that hop cuts the orchestrator's tail
            # latency, which is what intermittently exceeds the upstream (Copilot
            # Studio / Power Automate / APIM) timeout and surfaces as
            # FlowActionBadGateway.
            user_id = str(self.parameters.get("user_id", "")).strip()
            if user_id:
                profile_start = time.perf_counter()
                profile_response = await fetch_hr_profile(user_id)
                profile_elapsed = time.perf_counter() - profile_start
                specialist_input = (
                    "User request:\n"
                    f"{user_message}\n\n"
                    "User profile context:\n"
                    f"{profile_response}"
                )

        specialist = self.specialists.get(intent)
        if specialist is None:
            logger.info(
                "route timing | intent=%s | classify=%.2fs | profile=%.2fs | total=%.2fs",
                intent,
                classify_elapsed,
                profile_elapsed,
                time.perf_counter() - turn_start,
            )
            return "I am not able to answer your question. Please rephrase your question."

        specialist_start = time.perf_counter()
        response = await specialist.run(specialist_input)
        specialist_elapsed = time.perf_counter() - specialist_start

        total_elapsed = time.perf_counter() - turn_start
        logger.info(
            "route timing | intent=%s (%s) | classify=%.2fs | profile=%.2fs | specialist=%.2fs | total=%.2fs",
            intent,
            getattr(specialist, "name", "?"),
            classify_elapsed,
            profile_elapsed,
            specialist_elapsed,
            total_elapsed,
        )
        return str(response)

    @staticmethod
    def _extract_intent(response: str) -> Optional[str]:
        match = re.search(r"\b[1-7]\b", response)
        return match.group(0) if match else None


def create_multi_agent_orchestrator_agent(parameters: Mapping[str, Any] | None = None) -> Agent:
    """Create the primary public agent that delegates to the orchestrator class."""
    orchestrator = MultiAgentOrchestrator(parameters)

    @tool(approval_mode="never_require")
    async def route_employee_request(
        user_message: Annotated[
            str,
            Field(description="The full user message to route to the correct specialist."),
        ],
    ) -> str:
        return await orchestrator.route(user_message)

    return Agent(
        client=orchestrator.client,
        name="employee_orchestrator",
        instructions=render_prompt_template(
            (
                "You are an employee assistant router. Always call route_employee_request. "
                "If the user's message is a follow-up (for example: 'what about that one?', "
                "'and for dependents?'), rewrite it into a self-contained request using the "
                "relevant conversation context before calling the tool. "
                "Do not answer directly. Return the tool result as the final answer."
            ),
            parameters,
        ),
        tools=[route_employee_request],
        default_options={"store": False},
    )


# Backward-compatible alias used by earlier imports.
create_multi_agent_orchestrator = create_multi_agent_orchestrator_agent
