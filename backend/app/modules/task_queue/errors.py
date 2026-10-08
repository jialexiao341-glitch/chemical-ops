"""Classify transport failures without storing exception messages or credentials."""

import httpx
from sqlalchemy.exc import OperationalError


def transient(error):
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, (httpx.TransportError, ConnectionError, OperationalError)):
            return True
        if isinstance(error, httpx.HTTPStatusError) and (error.response.status_code == 429 or error.response.status_code >= 500):
            return True
        error = error.__cause__
    return False
