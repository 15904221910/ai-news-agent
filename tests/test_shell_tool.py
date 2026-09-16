"""bash 工具：白名单 / 危险模式 / Windows 别名（§16.2）。"""
from __future__ import annotations

import os

import pytest

from server.agent.tools import shell_tool
from server.agent.tools.registry import SecurityError


def test_deny_rm(run_ctx):
    with pytest.raises(SecurityError):
        shell_tool.bash({"command": "rm -rf workspace"}, run_ctx)


@pytest.mark.parametrize(
    "command",
    [
        "whoami",            # 不在白名单
        "cat a | b",         # 管道
        "ls a; rm b",        # 分号串联 + rm
        "echo a && del b",   # && 串联 + del
        "cat a > out.txt",   # 重定向
        "echo `whoami`",     # 命令替换
        "wget http://x",     # 下载
    ],
)
def test_deny_patterns(run_ctx, command):
    with pytest.raises(SecurityError):
        shell_tool.bash({"command": command}, run_ctx)


def test_deny_empty_command(run_ctx):
    with pytest.raises(ValueError):
        shell_tool.bash({"command": "   "}, run_ctx)


def test_allow_echo(run_ctx):
    result = shell_tool.bash({"command": "echo hello"}, run_ctx)
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


def test_allow_python_version(run_ctx):
    result = shell_tool.bash({"command": "python --version"}, run_ctx)
    assert result["exit_code"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows 专属命令翻译")
def test_windows_alias_translation(run_ctx):
    assert shell_tool._translate_for_windows("ls") == "dir /b"
    assert shell_tool._translate_for_windows("ls briefs") == "dir /b briefs"
    assert shell_tool._translate_for_windows("echo hi") == "echo hi"
    result = shell_tool.bash({"command": "ls"}, run_ctx)  # 白名单命令在 Windows 可执行
    assert result["exit_code"] == 0
