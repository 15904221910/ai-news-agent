"""FastAPI 应用入口：lifespan 初始化 + 异常映射 + 路由 + 静态前端。

启动顺序：日志 → 配置校验(fail fast) → 建表 → 清理悬挂 running → 种子数据 → 调度器。
静态挂载必须在 API 路由注册之后（避免 "/" 抢占 /api 前缀）。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from server.briefs.router import router as briefs_router
from server.config import PROJECT_ROOT, get_settings, validate_settings
from server.database import init_db, session_scope
from server.errors import AppError, ValidationAppError
from server.logging_conf import setup_logging
from server.runs.router import router as runs_router
from server.runs.service import cleanup_stale_runs
from server.scheduler import shutdown_scheduler, start_scheduler
from server.users.router import router as profile_router
from server.users.service import ensure_seed_data

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    validate_settings(settings)
    init_db()
    cleaned = cleanup_stale_runs()
    if cleaned:
        logger.warning("已清理悬挂运行", extra={"count": cleaned})
    ensure_seed_data()
    start_scheduler()
    logger.info("应用已就绪", extra={"model": settings.llm_model})
    yield
    shutdown_scheduler()


app = FastAPI(title="每日 AI 新闻助手", version="1.0.0", lifespan=lifespan)


# ---------- 请求 ID 中间件（贯穿日志与错误响应） ----------

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = uuid4().hex[:12]
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or "-"


# ---------- 统一异常 → 错误码映射（§11.3） ----------

@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict(_request_id(request)))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [
        {"loc": [str(part) for part in error.get("loc", [])], "msg": error.get("msg", "")}
        for error in exc.errors()
    ]
    error = ValidationAppError("请求参数校验失败", details={"fields": fields})
    return JSONResponse(status_code=error.http_status, content=error.to_dict(_request_id(request)))


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未处理异常", extra={"request_id": _request_id(request)})
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL",
                "message": "服务内部错误",
                "request_id": _request_id(request),
            }
        },
    )


# ---------- 健康检查 ----------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> JSONResponse:
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1"))
        return JSONResponse(status_code=200, content={"status": "ready"})
    except Exception as exc:  # noqa: BLE001
        logger.error("就绪检查失败: %s", exc)
        return JSONResponse(status_code=503, content={"status": "not_ready"})


# ---------- API 路由（必须在静态挂载之前） ----------

app.include_router(profile_router)
app.include_router(briefs_router)
app.include_router(runs_router)

# ---------- 静态前端（html=True：/ → index.html） ----------

_client_dir = PROJECT_ROOT / "client"
if _client_dir.exists():
    app.mount("/", StaticFiles(directory=_client_dir, html=True), name="client")
