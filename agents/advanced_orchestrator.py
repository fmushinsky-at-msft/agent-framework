"""Compatibility shim for previous imports.

The canonical implementation now lives in agents.multi_agent_orchestrator.
"""

from agents.multi_agent_orchestrator import (  # noqa: F401
    MultiAgentOrchestrator,
    create_multi_agent_orchestrator,
    create_multi_agent_orchestrator_agent,
)

__all__ = [
    "MultiAgentOrchestrator",
    "create_multi_agent_orchestrator",
    "create_multi_agent_orchestrator_agent",
]
