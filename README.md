# Microsoft Agent Framework — Full-Featured Sample on Azure AI Foundry

A comprehensive Python sample demonstrating the GA [Microsoft Agent Framework](https://github.com/microsoft/agent-framework) with **custom tools**, **multi-agent workflow orchestration**, and **observability** — hosted on [Azure AI Foundry](https://learn.microsoft.com/azure/ai-foundry/) using the **Responses protocol**.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Agent Modes](#agent-modes)
  - [Basic Agent (with Tools)](#basic-agent-with-tools)
  - [Workflow Agent (Multi-Agent Pipeline)](#workflow-agent-multi-agent-pipeline)
- [Tool Reference](#tool-reference)
- [Debugging with VS Code](#debugging-with-vs-code)
- [Deploying to Azure AI Foundry](#deploying-to-azure-ai-foundry)
  - [Step 1 — Build and Push Container to ACR](#step-1--build-and-push-container-to-acr)
  - [Step 2 — Create the Hosted Agent](#step-2--create-the-hosted-agent)
  - [Step 3 — Create a Session and Invoke](#step-3--create-a-session-and-invoke)
- [Observability](#observability)
- [Environment Variables Reference](#environment-variables-reference)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Resources](#resources)

---

## Overview

This sample shows how to build, test, and deploy AI agents using the Microsoft Agent Framework GA packages:

| Package | Purpose |
|---------|---------|
| [`agent-framework`](https://pypi.org/project/agent-framework/) | Core SDK — Agent, tools, workflows, FoundryChatClient |
| [`fastapi`](https://pypi.org/project/fastapi/) | HTTP router for the custom `/responses` endpoint |
| [`uvicorn`](https://pypi.org/project/uvicorn/) | Local ASGI server for the custom endpoint |

The sample includes **three agent modes** selected per request using the `agentid` field in the body:

- **`basic`** — A single agent with four custom tool functions (weather, knowledge base search, time, cost calculator).
- **`workflow`** — A three-agent pipeline (Researcher → Analyst → Report Formatter) demonstrating `WorkflowBuilder` orchestration.
- **`orchestrator`** — A multi-agent router that classifies intent and dispatches to specialized agents.

The app now exposes a custom `/responses` endpoint on port **8088** that accepts this request shape:

```json
{
  "message": "How many time can I have my tooth cleaning in my dental plan?",
  "agentid": "orchestrator",
  "parameters": {
    "user_id": "JDOE",
    "username": "John Doe"
  }
}
```

Any `{placeholder}` token in prompt text is merged from `parameters` on a per-request basis. Missing placeholders remain unchanged.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Client (curl / SDK)                       │
│            POST http://localhost:8088/responses                   │
│            {message, agentid, parameters}                         │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     FastAPI request router                        │
│   • Custom /responses body parser                                 │
│   • agentid-based runtime dispatch                                │
│   • Per-request prompt placeholder merge                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │   request.agentid       │
              ├─────────┐    ┌──────────┤
              ▼         │    │          ▼
     ┌─────────────┐    │    │   ┌──────────────────────────┐
     │ Basic Agent  │    │    │   │   Workflow Pipeline       │
     │  + 4 tools   │    │    │   │  ┌──────────┐            │
     └──────┬───────┘    │    │   │  │Researcher│──(tools)   │
            │            │    │   │  └────┬─────┘            │
            │            │    │   │       ▼                  │
            │            │    │   │  ┌──────────┐            │
            │            │    │   │  │ Analyst  │            │
            │            │    │   │  └────┬─────┘            │
            │            │    │   │       ▼                  │
            │            │    │   │  ┌──────────┐            │
            │            │    │   │  │Formatter │ ← output   │
            │            │    │   │  └──────────┘            │
            │            │    │   └──────────────────────────┘
            ▼            │    │              ▼
┌──────────────────────────────────────────────────────────────────┐
│                    FoundryChatClient                              │
│          (agent-framework → Azure OpenAI)                        │
│   • Responses API calls to deployed model                        │
│   • Credential: DefaultAzureCredential (local)                   │
│                  ManagedIdentityCredential (production)           │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│              Azure AI Foundry Model Deployment                   │
│                  (e.g., gpt-4.1-mini)                            │
└──────────────────────────────────────────────────────────────────┘
```

For a deeper technical walkthrough, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Python** | 3.12+ |
| **Azure subscription** | [Create one free](https://azure.microsoft.com/free/) |
| **Azure AI Foundry project** | [Create a project](https://learn.microsoft.com/azure/ai-foundry/how-to/create-projects) |
| **Model deployment** | Deploy a model (e.g., `gpt-4.1-mini`) in your Foundry project |
| **Azure CLI** | [Install](https://learn.microsoft.com/cli/azure/install-azure-cli) — needed for deployment and auth |
| **Docker** *(optional)* | For local container builds; ACR cloud builds work without Docker |
| **AI Toolkit for VS Code** *(optional)* | For Agent Inspector debugging UI |

Ensure you are logged in:

```bash
az login
```

---

## Quick Start (Local Development)

### 1. Create a virtual environment

```bash
cd agent-framework
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
# Windows PowerShell
Copy-Item .env.example .env

# macOS / Linux
cp .env.example .env
```

Edit `.env` and set your values:

```env
FOUNDRY_PROJECT_ENDPOINT="https://<your-account>.services.ai.azure.com/api/projects/<your-project>"
AZURE_AI_MODEL_DEPLOYMENT_NAME="gpt-4.1-mini"
AGENT_MODE="basic"
ENABLE_INSTRUMENTATION=true
ENABLE_SENSITIVE_DATA=true
```

`AGENT_MODE` is no longer used by the runtime router, but it is safe to leave in your `.env` file for local compatibility.

### 4. Run the agent

```bash
python main.py
```

You should see:

```
2026-05-19 10:00:00  INFO      __main__  Starting custom responses server on port 8088
```

### 5. Test the agent

**In a separate terminal:**

```bash
# Simple greeting
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello! What can you help me with?", "agentid": "basic", "parameters": {"user_id": "JDOE", "username": "John Doe"}}'
```

**PowerShell:**

```powershell
(Invoke-WebRequest -Uri http://localhost:8088/responses -Method POST `
  -ContentType "application/json" `
  -Body '{"message": "Hello! What can you help me with?", "agentid": "basic", "parameters": {"user_id": "JDOE", "username": "John Doe"}}').Content
```

**Non-streaming mode:**

```bash
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the weather in Tokyo?", "agentid": "basic", "parameters": {"user_id": "JDOE", "username": "John Doe"}}'
```

---

## Agent Modes

Switch between modes by setting the `agentid` field in the request body.

### Basic Agent (with Tools)

A single agent with four custom tools. It can answer questions, look up weather, search a knowledge base, tell the current time, and calculate costs.

**Example prompts:**

| Prompt | Tool Invoked |
|--------|-------------|
| "What's the weather in London?" | `get_weather` |
| "Search for information about Azure AI Foundry" | `search_knowledge_base` |
| "What time is it in Tokyo?" | `get_current_time` |
| "Calculate the cost of 3 laptops at $999 each and 2 mice at $29" | `calculate_cost` |
| "Tell me a joke" | *(no tool — direct LLM response)* |

### Workflow Agent (Multi-Agent Pipeline)

A three-agent pipeline that processes user queries through specialized stages:

| Stage | Agent | Role |
|-------|-------|------|
| 1 | **Researcher** | Gathers information using tools (`search_knowledge_base`, `get_weather`, `get_current_time`) |
| 2 | **Analyst** | Evaluates the research and draws conclusions |
| 3 | **Report Formatter** | Produces a polished report with Executive Summary, Key Findings, Recommendations, and Conclusion |

**Example prompts:**

```bash
curl -X POST http://localhost:8088/responses \
  -H "Content-Type: application/json" \
  -d '{"message": "Research Azure AI Foundry and give me a report on its capabilities", "agentid": "workflow", "parameters": {"user_id": "JDOE", "username": "John Doe"}}'
```

The workflow passes data through the pipeline using `context_mode="last_agent"`, so each agent only sees the output from the previous stage. Only the Formatter's output is returned to the caller.

### Orchestrator Agent (Intent Router)

```json
{
  "message": "How many times can I have my tooth cleaning in my dental plan?",
  "agentid": "orchestrator",
  "parameters": {
    "user_id": "JDOE",
    "username": "John Doe"
  }
}
```

The orchestrator classifies the request, optionally enriches it with profile information, and routes to the appropriate specialist agent.

---

## Tool Reference

All tools are defined in `agents/tools.py` using the `@tool` decorator.

| Tool | Parameters | Description |
|------|-----------|-------------|
| `get_weather` | `location: str` | Returns mock weather conditions (temperature, humidity, wind speed) for a given city |
| `search_knowledge_base` | `query: str` | Returns mock search results from an internal knowledge base (3 sample documents about Azure AI Foundry) |
| `get_current_time` | `timezone: str` | Returns the current date and time in a given timezone (e.g., "UTC", "US/Eastern", "Asia/Tokyo") |
| `calculate_cost` | `items: str` | Calculates totals for a JSON array of items with `name`, `quantity`, and `unit_price` fields |

### Tool Pattern

```python
from agent_framework import tool
from pydantic import Field
from typing import Annotated

@tool(approval_mode="never_require")
def my_tool(
    param: Annotated[str, Field(description="What this parameter is for.")],
) -> str:
    """Docstring becomes the tool description shown to the LLM."""
    return f"Result for {param}"
```

Key points:
- `@tool(approval_mode="never_require")` — the LLM can call the tool without user confirmation
- `Annotated[type, Field(description=...)]` — provides the LLM with parameter descriptions
- The function docstring is used as the tool's description in the schema

---

## Debugging with VS Code

This project includes pre-configured VS Code debug configurations that integrate with the **AI Toolkit Agent Inspector**.

### Prerequisites

```bash
pip install debugpy agent-dev-cli --pre
```

### Launch Configurations

| Configuration | What it does |
|--------------|-------------|
| **Debug Local Agent/Workflow HTTP Server** | Starts the agent with `agentdev` + `debugpy`, opens Agent Inspector UI, attaches the VS Code debugger |
| **Debug Local Agent/Workflow in Terminal** | Starts the agent in CLI mode with `debugpy`, attaches the VS Code debugger |

### How to Debug

1. Set breakpoints in your Python code (e.g., in `agents/tools.py` or `agents/basic_agent.py`)
2. Press **F5** or select **Run → Start Debugging**
3. Choose **"Debug Local Agent/Workflow HTTP Server"**
4. The Agent Inspector UI opens automatically — send messages to your agent and hit breakpoints

The debug setup uses:
- **Port 5679** for `debugpy` (VS Code debugger attachment)
- **Port 8088** for the agent HTTP server
- The **AI Toolkit** extension's `aitk` task type to validate port availability before starting

---

## Deploying to Azure AI Foundry

### Step 1 — Build and Push Container to ACR

**Option A: Cloud Build (recommended — no local Docker required)**

```bash
# Set variables
ACR_NAME="<your-acr-name>"
IMAGE_TAG="agent-framework-full-sample:$(date +%Y%m%d%H%M)"

# Build in the cloud
az acr build \
  --registry $ACR_NAME \
  --image $IMAGE_TAG \
  --platform linux/amd64 \
  --source-acr-auth-id "[caller]" \
  --file Dockerfile .
```

> The `--source-acr-auth-id "[caller]"` flag is **required** for ACR Tasks authentication.

**Option B: Local Docker Build**

```bash
ACR_NAME="<your-acr-name>"
IMAGE_TAG="agent-framework-full-sample:$(date +%Y%m%d%H%M)"

docker build --platform linux/amd64 -t $IMAGE_TAG -f Dockerfile .
az acr login --name $ACR_NAME
docker tag $IMAGE_TAG $ACR_NAME.azurecr.io/$IMAGE_TAG
docker push $ACR_NAME.azurecr.io/$IMAGE_TAG
```

**PowerShell (local build):**

```powershell
$ACR_NAME = "<your-acr-name>"
$IMAGE_TAG = "agent-framework-full-sample:$(Get-Date -Format 'yyyyMMddHHmm')"

docker build --platform linux/amd64 -t $IMAGE_TAG -f Dockerfile .
az acr login --name $ACR_NAME
docker tag $IMAGE_TAG "$ACR_NAME.azurecr.io/$IMAGE_TAG"
docker push "$ACR_NAME.azurecr.io/$IMAGE_TAG"
```

### Step 2 — Create the Hosted Agent

Use the Azure AI Foundry portal or the Foundry MCP tools to create the agent:

```json
{
  "kind": "hosted",
  "image": "<acr-name>.azurecr.io/agent-framework-full-sample:<tag>",
  "cpu": "0.25",
  "memory": "0.5Gi",
  "container_protocol_versions": [
    { "protocol": "responses", "version": "1.0.0" }
  ],
  "environment_variables": {
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "<your-model-deployment>",
    "AGENT_MODE": "basic",
    "ENABLE_INSTRUMENTATION": "true",
    "ENABLE_SENSITIVE_DATA": "true"
  }
}
```

`AGENT_MODE` in this snippet is legacy compatibility only. Runtime routing now uses the request body's `agentid` field.

**Important:** Ensure the Foundry project's managed identity has `Container Registry Repository Reader` on your ACR, and the agent's per-agent identity has `Azure AI User` on the Cognitive Services account.

### Step 3 — Create a Session and Invoke

Hosted agents require a session before invocation:

```bash
# 1. Create a session
curl -X POST "https://<project-endpoint>/agents/<agent-name>/sessions" \
  -H "Authorization: Bearer $(az account get-access-token --query accessToken -o tsv)" \
  -H "Content-Type: application/json"

# 2. Invoke the agent
curl -X POST "https://<project-endpoint>/agents/<agent-name>/endpoint/protocols/openai/responses" \
  -H "Authorization: Bearer $(az account get-access-token --query accessToken -o tsv)" \
  -H "Content-Type: application/json" \
  -d '{
    "input": "What is the weather in Seattle?",
    "session_id": "<session-id-from-step-1>"
  }'
```

**Multi-turn conversations:** Pass the `previous_response_id` from the previous response to maintain conversation context:

```json
{
  "input": "And what about tomorrow?",
  "previous_response_id": "<id-from-previous-response>"
}
```

---

## Observability

The Agent Framework has built-in OpenTelemetry instrumentation. Enable it via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENABLE_INSTRUMENTATION` | `false` | Enable OpenTelemetry tracing for all agent operations |
| `ENABLE_SENSITIVE_DATA` | `false` | Include prompt/completion text in trace data (caution: may contain PII) |

### What Gets Traced

When instrumentation is enabled:
- **Agent lifecycle** — agent creation, message handling, response generation
- **Tool calls** — tool name, parameters, execution time, results
- **LLM calls** — model name, token usage, latency
- **Workflow steps** — pipeline stage transitions, inter-agent data flow

### Viewing Traces

**Locally:** Traces are emitted to the console logger by default.

**In Foundry (production):** When deployed as a hosted agent, set `APPLICATIONINSIGHTS_CONNECTION_STRING` to export traces to Application Insights. View them in:
- **Azure Portal** → Application Insights → Transaction Search
- **Azure Portal** → Application Insights → Application Map (see agent → model call flow)

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FOUNDRY_PROJECT_ENDPOINT` | **Yes** | — | Azure AI Foundry project endpoint URL |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | **Yes** | — | Name of the deployed model (e.g., `gpt-4.1-mini`) |
| `AGENT_MODE` | No | `basic` | Legacy startup hint retained for compatibility; runtime routing now uses `agentid` in the request body |
| `ENABLE_INSTRUMENTATION` | No | `true` | Enable OpenTelemetry tracing |
| `ENABLE_SENSITIVE_DATA` | No | `true` | Include prompt/completion data in traces |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | No | — | Application Insights connection string (auto-injected in Foundry) |

---

## Project Structure

```
agent-framework/
├── main.py                     # Entrypoint — custom /responses router with agentid dispatch
├── agents/
│   ├── __init__.py
│   ├── basic_agent.py          # Single agent with 4 custom tools
│   ├── workflow_agent.py       # 3-agent pipeline (Researcher → Analyst → Formatter)
│   ├── multi_agent_orchestrator.py # Intent-router multi-agent orchestrator
│   ├── prompt_templates.py     # Per-request prompt placeholder rendering
│   └── tools.py                # Shared tool definitions (@tool decorated functions)
├── .env.example                # Environment variable template
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container image for Foundry deployment
├── .dockerignore               # Files excluded from Docker build
├── docker-compose.yml          # Local development with Docker Compose
├── agent.yaml                  # Foundry agent definition (kind: hosted)
├── agent.manifest.yaml         # Foundry agent manifest with model resource
├── .vscode/
│   ├── launch.json             # VS Code debug configurations
│   └── tasks.json              # Debug tasks (agentdev + Agent Inspector)
├── .foundry/
│   └── agent-metadata.yaml     # Foundry deployment metadata
├── README.md                   # This file
└── ARCHITECTURE.md             # Technical deep-dive
```

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'agent_framework'` | SDK not installed | `pip install -r requirements.txt` in your virtual environment |
| `KeyError: 'FOUNDRY_PROJECT_ENDPOINT'` | Missing environment variable | Copy `.env.example` → `.env` and fill in your project endpoint |
| `DefaultAzureCredentialError` | Not authenticated | Run `az login` |
| `Connection refused on port 8088` | Server not running | Run `python main.py` first |
| `401 Unauthorized` (Foundry) | Missing RBAC | Ensure `Azure AI User` role on Cognitive Services account for agent identity |
| `Image pull failed` (Foundry) | Missing ACR permission | Assign `Container Registry Repository Reader` to Foundry managed identity |
| Agent name validation error | Invalid characters | Use alphanumeric + hyphens only, start/end with alphanumeric, max 63 chars |
| `docker build` fails on Windows | Platform mismatch | Use `--platform linux/amd64` or use ACR cloud build instead |
| Port 8088 already in use | Another process on port | Stop the other process or change the port in `agent.yaml` |

---

## Resources

- [Microsoft Agent Framework — GitHub](https://github.com/microsoft/agent-framework)
- [Agent Framework Quick Start](https://learn.microsoft.com/agent-framework/tutorials/quick-start)
- [Agent Framework User Guide](https://learn.microsoft.com/agent-framework/user-guide/overview)
- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-foundry/)
- [Hosted Agents Overview](https://learn.microsoft.com/azure/ai-foundry/agents/concepts/hosted-agents)
- [Deploy a Hosted Agent](https://learn.microsoft.com/azure/ai-foundry/agents/how-to/deploy-hosted-agent)
- [Foundry Samples — Python Hosted Agents](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents)
- [agent-framework on PyPI](https://pypi.org/project/agent-framework/)
- [AI Toolkit for VS Code](https://marketplace.visualstudio.com/items?itemName=ms-windows-ai-studio.windows-ai-studio)
