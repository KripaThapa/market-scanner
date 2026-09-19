"""Small public HTTP boundary. Edge controls remain required for Internet use."""

from collections import defaultdict, deque
import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

log = logging.getLogger(__name__)


class PublicSecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.hits = defaultdict(deque)
        self.general_limit = max(1, int(os.getenv('PUBLIC_RATE_LIMIT_PER_MINUTE', '120')))
        self.expensive_limit = max(1, int(os.getenv('PUBLIC_EXPENSIVE_RATE_LIMIT_PER_MINUTE', '30')))

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith('/api/'):
            # Ignore X-Forwarded-For here: only a trusted reverse proxy may establish client identity.
            address = request.client.host if request.client else 'unknown'
            expensive = path.startswith('/api/symbols/')
            key = (address, 'expensive' if expensive else 'general')
            now = time.monotonic()
            queue = self.hits[key]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            limit = self.expensive_limit if expensive else self.general_limit
            if len(queue) >= limit:
                log.warning('Public API rate limit exceeded for client=%s group=%s', address, key[1])
                response = JSONResponse({'detail': 'Rate limit exceeded'}, status_code=429,
                                        headers={'Retry-After': '60'})
                return self._headers(response)
            queue.append(now)
        try:
            response = await call_next(request)
        except Exception:
            log.error('Unhandled public API error on %s', path)
            response = JSONResponse({'detail': 'Internal server error'}, status_code=500)
        return self._headers(response)

    @staticmethod
    def _headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'none'; frame-ancestors 'none'"
        return response
