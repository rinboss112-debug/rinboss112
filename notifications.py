from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any, Mapping

import requests


def send_telegram(config: Mapping[str, Any], message: str) -> str:
    token = str(config.get("bot_token", "")).strip()
    chat_id = str(config.get("chat_id", "")).strip()
    if not token or not chat_id:
        return ""
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": message},
        timeout=20,
    )
    response.raise_for_status()
    return "Đã gửi Telegram."


def send_email(config: Mapping[str, Any], subject: str, body: str) -> str:
    host = str(config.get("host", "")).strip()
    username = str(config.get("username", "")).strip()
    password = str(config.get("password", "")).strip()
    recipient = str(config.get("recipient", "")).strip()
    sender = str(config.get("sender", username)).strip()
    if not all((host, username, password, recipient, sender)):
        return ""

    port = int(config.get("port", 465))
    use_ssl = bool(config.get("use_ssl", True))
    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = sender
    email["To"] = recipient
    email.set_content(body)

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, timeout=20) as smtp:
            smtp.login(username, password)
            smtp.send_message(email)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(username, password)
            smtp.send_message(email)
    return "Đã gửi email."


def send_completion_notifications(
    telegram_config: Mapping[str, Any],
    email_config: Mapping[str, Any],
    subject: str,
    message: str,
) -> list[str]:
    results: list[str] = []
    for sender in (
        lambda: send_telegram(telegram_config, message),
        lambda: send_email(email_config, subject, message),
    ):
        try:
            result = sender()
            if result:
                results.append(result)
        except Exception as error:
            results.append(f"CẢNH BÁO: Không gửi được thông báo: {error}")
    return results
