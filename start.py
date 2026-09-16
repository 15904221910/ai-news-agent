"""一键启动：检查依赖与环境 → 启动服务 → 自动打开浏览器。

用法：双击 start.bat，或命令行执行 python start.py。
"""
from __future__ import annotations

import importlib
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"

# (import 名, pip 包名)
REQUIRED_MODULES = (
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("sqlalchemy", "sqlalchemy"),
    ("apscheduler", "apscheduler"),
    ("openai", "openai"),
    ("httpx", "httpx"),
    ("feedparser", "feedparser"),
    ("dotenv", "python-dotenv"),
    ("jsonschema", "jsonschema"),
    ("markdown", "markdown"),
)


def pause(message: str = "按回车键退出...") -> None:
    try:
        input(message)
    except EOFError:
        pass


def _importable(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def ensure_dependencies() -> None:
    missing = [pkg for mod, pkg in REQUIRED_MODULES if not _importable(mod)]
    if not missing:
        return
    print(f"[依赖] 缺少 {', '.join(missing)}，正在安装（首次耗时较长）...")
    try:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")]
        )
    except subprocess.CalledProcessError:
        print("[依赖] 安装失败，请手动执行: pip install -r requirements.txt")
        pause()
        sys.exit(1)


def ensure_env_file() -> None:
    """确保 .env 存在；缺失时从 .env.example 生成。"""
    env_path = ROOT / ".env"
    if env_path.exists():
        return
    example = ROOT / ".env.example"
    if example.exists():
        env_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print("[配置] 已从 .env.example 生成 .env")


def _read_env() -> dict[str, str]:
    """直接解析 .env 文件（不污染 os.environ）。"""
    from dotenv import dotenv_values

    return {
        key: (value or "").strip()
        for key, value in dotenv_values(ROOT / ".env").items()
    }


def _has_llm_key() -> bool:
    """检查 .env 或进程环境变量中是否已提供 LLM_API_KEY。"""
    return bool(_read_env().get("LLM_API_KEY") or os.getenv("LLM_API_KEY", "").strip())


def ensure_llm_key() -> None:
    if _has_llm_key():
        return
    env_path = ROOT / ".env"
    print()
    print("=" * 64)
    print("[需要配置] .env 里的 LLM_API_KEY 还没有填写，服务无法启动。")
    print("请在打开的记事本中找到 LLM_API_KEY= 这一行，把 Key 粘贴到等号后面，")
    print("保存后回到本窗口按回车继续。（Key 申请: https://platform.deepseek.com）")
    print("=" * 64)
    try:
        os.startfile(env_path)  # Windows：自动用默认编辑器打开
        print("[配置] 已自动打开 .env，请在记事本中填写。")
    except (AttributeError, OSError):
        print(f"[配置] 请手动编辑：{env_path}")
    while True:
        try:
            answer = input("填写并保存后按回车继续（输入 q 退出）: ").strip().lower()
        except EOFError:
            sys.exit(1)
        if answer == "q":
            print("已退出。配置好 .env 后，重新双击 start.bat 即可启动。")
            sys.exit(1)
        if _has_llm_key():
            print("[配置] LLM_API_KEY 检测通过")
            return
        print("[配置] 还没检测到 LLM_API_KEY，请确认已保存 .env 文件后重试。")


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex((HOST, PORT)) == 0


def open_browser_later(delay: float = 2.5) -> None:
    def _open() -> None:
        time.sleep(delay)
        webbrowser.open(URL)

    threading.Thread(target=_open, daemon=True).start()


def main() -> None:
    print("=" * 64)
    print("  每日 AI 新闻助手 Agent - 一键启动")
    print("=" * 64)
    ensure_dependencies()
    ensure_env_file()
    ensure_llm_key()

    if port_in_use():
        print(f"[提示] {URL} 已有服务在运行，直接打开浏览器。")
        webbrowser.open(URL)
        return

    sys.path.insert(0, str(ROOT))
    import uvicorn
    from server.main import app

    print()
    print(f"[启动] 工作台: {URL}/    设置页: {URL}/settings.html")
    print("[启动] 按 Ctrl+C 停止服务")
    open_browser_later()
    try:
        uvicorn.run(app, host=HOST, port=PORT)
    except OSError as exc:
        print(f"[错误] 服务启动失败（端口可能被占用）: {exc}")
        pause()
        sys.exit(1)
    print("[停止] 服务已退出")


if __name__ == "__main__":
    main()
