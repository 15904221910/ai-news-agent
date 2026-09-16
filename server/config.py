"""集中配置：环境变量 → Settings 单例；启动时校验（fail fast）。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# 默认 RSS 源（均为实测可用；可用环境变量 RSS_FEEDS 逗号分隔覆盖）
DEFAULT_RSS_FEEDS = [
    "https://www.qbitai.com/feed",              # 量子位（中文 AI）
    "https://www.ithome.com/rss/",              # IT之家（科技综合）
    "http://export.arxiv.org/rss/cs.AI",        # arXiv cs.AI（学术论文）
    "https://www.technologyreview.com/feed/",   # MIT Technology Review（国际 AI）
    "https://www.infoq.cn/feed",                # InfoQ 中文（工程实践）
    "https://www.solidot.org/index.rss",        # Solidot（科技快讯）
    "https://www.oschina.net/news/rss",         # 开源中国（开源生态）
    "https://sspai.com/feed",                   # 少数派（数字生活）
]


def _default_db_url() -> str:
    return f"sqlite:///{(PROJECT_ROOT / 'data' / 'app.db').as_posix()}"


@dataclass(frozen=True)
class Settings:
    # LLM
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-flash"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 4096
    llm_timeout: int = 60
    # 新闻搜索
    search_provider: str = "tavily"
    search_api_key: str = ""
    rss_feeds: tuple[str, ...] = tuple(DEFAULT_RSS_FEEDS)
    http_proxy: str = ""                 # 可选 HTTP 代理（如 http://127.0.0.1:7890）
    # 邮件（P1）
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    # 运行
    workspace_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "workspace")
    db_url: str = field(default_factory=_default_db_url)
    app_timezone: str = "Asia/Shanghai"
    max_steps: int = 15
    run_timeout_seconds: int = 300
    context_budget_tokens: int = 60000
    context_soft_warn_ratio: float = 0.70
    context_hard_limit_ratio: float = 0.85
    log_level: str = "INFO"


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


def load_settings() -> Settings:
    return Settings(
        llm_base_url=_env("LLM_BASE_URL", "https://api.deepseek.com"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_model=_env("LLM_MODEL", "deepseek-flash"),
        llm_temperature=float(_env("LLM_TEMPERATURE", "0.3")),
        llm_max_tokens=int(_env("LLM_MAX_TOKENS", "4096")),
        llm_timeout=int(_env("LLM_TIMEOUT", "60")),
        search_provider=_env("SEARCH_PROVIDER", "tavily"),
        search_api_key=os.getenv("SEARCH_API_KEY", ""),
        rss_feeds=tuple(
            feed.strip() for feed in os.getenv("RSS_FEEDS", "").split(",") if feed.strip()
        ) or tuple(DEFAULT_RSS_FEEDS),
        http_proxy=os.getenv("HTTP_PROXY_URL", ""),
        smtp_host=os.getenv("SMTP_HOST", ""),
        smtp_port=int(_env("SMTP_PORT", "465")),
        smtp_user=os.getenv("SMTP_USER", ""),
        smtp_pass=os.getenv("SMTP_PASS", ""),
        smtp_from=os.getenv("SMTP_FROM", ""),
        workspace_dir=Path(_env("WORKSPACE_DIR", str(PROJECT_ROOT / "workspace"))),
        db_url=_env("DB_URL", _default_db_url()),
        app_timezone=_env("APP_TIMEZONE", "Asia/Shanghai"),
        max_steps=int(_env("MAX_STEPS", "15")),
        run_timeout_seconds=int(_env("RUN_TIMEOUT_SECONDS", "300")),
        context_budget_tokens=int(_env("CONTEXT_BUDGET_TOKENS", "60000")),
        context_soft_warn_ratio=float(_env("CONTEXT_SOFT_WARN_RATIO", "0.70")),
        context_hard_limit_ratio=float(_env("CONTEXT_HARD_LIMIT_RATIO", "0.85")),
        log_level=_env("LOG_LEVEL", "INFO"),
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = load_settings()
    return _settings


def set_settings(settings: Settings) -> None:
    """测试注入用。"""
    global _settings
    _settings = settings


def validate_settings(settings: Settings | None = None) -> None:
    """启动时校验，缺失关键配置即 fail fast。"""
    settings = settings or get_settings()
    missing = [
        name for name, value in (("LLM_API_KEY", settings.llm_api_key),)
        if not value
    ]
    if missing:
        raise RuntimeError(f"缺少必需的环境变量: {', '.join(missing)}（参考 .env.example）")
