"""Loopback-only access and editor API for opt-in personal memory."""
import hmac
import os
import re
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web
from memory_store import MemoryStore


def validate_options(args):
    if not args.memory_dir:
        return
    if args.host != '127.0.0.1':
        raise ValueError('Memory requires --host 127.0.0.1.')
    if args.preview_only or args.no_tools:
        raise ValueError('Memory needs conversation tools, not preview-only or --no-tools.')
    if args.claude or args.frontier or args.search != 'off':
        raise ValueError('This memory version requires search, Claude and hosted-model tools to be off.')
    for name, url in (('LLM', args.mt_url), ('ASR', os.environ.get('ASR_URL', 'ws://127.0.0.1:8765/v1/transcribe')),
                      ('TTS', os.environ.get('TTS_URL', 'http://127.0.0.1:8000/v1/audio/speech'))):
        if urlsplit(url).hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError(f'Memory requires a loopback {name} service.')
    root = Path(args.memory_dir).expanduser().absolute()
    if root.resolve().is_relative_to(Path(__file__).resolve().parent.parent):
        raise ValueError('Choose a memory directory outside the repository.')
    args.memory_dir = str(root)


class MemoryAccess:
    def __init__(self, directory, port, key=None):
        self.store = MemoryStore(directory)
        self.port = port
        self.host = f'127.0.0.1:{port}'
        self.origin = f'http://{self.host}'
        self.key = key or secrets.token_urlsafe(32)
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', self.key):
            raise ValueError('Memory access key must contain 32-256 URL-safe characters.')
        self.cookie = f'speakrail_memory_{port}'
        self.active = False
        self.session = None

    @property
    def url(self):
        return self.origin + '/#memory-key=' + self.key

    @web.middleware
    async def gate(self, request, handler):
        # Strict Host validation also rejects DNS-rebinding requests.
        if request.host != self.host:
            raise web.HTTPForbidden()
        origin = request.headers.get('Origin')
        is_ws = request.path in ('/ws', '/live/ws', '/debug/ws')
        if origin and origin != self.origin or (request.method != 'GET' or is_ws) and origin != self.origin:
            raise web.HTTPForbidden()
        public = request.path in ('/', '/live/', '/memory/connect') or request.path.startswith(('/static/', '/live/static/'))
        if not public and not hmac.compare_digest(request.cookies.get(self.cookie, '').encode(), self.key.encode()):
            raise web.HTTPForbidden(text='Open the memory launch link printed in Terminal.')
        if is_ws:
            if self.active:
                raise web.HTTPConflict(text='One voice session at a time when memory is enabled.')
            self.active = True
            try:
                return await handler(request)
            finally:
                if self.session:
                    self.session.pending = None
                self.session = None
                self.active = False
        return await handler(request)

    async def connect(self, request):
        try:
            data = await request.json()
            key = data.get('key') if isinstance(data, dict) else None
            valid = isinstance(key, str) and hmac.compare_digest(key.encode(), self.key.encode())
        except (ValueError, UnicodeError):
            valid = False
        if not valid:
            raise web.HTTPForbidden()
        response = web.json_response({'ok': True}, headers={'Cache-Control': 'no-store'})
        response.set_cookie(self.cookie, self.key, httponly=True, samesite='Strict', path='/')
        return response

    async def api(self, request):
        try:
            if request.method == 'GET':
                pending = self.session.pending if self.session else None
                if pending and pending['expires'] <= time.monotonic():
                    pending = None
                return web.json_response({'files': self.store.snapshot(), 'active': self.active,
                    'pending': {k: v for k, v in pending.items() if k != 'expires'} if pending else None},
                    headers={'Cache-Control': 'no-store'})
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError('Expected an action.')
            action = data.get('action')
            if action in ('confirm', 'cancel'):
                if not self.session or not self.session.pending:
                    raise ValueError('No pending change.')
                current = {k: v for k, v in self.session.pending.items() if k != 'expires'}
                if data.get('proposal') != current:
                    raise ValueError('Proposal changed.')
                if action == 'confirm':
                    result = self.session.commit()
                else:
                    self.session.pending = None
                    result = {'ok': True, 'cancelled': True}
            else:
                if self.active:
                    raise web.HTTPConflict(text='Stop the voice session before editing memory files.')
                result = self.store.apply(action, data.get('id', ''), data.get('text', ''), data.get('revision', ''))
            return web.json_response(result, headers={'Cache-Control': 'no-store'})
        except (ValueError, OSError, UnicodeError, TypeError):
            raise web.HTTPBadRequest(text='Memory action failed. Reload and check the ID, revision, text length and file permissions.')

    def install(self, app):
        app.middlewares.append(self.gate)
        app.router.add_post('/memory/connect', self.connect)
        app.router.add_get('/memory', self.api)
        app.router.add_post('/memory', self.api)
