"""文件工具：list_dir / read_file / search_content / write_file（沙箱内操作）。"""
from __future__ import annotations

import os
from pathlib import Path

from server.agent.tools.registry import SecurityError

MAX_READ_CHARS_DEFAULT = 8000
MAX_LINE_CHARS = 200
SKIP_DIR_NAMES = {"__pycache__", ".git", "node_modules"}


def resolve_sandbox_path(path: str, root: Path) -> Path:
    """沙箱路径解析：拦截 `..` 穿越、绝对路径与符号链接逃逸。"""
    root_resolved = root.resolve()
    target = (root_resolved / (path or ".")).resolve()
    if not str(target).startswith(str(root_resolved) + os.sep) and target != root_resolved:
        raise SecurityError(f"路径越出沙箱: {path}")
    return target


def list_dir(args: dict, ctx) -> dict:
    target = resolve_sandbox_path(args.get("path", "."), ctx.workspace_root)
    if not target.exists():
        raise FileNotFoundError(f"目录不存在: {args.get('path')}")
    if not target.is_dir():
        raise NotADirectoryError(f"不是目录: {args.get('path')}")
    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (c.is_file(), c.name.lower())):
        entries.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return {"entries": entries}


def read_file(args: dict, ctx) -> dict:
    target = resolve_sandbox_path(args["path"], ctx.workspace_root)
    if not target.is_file():
        raise FileNotFoundError(f"文件不存在: {args['path']}")
    max_chars = int(args.get("max_chars", MAX_READ_CHARS_DEFAULT))
    try:
        text = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("不是文本文件（无法按 UTF-8 解码）") from exc
    return {
        "content": text[:max_chars],
        "truncated": len(text) > max_chars,
        "total_chars": len(text),
    }


def search_content(args: dict, ctx) -> dict:
    keyword = args["keyword"]
    keyword_lower = keyword.lower()
    max_hits = int(args.get("max_hits", 50))
    root = resolve_sandbox_path(args.get("dir", "."), ctx.workspace_root)
    sandbox_root = ctx.workspace_root.resolve()

    if root.is_file():
        files = [root]
    else:
        files = [
            p for p in root.rglob("*")
            if p.is_file() and not any(part in SKIP_DIR_NAMES for part in p.parts)
        ]

    hits: list[dict] = []
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if keyword_lower in line.lower():
                hits.append({
                    "file": file.relative_to(sandbox_root).as_posix(),
                    "line": line_no,
                    "text": line.strip()[:MAX_LINE_CHARS],
                })
                if len(hits) >= max_hits:
                    return {"hits": hits, "total": len(hits), "truncated": True}
    return {"hits": hits, "total": len(hits), "truncated": False}


def write_file(args: dict, ctx) -> dict:
    target = resolve_sandbox_path(args["path"], ctx.workspace_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = args["content"]
    target.write_text(content, encoding="utf-8")
    return {"path": args["path"], "bytes_written": len(content.encode("utf-8"))}
