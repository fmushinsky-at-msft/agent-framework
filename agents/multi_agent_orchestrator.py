"""Single-source multi-agent orchestrator inspired by AI Foundry wf-agent.yaml.

This module is the primary and only implementation for intent-based routing:
1. Orchestrator classifies user intent (1-7)
2. Optional User Profile enrichment for intents 1/3/4/5
3. Routes to the corresponding specialist agent
4. Returns a consolidated response
"""

import os
import re
from typing import Annotated, Any, Mapping, Optional

from agent_framework import Agent, tool
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential
from pydantic import Field

from agents.prompt_templates import build_template_context, render_prompt_template
from agents.tools import get_current_time, hr_info_given_userid, search_knowledge_base

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
    "- Use the user's name \"{username}\" to personalize the conversation. Use a friendly tone and refer to the user with the first name.\n"
    "- Do NOT ask follow on questions."
)

COMMUTER_INSTRUCTIONS = (
    "You are a commuter benefits specialist. Help employees understand commuter benefit programs, "
    "transportation allowances, parking options, transit subsidies, and enrollment procedures. "
    "Provide practical guidance on maximizing these benefits."
)

RETIREMENT_INSTRUCTIONS = (
    "You are a retirement planning advisor. Help employees with 401(k) plans, pension information, "
    "retirement savings strategies, investment options, and retirement planning questions. "
    "Provide educational information to help with retirement decisions."
)

HR_POLICY_INSTRUCTIONS = (
    "You are an HR policy expert. Answer questions about company policies including leave policies, "
    "attendance requirements, workplace conduct, remote work guidelines, and other HR procedures. "
    "Reference the employee handbook and company policies in your responses."
)

STAFF_PROFILE_INSTRUCTIONS = (
    "You are a staff directory assistant. Help employees find team members, locate contact information, "
    "understand organizational structure, and identify the right person to contact for specific issues. "
    "Use the knowledge base to provide accurate staff information."
)

AI_POLICY_INSTRUCTIONS = (
    "You are an AI policy expert. Provide guidance on responsible AI usage, company AI usage policies, "
    "compliance requirements, ethical AI use, and limitations on AI tools in the workplace. "
    "Help employees understand how to use AI responsibly."
)

DATA_CLASSIFICATION_INSTRUCTIONS = (
    "You are a data classification and privacy expert. Help employees understand data handling standards, "
    "data classification levels, privacy requirements, data security practices, and compliance with "
    "data protection regulations. Ensure proper data management practices."
)


class MultiAgentOrchestrator:
    """Intent-based orchestrator that performs conditional routing end-to-end."""

    def __init__(self, parameters: Mapping[str, Any] | None = None) -> None:
        self.parameters = build_template_context(parameters)
        self.client = FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
            credential=DefaultAzureCredential(),
        )

        self.orchestrator = Agent(
            client=self.client,
            instructions=render_prompt_template(ORCHESTRATOR_INSTRUCTIONS, self.parameters),
            name="orchestrator",
            default_options={"store": False},
        )

        self.user_profile_agent = Agent(
            client=self.client,
            instructions=render_prompt_template(USER_PROFILE_INSTRUCTIONS, self.parameters),
            name="user_profile",
            tools=[hr_info_given_userid],
            default_options={"store": False},
        )

        self.specialists = {
            "1": Agent(
                client=self.client,
                instructions=render_prompt_template(HEALTH_BENEFIT_INSTRUCTIONS, self.parameters),
                name="health_benefit",
                tools=[search_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "2": Agent(
                client=self.client,
                instructions=render_prompt_template(COMMUTER_INSTRUCTIONS, self.parameters),
                name="commuter",
                tools=[search_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "3": Agent(
                client=self.client,
                instructions=render_prompt_template(RETIREMENT_INSTRUCTIONS, self.parameters),
                name="retirement",
                tools=[search_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "4": Agent(
                client=self.client,
                instructions=render_prompt_template(HR_POLICY_INSTRUCTIONS, self.parameters),
                name="hr_policy",
                tools=[search_knowledge_base, get_current_time, hr_info_given_userid],
                default_options={"store": False},
            ),
            "5": Agent(
                client=self.client,
                instructions=render_prompt_template(STAFF_PROFILE_INSTRUCTIONS, self.parameters),
                name="staff_profile",
                tools=[search_knowledge_base, get_current_time, hr_info_given_userid],
                default_options={"store": False},
            ),
            "6": Agent(
                client=self.client,
                instructions=render_prompt_template(AI_POLICY_INSTRUCTIONS, self.parameters),
                name="ai_policy",
                tools=[search_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
            "7": Agent(
                client=self.client,
                instructions=render_prompt_template(DATA_CLASSIFICATION_INSTRUCTIONS, self.parameters),
                name="data_classification",
                tools=[search_knowledge_base, get_current_time],
                default_options={"store": False},
            ),
        }

    async def route(self, user_message: str) -> str:
        """Run full orchestration: classify, branch, and answer."""
        intent_response = await self.orchestrator.run(user_message)
        intent = self._extract_intent(str(intent_response))
        specialist_input = user_message

        if not intent:
            return "I am not able to answer your question. Please rephrase your question."

        if intent in {"1", "3", "4", "5"}:
            # Keep parity with Foundry workflow which fetches user profile first.
            profile_response = await self.user_profile_agent.run(user_message)
            specialist_input = (
                "User request:\n"
                f"{user_message}\n\n"
                "User profile context:\n"
                f"{profile_response}"
            )

        specialist = self.specialists.get(intent)
        if specialist is None:
            return "I am not able to answer your question. Please rephrase your question."

        response = await specialist.run(specialist_input)
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
