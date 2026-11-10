"""Compile and probe the patched native parser; no weights or inference required."""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest

from patch_audio import apply_patch

ROOT = Path(__file__).resolve().parent


class NativeBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = ROOT / 'audio.cpp'
        revision = json.loads((ROOT / 'sources.json').read_text())['dependencies']['audio.cpp']['revision']
        state = apply_patch(source, revision, ROOT / 'patches/audio-local-access.patch', check_only=True)
        if state != 'already patched':
            raise RuntimeError('Run mac/patch_audio.py before the native boundary test')
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        binary = Path(cls.tmp.name) / 'http-boundary'
        subprocess.run([os.environ.get('CXX', 'c++'), '-std=c++17', '-pthread',
                        '-I' + str(source), '-I' + str(source / 'include'),
                        str(ROOT / 'fixtures/http_boundary.cpp'), str(source / 'app/server/http.cpp'),
                        '-o', str(binary)], check=True, timeout=120)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        cls.process = subprocess.Popen([str(binary), str(cls.port)], stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
        cls.addClassCleanup(cls.stop)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError('Native fixture exited')
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.1):
                    return
            except OSError:
                time.sleep(.05)
        raise TimeoutError('Native fixture startup timed out')

    @classmethod
    def stop(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)

    def request(self, method='GET', path='/health', headers='', body=b'', host=None):
        host = host or f'127.0.0.1:{self.port}'
        head = f'{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n{headers}\r\n'
        with socket.create_connection(('127.0.0.1', self.port), timeout=2) as sock:
            sock.sendall(head.encode() + body)
            data = b''
            while chunk := sock.recv(4096):
                data += chunk
        status = int(data.split(b' ', 2)[1])
        return status, data.split(b'\r\n\r\n', 1)[1]

    def test_rejection_before_body_and_valid_stream(self):
        marker = 'X-Speakrail-Client: local-controller\r\n'
        before = self.request()[1]
        for extra in ('', 'Origin: null\r\n', 'Origin: \r\n', 'Sec-Fetch-Mode: no-cors\r\n',
                      f'Host: 127.0.0.1:{self.port}\r\n', marker * 2):
            headers = extra + 'Content-Length: 999999\r\n'
            if extra and extra != marker * 2:
                headers += marker
            status, _ = self.request('POST', '/v1/audio/transcriptions/live', headers)
            self.assertEqual(status, 403, extra)
        self.assertEqual(self.request('OPTIONS', '/health', marker)[0], 403)
        self.assertEqual(self.request(host='evil.example')[0], 403)
        self.assertEqual(self.request(host=f'127.0.0.1:{self.port + 1}')[0], 403)
        self.assertEqual(self.request(headers='Origin: https://evil.example\r\n')[0], 403)
        self.assertEqual(self.request()[1], before)
        status, body = self.request('POST', '/v1/audio/transcriptions/live',
                                    marker + 'Transfer-Encoding: chunked\r\n', b'3\r\nabc\r\n0\r\n\r\n')
        self.assertEqual((status, body), (200, b'3'))
        self.assertEqual(self.request()[1], str(int(before) + 1).encode())


if __name__ == '__main__':
    unittest.main()
