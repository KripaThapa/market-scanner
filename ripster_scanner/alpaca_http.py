"""Instance-scoped HTTP deadlines for the pinned alpaca-py 0.44.0 clients.

The SDK exposes no timeout constructor argument. Its _one_request hook forwards
opts to requests.Session.request; override only that hook, preserving SDK retry
and pagination behavior. Recheck this integration when upgrading alpaca-py.
"""

from alpaca.data.historical import StockHistoricalDataClient as SDKStockClient
from alpaca.data.historical.screener import ScreenerClient as SDKScreenerClient

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 20


class _HTTPTimeoutMixin:
    def _one_request(self, method, url, opts, retry):
        return super()._one_request(method, url, {
            **opts, 'timeout': (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        }, retry)


class StockHistoricalDataClient(_HTTPTimeoutMixin, SDKStockClient):
    """Historical client with connect/read timeouts on every page and retry."""


class ScreenerClient(_HTTPTimeoutMixin, SDKScreenerClient):
    """Screener client with connect/read timeouts on every request and retry."""
