"""RunContext：单次 Agent 运行的共享上下文。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.agent.context_manager import ContextManager
    from server.config import Settings


@dataclass
class RunContext:
    run_id: str
    user_id: int
    settings: "Settings"
    workspace_root: Path
    cm: "ContextManager | None" = None
    warned: bool = False  # 软线预算提醒是否已注入（每窗口一次，切窗后由 CM 复位）
