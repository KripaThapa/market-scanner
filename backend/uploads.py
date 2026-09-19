"""Bounded image validation and storage, independent of scanner logic."""

from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import uuid
import os
import warnings
import logging

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from starlette.responses import JSONResponse

MAX_UPLOAD = 10 * 1024 * 1024
MAX_PIXELS = 20_000_000
log = logging.getLogger(__name__)
ALLOWED_ORIGINS = {'http://localhost:3000', 'http://127.0.0.1:3000', 'http://localhost:5173', 'http://127.0.0.1:5173',
                   'http://localhost:8000', 'http://127.0.0.1:8000'}
_frontend_port = int(os.getenv('FRONTEND_PORT', '3000'))
ALLOWED_ORIGINS.update({f'http://localhost:{_frontend_port}', f'http://127.0.0.1:{_frontend_port}'})


class UploadBoundary:
    """Limit the entire multipart body before Starlette parses/spools it."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] != 'POST' or scope['path'] != '/internal/watchlist/upload':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        origin = headers.get(b'origin', b'').decode()
        if origin and origin not in ALLOWED_ORIGINS:
            log.warning('Rejected internal upload: disallowed origin')
            return await JSONResponse({'detail': 'Upload origin is not allowed'}, status_code=403)(scope, receive, send)
        chunks, total = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            total += len(message.get('body', b''))
            if total > MAX_UPLOAD + 65536:
                log.warning('Rejected internal upload: body too large')
                return await JSONResponse({'detail': 'Upload exceeds the 10 MiB limit'}, status_code=413)(scope, receive, send)
            chunks.append(message.get('body', b''))
            if not message.get('more_body', False):
                break
        delivered = False
        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
        await self.app(scope, replay, send)


def save_image(upload, directory):
    suffix = Path(upload.filename or '').suffix.lower()
    formats = {'.png': ('image/png', 'PNG'), '.jpg': ('image/jpeg', 'JPEG'), '.jpeg': ('image/jpeg', 'JPEG')}
    if suffix not in formats or upload.content_type != formats[suffix][0]:
        log.warning('Rejected internal upload: unsupported type')
        raise HTTPException(415, 'Only PNG, JPG and JPEG images are accepted')
    data = upload.file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        log.warning('Rejected internal upload: file too large')
        raise HTTPException(413, 'Upload exceeds the 10 MiB limit')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format != formats[suffix][1] or image.width * image.height > MAX_PIXELS:
                    raise ValueError('Invalid format or image dimensions')
                image.verify()
            with Image.open(BytesIO(data)) as image:
                # Re-encode pixels only; discard metadata and any trailing payload.
                image.load()
                sanitized = image.convert('RGB')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombWarning, Image.DecompressionBombError):
        log.warning('Rejected internal upload: invalid image')
        raise HTTPException(415, 'Invalid image or image exceeds 20 megapixels') from None
    folder = Path(directory) / datetime.now(timezone.utc).date().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{uuid.uuid4().hex}.png'
    sanitized.save(path, format='PNG')
    filename = (upload.filename or 'screenshot').replace('\\', '/').split('/')[-1]
    filename = ''.join(char for char in filename if char.isprintable())[:180]
    return path, filename
