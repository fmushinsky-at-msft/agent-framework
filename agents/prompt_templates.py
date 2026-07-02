"""Utilities for per-request prompt placeholder rendering."""

import re
from typing import Any, Mapping

_PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")

# Reusable instruction appended to answering agents so they never emit cryptic
# source-citation markers (e.g. "[371:1\u2020source]", "\u30103:0\u2020source\u3011")
# to end users.
NO_SOURCE_REFERENCES_RULE = (
    "\n\n# Output formatting\n"
    "- Do NOT include any source citations, reference markers, document IDs, or "
    "chunk IDs in your answer. Never emit tokens such as \"[371:1\u2020source]\", "
    "\"\u30103:0\u2020source\u3011\", \"[doc1]\", or any bracketed \"source\" tag. "
    "Return only clean, human-readable text with no bracketed reference markers."
)


def build_template_context(parameters: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a normalized context for placeholder rendering.

    Missing keys are intentionally not backfilled so unresolved placeholders
    remain unchanged in prompts.
    """
    context: dict[str, Any] = dict(parameters or {})

    # Convenience aliases to support current prompt tokens.
    if "username" in context and "user_full_name" not in context:
        context["user_full_name"] = context["username"]
    if "user_full_name" in context and "username" not in context:
        context["username"] = context["user_full_name"]

    return context


def render_prompt_template(template: str, parameters: Mapping[str, Any] | None) -> str:
    """Render a prompt template using values from parameters.

    Any placeholder without a corresponding key is left unchanged.
    """
    context = build_template_context(parameters)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in context:
            return str(context[key])
        return match.group(0)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)
