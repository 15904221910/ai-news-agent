"""工具注册表 + 统一执行管线（校验/安全/超时/截断/错误包装）。

执行管线（§9.3）：查注册表 → Schema 校验 → 安全校验（处理器内抛 SecurityError）
→ 执行+超时 → 截断 → 异常包装为结构化错误。任何失败都不抛出，返回给 LLM 自纠。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import jsonschema

logger = logging.getLogger(__name__)

TOOL_TIMEOUT_SECONDS = 10
MAX_RESULT_CHARS = 4000


class SecurityError(Exception):
    """工具安全校验不通过（沙箱逃逸 / 命令被拒），管线映射为 SECURITY_DENIED。"""


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[[dict, Any], Any]  # (args, ctx) -> 任意可 JSON 序列化值


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(self, name: str, description: str, parameters: dict, handler: Callable) -> None:
        self._tools[name] = ToolDef(name, description, parameters, handler)

    def schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def tool_names(self) -> list[str]:
        return list(self._tools)

    def execute(self, name: str, args: dict, ctx) -> str:
        text, _ = self.execute_detail(name, args, ctx)
        return text

    def execute_detail(self, name: str, args: dict, ctx) -> tuple[str, bool]:
        """执行工具，返回 (结果文本, 是否错误)。"""
        tool = self._tools.get(name)
        if tool is None:
            return self._error("UNKNOWN_TOOL", f"未知工具: {name}；可用工具: {self.tool_names()}"), True

        try:
            jsonschema.validate(instance=args or {}, schema=tool.parameters)
        except jsonschema.ValidationError as exc:
            return self._error("VALIDATION_ERROR", f"参数校验失败: {exc.message}"), True

        box: dict = {}

        def _run() -> None:
            try:
                box["value"] = tool.handler(args or {}, ctx)
            except SecurityError as exc:
                box["security"] = str(exc)
            except Exception as exc:  # noqa: BLE001
                box["error"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=_run, daemon=True)
        worker.start()
        worker.join(timeout=TOOL_TIMEOUT_SECONDS)

        if worker.is_alive():
            return self._error("TOOL_TIMEOUT", f"工具 {name} 执行超时(>{TOOL_TIMEOUT_SECONDS}s)"), True
        if "security" in box:
            logger.warning("安全拦截", extra={"tool": name, "error": box["security"]})
            return self._error("SECURITY_DENIED", box["security"]), True
        if "error" in box:
            return self._error("TOOL_ERROR", box["error"]), True
        return self._stringify(box.get("value")), False

    @staticmethod
    def _stringify(value) -> str:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + f"…(truncated, total {len(text)} chars)"
        return text

    @staticmethod
    def _error(code: str, message: str) -> str:
        return json.dumps({"error": {"code": code, "message": message}}, ensure_ascii=False)


def is_error_result(text: str) -> bool:
    """辅助：判断工具结果文本是否为结构化错误。"""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(data, dict) and "error" in data
