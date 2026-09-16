"""工具注册入口：build_registry() 构建包含全部 12 个工具的注册表。

8 个基础/新闻工具（list_dir/read_file/search_content/write_file/bash/search_news/
get_user_profile/get_current_time）+ 4 个记忆工具（get_context_status/save_notes/
new_context/search_history，§9.9）。
"""
from __future__ import annotations

from server.agent.tools import file_tools, memory_tools, meta_tools, news_tool, shell_tool
from server.agent.tools.registry import ToolRegistry

_EMPTY_PARAMS = {"type": "object", "properties": {}}


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(
        "list_dir",
        "列出沙箱目录内容。path 为相对于 workspace 沙箱根目录的路径（如 '.' 或 'briefs'）。",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "目录相对路径，如 . 或 briefs"}},
            "required": ["path"],
        },
        file_tools.list_dir,
    )
    registry.register(
        "read_file",
        "读取沙箱内的文本文件内容。最长返回 max_chars 字符，超出部分标记 truncated。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件相对路径"},
                "max_chars": {"type": "integer", "default": 8000, "minimum": 1, "maximum": 20000},
            },
            "required": ["path"],
        },
        file_tools.read_file,
    )
    registry.register(
        "search_content",
        "在沙箱目录下按关键词（大小写不敏感）搜索文件内容，返回命中的文件/行号/该行文本。",
        {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "dir": {"type": "string", "default": ".", "description": "搜索起始目录（沙箱内相对路径）"},
                "max_hits": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200},
            },
            "required": ["keyword"],
        },
        file_tools.search_content,
    )
    registry.register(
        "write_file",
        "把文本内容写入沙箱内的文件（自动创建父目录，覆盖已有文件）。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件相对路径，如 briefs/2026-09-16.md"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        file_tools.write_file,
    )
    registry.register(
        "bash",
        "执行一条安全命令（仅白名单：date/ls/pwd/cat/echo/wc/python --version）。不确定是否被允许时不要调用。",
        {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
        shell_tool.bash,
    )
    registry.register(
        "search_news",
        "联网搜索最近几天的 AI 新闻。可以多次调用、每次换不同查询词；"
        "返回结构化条目列表（title/url/source/published_at/snippet）。",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索查询词，如 '大模型 发布'、'AI 芯片 新闻'"},
                "max_results": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
                "days": {"type": "integer", "default": 1, "minimum": 1, "maximum": 7,
                         "description": "只取最近 N 天内的新闻"},
            },
            "required": ["query"],
        },
        news_tool.search_news,
    )
    registry.register(
        "get_user_profile",
        "读取当前用户的订阅话题、关键词、排除词（无参数，user_id 由运行时注入）。",
        _EMPTY_PARAMS,
        meta_tools.get_user_profile,
    )
    registry.register(
        "get_current_time",
        "获取当前日期、星期与时间（无参数），用于判断'今日'范围。",
        _EMPTY_PARAMS,
        meta_tools.get_current_time,
    )
    registry.register(
        "get_context_status",
        "查看当前上下文窗口的 token 预算使用情况（油量表，无参数）。返回已用/剩余/窗口序号等。",
        _EMPTY_PARAMS,
        memory_tools.get_context_status,
    )
    registry.register(
        "save_notes",
        "覆盖式保存/更新交接笔记（Markdown）。笔记必含：任务目标/当前进度/关键参数/已完成/待办/踩过的坑。"
        "阶段进展后随时调用，切换窗口时会自动带入新窗口。",
        {
            "type": "object",
            "properties": {"notes": {"type": "string", "description": "完整交接笔记（Markdown）"}},
            "required": ["notes"],
        },
        memory_tools.save_notes,
    )
    registry.register(
        "new_context",
        "主动硬切换上下文窗口：旧窗口整体归档，新窗口仅携带交接笔记继续任务。"
        "预算不足时调用（建议先 save_notes）。不要尝试压缩旧对话。",
        {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "切换原因，如 '预算不足'"},
                "notes": {"type": "string", "description": "可选：切换前最后一次更新交接笔记"},
            },
            "required": ["reason"],
        },
        memory_tools.new_context,
    )
    registry.register(
        "search_history",
        "检索已归档窗口（History 档案）中的原始对话内容，按关键词匹配返回片段。需要旧窗口细节时使用。",
        {
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "max_hits": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
            },
            "required": ["keyword"],
        },
        memory_tools.search_history,
    )
    return registry
