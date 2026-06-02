# Architecture Deep-Dive

This document provides a technical walkthrough of the Microsoft Agent Framework sample's architecture, component interactions, and deployment pipeline.

---

## Table of Contents

- [Component Overview](#component-overview)
- [Agent Framework SDK Layers](#agent-framework-sdk-layers)
- [Custom Request Routing Flow](#custom-request-routing-flow)
- [Tool Execution Lifecycle](#tool-execution-lifecycle)
- [Multi-Agent Workflow Data Flow](#multi-agent-workflow-data-flow)
- [Observability Pipeline](#observability-pipeline)
- [Deployment Architecture](#deployment-architecture)
- [Key Design Decisions](#key-design-decisions)

---

## Component Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          main.py (Entrypoint)                          │
│                                                                         │
│   • Starts custom FastAPI /responses endpoint                           │
│   • Parses request body: message, agentid, parameters                   │
│   • Routes request to selected mode at runtime                          │
└───────────────┬─────────────────────────────────┬───────────────────────┘
                │                                 │
    agentid=basic                   agentid=workflow
                │                                 │
                ▼                                 ▼
┌───────────────────────────┐   ┌──────────────────────────────────────┐
│   agents/basic_agent.py   │   │    agents/workflow_agent.py          │
│                           │   │                                      │
│  create_basic_agent()     │   │  create_workflow_agent()             │
│  → FoundryChatClient      │   │  → FoundryChatClient (shared)       │
│  → Agent(tools=[...])     │   │  → 3× Agent + AgentExecutor         │
│  → returns Agent          │   │  → WorkflowBuilder pipeline         │
│                           │   │  → workflow.as_agent()               │
└───────────────────────────┘   └──────────────────────────────────────┘
                │                                 │
                └────────────┬────────────────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │   agents/tools.py     │
                 │                       │
                 │  @tool get_weather    │
                 │  @tool search_kb     │
                 │  @tool get_time      │
                 │  @tool calc_cost     │
                 └───────────────────────┘
```

---

## Agent Framework SDK Layers

The Microsoft Agent Framework SDK is organized into three layers:

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 3: Hosting Adapter                                         │
│ Package: fastapi / uvicorn                                       │
│                                                                  │
│ • FastAPI router — custom request body handling                  │
│ • Dispatches by agentid (basic/workflow/orchestrator)            │
│ • Merges request.parameters into prompt placeholders              │
│ • Listens on port 8088 by default                                │
└──────────────────────────────────────────────────────────────────┘
                              │ uses
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ Layer 2: Agent & Orchestration                                   │
│ Package: agent-framework                                         │
│                                                                  │
│ • Agent — wraps an LLM client with instructions and tools        │
│ • @tool decorator — registers Python functions as LLM tools      │
│ • AgentExecutor — wraps Agent with context_mode control          │
│ • WorkflowBuilder — graph-based multi-agent orchestration        │
│ • Workflow.as_agent() — exposes pipeline as a single Agent       │
└──────────────────────────────────────────────────────────────────┘
                              │ uses
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1: LLM Client                                              │
│ Package: agent-framework (FoundryChatClient)                     │
│                                                                  │
│ • FoundryChatClient — Responses API client for Azure OpenAI      │
│ • Manages credentials (DefaultAzureCredential / ManagedIdentity) │
│ • Handles model calls, token usage, streaming                    │
│ • project_endpoint + model deployment name → API calls           │
└──────────────────────────────────────────────────────────────────┘
                              │ calls
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│ Azure OpenAI Responses API                                       │
│ (Azure AI Foundry Model Deployment)                              │
└──────────────────────────────────────────────────────────────────┘
```

### Key Classes

| Class | Package | Role |
|-------|---------|------|
| `Agent` | `agent_framework` | Core agent — binds instructions, tools, and an LLM client |
| `FoundryChatClient` | `agent_framework.foundry` | Authenticated Responses API client for Azure OpenAI |
| `@tool` | `agent_framework` | Decorator that registers a Python function as an LLM-callable tool |
| `AgentExecutor` | `agent_framework` | Wraps `Agent` with context propagation control (`context_mode`) |
| `WorkflowBuilder` | `agent_framework` | Builds directed graphs of `AgentExecutor` nodes |
| `FastAPI` | `fastapi` | HTTP request router for the custom `/responses` endpoint |

---

## Custom Request Routing Flow

The custom request router handles the request/response lifecycle for the new body shape:

```
Client                        FastAPI Router                        Agent
  │                              │                                 │
  │  POST /responses             │                                 │
  │  {message, agentid,          │                                 │
  │   parameters}                │                                 │
  │─────────────────────────────►│                                 │
    │                              │  Validate request body          │
    │                              │  Resolve agentid                │
    │                              │  Render prompt placeholders      │
  │                              │─────────────────────────────────►│
  │                              │                                 │
  │                              │          Agent processes:       │
  │                              │          1. LLM call            │
  │                              │          2. Tool calls (if any) │
  │                              │          3. LLM with results    │
  │                              │                                 │
  │  SSE: response.created       │◄─────────────────────────────────│
  │◄─────────────────────────────│                                 │
  │  SSE: response.in_progress   │                                 │
  │◄─────────────────────────────│                                 │
  │  SSE: response.output_item   │                                 │
  │◄─────────────────────────────│                                 │
  │  SSE: content.delta (×N)     │  ← streaming token chunks       │
  │◄─────────────────────────────│                                 │
  │  SSE: response.completed     │                                 │
  │◄─────────────────────────────│                                 │
  │                              │                                 │
```

### SSE Event Sequence

1. `response.created` — Response object created, contains `response_id`
2. `response.in_progress` — Agent is processing
3. `response.output_item.added` — New output item (message, tool call, etc.)
4. `response.content_part.added` — Content part started
5. `response.output_text.delta` — Streaming text chunk (repeated)
6. `response.content_part.done` — Content part finished
7. `response.output_item.done` — Output item finished
8. `response.completed` — Full response ready

### Non-Streaming Mode

When `"stream": false`, the server collects the full response and returns it as a single JSON object:

```json
{
  "id": "resp_abc123",
  "status": "completed",
  "output": [
    {
      "type": "message",
      "role": "assistant",
      "content": [{ "type": "output_text", "text": "The weather in Paris is..." }]
    }
  ]
}
```

---

## Tool Execution Lifecycle

When the LLM decides to call a tool, the Agent Framework manages the full tool-call loop:

```
Agent                        LLM (Azure OpenAI)              Tool Function
  │                               │                              │
  │  Send user message            │                              │
  │  + tool schemas               │                              │
  │──────────────────────────────►│                              │
  │                               │                              │
  │  Response: tool_call          │                              │
  │  name="get_weather"           │                              │
  │  args={"location":"Paris"}    │                              │
  │◄──────────────────────────────│                              │
  │                               │                              │
  │  Execute get_weather("Paris") │                              │
  │──────────────────────────────────────────────────────────────►│
  │                               │                              │
  │  "Weather in Paris: sunny..." │                              │
  │◄──────────────────────────────────────────────────────────────│
  │                               │                              │
  │  Send tool result back        │                              │
  │──────────────────────────────►│                              │
  │                               │                              │
  │  Final response text          │                              │
  │◄──────────────────────────────│                              │
  │                               │                              │
```

### Tool Schema Generation

The `@tool` decorator automatically generates the JSON schema from:

1. **Function name** → `name` field
2. **Docstring** → `description` field
3. **Annotated parameters** → `parameters` object with types and descriptions from `Field(description=...)`
4. **Return type** → informs the framework about expected output format

Example schema generated for `get_weather`:

```json
{
  "type": "function",
  "name": "get_weather",
  "description": "Get the current weather conditions for a given location.",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "The city or region to get weather for."
      }
    },
    "required": ["location"]
  }
}
```

---

## Multi-Agent Workflow Data Flow

The workflow pipeline uses `WorkflowBuilder` to chain three agents sequentially:

```
User Input: "Research Azure AI Foundry capabilities"
                          │
                          ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 1: Researcher (AgentExecutor, context_mode=last_agent)│
│                                                              │
│  Instructions: "Gather comprehensive information..."        │
│  Tools: [search_knowledge_base, get_weather, get_current_time]│
│                                                              │
│  Actions:                                                    │
│    → search_knowledge_base("Azure AI Foundry") → 3 results  │
│    → get_current_time("UTC") → current timestamp             │
│                                                              │
│  Output: Structured research brief with findings             │
└──────────────────────────┬───────────────────────────────────┘
                           │ context_mode="last_agent"
                           │ (only researcher's output is passed)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 2: Analyst (AgentExecutor, context_mode=last_agent)   │
│                                                              │
│  Instructions: "Evaluate quality, identify insights..."     │
│  Tools: [] (no tools — pure reasoning)                       │
│                                                              │
│  Input: Research brief from Stage 1                          │
│  Output: Numbered key findings + recommendations             │
└──────────────────────────┬───────────────────────────────────┘
                           │ context_mode="last_agent"
                           ▼
┌──────────────────────────────────────────────────────────────┐
│  Stage 3: Report Formatter (AgentExecutor)                   │
│  ★ output_executors=[formatter] — only this output returned  │
│                                                              │
│  Instructions: "Format into polished report..."             │
│  Tools: [] (no tools — pure formatting)                      │
│                                                              │
│  Input: Analysis from Stage 2                                │
│  Output:                                                     │
│    ## Executive Summary                                      │
│    ## Key Findings                                           │
│    ## Recommendations                                        │
│    ## Conclusion                                             │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
              Final formatted report → Client
```

### WorkflowBuilder Code Pattern

```python
workflow_agent = (
    WorkflowBuilder(
        start_executor=researcher_executor,
        output_executors=[formatter_executor],  # Only formatter output returned
    )
    .add_edge(researcher_executor, analyst_executor)
    .add_edge(analyst_executor, formatter_executor)
    .build()
    .as_agent()  # Exposes entire pipeline as a single Agent
)
```

### Context Modes

| Mode | Behavior |
|------|----------|
| `last_agent` | Agent sees only the previous agent's output (used in this sample) |
| `all` | Agent sees the full conversation history from all previous stages |
| `none` | Agent sees only the original user input |

---

## Observability Pipeline

The Agent Framework integrates with OpenTelemetry for distributed tracing:

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent Framework                           │
│                                                             │
│  Instrumented spans:                                        │
│  ├─ agent.handle_message          (root span)               │
│  │  ├─ llm.chat                   (model call)              │
│  │  ├─ tool.execute.get_weather   (tool invocation)         │
│  │  ├─ llm.chat                   (model call with results) │
│  │  └─ response.stream            (SSE streaming)           │
│  │                                                          │
│  For workflows:                                             │
│  ├─ workflow.execute              (pipeline root)           │
│  │  ├─ agent.researcher           (stage 1)                 │
│  │  │  ├─ tool.search_kb          (tool call)               │
│  │  │  └─ llm.chat                (model call)              │
│  │  ├─ agent.analyst              (stage 2)                 │
│  │  │  └─ llm.chat                (model call)              │
│  │  └─ agent.formatter            (stage 3)                 │
│  │     └─ llm.chat                (model call)              │
└───────────────┬─────────────────────────────────────────────┘
                │  OpenTelemetry
                │  (OTLP / stdout)
                ▼
┌─────────────────────────────────────────────────────────────┐
│                  Telemetry Destination                        │
│                                                             │
│  Local:  Console logger (default)                           │
│  Foundry: Application Insights (via connection string)      │
│           → Transaction Search                              │
│           → Application Map                                 │
│           → End-to-end transaction details                   │
└─────────────────────────────────────────────────────────────┘
```

### Environment Variable Control

| Variable | Effect |
|----------|--------|
| `ENABLE_INSTRUMENTATION=true` | Activates OpenTelemetry span collection for agent, tool, and LLM operations |
| `ENABLE_SENSITIVE_DATA=true` | Adds prompt text, completion text, and tool parameters to span attributes (caution: PII risk) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Routes traces to Application Insights (auto-injected by Foundry in production) |

---

## Deployment Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────────┐
│              │     │              │     │   Azure AI Foundry        │
│  Source Code │────►│  ACR Build   │────►│   Agent Service           │
│              │     │  (or Docker) │     │                          │
│  main.py     │     │              │     │  ┌────────────────────┐  │
│  agents/     │     │  Image:      │     │  │  Hosted Agent      │  │
│  Dockerfile  │     │  python:3.12 │     │  │  Container         │  │
│  agent.yaml  │     │  + deps      │     │  │                    │  │
│              │     │  + code      │     │  │  Port 8088         │  │
└──────────────┘     └──────────────┘     │  │  Responses proto   │  │
                                          │  └─────────┬──────────┘  │
                                          │            │             │
                                          │  ┌─────────▼──────────┐  │
                                          │  │  Foundry Gateway    │  │
                                          │  │  • Auth (Entra ID)  │  │
                                          │  │  • Session mgmt    │  │
                                          │  │  • History store    │  │
                                          │  │  • Load balancing   │  │
                                          │  └─────────┬──────────┘  │
                                          └────────────┼─────────────┘
                                                       │
                                          ┌────────────▼─────────────┐
                                          │  Clients                  │
                                          │  • curl / Postman         │
                                          │  • OpenAI Python SDK      │
                                          │  • Custom applications    │
                                          │  • Agent Inspector (dev)  │
                                          └──────────────────────────┘
```

### Deployment Pipeline Steps

| Step | Action | Tool |
|------|--------|------|
| 1 | Build container image from Dockerfile | `az acr build` or `docker build` |
| 2 | Push to Azure Container Registry | ACR Tasks (auto) or `docker push` |
| 3 | Create/update agent definition | Foundry MCP `agent_update` or Portal |
| 4 | Assign RBAC (ACR pull + Azure AI User) | `az role assignment create` |
| 5 | Create session | Foundry MCP `session_create` |
| 6 | Invoke and test | Foundry MCP `agent_invoke` or `curl` |
| 7 | Clean up session | Foundry MCP `session_delete` |

### Container Details

| Property | Value |
|----------|-------|
| Base image | `python:3.12-slim` |
| Working directory | `/app/user_agent` |
| Exposed port | `8088` |
| Entrypoint | `python main.py` |
| Platform | `linux/amd64` |

### RBAC Requirements

| Identity | Role | Scope |
|----------|------|-------|
| Foundry project managed identity | `Container Registry Repository Reader` | ACR registry/repository |
| Agent per-agent identity | `Azure AI User` | Cognitive Services account |
| Project-level agent identity | `Azure AI User` | Cognitive Services account |

---

## Key Design Decisions

### 1. Single Entrypoint with Request-Time Dispatch

Rather than separate scripts for each agent type, `main.py` now uses `agentid` in the request body to select the agent at request time. This means:
- **One Dockerfile** — same container image serves all modes
- **One runtime endpoint** — choose mode per request without redeploying
- **Per-request prompt templates** — `parameters` can be merged into prompt placeholders

### 2. `load_dotenv(override=False)`

Environment variables set by the Foundry runtime (e.g., `FOUNDRY_PROJECT_ENDPOINT`, `APPLICATIONINSIGHTS_CONNECTION_STRING`) take precedence over `.env` values. This ensures production configuration is never accidentally overridden by local development settings.

### 3. `default_options={"store": False}`

Conversation history storage is disabled at the agent level because the custom router passes request text and parameters directly. This avoids duplicate storage and keeps runtime behavior deterministic per request.

### 4. `context_mode="last_agent"` in Workflows

Each agent in the pipeline sees only the output from the previous stage, not the full conversation history. This:
- Reduces token usage (each agent gets a focused input)
- Prevents context confusion (the analyst doesn't see tool call details from the researcher)
- Gives each agent a clear, scoped responsibility

### 5. `output_executors=[formatter]`

Only the formatter's output is returned to the caller. Without this, the response would include all intermediate outputs from the researcher and analyst, which would be noisy and confusing for the end user.

### 6. `approval_mode="never_require"` on Tools

All tools are marked as not requiring user approval. This is appropriate for a hosted agent where there is no interactive user session to prompt for approval. In a human-in-the-loop scenario, you would use `approval_mode="always_require"` or `approval_mode="auto"`.
