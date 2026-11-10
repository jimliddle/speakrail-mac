"""Browser boundary for loopback-only, server-to-server voice endpoints.

The client marker is deliberately not a secret. Browsers cannot attach it in a
simple request; preflights, browser Origins and Fetch Metadata are rejected.
This prevents drive-by web access, not access by other local processes.
"""


def rejection(headers, port, *, health=False):
    pairs = [(k.lower(), v) for k, v in headers]
    names = [k for k, _ in pairs]
    if any(names.count(k) > 1 for k in ("host", "origin", "x-speakrail-client")):
        return "Duplicate security header"
    values = dict(pairs)
    if values.get("host") not in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}:
        return "Invalid local Host"
    if "origin" in values or any(k.startswith("sec-fetch-") for k in values):
        return "Browser requests are not enabled on this backend"
    if not health and values.get("x-speakrail-client") != "local-controller":
        return "Local controller header required"
    return None


async def aiohttp_guard(request, handler):
    from aiohttp import web
    if request.method == "OPTIONS":
        raise web.HTTPForbidden(text="Browser preflights are not enabled")
    port = request.transport.get_extra_info("sockname")[1]
    reason = rejection(request.headers.items(), port,
                       health=request.method in {"GET", "HEAD"} and request.path == "/health")
    if reason:
        raise web.HTTPForbidden(text=reason)
    return await handler(request)


class ASGIGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        reason = rejection(((k.decode("latin1"), v.decode("latin1")) for k, v in scope["headers"]),
                           scope["server"][1],
                           health=scope["method"] in {"GET", "HEAD"} and scope["path"] == "/health")
        if scope["method"] == "OPTIONS":
            reason = "Browser preflights are not enabled"
        if reason:
            body = reason.encode()
            await send({"type": "http.response.start", "status": 403,
                        "headers": [(b"content-type", b"text/plain"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)
