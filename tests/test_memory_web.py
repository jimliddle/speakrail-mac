"""Authenticated loopback API checks with temporary, synthetic memory files."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from aiohttp import ClientSession, CookieJar, web
from aiohttp.test_utils import TestServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from memory_store import MemorySession
from memory_web import MemoryAccess, validate_options


class MemoryWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.access = MemoryAccess(Path(self.temp.name) / 'memory', 1)
        app = web.Application()
        self.access.install(app)
        self.ws_entered, self.ws_release = asyncio.Event(), asyncio.Event()
        async def ws(request):
            self.ws_entered.set()
            await self.ws_release.wait()
            return web.Response(text='finished')
        app.router.add_get('/ws', ws)
        self.server = TestServer(app)
        await self.server.start_server()
        self.origin = str(self.server.make_url('/')).rstrip('/')
        self.access.origin = self.origin
        self.access.host = self.origin.removeprefix('http://')
        self.http = ClientSession(cookie_jar=CookieJar(unsafe=True))

    async def asyncTearDown(self):
        self.ws_release.set()
        await self.http.close()
        await self.server.close()
        self.temp.cleanup()

    async def connect(self):
        return await self.http.post(self.origin + '/memory/connect', json={'key': self.access.key},
                                    headers={'Origin': self.origin})

    async def call(self, body=None, origin=None):
        if body is None:
            return await self.http.get(self.origin + '/memory')
        return await self.http.post(self.origin + '/memory', json=body, headers={'Origin': origin or self.origin})

    async def test_auth_origin_host_cookie_and_cache(self):
        self.assertEqual((await self.call()).status, 403)
        self.assertFalse(self.access.store.root.exists())
        bad = await self.http.post(self.origin + '/memory/connect', json={'key': self.access.key},
                                   headers={'Origin': 'https://untrusted.example'})
        self.assertEqual(bad.status, 403)
        response = await self.connect()
        self.assertEqual(response.status, 200)
        cookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Strict', cookie)
        response = await self.call()
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(len((await response.json())['files']), 2)
        self.assertEqual((await self.call({'action':'save','text':'No'}, 'https://untrusted.example')).status, 403)
        self.assertEqual((await self.http.get(self.origin + '/memory', headers={'Host':'rebound.example'})).status, 403)

    async def test_revision_and_active_session_confirmation(self):
        await self.connect()
        saved = await (await self.call({'action':'save','text':'Synthetic note'})).json()
        self.assertEqual((await self.call({'action':'update','id':saved['id'],'revision':'stale','text':'No'})).status, 400)
        self.access.active = True
        self.assertEqual((await self.call({'action':'save','text':'No'})).status, 409)
        self.access.session = MemorySession(self.access.store)
        self.access.session.propose('forget', saved['id'])
        proposal = (await (await self.call()).json())['pending']
        self.assertEqual((await self.call({'action':'confirm','proposal':{}})).status, 400)
        self.assertEqual((await self.call({'action':'confirm','proposal':proposal})).status, 200)
        self.assertEqual(len(self.access.store.snapshot()), 2)

    async def test_voice_access_single_session_and_cleanup(self):
        self.assertEqual((await self.http.get(self.origin+'/ws', headers={'Origin':self.origin})).status, 403)
        await self.connect()
        self.assertEqual((await self.http.get(self.origin+'/ws')).status, 403)
        self.access.session = MemorySession(self.access.store)
        memory = self.access.session
        memory.propose('save', text='Unconfirmed')
        task = asyncio.create_task(self.http.get(self.origin+'/ws', headers={'Origin':self.origin}))
        await self.ws_entered.wait()
        self.assertEqual((await self.http.get(self.origin+'/ws', headers={'Origin':self.origin})).status, 409)
        self.ws_release.set()
        response = await task
        self.assertEqual(response.status, 200)
        self.assertFalse(self.access.active)
        self.assertIsNone(self.access.session)
        self.assertIsNone(memory.pending)


class ConfigTests(unittest.TestCase):
    def options(self, **changes):
        return SimpleNamespace(**(dict(memory_dir='/tmp/speakrail-memory-test', host='127.0.0.1',
            preview_only=False, no_tools=False, claude=False, frontier=False, search='off',
            mt_url='http://127.0.0.1:8001/v1/completions') | changes))

    def test_options_fail_closed(self):
        with patch.dict(os.environ, {'ASR_URL':'ws://127.0.0.1:1', 'TTS_URL':'http://127.0.0.1:2'}):
            validate_options(self.options())
            for change in ({'host':'0.0.0.0'}, {'claude':True}, {'frontier':True}, {'search':'brave'},
                           {'mt_url':'https://example.org'}, {'no_tools':True}, {'preview_only':True},
                           {'memory_dir':str(ROOT / 'memory')}):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_options(self.options(**change))
        with patch.dict(os.environ, {'ASR_URL':'wss://example.org'}), self.assertRaises(ValueError):
            validate_options(self.options())


if __name__ == '__main__':
    unittest.main()
