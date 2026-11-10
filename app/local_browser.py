"""Own-page browser boundary for the loopback UI, separate from backend access."""
from aiohttp import web


@web.middleware
async def local_page_only(request, handler):
    port = request.transport.get_extra_info('sockname')[1]
    names = [name.lower() for name in request.headers]
    host = request.headers.get('Host', '')
    origin = request.headers.get('Origin')
    site = request.headers.get('Sec-Fetch-Site')
    if (any(names.count(name) > 1 for name in ('host', 'origin', 'sec-fetch-site', 'x-speakrail-client'))
            or host not in {f'127.0.0.1:{port}', f'localhost:{port}', f'[::1]:{port}'}
            or origin is not None and origin != 'http://' + host
            or site not in {None, 'none', 'same-origin'}
            or request.method == 'OPTIONS'):
        raise web.HTTPForbidden(text='Open the local Speakrail page directly.')
    operation = request.method not in {'GET', 'HEAD'} or request.path.rstrip('/').endswith(('/ws', '/avatar-preview'))
    if operation and not (origin == 'http://' + host or site == 'same-origin'
                          or request.headers.get('X-Speakrail-Client') == 'local-controller'):
        raise web.HTTPForbidden(text='Use the local page or a marked local controller request.')
    response = await handler(request)
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
    return response
