"""Web search tool."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry


def _web_search(ctx: ToolContext, query: str) -> str:
    """Search the web via OpenAI Responses API or FlowAI.
    
    Requires OPENAI_API_KEY for web_search capability.
    Uses FlowAI models when IFLOW_API_KEY is set.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    iflow_key = os.environ.get("IFLOW_API_KEY", "")
    
    if not api_key and not iflow_key:
        return json.dumps({"error": "OPENAI_API_KEY or IFLOW_API_KEY not set; web_search unavailable."})
    
    # Determine which model to use
    # Priority: explicit env var > FlowAI default > OpenAI default
    if iflow_key:
        # FlowAI mode: use Qwen3-Coder-Plus (stable model)
        # Ignore OUROBOROS_WEBSEARCH_MODEL if it points to non-existent model
        explicit_model = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "")
        # List of known valid FlowAI models
        valid_flowai_models = {"Qwen3-Coder-Plus", "Qwen3-Coder-30B-A3B-Instruct", "Kimi-K2-Instruct-0905"}
        if explicit_model and explicit_model in valid_flowai_models:
            model = explicit_model
        else:
            model = "Qwen3-Coder-Plus"  # Default for FlowAI
    else:
        # OpenAI mode
        model = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "gpt-4o")
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key if api_key else iflow_key, 
                       base_url="https://apis.iflow.cn/v1" if iflow_key and not api_key else None)
        resp = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            input=query,
        )
        d = resp.model_dump()
        text = ""
        for item in d.get("output", []) or []:
            if item.get("type") == "message":
                for block in item.get("content", []) or []:
                    if block.get("type") in ("output_text", "text"):
                        text += block.get("text", "")
        return json.dumps({"answer": text or "(no answer)"}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": repr(e)}, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web via OpenAI Responses API or FlowAI. Returns JSON with answer + sources.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
            }, "required": ["query"]},
        }, _web_search),
    ]
