import logging
from dataclasses import dataclass

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class ConsoleEmailBackend:
    """DEVELOPMENT ONLY. Writes the message to the server log; nothing is delivered.

    Settings validation refuses this backend when ENVIRONMENT=production.
    """

    name = "console"

    def send(self, message: EmailMessage) -> None:
        logger.warning("DEV EMAIL (not delivered) to=%s subject=%r\n%s", message.to, message.subject, message.body)


def get_email_backend() -> ConsoleEmailBackend:
    backend = get_settings().email_backend
    if backend == "console":
        return ConsoleEmailBackend()
    raise RuntimeError(f"Unsupported email backend: {backend}")
