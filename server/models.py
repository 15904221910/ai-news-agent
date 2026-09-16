"""汇总导入所有 ORM 模型，确保 Base.metadata 完整。"""
from server.briefs.models import Brief  # noqa: F401
from server.runs.models import AgentRun, ContextWindow, ToolCall  # noqa: F401
from server.users.models import Preference, User  # noqa: F401
