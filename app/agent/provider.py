"""
Multi-LLM provider abstraction — exact port of src/chat/llm.provider.ts.
Supports Claude (Anthropic), OpenAI, Groq, and Grok (xAI).
All providers normalise to Anthropic-style rawContent for the agent loop.
Streaming support added for real-time token delivery via SSE.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import LLMProviderEnum, get_settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    text: str
    raw_content: list[Any]
    stop_reason: str


@dataclass
class StreamEvent:
    """A single event from a streaming LLM response."""
    type: str  # "token", "tool_use_start", "tool_use_delta", "tool_use_end", "done"
    content: str = ""
    tool_call: dict[str, Any] | None = None


@dataclass
class StreamResult:
    """Accumulated result after streaming completes."""
    text: str = ""
    raw_content: list[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamEvent]:
        """Stream LLM response token by token. Default falls back to non-streaming."""
        response = await self.chat(messages, system_prompt, tools)
        if response.text:
            yield StreamEvent(type="token", content=response.text)
        for block in response.raw_content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield StreamEvent(type="tool_use_end", tool_call=block)
        yield StreamEvent(type="done")

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

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamEvent]:
        """Stream Claude response — yields tokens in real-time."""
        async with self._client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            tools=tools,  # type: ignore[arg-type]
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            current_tool: dict[str, Any] | None = None
            tool_json_parts: list[str] = []

            async for event in stream:
                # Text tokens — stream immediately
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield StreamEvent(type="token", content=event.delta.text)
                    elif hasattr(event.delta, "partial_json"):
                        tool_json_parts.append(event.delta.partial_json)

                # New content block starting
                elif event.type == "content_block_start":
                    if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                        current_tool = {
                            "type": "tool_use",
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input": {},
                        }
                        tool_json_parts = []
                        yield StreamEvent(
                            type="tool_use_start",
                            content=event.content_block.name,
                        )

                # Content block finished
                elif event.type == "content_block_stop":
                    if current_tool is not None:
                        try:
                            current_tool["input"] = json.loads("".join(tool_json_parts)) if tool_json_parts else {}
                        except json.JSONDecodeError:
                            current_tool["input"] = {}
                        yield StreamEvent(type="tool_use_end", tool_call=current_tool)
                        current_tool = None
                        tool_json_parts = []

            # Get the final message for stop_reason
            final_message = await stream.get_final_message()
            stop_reason = final_message.stop_reason or "end_turn"

        yield StreamEvent(type="done", content=stop_reason)


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

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamEvent]:
        """Stream OpenAI response token by token."""
        openai_messages = self._convert_messages(messages, system_prompt)
        openai_tools = self._convert_tools(tools)
        stream = await self._client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=openai_messages,  # type: ignore[arg-type]
            tools=openai_tools,  # type: ignore[arg-type]
            tool_choice="auto",
            max_tokens=2048,
            stream=True,
        )

        tool_calls_acc: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            # Text content
            if delta.content:
                yield StreamEvent(type="token", content=delta.content)

            # Tool calls accumulation
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function and tc_delta.function.name else "",
                            "arguments": "",
                        }
                        if tool_calls_acc[idx]["name"]:
                            yield StreamEvent(type="tool_use_start", content=tool_calls_acc[idx]["name"])
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

            # Check finish reason
            finish = chunk.choices[0].finish_reason if chunk.choices else None
            if finish:
                break

        # Emit accumulated tool calls
        for tc_data in tool_calls_acc.values():
            try:
                inp = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
            except json.JSONDecodeError:
                inp = {}
            yield StreamEvent(
                type="tool_use_end",
                tool_call={
                    "type": "tool_use",
                    "id": tc_data["id"],
                    "name": tc_data["name"],
                    "input": inp,
                },
            )

        stop = "tool_use" if tool_calls_acc else "end_turn"
        yield StreamEvent(type="done", content=stop)


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

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamEvent]:
        """Stream Groq response token by token (same format as OpenAI)."""
        groq_messages = OpenAIProvider._convert_messages(messages, system_prompt)
        groq_tools = OpenAIProvider._convert_tools(tools)
        stream = await self._client.chat.completions.create(
            model="llama-3.1-70b-versatile",
            messages=groq_messages,  # type: ignore[arg-type]
            tools=groq_tools,  # type: ignore[arg-type]
            tool_choice="auto",
            max_tokens=2048,
            stream=True,
        )

        tool_calls_acc: dict[int, dict[str, Any]] = {}

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue
            if delta.content:
                yield StreamEvent(type="token", content=delta.content)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": tc_delta.id or "", "name": "", "arguments": ""}
                        if tc_delta.function and tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                            yield StreamEvent(type="tool_use_start", content=tc_delta.function.name)
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments
            finish = chunk.choices[0].finish_reason if chunk.choices else None
            if finish:
                break

        for tc_data in tool_calls_acc.values():
            try:
                inp = json.loads(tc_data["arguments"]) if tc_data["arguments"] else {}
            except json.JSONDecodeError:
                inp = {}
            yield StreamEvent(
                type="tool_use_end",
                tool_call={"type": "tool_use", "id": tc_data["id"], "name": tc_data["name"], "input": inp},
            )

        stop = "tool_use" if tool_calls_acc else "end_turn"
        yield StreamEvent(type="done", content=stop)


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
