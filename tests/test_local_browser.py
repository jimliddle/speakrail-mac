import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from local_browser import local_page_only


class BrowserBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_page_and_operations(self):
        calls = []

        async def handler(request):
            calls.append(request.path)
            return web.Response(text='fixture')

        app = web.Application(middlewares=[local_page_only])
        app.router.add_route('*', '/{path:.*}', handler)
        async with TestClient(TestServer(app)) as client:
            origin = f'http://127.0.0.1:{client.server.port}'
            for path in ('/', '/ws', '/avatar-preview', '/memory/connect'):
                for headers in ({'Origin': 'null'}, {'Origin': ''}, {'Origin': 'https://evil.example'},
                                {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'},
                                {'Sec-Fetch-Site': 'same-site'}):
                    r = await client.get(path, headers=headers)
                    self.assertEqual(r.status, 403)
            self.assertEqual(calls, [])
            for path in ('/ws', '/avatar-preview'):
                r = await client.get(path)
                self.assertEqual(r.status, 403)
                for headers in ({'Origin': origin}, {'Sec-Fetch-Site': 'same-origin'},
                                {'X-Speakrail-Client': 'local-controller'}):
                    r = await client.get(path, headers=headers)
                    self.assertEqual(r.status, 200)
            r = await client.get('/')
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers['X-Frame-Options'], 'DENY')
            r = await client.post('/memory/connect')
            self.assertEqual(r.status, 403)
            r = await client.post('/memory/connect', headers={'Origin': origin})
            self.assertEqual(r.status, 200)


if __name__ == '__main__':
    unittest.main()
