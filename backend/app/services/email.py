"""Transactional email (verification links, notifications).

Dev-friendly: if SMTP is not configured, emails are logged instead of sent.

Delivery is queued to the Celery worker rather than performed inline. Against a
real relay an inline send cost ~8 seconds per signup — the user watched a dead
button while smtplib negotiated TLS — and a queued send can be retried, which an
inline one never was.

If the broker itself is unreachable we fall back to sending in a worker thread
rather than dropping the mail: losing a verification link strands an account,
and a slow send still beats no send. Either way a signup never fails because the
mail relay is down.
"""

from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage
from urllib.parse import quote

from anyio import to_thread

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def send_email_sync(to: str, subject: str, body: str, html_body: str | None = None) -> None:
    """Blocking send. Prefer :func:`send_email` from async code."""
    if not settings.SMTP_HOST:
        log.info("email_stub", to=to, subject=subject, body=body)
        return

    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    # Port 465 is implicit TLS (SMTPS); 587 is STARTTLS on a plain connection.
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as server:
        if settings.SMTP_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


def _enqueue(to: str, subject: str, body: str, html_body: str | None) -> None:
    """Hand the send to the worker. Raises if the broker will not take it."""
    from app.workers.tasks.email import send_email_task

    # retry=False so a dead broker raises immediately instead of blocking the
    # request for kombu's own retry policy — the caller's fallback is faster.
    send_email_task.apply_async(args=[to, subject, body, html_body], retry=False)


async def send_email(
    to: str, subject: str, body: str, html_body: str | None = None
) -> bool:
    """Queue an email for delivery. Returns False only if it could not be sent
    at all.

    Nothing here waits on the mail relay: queuing is a Redis round trip, and the
    inline fallback only runs when the broker is unreachable.
    """
    # A stub send is a log line — no point paying for a task round trip, and it
    # keeps tests and local dev synchronous and inspectable.
    if not settings.SMTP_HOST:
        send_email_sync(to, subject, body, html_body)
        return True

    try:
        await to_thread.run_sync(_enqueue, to, subject, body, html_body)
        return True
    except Exception as exc:  # noqa: BLE001 - broker down; send it ourselves
        log.warning("email_enqueue_failed", to=to, error=str(exc)[:200])

    try:
        await to_thread.run_sync(send_email_sync, to, subject, body, html_body)
        return True
    except Exception as exc:  # noqa: BLE001 - delivery must not break the request
        log.error("email_send_failed", to=to, subject=subject, error=str(exc))
        return False


def _link(path: str, token: str) -> str:
    return f"{settings.frontend_base_url}{path}?token={quote(token, safe='')}"


def _wrap(heading: str, intro: str, url: str, cta: str, footer: str) -> str:
    safe_url = html.escape(url, quote=True)
    return (
        f"<p>{html.escape(heading)}</p>"
        f"<p>{html.escape(intro)}</p>"
        f'<p><a href="{safe_url}">{html.escape(cta)}</a></p>'
        f"<p>{html.escape(footer)}</p>"
    )


async def send_verification_email(to: str, token: str) -> bool:
    link = _link("/verify-email", token)
    return await send_email(
        to,
        f"Verify your {settings.PROJECT_NAME} email",
        f"Welcome to {settings.PROJECT_NAME}! Verify your email: {link}\n\n"
        "This link expires in 24 hours.",
        _wrap(
            f"Welcome to {settings.PROJECT_NAME}!",
            "Confirm your email address to activate your account.",
            link,
            "Verify your email",
            "This link expires in 24 hours. If you didn't sign up, ignore this email.",
        ),
    )


async def send_password_reset_email(to: str, token: str) -> bool:
    link = _link("/reset-password", token)
    return await send_email(
        to,
        f"Reset your {settings.PROJECT_NAME} password",
        f"Reset your password: {link}\n\nThis link expires in 60 minutes. "
        "If you didn't request this, you can ignore this email.",
        _wrap(
            "Password reset requested",
            "Choose a new password using the link below.",
            link,
            "Reset your password",
            "This link expires in 60 minutes. If you didn't request it, ignore this email.",
        ),
    )


async def send_application_submitted_email(to: str, company: str, title: str) -> bool:
    return await send_email(
        to,
        f"Applied: {title} at {company}",
        f"{settings.PROJECT_NAME} submitted your application for {title} at {company}.\n"
        f"Track it on your dashboard: {settings.frontend_base_url}/dashboard",
        _wrap(
            f"Applied to {title} at {company}",
            "Your application was submitted through the company's official ATS.",
            f"{settings.frontend_base_url}/dashboard",
            "View your pipeline",
            "You are receiving this because you enabled automated applications.",
        ),
    )
