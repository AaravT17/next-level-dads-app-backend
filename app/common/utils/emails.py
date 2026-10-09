import logging
import os
import resend

logger = logging.getLogger(__name__)

resend.api_key = os.getenv('RESEND_API_KEY', '')

_FROM_ADDRESS = os.getenv('RESEND_FROM_ADDRESS', 'Next Level Dads <noreply@mail.nextleveldads.ca>')


async def send_email(to: str, subject: str, html: str, text: str) -> None:
    """Send a transactional email via Resend."""
    if not resend.api_key:
        raise RuntimeError('RESEND_API_KEY is not set.')

    await resend.Emails.send_async(
        {
            'from': _FROM_ADDRESS,
            'to': to,
            'subject': subject,
            'html': html,
            'text': text,
        }
    )
