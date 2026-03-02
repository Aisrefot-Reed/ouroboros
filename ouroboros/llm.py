"""
Ouroboros — LLM client.

Supports multiple providers:
1. FlowAI / iFlow (default for Qwen3-Coder-Plus)
2. Google Gemini (native via google-generativeai)
3. OpenAI (native fallback)

Contract: chat(), default_model(), available_models(), add_usage().
"""

from __future__ import annotations

import logging
import os
import time
import json
import traceback
import sys
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

DEFAULT_LIGHT_MODEL = "Qwen3-Coder-30B-A3B-Instruct"


def normalize_reasoning_effort(value: str, default: str = "medium") -> str:
    allowed = {"none", "minimal", "low", "medium", "high", "xhigh"}
    v = str(value or "").strip().lower()
    return v if v in allowed else default


def reasoning_rank(value: str) -> int:
    order = {"none": 0, "minimal": 1, "low": 2, "medium": 3, "high": 4, "xhigh": 5}
    return int(order.get(str(value or "").strip().lower(), 3))


def add_usage(total: Dict[str, Any], usage: Dict[str, Any]) -> None:
    """Accumulate usage from one LLM call into a running total."""
    for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cache_write_tokens"):
        total[k] = int(total.get(k) or 0) + int(usage.get(k) or 0)
    if usage.get("cost"):
        total["cost"] = float(total.get("cost") or 0) + float(usage["cost"])


class LLMClient:
    """Multi-provider LLM client: FlowAI, Google Gemini, OpenAI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self._iflow_key = api_key or os.environ.get("IFLOW_API_KEY")
        self._google_key = os.environ.get("GOOGLE_API_KEY")
        self._openai_key = os.environ.get("OPENAI_API_KEY")
        
        self._iflow_base_url = base_url or "https://apis.iflow.cn/v1"
        
        self._openai_client = None
        self._iflow_client = None
        
        msg = f"LLMClient init: iFlow={'OK' if self._iflow_key else 'NO'}, Google={'OK' if self._google_key else 'NO'}, OpenAI={'OK' if self._openai_key else 'NO'}"
        log.info(msg)
        print(f"[LLM] {msg}", file=sys.stderr)

    def _get_iflow_client(self):
        if self._iflow_client is None and self._iflow_key:
            from openai import OpenAI
            self._iflow_client = OpenAI(
                base_url=self._iflow_base_url,
                api_key=self._iflow_key,
                default_headers={
                    "HTTP-Referer": "https://colab.research.google.com/",
                    "X-Title": "Ouroboros",
                },
            )
        return self._iflow_client

    def _get_openai_client(self):
        if self._openai_client is None and self._openai_key:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self._openai_key)
        return self._openai_client

    def chat(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        reasoning_effort: str = "medium",
        max_tokens: int = 16384,
        tool_choice: str = "auto",
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Single LLM call. Routes to appropriate provider based on model prefix."""
        
        print(f"[LLM] Routing call: model='{model}'", file=sys.stderr)
        
        # 1. Route to Google Gemini
        if (model.startswith(("google/", "gemini-")) or "gemini" in model.lower()):
            if not self._google_key:
                err = "⚠️ Error: GOOGLE_API_KEY is missing in Secrets"
                print(f"[LLM] {err}", file=sys.stderr)
                return {"role": "assistant", "content": err}, {"cost": 0}
            return self._chat_gemini(messages, model, tools, max_tokens)
        
        # 2. Route to OpenAI
        if (model.startswith(("openai/", "gpt-", "o1-", "o3-")) or "gpt" in model.lower()) and self._openai_key:
            return self._chat_openai(messages, model, tools, max_tokens, reasoning_effort)

        # 3. Default to iFlow (FlowAI)
        return self._chat_iflow(messages, model, tools, max_tokens, reasoning_effort, tool_choice)

    def _strip_defaults(self, obj: Any) -> Any:
        """Recursively remove 'default' fields from JSON schema for Gemini compatibility."""
        if isinstance(obj, dict):
            return {k: self._strip_defaults(v) for k, v in obj.items() if k != 'default'}
        elif isinstance(obj, list):
            return [self._strip_defaults(i) for i in obj]
        return obj

    def _format_gemini_content(self, content: Any) -> Any:
        """Format message content for Gemini API. Handles string and list content."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    elif item.get("type") == "image_url":
                        # Image URL needs conversion to bytes/PIL for native library
                        # For now, just skip or provide a note
                        parts.append(f"[Image: {item.get('image_url', {}).get('url', 'unknown')}]")
            return " ".join(parts)
        return str(content)

    def _chat_gemini(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192,
        _retry_count: int = 0
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        import google.generativeai as genai
        
        try:
            genai.configure(api_key=self._google_key)
            
            gemini_model_id = model.replace("google/", "")
            print(f"[LLM] Gemini call: {gemini_model_id} (attempt {_retry_count+1})", file=sys.stderr)
            
            gemini_history = []
            system_instruction = None
            
            for m in messages:
                role = m["role"]
                content = m["content"]
                if role == "system":
                    system_instruction = self._format_gemini_content(content)
                elif role == "user":
                    gemini_history.append({"role": "user", "parts": [self._format_gemini_content(content)]})
                elif role == "assistant":
                    if m.get("tool_calls"):
                        parts = [{"text": self._format_gemini_content(content) or ""}]
                        for tc in m["tool_calls"]:
                            parts.append({
                                "function_call": {
                                    "name": tc["function"]["name"],
                                    "args": json.loads(tc["function"]["arguments"])
                                }
                            })
                        gemini_history.append({"role": "model", "parts": parts})
                    else:
                        gemini_history.append({"role": "model", "parts": [self._format_gemini_content(content) or ""]})
                elif role == "tool":
                    gemini_history.append({
                        "role": "user",
                        "parts": [{
                            "function_response": {
                                "name": m["name"],
                                "response": {"result": m["content"]}
                            }
                        }]
                    })

            gemini_tools = []
            if tools:
                gemini_tool_list = []
                for t in tools:
                    func = t["function"]
                    gemini_tool_list.append({
                        "name": func["name"],
                        "description": func["description"],
                        "parameters": self._strip_defaults(func["parameters"])
                    })
                gemini_tools = [{"function_declarations": gemini_tool_list}]

            gen_model = genai.GenerativeModel(
                model_name=gemini_model_id,
                system_instruction=system_instruction,
                tools=gemini_tools
            )
            
            if not gemini_history:
                # If history is empty, create a dummy one
                gemini_history = [{"role": "user", "parts": ["Hello"]}]

            last_msg = gemini_history.pop()
            chat = gen_model.start_chat(history=gemini_history)
            response = chat.send_message(last_msg["parts"], generation_config={"max_output_tokens": max_tokens})
            
            if not response.candidates:
                return {"role": "assistant", "content": "⚠️ Gemini Error: No response candidates"}, {"cost": 0}

            candidate = response.candidates[0]
            res_content = ""
            tool_calls = []
            
            for part in candidate.content.parts:
                if hasattr(part, 'text') and part.text:
                    res_content += part.text
                if fn := part.function_call:
                    tool_calls.append({
                        "id": f"call_{int(time.time())}_{fn.name}",
                        "type": "function",
                        "function": {
                            "name": fn.name,
                            "arguments": json.dumps(dict(fn.args))
                        }
                    })
            
            res_msg = {"role": "assistant", "content": res_content or None}
            if tool_calls:
                res_msg["tool_calls"] = tool_calls
                
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
                "cost": 0.0
            }
            return res_msg, usage
            
        except Exception as e:
            err_str = str(e)
            if ("ResourceExhausted" in err_str or "429" in err_str):
                if _retry_count < 1:
                    import re
                    wait_time = 10.0
                    match = re.search(r"retry in ([\d.]+)s", err_str)
                    if match:
                        wait_time = float(match.group(1)) + 1.0
                    print(f"[LLM] Gemini Quota. Waiting {wait_time}s...", file=sys.stderr)
                    time.sleep(wait_time)
                    return self._chat_gemini(messages, model, tools, max_tokens, _retry_count + 1)
                else:
                    # After retry failed, return None to trigger Ouroboros fallback logic
                    print(f"[LLM] Gemini Quota exhausted after retry. Triggering fallback.", file=sys.stderr)
                    return None, {}

            tb = traceback.format_exc()
            print(f"[LLM] Gemini Error: {e}", file=sys.stderr)
            return {"role": "assistant", "content": f"⚠️ Gemini API Error: {err_str}"}, {"cost": 0}


    def _chat_iflow(self, messages, model, tools, max_tokens, reasoning_effort, tool_choice):
        client = self._get_iflow_client()
        if not client:
            return {"role": "assistant", "content": "⚠️ Error: IFLOW_API_KEY not found."}, {}
            
        try:
            kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice

            resp = client.chat.completions.create(**kwargs)
            resp_dict = resp.model_dump()
            usage = resp_dict.get("usage") or {}
            msg = (resp_dict.get("choices") or [{}])[0].get("message") or {}
            
            if not usage.get("cost"):
                usage["cost"] = (usage.get("prompt_tokens", 0) * 0.5 + usage.get("completion_tokens", 0) * 1.5) / 1_000_000

            return msg, usage
        except Exception as e:
            print(f"[LLM] iFlow Error: {e}", file=sys.stderr)
            return {"role": "assistant", "content": f"⚠️ iFlow API Error: {repr(e)}"}, {"cost": 0}

    def _chat_openai(self, messages, model, tools, max_tokens, reasoning_effort):
        client = self._get_openai_client()
        if not client:
            return {"role": "assistant", "content": "⚠️ Error: OPENAI_API_KEY not found."}, {}
            
        try:
            openai_model_id = model.replace("openai/", "")
            kwargs = {"model": openai_model_id, "messages": messages, "max_tokens": max_tokens}
            if tools:
                kwargs["tools"] = tools
                
            resp = client.chat.completions.create(**kwargs)
            resp_dict = resp.model_dump()
            usage = resp_dict.get("usage") or {}
            msg = (resp_dict.get("choices") or [{}])[0].get("message") or {}
            return msg, usage
        except Exception as e:
            print(f"[LLM] OpenAI Error: {e}", file=sys.stderr)
            return {"role": "assistant", "content": f"⚠️ OpenAI API Error: {repr(e)}"}, {"cost": 0}

    def vision_query(
        self,
        prompt: str,
        images: List[Dict[str, Any]],
        model: str = "gemini-1.5-pro",
        max_tokens: int = 1024,
        reasoning_effort: str = "low",
    ) -> Tuple[str, Dict[str, Any]]:
        if model.startswith(("google/", "gemini-")) or "gemini" in model.lower():
            import google.generativeai as genai
            try:
                genai.configure(api_key=self._google_key)
                gemini_model_id = model.replace("google/", "")
                parts = [prompt]
                for img in images:
                    if "url" in img:
                        import requests
                        from PIL import Image
                        from io import BytesIO
                        resp = requests.get(img["url"])
                        parts.append(Image.open(BytesIO(resp.content)))
                    elif "base64" in img:
                        import base64
                        from PIL import Image
                        from io import BytesIO
                        img_data = base64.b64decode(img["base64"])
                        parts.append(Image.open(BytesIO(img_data)))
                
                gen_model = genai.GenerativeModel(model_name=gemini_model_id)
                response = gen_model.generate_content(parts)
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count,
                    "completion_tokens": response.usage_metadata.candidates_token_count,
                    "total_tokens": response.usage_metadata.total_token_count,
                    "cost": 0.0
                }
                return response.text, usage
            except Exception as e:
                return f"⚠️ Vision Error (Gemini): {repr(e)}", {"cost": 0}

        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
        for img in images:
            if "url" in img:
                messages[0]["content"].append({"type": "image_url", "image_url": {"url": img["url"]}})
            elif "base64" in img:
                mime = img.get("mime", "image/png")
                messages[0]["content"].append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img['base64']}"}})
        
        response_msg, usage = self.chat(messages, model, max_tokens=max_tokens)
        return response_msg.get("content") or "", usage

    def default_model(self) -> str:
        return os.environ.get("OUROBOROS_MODEL", "gemini-2.5-pro")

    def available_models(self) -> List[str]:
        main = os.environ.get("OUROBOROS_MODEL", "gemini-2.5-pro")
        code = os.environ.get("OUROBOROS_MODEL_CODE", "Qwen3-Coder-Plus")
        light = os.environ.get("OUROBOROS_MODEL_LIGHT", "gemini-3-flash")
        models = [main, code, light]
        return list(set(models))
