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
        self._google_gen_model = None
        
        log.info(f"LLMClient initialized. Keys: iFlow={'SET' if self._iflow_key else 'MISSING'}, Google={'SET' if self._google_key else 'MISSING'}, OpenAI={'SET' if self._openai_key else 'MISSING'}")

    def _get_iflow_client(self):
        if self._iflow_client is None and self._iflow_key:
            from openai import OpenAI
            self._iflow_client = OpenAI(
                base_url=self._base_url if hasattr(self, '_base_url') else self._iflow_base_url,
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
        
        log.info(f"LLM Routing: model='{model}', tools={len(tools) if tools else 0}")
        
        # 1. Route to Google Gemini
        if (model.startswith(("google/", "gemini-")) or "gemini" in model.lower()) and self._google_key:
            log.info("Routing to Google Gemini API")
            return self._chat_gemini(messages, model, tools, max_tokens)
        
        # 2. Route to OpenAI
        if (model.startswith(("openai/", "gpt-", "o1-", "o3-")) or "gpt" in model.lower()) and self._openai_key:
            log.info("Routing to OpenAI API")
            return self._chat_openai(messages, model, tools, max_tokens, reasoning_effort)

        # 3. Default to iFlow (FlowAI)
        log.info("Routing to iFlow (FlowAI) API")
        return self._chat_iflow(messages, model, tools, max_tokens, reasoning_effort, tool_choice)

    def _strip_defaults(self, obj: Any) -> Any:
        """Recursively remove 'default' fields from JSON schema for Gemini compatibility."""
        if isinstance(obj, dict):
            return {k: self._strip_defaults(v) for k, v in obj.items() if k != 'default'}
        elif isinstance(obj, list):
            return [self._strip_defaults(i) for i in obj]
        return obj

    def _chat_gemini(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        max_tokens: int = 8192
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        import google.generativeai as genai
        from google.generativeai.types import content_types
        
        try:
            genai.configure(api_key=self._google_key)
            
            # Remove 'google/' prefix if present
            gemini_model_id = model.replace("google/", "")
            log.info(f"Gemini call: model='{gemini_model_id}'")
            
            # Format messages for Gemini
            gemini_history = []
            system_instruction = None
            
            for m in messages:
                role = m["role"]
                content = m["content"]
                if role == "system":
                    system_instruction = content
                elif role == "user":
                    gemini_history.append({"role": "user", "parts": [content]})
                elif role == "assistant":
                    if m.get("tool_calls"):
                        parts = [{"text": content or ""}]
                        for tc in m["tool_calls"]:
                            parts.append({
                                "function_call": {
                                    "name": tc["function"]["name"],
                                    "args": json.loads(tc["function"]["arguments"])
                                }
                            })
                        gemini_history.append({"role": "model", "parts": parts})
                    else:
                        gemini_history.append({"role": "model", "parts": [content or ""]})
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

            # Set up tools for Gemini (strip 'default' field as Google doesn't support it)
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
                return {"role": "assistant", "content": "⚠️ Gemini Error: Empty message history"}, {"cost": 0}

            last_msg = gemini_history.pop()
            
            chat = gen_model.start_chat(history=gemini_history)
            response = chat.send_message(last_msg["parts"], generation_config={"max_output_tokens": max_tokens})
            
            # Robust extraction of content and tool calls
            if not response.candidates:
                log.error("Gemini Error: No candidates in response")
                return {"role": "assistant", "content": f"⚠️ Gemini Error: No response candidates. Safety filter or block?"}, {"cost": 0}

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
            
            log.info(f"Gemini response: content_len={len(res_content)}, tool_calls={len(tool_calls)}")
            return res_msg, usage
            
        except Exception as e:
            err_str = str(e)
            if "ResourceExhausted" in err_str or "429" in err_str:
                # Attempt to parse "Please retry in X.Xs"
                import re
                wait_time = 10.0 # Default
                match = re.search(r"retry in ([\d.]+)s", err_str)
                if match:
                    wait_time = float(match.group(1)) + 1.0 # Add buffer
                
                log.warning(f"Gemini Quota Exceeded. Sleeping {wait_time}s and retrying...")
                time.sleep(wait_time)
                # Retry once
                return self._chat_gemini(messages, model, tools, max_tokens)

            tb = traceback.format_exc()
            log.error(f"Gemini API Error: {e}\n{tb}")
            return {"role": "assistant", "content": f"⚠️ Gemini API Error: {repr(e)}"}, {"cost": 0}


    def _chat_iflow(self, messages, model, tools, max_tokens, reasoning_effort, tool_choice):
        client = self._get_iflow_client()
        if not client:
            return {"role": "assistant", "content": "⚠️ Error: IFLOW_API_KEY not found."}, {}
            
        try:
            effort = normalize_reasoning_effort(reasoning_effort)
            kwargs = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice

            resp = client.chat.completions.create(**kwargs)
            resp_dict = resp.model_dump()
            usage = resp_dict.get("usage") or {}
            choices = resp_dict.get("choices") or [{}]
            msg = (choices[0] if choices else {}).get("message") or {}
            
            # Cost estimate if missing
            if not usage.get("cost"):
                # Simple estimate for Qwen3 Coder Plus
                in_p = 0.5 / 1_000_000
                out_p = 1.5 / 1_000_000
                usage["cost"] = (usage.get("prompt_tokens", 0) * in_p) + (usage.get("completion_tokens", 0) * out_p)

            return msg, usage
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"iFlow API Error: {e}\n{tb}")
            return {"role": "assistant", "content": f"⚠️ iFlow API Error: {repr(e)}"}, {"cost": 0}

    def _chat_openai(self, messages, model, tools, max_tokens, reasoning_effort):
        client = self._get_openai_client()
        if not client:
            return {"role": "assistant", "content": "⚠️ Error: OPENAI_API_KEY not found."}, {}
            
        try:
            # Remove 'openai/' prefix if present
            openai_model_id = model.replace("openai/", "")
            log.info(f"OpenAI call: model='{openai_model_id}'")
            
            kwargs = {
                "model": openai_model_id,
                "messages": messages,
                "max_tokens": max_tokens,
            }
            if tools:
                kwargs["tools"] = tools
                
            resp = client.chat.completions.create(**kwargs)
            resp_dict = resp.model_dump()
            usage = resp_dict.get("usage") or {}
            choices = resp_dict.get("choices") or [{}]
            msg = (choices[0] if choices else {}).get("message") or {}
            
            log.info(f"OpenAI response: content_len={len(msg.get('content') or '')}, tool_calls={len(msg.get('tool_calls') or [])}")
            return msg, usage
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"OpenAI API Error: {e}\n{tb}")
            return {"role": "assistant", "content": f"⚠️ OpenAI API Error: {repr(e)}"}, {"cost": 0}

    def vision_query(
        self,
        prompt: str,
        images: List[Dict[str, Any]],
        model: str = "google/gemini-2.0-pro-exp-02-05", # Default to Gemini for vision
        max_tokens: int = 1024,
        reasoning_effort: str = "low",
    ) -> Tuple[str, Dict[str, Any]]:
        # If it's Gemini, use native vision support
        if model.startswith(("google/", "gemini-")):
            import google.generativeai as genai
            try:
                genai.configure(api_key=self._google_key)
                gemini_model_id = model.replace("google/", "")
                
                parts = [prompt]
                for img in images:
                    if "url" in img:
                        # In Gemini, URLs need to be downloaded or passed as file refs
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

        # Fallback to OpenAI vision (if iFlow supports it)
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
        return os.environ.get("OUROBOROS_MODEL", "google/gemini-1.5-pro")

    def available_models(self) -> List[str]:
        main = os.environ.get("OUROBOROS_MODEL", "google/gemini-1.5-pro")
        code = os.environ.get("OUROBOROS_MODEL_CODE", "Qwen3-Coder-Plus")
        light = os.environ.get("OUROBOROS_MODEL_LIGHT", "google/gemini-1.5-flash")
        models = [main, code, light]
        return list(set(models))
