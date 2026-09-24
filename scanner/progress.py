"""Private progress logging with fixed, non-sensitive error categories."""

from requests.exceptions import ConnectionError, HTTPError, Timeout
from alpaca.common.exceptions import APIError


def error_category(exc):
    if isinstance(exc, (Timeout, TimeoutError)):
        return 'timeout'
    if isinstance(exc, ConnectionError):
        return 'connection_error'
    if isinstance(exc, (APIError, HTTPError)):
        return 'provider_error'
    return 'processing_error'
