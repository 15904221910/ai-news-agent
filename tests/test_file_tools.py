"""文件工具：沙箱边界 / 读写 / 搜索（§16.2）。"""
from __future__ import annotations

import pytest

from server.agent.tools import file_tools
from server.agent.tools.registry import SecurityError


def test_write_read_roundtrip(run_ctx):
    file_tools.write_file({"path": "notes/a.md", "content": "hello 沙箱"}, run_ctx)
    result = file_tools.read_file({"path": "notes/a.md"}, run_ctx)
    assert result["content"] == "hello 沙箱"
    assert result["truncated"] is False
    assert result["total_chars"] == len("hello 沙箱")


def test_read_truncation(run_ctx):
    file_tools.write_file({"path": "big.txt", "content": "x" * 100}, run_ctx)
    result = file_tools.read_file({"path": "big.txt", "max_chars": 10}, run_ctx)
    assert len(result["content"]) == 10
    assert result["truncated"] is True


def test_sandbox_escape_denied(run_ctx):
    with pytest.raises(SecurityError):
        file_tools.read_file({"path": "../.env"}, run_ctx)


def test_absolute_path_escape_denied(run_ctx):
    with pytest.raises(SecurityError):
        file_tools.write_file({"path": "/etc/evil.txt", "content": "x"}, run_ctx)
    with pytest.raises(SecurityError):
        file_tools.read_file({"path": "sub/../../outside.txt"}, run_ctx)


def test_list_dir(run_ctx):
    file_tools.write_file({"path": "briefs/a.md", "content": "a"}, run_ctx)
    result = file_tools.list_dir({"path": "."}, run_ctx)
    names = [entry["name"] for entry in result["entries"]]
    assert "briefs" in names


def test_search_content(run_ctx):
    file_tools.write_file({"path": "a.txt", "content": "第一行\nAI 新闻摘要\n第三行"}, run_ctx)
    file_tools.write_file({"path": "b.txt", "content": "无关内容"}, run_ctx)
    result = file_tools.search_content({"keyword": "ai"}, run_ctx)  # 大小写不敏感
    assert result["total"] == 1
    assert result["hits"][0]["file"] == "a.txt"
    assert result["hits"][0]["line"] == 2


def test_read_missing_file_raises(run_ctx):
    with pytest.raises(FileNotFoundError):
        file_tools.read_file({"path": "nope.txt"}, run_ctx)


def test_list_missing_dir_raises(run_ctx):
    with pytest.raises(FileNotFoundError):
        file_tools.list_dir({"path": "no_such_dir"}, run_ctx)
