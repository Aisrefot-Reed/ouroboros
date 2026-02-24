"""Web search tool.

Uses OpenAI Chat Completions API with web_search capability.
Requires OPENAI_API_KEY to be set separately from IFLOW_API_KEY.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry


def _web_search(ctx: ToolContext, query: str) -> str:
    """Search the web via OpenAI Chat Completions API.
    
    Requires OPENAI_API_KEY (separate from IFLOW_API_KEY).
    Uses gpt-4o or model from OUROBOROS_WEBSEARCH_MODEL env var.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    
    if not api_key:
        return json.dumps({
            "error": "OPENAI_API_KEY not set. Add your OpenAI API key to enable web search.",
            "hint": "Set OPENAI_API_KEY in Colab Secrets or environment variables."
        }, ensure_ascii=False, indent=2)
    
    # Use model from env or default to gpt-4o (which supports web_search)
    model = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "gpt-4o")
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)  # Uses default OpenAI base_url
        
        # Use Chat Completions API with web_search tool
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search"}],
            tool_choice="auto",
        )
        
        # Get the response
        answer = response.choices[0].message.content or "(no answer)"
        
        # Try to extract sources from web search results if available
        sources = []
        if hasattr(response, 'web_search_results') and response.web_search_results:
            for result in response.web_search_results[:5]:
                sources.append(f"- {result.get('title', 'Untitled')}: {result.get('url', 'No URL')}")
        
        result_data = {"answer": answer}
        if sources:
            result_data["sources"] = sources
        
        return json.dumps(result_data, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return json.dumps({"error": repr(e)}, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web via OpenAI Chat Completions API with web_search tool. Requires OPENAI_API_KEY. Returns JSON with answer + sources.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Search query"},
            }, "required": ["query"]},
        }, _web_search),
    ]
