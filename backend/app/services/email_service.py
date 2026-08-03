"""Sends the one transactional email this platform needs so far: the access-pass approval
link (CNADE 2026 Roadmap Pieza 4). No Resend account exists yet -- `settings.resend_api_key`
stays unset until Paranoid creates one, and `send_activation_email` logs the email instead of
sending it in that case, same "build the flow now, wire the real provider later without
touching code again" pragmatism already used for phone numbers on AccessPass (collected, never
verified).
"""

import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RESEND_API_URL = "https://api.resend.com/emails"


async def send_activation_email(*, to_email: str, full_name: str, tournament_name: str, activation_url: str) -> None:
    settings = get_settings()
    subject = f"Tu pase para {tournament_name} fue aprobado"
    html = (
        f"<p>Hola {full_name},</p>"
        f"<p>Tu pase para apostar en <strong>{tournament_name}</strong> en Claim fue aprobado.</p>"
        f'<p><a href="{activation_url}">Activá tu cuenta acá</a> para empezar.</p>'
    )

    if not settings.resend_api_key:
        logger.info(
            "RESEND_API_KEY no configurada -- log en vez de envío real. to=%s subject=%r "
            "activation_url=%s",
            to_email,
            subject,
            activation_url,
        )
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            _RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
        )
        response.raise_for_status()
