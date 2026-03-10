"""
Multi-LLM provider abstraction — exact port of src/chat/llm.provider.ts.
Supports Claude (Anthropic), OpenAI, Groq, and Grok (xAI).
All providers normalise to Anthropic-style rawContent for the agent loop.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import LLMProviderEnum, get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    raw_content: list[Any]
    stop_reason: str


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...

    def is_tool_use(self, response: LLMResponse) -> bool:
        return response.stop_reason == "tool_use"

    def extract_tool_calls(self, response: LLMResponse) -> list[dict[str, Any]]:
        return [
            {"id": b["id"], "name": b["name"], "input": b["input"]}
            for b in response.raw_content
            if isinstance(b, dict) and b.get("type") == "tool_use"
        ]

    def build_tool_result_message(self, tool_results: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]}
                for r in tool_results
            ],
        }


# ─────────────────────────────────────────────────────────
# Claude Provider (Anthropic)
# ─────────────────────────────────────────────────────────


class ClaudeProvider(LLMProvider):
    def __init__(self) -> None:
        import anthropic

        settings = get_settings()
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        response = await self._client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            tools=tools,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        )
        text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        raw_content: list[Any] = []
        for block in response.content:
            if block.type == "text":
                raw_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                raw_content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
        return LLMResponse(
            text=text,
            raw_content=raw_content,
            stop_reason=response.stop_reason or "end_turn",
        )


# ─────────────────────────────────────────────────────────
# OpenAI Provider
# ─────────────────────────────────────────────────────────


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        import openai

        settings = get_settings()
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]], system_prompt: str
    ) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for msg in messages:
            if msg["role"] == "user" and isinstance(msg.get("content"), list):
                for r in msg["content"]:
                    if isinstance(r, dict) and r.get("type") == "tool_result":
                        converted.append(
                            {"role": "tool", "tool_call_id": r["tool_use_id"], "content": r["content"]}
                        )
            elif msg["role"] == "assistant" and isinstance(msg.get("content"), list):
                blocks = msg["content"]
                text_parts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
                tool_calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                    }
                    for b in blocks
                    if isinstance(b, dict) and b.get("type") == "tool_use"
                ]
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                converted.append(assistant_msg)
            else:
                converted.append({"role": msg["role"], "content": msg["content"]})
        return converted

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        openai_messages = self._convert_messages(messages, system_prompt)
        openai_tools = self._convert_tools(tools)
        response = await self._client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=openai_messages,  # type: ignore[arg-type]
            tools=openai_tools,  # type: ignore[arg-type]
            tool_choice="auto",
            max_tokens=2048,
        )
        choice = response.choices[0]
        message = choice.message
        raw_content: list[Any] = []
        if message.content:
            raw_content.append({"type": "text", "text": message.content})
        if message.tool_calls:
            for tc in message.tool_calls:
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments),
                    }
                )
        stop_reason = "tool_use" if message.tool_calls else "end_turn"
        return LLMResponse(text=message.content or "", raw_content=raw_content, stop_reason=stop_reason)


# ─────────────────────────────────────────────────────────
# Groq Provider
# ─────────────────────────────────────────────────────────


class GroqProvider(LLMProvider):
    def __init__(self) -> None:
        import groq

        settings = get_settings()
        self._client = groq.AsyncGroq(api_key=settings.groq_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        groq_messages = OpenAIProvider._convert_messages(messages, system_prompt)
        groq_tools = OpenAIProvider._convert_tools(tools)
        response = await self._client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=groq_messages,  # type: ignore[arg-type]
            tools=groq_tools,  # type: ignore[arg-type]
            tool_choice="auto",
            max_tokens=2048,
        )
        choice = response.choices[0]
        message = choice.message
        raw_content: list[Any] = []
        if message.content:
            raw_content.append({"type": "text", "text": message.content})
        if message.tool_calls:
            for tc in message.tool_calls:
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.function.name,
                        "input": json.loads(tc.function.arguments),
                    }
                )
        stop_reason = "tool_use" if message.tool_calls else "end_turn"
        return LLMResponse(text=message.content or "", raw_content=raw_content, stop_reason=stop_reason)


# ─────────────────────────────────────────────────────────
# Grok Provider (xAI via Groq-compatible API)
# ─────────────────────────────────────────────────────────


class GrokProvider(LLMProvider):
    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.grok_api_key
        self._http = httpx.AsyncClient(timeout=30.0)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10), reraise=True)
    async def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        openai_messages = OpenAIProvider._convert_messages(messages, system_prompt)
        openai_tools = OpenAIProvider._convert_tools(tools)
        # Add additionalProperties: false for Grok compatibility
        for t in openai_tools:
            params = t["function"]["parameters"]
            if params.get("type") == "object" and "additionalProperties" not in params:
                params["additionalProperties"] = False

        resp = await self._http.post(
            f"{self.BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "meta-llama/llama-4-scout-17b-16e-instruct",
                "messages": openai_messages,
                "tools": openai_tools,
                "tool_choice": "auto",
                "max_completion_tokens": 2048,
                "parallel_tool_calls": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        choice = data["choices"][0]
        message = choice["message"]

        raw_content: list[Any] = []
        if message.get("content"):
            raw_content.append({"type": "text", "text": message["content"]})
        if message.get("tool_calls"):
            for tc in message["tool_calls"]:
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": json.loads(tc["function"]["arguments"]),
                    }
                )
        stop_reason = "tool_use" if message.get("tool_calls") else "end_turn"
        return LLMResponse(text=message.get("content") or "", raw_content=raw_content, stop_reason=stop_reason)


# ─────────────────────────────────────────────────────────
# Factory — Returns the right provider based on .env
# ─────────────────────────────────────────────────────────


def create_llm_provider() -> LLMProvider:
    settings = get_settings()
    match settings.llm_provider:
        case LLMProviderEnum.claude:
            return ClaudeProvider()
        case LLMProviderEnum.openai:
            return OpenAIProvider()
        case LLMProviderEnum.groq:
            return GroqProvider()
        case LLMProviderEnum.grok:
            return GrokProvider()
        case _:
            logger.warning("[LLMProvider] Unknown provider '%s', defaulting to Claude", settings.llm_provider)
            return ClaudeProvider()
