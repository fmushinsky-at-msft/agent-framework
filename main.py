# Copyright (c) Microsoft. All rights reserved.

"""Microsoft Agent Framework — Full-Featured Sample.

Entrypoint exposing a custom /responses HTTP API on port 8088.

Expected request body:
{
    "message": "How many time can I have my tooth cleaning in my dental plan?",
    "agentid": "orchestrator",
    "parameters": {
        "user_id": "JDOE",
        "username": "John Doe"
    }
}

Environment variables:
    FOUNDRY_PROJECT_ENDPOINT        — Azure AI Foundry project endpoint (required).
    AZURE_AI_MODEL_DEPLOYMENT_NAME  — Model deployment name (required).
    ENABLE_INSTRUMENTATION          — "true" to enable OpenTelemetry tracing.
    ENABLE_SENSITIVE_DATA           — "true" to include prompt/completion data in traces.
"""

import logging
import re
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from agents.azure_clients import (
    build_model_options,
    disable_reasoning_options,
    reasoning_options_active,
)
from agents.basic_agent import create_basic_agent
from agents.multi_agent_orchestrator import create_multi_agent_orchestrator_agent
from agents.workflow_agent import create_workflow_agent

# Load .env but do NOT override variables already set by the Foundry runtime.
load_dotenv(override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


class CustomResponseRequest(BaseModel):
    message: str = Field(description="The user prompt message")
    agentid: str = Field(description="Target agent mode: basic, workflow, or orchestrator")
    parameters: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str | None = Field(
        default=None,
        description=(
            "Optional conversation identifier. Send empty/null for a new conversation; "
            "send the returned conversation_id for follow-up turns."
        ),
    )


# Strip cryptic source-citation markers (e.g. "[371:1†source]", "【3:0†source】")
# that models sometimes append when answering from retrieved documents, so they
# never surface in the end-user (Teams) response.
_CITATION_MARKER_PATTERN = re.compile(
    r"[\[【][^\]】]*?(?:†|\+)\s*source[^\]】]*?[\]】]",
    re.IGNORECASE,
)


def _strip_citation_markers(text: str) -> str:
    """Remove cryptic bracketed source-citation markers from model output."""
    cleaned = _CITATION_MARKER_PATTERN.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned).strip()


def _extract_text_response(response: Any) -> str:
    """Extract readable text from AgentResponse-like objects."""
    messages = getattr(response, "messages", None)
    if messages:
        chunks: list[str] = []
        for message in messages:
            for content in getattr(message, "contents", []):
                content_type = getattr(content, "type", "")
                if content_type in {
                    "function_call",
                    "function_result",
                    "mcp_server_tool_call",
                    "mcp_server_tool_result",
                }:
                    # Suppress tool plumbing artifacts from end-user output.
                    continue
                if getattr(content, "text", None):
                    chunks.append(str(content.text))
                elif getattr(content, "data", None):
                    chunks.append(str(content.data))
        if chunks:
            return _strip_citation_markers("\n".join(chunks))
    return ""


def _create_agent_for_mode(agent_id: str, parameters: dict[str, Any]):
    mode = agent_id.lower()
    if mode == "orchestrator":
        return create_multi_agent_orchestrator_agent(parameters)
    if mode == "workflow":
        return create_workflow_agent(parameters)
    if mode == "basic":
        return create_basic_agent(parameters)
    raise HTTPException(
        status_code=400,
        detail="Invalid agentid. Allowed values: basic, workflow, orchestrator.",
    )


async def _run_agent(request: CustomResponseRequest) -> tuple[Any, Any]:
    """Create the agent, open the session, and run it. Returns (response, session)."""
    agent = _create_agent_for_mode(request.agentid, request.parameters)
    incoming_conversation_id = (request.conversation_id or "").strip() or None
    session = (
        agent.get_session(incoming_conversation_id)
        if incoming_conversation_id
        else agent.create_session()
    )
    # Force service-side storage so Foundry manages multi-turn conversation natively.
    response = await agent.run(
        request.message,
        stream=False,
        session=session,
        options=build_model_options(store=True),
    )
    return response, session


def _is_unsupported_reasoning_error(err: str) -> bool:
    """Heuristic: does this error look like the model/framework rejecting the
    optional reasoning/verbosity parameters?"""
    e = err.lower()
    mentions_param = "reasoning" in e or "verbosity" in e
    looks_unsupported = any(
        kw in e
        for kw in ("unsupported", "unrecognized", "unknown", "not support", "invalid", "extra_forbidden", "400")
    )
    return mentions_param and looks_unsupported


def _error_response(exc: Exception, req_start: float, agentid: str) -> JSONResponse:
    """Map an agent failure to a graceful JSON error response."""
    err_str = str(exc)
    logger.error(
        "Agent run FAILED after %.2fs (agentid=%s): %s",
        time.perf_counter() - req_start,
        agentid,
        err_str,
    )
    # Surface connectivity / auth errors as 503; other failures as 500.
    if any(kw in err_str for kw in ("Connection error", "ConnectError", "timed out", "timeout")):
        return JSONResponse(
            status_code=503,
            content={"error": "Upstream service unavailable. Please retry.", "detail": err_str[:400]},
        )
    if "DefaultAzureCredential" in err_str or "authentication" in err_str.lower():
        return JSONResponse(
            status_code=503,
            content={"error": "Authentication failed. Ensure you are logged in with `az login` or `azd auth login`.", "detail": err_str[:400]},
        )
    return JSONResponse(
        status_code=500,
        content={"error": "Agent request failed.", "detail": err_str[:400]},
    )


app = FastAPI(title="Agent Framework Custom Responses API", version="1.0.0")


@app.post("/responses")
async def create_response(request: CustomResponseRequest) -> dict[str, Any]:
    req_start = time.perf_counter()
    agentid = request.agentid.lower()

    try:
        response, session = await _run_agent(request)
    except HTTPException:
        # Preserve explicit HTTP errors (e.g. invalid agentid -> 400).
        raise
    except Exception as exc:
        # Self-heal: if the optional reasoning/verbosity params were rejected, drop
        # them (process-wide) and retry once so a shape/param mismatch can never take
        # the endpoint down.
        if reasoning_options_active() and _is_unsupported_reasoning_error(str(exc)):
            logger.warning(
                "Reasoning/verbosity options rejected; disabling them and retrying once. Detail: %s",
                str(exc)[:300],
            )
            disable_reasoning_options()
            try:
                response, session = await _run_agent(request)
            except HTTPException:
                raise
            except Exception as exc2:
                return _error_response(exc2, req_start, agentid)
        else:
            return _error_response(exc, req_start, agentid)

    returned_conversation_id = session.service_session_id or session.session_id
    logger.info(
        "request timing | agentid=%s | end_to_end_total=%.2fs",
        agentid,
        time.perf_counter() - req_start,
    )
    return {
        "agentid": agentid,
        "output": _extract_text_response(response),
        "conversation_id": returned_conversation_id,
        "service_conversation_id": session.service_session_id,
        "is_service_managed_conversation": bool(session.service_session_id),
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """Lightweight liveness probe.

    Returns 200 immediately without touching Azure so App Service / APIM health
    probes never mark a healthy instance as down. A false-negative health probe
    replaces or fails over instances and is itself a common source of
    intermittent 502 errors.
    """
    return {"status": "ok"}


def main():
    logger.info("Starting custom responses server on port 8088")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8088,
        # Keep idle backend connections open LONGER than the Azure App Service /
        # APIM front-end idle timeout (~230s). uvicorn's default keep-alive is only
        # 5s, so between bursts of Teams traffic it closes pooled connections that
        # the reverse proxy still believes are open; the proxy then sends the next
        # request on a dead socket and the caller sees an intermittent 502
        # (FlowActionBadGateway). Making the server the slower side to recycle idle
        # connections removes that race.
        timeout_keep_alive=620,
        # Honor X-Forwarded-* headers set by APIM / the App Service front end.
        proxy_headers=True,
        forwarded_allow_ips="*",
    )

if __name__ == "__main__":
    main()
