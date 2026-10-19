"""The one place that talks to an LLM outside the live call, so evals and post-call run on either provider.

- LLM_PROVIDER=anthropic: the Anthropic SDK with ANTHROPIC_API_KEY.
- LLM_PROVIDER=emergent: the Emergent universal key (EMERGENT_LLM_KEY), sent exactly the way Emergent-built apps
  send it through `emergentintegrations` (repo emergentbase/emergent_integrations, llm/chat.py): OpenAI chat format
  to {INTEGRATION_PROXY_URL}/llm with the bare model name. We call that endpoint with the OpenAI client rather than
  importing emergentintegrations, because the library pins openai==1.99.9 and LiveKit needs openai>=3.
  The proxy only accepts traffic from Emergent's own servers (Cloud Armor allowlist), so this mode must run on
  Emergent infrastructure; from a laptop it returns 403.

Tools are written once in Anthropic's shape ({name, description, input_schema}) and converted when needed.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .config import settings

M = TypeVar("M", bound=BaseModel)
EMERGENT_PROXY = "https://integrations.emergentagent.com"


@dataclass
class ToolUse:
    id: str
    name: str
    input: dict


def provider() -> str:
    return settings().llm_provider


def proxy_url() -> str:
    """Same lookup as emergentintegrations.llm.utils.get_integration_proxy_url."""
    return os.environ.get("INTEGRATION_PROXY_URL") or os.environ.get("integration_proxy_url") or EMERGENT_PROXY


def _emergent_client():
    """OpenAI-format client for the configured gateway: internal LiteLLM (direct) or the Emergent proxy/relay."""
    from openai import AsyncOpenAI
    s = settings()
    if s.llm_provider == "litellm":
        return AsyncOpenAI(base_url=s.litellm_base_url, api_key=s.litellm_api_key)
    return AsyncOpenAI(base_url=proxy_url() + "/llm", api_key=s.emergent_llm_key)


def _openai_format() -> bool:
    return settings().llm_provider in ("emergent", "litellm")


def _openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}} for t in tools]


class ToolChat:
    """One multi-turn conversation in which the model may call tools."""

    def __init__(self, system: str, tools: list[dict], *, model: str | None = None, max_tokens: int = 1000,
                 effort: str | None = None):
        s = settings()
        self.model = model or s.llm_model
        self.max_tokens = max_tokens
        self.emergent = _openai_format()
        if self.emergent:
            self._client = _emergent_client()
            self._tools = _openai_tools(tools)
            self._messages: list[dict] = [{"role": "system", "content": system}]
        else:
            import anthropic
            self._client = anthropic.AsyncAnthropic()
            self._system, self._tools, self._messages = system, tools, []
            self._extra = {"output_config": {"effort": effort}} if effort else {}

    def seed(self, messages: list[dict]) -> None:
        """Start the history with plain {"role", "content": str} turns, e.g. the fixed opener already spoken."""
        self._messages.extend(messages)

    async def send(self, user_text: str | None = None,
                   tool_results: list[tuple[str, str]] | None = None) -> tuple[str, list[ToolUse]]:
        """Send the person's words and/or the results of the last tool calls. Returns (spoken text, tool calls)."""
        if self.emergent:
            for call_id, content in tool_results or []:
                self._messages.append({"role": "tool", "tool_call_id": call_id, "content": content})
            if user_text:
                self._messages.append({"role": "user", "content": user_text})
            resp = await self._client.chat.completions.create(model=self.model, max_tokens=self.max_tokens,
                                                              messages=self._messages, tools=self._tools)
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            entry: dict = {"role": "assistant", "content": msg.content}
            if calls:
                entry["tool_calls"] = [{"id": c.id, "type": "function",
                                        "function": {"name": c.function.name, "arguments": c.function.arguments}}
                                       for c in calls]
            self._messages.append(entry)
            uses = []
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                uses.append(ToolUse(c.id, c.function.name, args))
            return (msg.content or "").strip(), uses
        if tool_results:
            self._messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": i, "content": c} for i, c in tool_results]})
        if user_text:
            if tool_results:
                self._messages[-1]["content"].append({"type": "text", "text": user_text})
            else:
                self._messages.append({"role": "user", "content": user_text})
        resp = await self._client.messages.create(model=self.model, max_tokens=self.max_tokens, system=self._system,
                                                  tools=self._tools, messages=self._messages, **self._extra)
        self._messages.append({"role": "assistant", "content": resp.content})
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text, [ToolUse(b.id, b.name, b.input) for b in resp.content if b.type == "tool_use"]


async def complete(system: str, messages: list[dict], *, model: str | None = None, max_tokens: int = 300) -> str:
    """Plain text reply to a short history of {"role", "content": str} messages ending with a user turn."""
    s = settings()
    model = model or s.summary_model
    if _openai_format():
        resp = await _emergent_client().chat.completions.create(
            model=model, max_tokens=max_tokens, messages=[{"role": "system", "content": system}, *messages])
        return (resp.choices[0].message.content or "").strip()
    import anthropic
    resp = await anthropic.AsyncAnthropic().messages.create(model=model, max_tokens=max_tokens, system=system,
                                                            messages=messages)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def _json_object(text: str) -> str:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end != -1 else text


async def structured(system: str, user_text: str, output: type[M], *, model: str | None = None,
                     max_tokens: int = 4000) -> M:
    """Extract a pydantic object. Anthropic: native structured output. Emergent proxy: JSON by instruction."""
    s = settings()
    model = model or s.summary_model
    if not _openai_format():
        import anthropic
        resp = await anthropic.AsyncAnthropic().messages.parse(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user_text}], output_format=output)
        return resp.parsed_output
    schema = json.dumps(output.model_json_schema(), ensure_ascii=False)
    sys_json = (f"{system}\n\nReply with only one JSON object that matches this JSON schema, "
                f"no prose and no code fences:\n{schema}")
    last_error: Exception | None = None
    for _ in range(2):
        text = await complete(sys_json, [{"role": "user", "content": user_text}], model=model, max_tokens=max_tokens)
        try:
            return output.model_validate_json(_json_object(text))
        except ValidationError as e:
            last_error = e
    raise last_error
