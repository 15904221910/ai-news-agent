"""邮件推送（P1，FR-U3）：Markdown → HTML → SMTP SSL。

发送失败由调用方（executor）兜底为 WARNING 日志，不影响 run 状态与简报落库。
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from server.config import Settings

logger = logging.getLogger(__name__)


def send_brief_email(to_addr: str, content_md: str, settings: Settings) -> None:
    """发送简报邮件；配置缺失或网络失败均抛异常，由调用方处理。"""
    import markdown  # 延迟导入：未启用邮件推送的环境无需加载

    html_body = markdown.markdown(content_md, extensions=["tables", "nl2br"])
    html = (
        "<html><body style=\"font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', "
        'sans-serif; max-width: 720px; margin: 0 auto; padding: 16px;">'
        f"{html_body}</body></html>"
    )

    msg = EmailMessage()
    msg["Subject"] = f"【AI 新闻简报】{datetime.now().strftime('%Y-%m-%d')}"
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = to_addr
    msg.set_content(content_md)               # 纯文本兜底
    msg.add_alternative(html, subtype="html")  # HTML 正文

    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
        server.login(settings.smtp_user, settings.smtp_pass)
        server.send_message(msg)
