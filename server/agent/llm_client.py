"""LLM 客户端：OpenAI 兼容封装（重试、超时、tool_calls 解析）。

内部消息格式（全程 JSON 可序列化）：
- assistant: {"role": "assistant", "content": str|None, "tool_calls": [{"id","name","arguments"(dict)}]}
- tool:      {"role": "tool", "tool_call_id": str, "content": str}
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from openai import OpenAI

from server.config import Settings
from server.errors import LLMFailedAppError

logger = logging.getLogger(__name__)

RETRY_TIMES = 2  # 失败后重试次数（总计 1 + 2 次尝试，退避 1s / 2s）


@dataclass
class ToolCallRequest:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """内部消息 → OpenAI 消息（tool_calls 的 arguments 转字符串）。"""
    converted: list[dict] = []
    for message in messages:
        if message.get("role") == "assistant" and message.get("tool_calls"):
            converted.append({
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in message["tool_calls"]
                ],
            })
        else:
            converted.append(message)
    return converted


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = OpenAI(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key or "EMPTY",
            timeout=settings.llm_timeout,
        )

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        last_error: Exception | None = None
        for attempt in range(RETRY_TIMES + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=_to_openai_messages(messages),
                    tools=tools or None,
                    temperature=(
                        self.settings.llm_temperature if temperature is None else temperature
                    ),
                    max_tokens=self.settings.llm_max_tokens if max_tokens is None else max_tokens,
                )
                return self._parse(response)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("LLM 调用失败（第 %s 次）: %s", attempt + 1, exc)
                if attempt < RETRY_TIMES:
                    time.sleep(2 ** attempt)
        raise LLMFailedAppError(f"LLM 调用失败（重试 {RETRY_TIMES} 次后仍失败）: {last_error}")

    @staticmethod
    def _parse(response) -> LLMResponse:
        message = response.choices[0].message
        tool_calls: list[ToolCallRequest] = []
        for tc in message.tool_calls or []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
                if not isinstance(arguments, dict):
                    arguments = {}
            except (json.JSONDecodeError, TypeError):
                arguments = {}  # 交由 Schema 校验给出错误反馈，让模型纠正
            tool_calls.append(ToolCallRequest(id=tc.id, name=tc.function.name, arguments=arguments))
        return LLMResponse(content=message.content, tool_calls=tool_calls)
