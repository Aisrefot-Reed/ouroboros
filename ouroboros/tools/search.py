"""Web search tool.

Provides real web search via multiple methods:
1. DuckDuckGo Search API (free, no key required) - PRIMARY
2. OpenAI web_search tool (requires OPENAI_API_KEY with search access) - FALLBACK
3. Browser search via Playwright (if other methods fail) - LAST RESORT
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List

from ouroboros.tools.registry import ToolContext, ToolEntry


def _duckduckgo_search(query: str, num_results: int = 5) -> Dict[str, Any]:
    """
    Search via DuckDuckGo (free, no API key required).
    
    Uses duckduckgo-search library for reliable results.
    """
    try:
        from duckduckgo_search import DDGS
        
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        
        if not results:
            return {
                "answer": f"No results found for: {query}",
                "sources": [],
                "method": "duckduckgo"
            }
        
        # Format results
        answer_parts = []
        sources = []
        
        for i, r in enumerate(results[:num_results], 1):
            title = r.get("title", "Untitled")
            body = r.get("body", "")
            url = r.get("href", "")
            
            answer_parts.append(f"{i}. **{title}**\n   {body[:200]}...")
            sources.append({"title": title, "url": url, "snippet": body})
        
        return {
            "answer": f"Search results for: {query}\n\n" + "\n\n".join(answer_parts),
            "sources": sources,
            "method": "duckduckgo",
            "result_count": len(results)
        }
        
    except ImportError:
        return {
            "error": "duckduckgo-search not installed",
            "hint": "Run: pip install duckduckgo-search",
            "method": "duckduckgo"
        }
    except Exception as e:
        return {
            "error": f"DuckDuckGo search failed: {repr(e)}",
            "method": "duckduckgo"
        }


def _openai_web_search(query: str, model: str = "gpt-4o") -> Dict[str, Any]:
    """
    Search via OpenAI Chat Completions API with web_search tool.
    Requires OPENAI_API_KEY with search access.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    
    if not api_key:
        return {"error": "OPENAI_API_KEY not set"}
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": query}],
            tools=[{"type": "web_search"}],
            tool_choice="auto",
        )
        
        answer = response.choices[0].message.content or "(no answer)"
        
        sources = []
        if hasattr(response, 'web_search_results') and response.web_search_results:
            for result in response.web_search_results[:5]:
                sources.append({
                    "title": result.get("title", "Untitled"),
                    "url": result.get("url", "No URL")
                })
        
        return {
            "answer": answer,
            "sources": sources,
            "method": "openai"
        }
        
    except Exception as e:
        return {"error": f"OpenAI web_search failed: {repr(e)}", "method": "openai"}


def _browser_search(query: str) -> Dict[str, Any]:
    """
    Fallback: Search via browser (Google).
    This is a last resort when other methods fail.
    """
    try:
        import requests
        from urllib.parse import quote
        
        # Use Google search and fetch the page
        search_url = f"https://www.google.com/search?q={quote(query)}&num=5"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        resp = requests.get(search_url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        # Extract basic info from HTML (simple parsing)
        html = resp.text[:50000]  # Limit parsing
        
        # Look for search result titles and URLs
        import re
        results = []
        
        # Google search result pattern (simplified)
        title_pattern = r'<h3[^>]*>([^<]+)</h3>'
        url_pattern = r'href="https?://(www\.)?google\.com/url\?q=([^&]+)"'
        
        titles = re.findall(title_pattern, html)
        urls = re.findall(url_pattern, html)
        
        for i, (title, (_, url)) in enumerate(zip(titles[:5], urls[:5]), 1):
            # Unquote URL
            from urllib.parse import unquote
            clean_url = unquote(url.replace('+', ' '))
            results.append({"title": title, "url": clean_url})
        
        if results:
            answer_parts = [f"Search results for: {query}\n"]
            for i, r in enumerate(results, 1):
                answer_parts.append(f"{i}. **{r['title']}** - {r['url']}")
            
            return {
                "answer": "\n\n".join(answer_parts),
                "sources": results,
                "method": "browser_google"
            }
        else:
            return {"error": "No results extracted from Google search", "method": "browser"}
            
    except Exception as e:
        return {"error": f"Browser search failed: {repr(e)}", "method": "browser"}


def _web_search(ctx: ToolContext, query: str) -> str:
    """
    Search the web using multiple methods with automatic fallback.
    
    Priority:
    1. DuckDuckGo (free, no key) - PRIMARY
    2. OpenAI web_search (if OPENAI_API_KEY set) - SECONDARY
    3. Browser Google search - LAST RESORT
    
    Returns JSON with answer + sources.
    """
    if not query or not query.strip():
        return json.dumps({"error": "Query is required"}, ensure_ascii=False)
    
    # Method 1: DuckDuckGo (PRIMARY - free, no key)
    ctx.emit_progress_fn("🔍 Searching via DuckDuckGo...")
    result = _duckduckgo_search(query, num_results=5)
    
    if "error" not in result and result.get("result_count", 0) > 0:
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    # Method 2: OpenAI web_search (if key available)
    if os.environ.get("OPENAI_API_KEY"):
        ctx.emit_progress_fn("🔍 DuckDuckGo failed, trying OpenAI web_search...")
        result = _openai_web_search(query)
        
        if "error" not in result:
            return json.dumps(result, ensure_ascii=False, indent=2)
    
    # Method 3: Browser search (LAST RESORT)
    ctx.emit_progress_fn("🔍 Falling back to browser search...")
    result = _browser_search(query)
    
    return json.dumps(result, ensure_ascii=False, indent=2)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": "Search the web with automatic fallback. Uses DuckDuckGo (free), OpenAI (if key set), or browser. Returns JSON with answer + sources.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Search query"},
            }, "required": ["query"]},
        }, _web_search),
    ]
