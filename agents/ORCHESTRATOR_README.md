# Multi-Agent Orchestrator Workflow

This directory contains workflow agents inspired by the AI Foundry Workflow Agent pattern from `wf-agent.yaml`.

## Overview

The multi-agent orchestrator implements an intent-based routing workflow that:

1. **Classifies Intent**: An Orchestrator agent listens to the user's request and classifies it into one of 7 categories
2. **Routes Intelligently**: Based on the classification, routes to specialized agents
3. **Gathers Context**: For certain intents, retrieves user profile information
4. **Provides Expert Response**: Specialized agents answer domain-specific questions

## Supported Intents

| Intent | Domain | Agents Involved |
|--------|--------|-----------------|
| 1 | Health Benefits | User-Profile + Health-Benefit |
| 2 | Commuter Benefits | Commuter |
| 3 | Retirement Planning | User-Profile + Retirement |
| 4 | HR Policies | User-Profile + HR-Policy |
| 5 | Staff Directory | User-Profile + Staff-Profile |
| 6 | AI Usage Policy | AI-Policy |
| 7 | Data Classification | Data-Classification |

## Implementations

### 1. `multi_agent_orchestrator.py`

A WorkflowBuilder-based implementation using the agent framework's native workflow patterns.

**Features:**
- Uses WorkflowBuilder for workflow composition
- Multiple specialized agents
- AgentExecutor wrappers for context isolation
- Suitable for linear or simple branching workflows

**Usage:**
```python
from agents.multi_agent_orchestrator import create_multi_agent_orchestrator

orchestrator = create_multi_agent_orchestrator()
```

### 2. `advanced_orchestrator.py`

A more sophisticated implementation with explicit intent classification and routing logic.

**Features:**
- `MultiAgentOrchestrator` class with async request processing
- Explicit intent extraction and validation
- Conditional agent invocation (e.g., user profile for certain intents)
- Response consolidation
- Better error handling

**Usage:**
```python
from agents.advanced_orchestrator import MultiAgentOrchestrator

orchestrator = MultiAgentOrchestrator()
response = await orchestrator.process_request(user_message)
```

## Architecture

```
User Input
    ↓
Orchestrator Agent (Intent Classification)
    ↓
    ├─ Intent 1,3,4,5 → User-Profile Agent + Specialized Agent
    └─ Intent 2,6,7 → Specialized Agent Only
    ↓
Consolidated Response
    ↓
User Output
```

## Integration with Main Agent

To use the new workflow in your main application:

1. **Option A: Replace existing workflow**
   ```python
   # In main.py
   from agents.advanced_orchestrator import MultiAgentOrchestrator
   
   orchestrator = MultiAgentOrchestrator()
   ```

2. **Option B: Add as alternative workflow**
   ```python
   # Create both agents
   from agents.workflow_agent import create_workflow_agent
   from agents.advanced_orchestrator import MultiAgentOrchestrator
   
   # Use based on user selection or configuration
   ```

## Tools Used

Each specialized agent has access to:
- `search_knowledge_base`: Search internal documentation
- `get_current_time`: Get current date/time in any timezone
- `get_weather`: (Available for certain agents)

## Configuration

Required environment variables:
- `FOUNDRY_PROJECT_ENDPOINT`: Your Azure AI Foundry project endpoint
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`: Your model deployment name (e.g., gpt-4.1-mini)

## Extending the Workflow

To add a new intent:

1. Add a new case in the `ORCHESTRATOR_INSTRUCTIONS`
2. Create a new specialized agent method in `MultiAgentOrchestrator`
3. Add mapping in `self.agents` dictionary
4. Update routing logic if needed

## Mapping from wf-agent.yaml

The implementation directly maps the AI Foundry YAML structure:

| YAML Component | Python Implementation |
|---|---|
| `trigger: OnConversationStart` | `process_request()` async method |
| `InvokeAzureAgent: Orchestrator-Agent` | `orchestrator` agent |
| `ConditionGroup` | `_extract_intent()` and conditional routing |
| Conditional branches | `if intent in ["1", "3", "4", "5"]` logic |
| `SendActivity` | Response return from `process_request()` |

## Notes

- The advanced orchestrator uses async/await patterns compatible with modern Python agents
- Error handling includes fallback responses when intent cannot be classified
- User profile information is cached and reused for intents that need it
- The workflow is designed to be extensible for additional intents or agents
