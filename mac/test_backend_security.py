"""No-model tests for browser rejection and legitimate controller traffic."""
import asyncio
import importlib.util
from pathlib import Path
import unittest

from aiohttp import web, ClientSession
from aiohttp.test_utils import TestServer
from websockets.asyncio.server import serve
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from backend_security import rejection, ASGIGuard, aiohttp_guard

ROOT = Path(__file__).resolve().parent
MARKER = {"X-Speakrail-Client": "local-controller"}


class PolicyTests(unittest.TestCase):
    def test_hosts_origins_fetch_metadata_and_marker(self):
        good = [("Host", "127.0.0.1:1234"), *MARKER.items()]
        self.assertIsNone(rejection(good, 1234))
        for extra in [("Origin", "https://evil.example"), ("Origin", "null"),
                      ("Origin", ""), ("Sec-Fetch-Site", "same-origin"),
                      ("Sec-Fetch-Mode", "navigate"), ("Host", "127.0.0.1:1234"),
                      ("X-Speakrail-Client", "local-controller")]:
            with self.subTest(extra=extra):
                self.assertIsNotNone(rejection(good + [extra], 1234))
        for host in ("evil.example:1234", "127.0.0.1.evil.example:1234", "127.0.0.1:1235", "0.0.0.0:1234"):
            self.assertIsNotNone(rejection([("host", host), *MARKER.items()], 1234))
        self.assertIsNotNone(rejection([("host", "127.0.0.1:1234")], 1234))
        self.assertIsNone(rejection([("host", "127.0.0.1:1234")], 1234, health=True))


class AsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_asgi_preflight_and_websocket_closed(self):
        async def inner(scope, receive, send):
            self.fail("Rejected request reached the application")
        async def receive():
            self.fail("Rejected request read its body")
        messages = []
        async def send(message):
            messages.append(message)
        app = ASGIGuard(inner)
        await app({"type": "http", "server": ("127.0.0.1", 1234), "method": "OPTIONS",
                   "path": "/health", "headers": [(b"host", b"127.0.0.1:1234"),
                   (b"x-speakrail-client", b"local-controller")]}, receive, send)
        self.assertEqual(messages[0]["status"], 403)
        messages.clear()
        await app({"type": "websocket"}, receive, send)
        self.assertEqual(messages, [{"type": "websocket.close", "code": 1008}])

    async def test_readiness_rejects_unprotected_backend(self):
        from unittest.mock import Mock
        from test_speech import ready
        process = Mock()
        process.poll.return_value = None
        for guarded in (False, True):
            async def health(request):
                return web.Response(status=403 if guarded and 'Origin' in request.headers else 200)
            app = web.Application()
            app.router.add_get('/health', health)
            async with TestServer(app, host='127.0.0.1') as server:
                if guarded:
                    await ready(process, server.port, '/health', timeout=2)
                else:
                    with self.assertRaisesRegex(RuntimeError, 'lacks browser protection'):
                        await ready(process, server.port, '/health', timeout=2)

    async def test_asgi_get_synthesis_and_posts_rejected_before_body(self):
        calls = []

        async def inner(scope, receive, send):
            calls.append(scope["path"])
            await send({"type": "http.response.start", "status": 200, "headers": []})

        async def no_body():
            self.fail("Rejected request tried to read its body")

        app = ASGIGuard(inner)
        for path, method in [("/v1/audio/speech.wav", "GET"), ("/v1/audio/speech", "POST"),
                             ("/v1/voices", "POST"), ("/v1/audio/speech", "OPTIONS")]:
            for extras in ([], [(b"origin", b"null")], [(b"sec-fetch-mode", b"no-cors")]):
                messages = []

                async def send(message):
                    messages.append(message)

                await app({"type": "http", "server": ("127.0.0.1", 1234), "method": method,
                           "path": path, "headers": [(b"host", b"127.0.0.1:1234"), *extras]}, no_body, send)
                self.assertEqual(messages[0]["status"], 403)
        self.assertFalse(calls)
        for path, headers in [("/health", []), ("/v1/audio/speech.wav", [(b"x-speakrail-client", b"local-controller")])]:
            await app({"type": "http", "server": ("127.0.0.1", 1234), "method": "GET",
                       "path": path, "headers": [(b"host", b"127.0.0.1:1234"), *headers]}, no_body, send)
        self.assertEqual(calls, ["/health", "/v1/audio/speech.wav"])

    async def test_http_guard(self):
        calls = []

        async def handler(request):
            calls.append(request.path)
            return web.json_response({"ok": True})

        app = web.Application(middlewares=[web.middleware(aiohttp_guard)])
        app.router.add_route("*", "/{path:.*}", handler)
        async with TestServer(app, host="127.0.0.1") as server, ClientSession() as client:
            for method, headers in [("POST", {}), ("OPTIONS", {"Origin": "https://evil.example"}),
                                    ("POST", {**MARKER, "Origin": "null"}),
                                    ("GET", {**MARKER, "Host": "evil.example"})]:
                async with client.request(method, server.make_url("/v1/completions"), headers=headers) as response:
                    self.assertEqual(response.status, 403)
            self.assertFalse(calls)
            async with client.post(server.make_url("/v1/completions"), headers=MARKER, json={}) as response:
                self.assertEqual(response.status, 200)
            async with client.get(server.make_url("/health")) as response:
                self.assertEqual(response.status, 200)

    async def test_websocket_handshake_rejects_before_handler(self):
        spec = importlib.util.spec_from_file_location("asr_bridge", ROOT.parent / "services/asr/bridge.py")
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        calls = []

        async def handler(ws):
            calls.append(True)
            await ws.send("accepted")

        async with serve(handler, "127.0.0.1", 0, origins=[None], process_request=bridge.check_handshake) as server:
            port = server.sockets[0].getsockname()[1]
            for origin, headers in [(None, {}), ("https://evil.example", MARKER), ("null", MARKER)]:
                with self.assertRaises(InvalidStatus) as error:
                    async with connect(f"ws://127.0.0.1:{port}/v1/transcribe", origin=origin, additional_headers=headers):
                        self.fail("Unexpected upgrade")
                self.assertEqual(error.exception.response.status_code, 403)
            self.assertFalse(calls)
            async with connect(f"ws://127.0.0.1:{port}/v1/transcribe", additional_headers=MARKER) as ws:
                self.assertEqual(await ws.recv(), "accepted")
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
