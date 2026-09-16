"""bash 工具：白名单 + 危险模式双重拦截（§9.8）。"""
from __future__ import annotations

import os
import re
import subprocess

from server.agent.tools.registry import SecurityError

ALLOWED_PREFIXES = ("date", "ls", "pwd", "cat", "echo", "wc", "python --version")
DENY_PATTERNS = [
    r"\brm\b", r"\bmkfs\b", r"\bdd\b", r"\bsudo\b", r"\bshutdown\b",
    r"\bdel\b", r"\bformat\b", r"[>|]", r"\bcurl\b", r"\bwget\b",
    r"&", r";", r"\$\(", r"`",   # 拼接/命令替换/反引号串联一律拒绝
]
MAX_OUTPUT_CHARS = 2000
COMMAND_TIMEOUT_SECONDS = 8

# Windows 无 Unix 命令：白名单校验通过后，执行前做最小等价翻译（仅精确匹配命令头）
_WINDOWS_ALIASES = {
    "ls": "dir /b",
    "pwd": "cd",
    "cat": "type",
    "date": "date /t",
}


def _translate_for_windows(command: str) -> str:
    """ls/cat/pwd/date 在 Windows 上映射为 cmd 等价命令；其余原样执行。"""
    if os.name != "nt":
        return command
    head, _, rest = command.partition(" ")
    alias = _WINDOWS_ALIASES.get(head)
    if alias is None:
        return command
    return alias + ((" " + rest) if rest else "")


def bash(args: dict, ctx) -> dict:
    command = (args.get("command") or "").strip()
    if not command:
        raise ValueError("命令为空")

    # 第一层：白名单前缀
    if not any(command == prefix or command.startswith(prefix + " ") for prefix in ALLOWED_PREFIXES):
        raise SecurityError(f"命令不在白名单内: {command}")

    # 第二层：危险模式（重定向、管道、删除、下载等一律拒绝）
    for pattern in DENY_PATTERNS:
        if re.search(pattern, command):
            raise SecurityError(f"命令命中危险模式({pattern}): {command}")

    os.makedirs(ctx.workspace_root, exist_ok=True)  # 沙箱根目录可能尚未创建
    proc = subprocess.run(
        _translate_for_windows(command),
        shell=True,
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        cwd=str(ctx.workspace_root),
    )
    return {
        "stdout": proc.stdout[:MAX_OUTPUT_CHARS],
        "stderr": proc.stderr[:MAX_OUTPUT_CHARS],
        "exit_code": proc.returncode,
    }
