"""Apply secret redaction to worker and third-party transport logs."""

import logging
from urllib.parse import quote, quote_plus


class SecretFilter(logging.Filter):
    def __init__(self, settings):
        super().__init__()
        self.secrets = set()
        for key, value in settings.model_dump().items():
            if value and any(part in key for part in ("password", "secret", "api_key")):
                self.secrets.update((str(value), quote(str(value), safe=""), quote_plus(str(value))))

    def filter(self, record):
        message = record.getMessage()
        for secret in sorted(self.secrets, key=len, reverse=True):
            message = message.replace(secret, "[redacted]")
        if record.exc_info:
            message += " error_type=" + record.exc_info[0].__name__
            record.exc_info = None
            record.exc_text = None
        record.msg, record.args = message, ()
        return True


def configure(settings):
    logging.basicConfig(level=logging.INFO)
    for handler in logging.getLogger().handlers:
        handler.addFilter(SecretFilter(settings))
