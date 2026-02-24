"""Web search tool."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry


def _web_search(ctx: ToolContext, query: str) -> str:
    """Search the web via OpenAI Chat Completions API with web_search tool.
    
    Requires OPENAI_API_KEY for web_search capability.
    Uses FlowAI models when IFLOW_API_KEY is set.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    iflow_key = os.environ.get("IFLOW_API_KEY", "")
    
    if not api_key and not iflow_key:
        return json.dumps({"error": "OPENAI_API_KEY or IFLOW_API_KEY not set; web_search unavailable."})
    
    # Determine which model to use
    if iflow_key and not api_key:
        # FlowAI mode: use Qwen3-Coder-Plus (stable model)
        # Ignore OUROBOROS_WEBSEARCH_MODEL if it points to non-existent model
        explicit_model = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "")
        valid_flowai_models = {"Qwen3-Coder-Plus", "Qwen3-Coder-30B-A3B-Instruct", "Kimi-K2-Instruct-0905"}
        if explicit_model and explicit_model in valid_flowai_models:
            model = explicit_model
        else:
            model = "Qwen3-Coder-Plus"  # Default for FlowAI
        base_url = "https://apis.iflow.cn/v1"
        use_key = iflow_key
    else:
        # OpenAI mode
        model = os.environ.get("OUROBOROS_WEBSEARCH_MODEL", "gpt-4o")
        base_url = None
        use_key = api_key
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=use_key, base_url=base_url)
        
        # Use Chat Completions API with web_search tool
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search"}],
            tool_choice="auto",
        )
        
        # Check if model used web_search tool
        if response.choices[0].message.tool_calls:
            # Extract web search results
            sources = []
            for tool_call in response.choices[0].message.tool_calls:
                if tool_call.function.name == "web_search":
                    # The model has already processed the search
                    pass
            
            # Get the final response with search results incorporated
            answer = response.choices[0].message.content or "(no answer)"
            
            # Try to extract sources from response if available
            if hasattr(response, 'web_search_results') and response.web_search_results:
                for result in response.web_search_results[:5]:
                    sources.append(f"- {result.get('title', 'Untitled')}: {result.get('url', 'No URL')}")
            
            result_data = {"answer": answer}
            if sources:
                result_data["sources"] = sources
            return json.dumps(result_data, ensure_ascii=False, indent=2)
        else:
            # No web search was performed, just return the answer
            return json.dumps({"answer": response.choices[0].message.content or "(no answer)"}, ensure_ascii=False, indent=2)
            
    except Exception as e:
        return json.dumps({"error": repr(e)}, ensure_ascii=False)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web via OpenAI Chat Completions API with web_search tool. Returns JSON with answer + sources.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string"},
            }, "required": ["query"]},
        }, _web_search),
    ]
