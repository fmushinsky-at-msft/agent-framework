# Copyright (c) Microsoft. All rights reserved.

"""Shared tool definitions for the Agent Framework sample.

Tools are decorated with @tool from agent_framework and use Annotated type hints
with pydantic Field descriptions. Each tool sets approval_mode="never_require"
so the LLM can invoke them without user confirmation.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from random import randint, choice
from urllib import error, parse, request
from typing import Annotated, Any, Iterable, Mapping, cast

from agent_framework import tool
from azure.core.credentials import AzureKeyCredential
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from pydantic import Field


@tool(approval_mode="never_require")
def get_weather(
    location: Annotated[str, Field(description="The city or region to get weather for.")],
) -> str:
    """Get the current weather conditions for a given location."""
    conditions = ["sunny", "partly cloudy", "cloudy", "rainy", "stormy", "snowy"]
    temp = randint(-5, 38)
    humidity = randint(20, 95)
    wind_speed = randint(0, 50)
    return (
        f"Weather in {location}: {choice(conditions)}, "
        f"temperature {temp}°C, humidity {humidity}%, "
        f"wind speed {wind_speed} km/h."
    )


@tool(approval_mode="never_require")
def search_knowledge_base(
    query: Annotated[str, Field(description="The search query to look up in the knowledge base.")],
    top: Annotated[int, Field(description="Maximum number of search results to return.")] = 5,
    filter_expression: Annotated[
        str,
        Field(description="Optional OData filter expression to narrow results."),
    ] = "",
) -> str:
    """Search Azure AI Search index and return relevant grounding context.

    Required environment variables:
        AZURE_SEARCH_ENDPOINT (e.g. https://<service>.search.windows.net)
        AZURE_SEARCH_INDEX_NAME

    Optional environment variable:
        AZURE_SEARCH_API_KEY (if omitted, DefaultAzureCredential is used)
    """
    endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
    index_name = os.environ.get("AZURE_SEARCH_INDEX_NAME")
    api_key = os.environ.get("AZURE_SEARCH_API_KEY")

    if not endpoint or not index_name:
        return (
            "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT and "
            "AZURE_SEARCH_INDEX_NAME environment variables."
        )

    # Use managed identity / Entra ID by default; API key is optional fallback.
    credential: Any = (
        AzureKeyCredential(api_key) if api_key else DefaultAzureCredential()
    )

    client = SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=credential,
    )

    search_kwargs: dict[str, Any] = {"top": max(1, min(top, 20))}
    if filter_expression:
        search_kwargs["filter"] = filter_expression

    try:
        results = cast(
            Iterable[Mapping[str, Any]],
            client.search(search_text=query, **search_kwargs),
        )
        output_results: list[dict[str, Any]] = []
        for item in results:
            doc = item
            snippet = str(
                doc.get("content")
                or doc.get("chunk")
                or doc.get("text")
                or doc.get("body")
                or doc.get("description")
                or ""
            )
            output_results.append(
                {
                    "id": doc.get("id") or doc.get("key") or doc.get("chunk_id"),
                    "title": doc.get("title") or doc.get("name"),
                    "snippet": snippet,
                    "relevance": doc.get("@search.score"),
                }
            )

        return json.dumps(
            {
                "query": query,
                "index": index_name,
                "total_results": len(output_results),
                "results": output_results,
            },
            indent=2,
        )
    except Exception as exc:
        return f"Azure AI Search query failed: {exc}"


@tool(approval_mode="never_require")
def get_current_time(
    timezone_name: Annotated[
        str,
        Field(description="Timezone offset from UTC, e.g. 'UTC', 'UTC+5', 'UTC-8'."),
    ] = "UTC",
) -> str:
    """Get the current date and time in the specified timezone."""
    offset_hours = 0
    if timezone_name != "UTC":
        try:
            offset_str = timezone_name.replace("UTC", "").strip()
            offset_hours = int(offset_str)
        except (ValueError, AttributeError):
            return f"Invalid timezone format: '{timezone_name}'. Use 'UTC', 'UTC+5', 'UTC-8', etc."

    tz = timezone(timedelta(hours=offset_hours))
    now = datetime.now(tz)
    return f"Current time in {timezone_name}: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"


@tool(approval_mode="never_require")
def calculate_cost(
    items: Annotated[
        str,
        Field(
            description=(
                "JSON string with a list of items. Each item should have "
                "'name' (string), 'quantity' (number), and 'unit_price' (number). "
                'Example: [{"name": "Widget", "quantity": 3, "unit_price": 9.99}]'
            )
        ),
    ],
) -> str:
    """Calculate the total cost for a list of items with quantities and unit prices."""
    try:
        item_list_raw = json.loads(items)
    except json.JSONDecodeError:
        return "Error: Invalid JSON. Please provide a valid JSON array of items."

    if not isinstance(item_list_raw, list):
        return "Error: Input must be a JSON array of items."

    item_list = cast(list[Mapping[str, Any]], item_list_raw)

    total = 0.0
    breakdown: list[str] = []
    for item in item_list:
        name = str(item.get("name", "Unknown"))
        qty = float(item.get("quantity", 1))
        price = float(item.get("unit_price", 0.0))
        subtotal = qty * price
        total += subtotal
        breakdown.append(f"  - {name}: {qty} x ${price:.2f} = ${subtotal:.2f}")

    return f"Cost Breakdown:\n" + "\n".join(breakdown) + f"\n  Total: ${total:.2f}"


@tool(approval_mode="never_require")
def hr_info_given_userid(
    user_name: Annotated[
        str,
        Field(description="The user identifier/name to fetch HR profile information for."),
    ],
) -> str:
    """Get user HR profile information for the provided user from the OpenAPI endpoint."""
    base_url = (
        "https://prod-12.eastus2.logic.azure.com:443/workflows/"
        "e518d7921d7f4f2ebd1b9dc00df606ad/triggers/When_a_HTTP_request_is_received/paths/invoke"
    )
    query = parse.urlencode(
        {
            "api-version": "2016-10-01",
            "sp": "/triggers/When_a_HTTP_request_is_received/run",
            "sv": "1.0",
            "sig": "en1VbMKU7MtGQH9kpQ_18T-Z9pwK5sjbaCTwMugnpzs",
        }
    )
    url = f"{base_url}?{query}"
    payload = json.dumps({"userid": user_name}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8")
            try:
                return json.dumps(json.loads(body), indent=2)
            except json.JSONDecodeError:
                return body
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        return f"HR API HTTP error {exc.code}: {details}"
    except error.URLError as exc:
        return f"HR API connection error: {exc.reason}"


