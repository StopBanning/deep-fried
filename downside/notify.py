"""Push the summary (and the full report as a file) to whichever channels are configured in the environment.

  DISCORD_WEBHOOK_URL
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  SMTP_HOST + SMTP_USER + SMTP_PASSWORD + EMAIL_TO   (SMTP_PORT defaults to 465, SSL)
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.request
import uuid
from email.message import EmailMessage

from .data import AGENT


def _multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    out = b""
    for name, value in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").encode()
    for name, (filename, data, ctype) in files.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n").encode() + data + b"\r\n"
    return out + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def _post(url: str, body: bytes, ctype: str) -> None:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype, "User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def discord(url: str, summary: str, report: str, filename: str) -> None:
    body, ctype = _multipart({"payload_json": json.dumps({"content": summary[:1990]})},
                             {"files[0]": (filename, report.encode(), "text/markdown")})
    _post(url, body, ctype)


def telegram(token: str, chat: str, summary: str, report: str, filename: str) -> None:
    base = f"https://api.telegram.org/bot{token}"
    body, ctype = _multipart({"chat_id": chat, "caption": summary[:1000]},
                             {"document": (filename, report.encode(), "text/markdown")})
    _post(f"{base}/sendDocument", body, ctype)


def email(summary: str, report: str, filename: str, subject: str) -> None:
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, os.environ["SMTP_USER"], os.environ["EMAIL_TO"]
    msg.set_content(summary + "\n\nFull report attached.")
    msg.add_attachment(report.encode(), maintype="text", subtype="markdown", filename=filename)
    with smtplib.SMTP_SSL(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "465")),
                          context=ssl.create_default_context()) as s:
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
        s.send_message(msg)


def send_all(summary: str, report: str, filename: str, subject: str) -> list[str]:
    """Send to every configured channel. Returns one status line per channel tried."""
    env, out = os.environ, []
    jobs = []
    if env.get("DISCORD_WEBHOOK_URL"):
        jobs.append(("discord", lambda: discord(env["DISCORD_WEBHOOK_URL"], summary, report, filename)))
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        jobs.append(("telegram", lambda: telegram(env["TELEGRAM_BOT_TOKEN"], env["TELEGRAM_CHAT_ID"],
                                                  summary, report, filename)))
    if all(env.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_TO")):
        jobs.append(("email", lambda: email(summary, report, filename, subject)))
    for name, job in jobs:
        try:
            job()
            out.append(f"{name}: sent")
        except Exception as e:  # one broken channel shouldn't stop the others
            out.append(f"{name}: failed ({type(e).__name__})")
    return out
