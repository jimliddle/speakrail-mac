"""Keep the upstream UI/session engine, with a local-only single-session gate."""
from pathlib import Path
import sys
from urllib.parse import urlsplit

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
import server

original_ws = server.ws_handler
active = False


async def local_ws(request):
    global active
    origin = request.headers.get("Origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or parsed.netloc != request.host:
            raise web.HTTPForbidden(text="This isolated prototype accepts its own local page only.")
    if active:
        raise web.HTTPConflict(text="One voice session at a time in this prototype.")
    active = True
    try:
        return await original_ws(request)
    finally:
        active = False


server.ws_handler = local_ws

if __name__ == "__main__":
    server.main()
