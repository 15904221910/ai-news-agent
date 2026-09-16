"""简报服务单测：正文前言剥离（模型偶尔在简报前输出"以下是全文"等元话语）。"""
from __future__ import annotations

from server.briefs.service import extract_brief_body


def test_extract_brief_body_strips_preamble():
    content = (
        "简报已生成并写入 briefs/2026-09-16.md，以下是全文交付物：\n\n"
        "# 🎯 AI 新闻简报 · 2026-09-16\n\n> 订阅者：Demo User\n\n正文内容"
    )
    body = extract_brief_body(content)
    assert body.startswith("# 🎯 AI 新闻简报")
    assert "以下是全文交付物" not in body


def test_extract_brief_body_keeps_normal_content():
    content = "# 🎯 AI 新闻简报 · 2026-09-16\n\n正文内容"
    assert extract_brief_body(content) == content


def test_extract_brief_body_without_h1_unchanged():
    content = "## 🔥 今日头条\n内容"
    assert extract_brief_body(content) == content


def test_extract_brief_body_empty():
    assert extract_brief_body("") == ""
    assert extract_brief_body(None) == ""
