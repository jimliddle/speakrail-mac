#!/usr/bin/env python3
# Modified by Jim Liddle, 2026: Astra preview, speech timing and opt-in memory access.
"""Speakrail web server (aiohttp).

    /                the voice UI (web/live)
    /debug/          the measurement UI (web): head meters, decisions, per-turn latencies
    /ws, /debug/ws   one voice session per websocket
                     binary in  = int16 mono 16 kHz mic audio
                     binary out = 2-byte utterance id, 2 pad bytes, int16 24 kHz PCM
                     JSON in:  {cmd: play_start, utt, delay_ms} | {cmd: interrupt} | {cmd: reconnect_asr} | {cmd: stop}
                     JSON out: the session's events (word, endpoint, reply_delta, turn, ...)

`--stub` serves the same UI and protocol with no models at all (stub.py), to try the interface.
"""
import argparse
import asyncio
import base64
import json
import os
import time
import wave
from html import escape

from aiohttp import web, WSMsgType

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
HUB = None
ARGS = None
ALIGNMENT = None
MEMORY = None
PREVIEW_CACHE = web.AppKey("avatar_preview_cache", dict)


def page(path):
    async def handler(_):
        if path == 'live/index.html' and MEMORY is not None:
            with open(os.path.join(HERE, 'web', path)) as source:
                html = source.read().replace('</body>', '<script src="/static/memory.js"></script></body>')
            return web.Response(text=html, content_type='text/html',
                                headers={'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'})
        if path == "live/index.html" and getattr(ARGS, "preview_only", False):
            with open(os.path.join(HERE, "web", path)) as source:
                conversation = escape(getattr(ARGS, "conversation_url", ""), quote=True)
                html = source.read().replace('<body>', f'<body data-preview-only="true" data-conversation-url="{conversation}">')
            return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})
        return web.FileResponse(os.path.join(HERE, "web", path))
    return handler


def session_cfg(q):
    from cascade import Cfg
    barge = {"0": "off", "1": "word"}.get(q.get("barge", ARGS.barge), q.get("barge", ARGS.barge))
    return Cfg(asr_url=os.environ.get("ASR_URL", "ws://127.0.0.1:8765/v1/transcribe"), barge_in=barge,
               voice=ARGS.voice, silence_ms=int(q.get("silence_ms", ARGS.silence_ms)),
               search=search_for(q))


def search_for(q):
    """the server's SEARCH decides which backend exists; the page can only turn it off for its session"""
    if ARGS.search == "off" or q.get("search") == "off":
        return "off"
    return ARGS.search


def micro_cfg(q, cfg):
    from claude_tool import check_key
    from session import MicroCfg
    key_ok = check_key(q.get("ck"))
    return MicroCfg(url=ARGS.mt_url, lora=os.environ.get("LLM_LORA", "speakrail"),
                    think_model=os.environ.get("LLM_BASE_MODEL", "speakrail-base"), undo_words=ARGS.undo_words, tool_hold_ms=ARGS.tool_hold_ms,
                    persona=ARGS.persona, tools=not ARGS.no_tools, memory_dir=getattr(ARGS, 'memory_dir', ''),
                    allow_interject=not ARGS.no_interject, silence_fallback_ms=cfg.silence_ms,
                    notes=ARGS.notes, phrase_cache=not ARGS.no_phrase_cache, safety_yield_s=ARGS.safety_yield_s,
                    claude=bool(ARGS.claude and key_ok), claude_model=ARGS.claude_model or None,
                    claude_mode=ARGS.claude_mode, claude_cwd=os.path.expanduser(ARGS.claude_cwd),
                    frontier=ARGS.frontier)               # paid, on the user's own Fireworks key; no shell access


async def ws_handler(request):
    if getattr(ARGS, "preview_only", False):
        raise web.HTTPConflict(text="This server provides sample playback only.")
    pace = request_pace(request)
    ws = web.WebSocketResponse(max_msg_size=0, heartbeat=20)
    await ws.prepare(request)
    q = request.query
    out: asyncio.Queue = asyncio.Queue()

    def send(obj):
        out.put_nowait(obj)

    async def writer():
        try:
            while True:
                obj = await out.get()
                if obj is None:
                    return
                if isinstance(obj, bytes):
                    await ws.send_bytes(obj)
                else:
                    await ws.send_str(json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass

    wtask = asyncio.create_task(writer())
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if ARGS.stub:
        from types import SimpleNamespace
        from stub import StubSession
        sess = StubSession(SimpleNamespace(delay_ms=480, barge_in=q.get("barge", ARGS.barge)), send)
        if q.get("lipsync") == "phoneme":
            send({"type": "lip_sync_status", "available": False, "reason": "stub"})
    else:
        from session import MicroSession
        cfg = session_cfg(q)
        log_dir = os.path.join(ARGS.sessions_dir, f"session-{stamp}") if ARGS.sessions_dir else None
        mcfg = micro_cfg(q, cfg)
        if q.get("lipsync") == "phoneme" and alignment_service() is not None:
            from lipsync_session import LipSyncSession
            mcfg.phrase_cache = False
            sess = LipSyncSession(cfg, HUB, send, log_dir=log_dir, mcfg=mcfg, alignment_service=ALIGNMENT, speech_pace=pace)
            send({"type": "lip_sync_status", "available": True})
        else:
            sess = MicroSession(cfg, HUB, send, log_dir=log_dir, mcfg=mcfg)
            if q.get("lipsync") == "phoneme":
                send({"type": "lip_sync_status", "available": False})
    if MEMORY is not None:
        MEMORY.session = getattr(sess, 'personal_memory', None)
    try:
        await sess.start()
    except Exception as e:
        send({"type": "error", "where": "asr connect", "detail": repr(e)})
        await sess.close()
        send(None)
        await wtask
        await ws.close()
        return ws
    print(f"[ws] session {stamp} started{' (stub)' if ARGS.stub else ''}", flush=True)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                sess.feed_audio(msg.data)
            elif msg.type == WSMsgType.TEXT:
                m = json.loads(msg.data)
                c = m.get("cmd")
                if c == "play_start":
                    sess.note_play_start(int(m["utt"]), float(m.get("delay_ms", 0)))
                elif c == "play_segment" and hasattr(sess, "note_play_segment"):
                    sess.note_play_segment(int(m["utt"]), int(m["segment"]), float(m["remaining_ms"]))
                elif c == "interrupt":
                    sess.counters["barge_ins"] += 1
                    sess._cancel_reply("interrupt button")
                elif c == "reconnect_asr":
                    try:
                        await sess.reconnect_asr()
                    except Exception as e:
                        send({"type": "error", "where": "asr reconnect", "detail": repr(e)})
                elif c == "stop":
                    break
            elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        await sess.close()
        send(None)
        await wtask
        summ = sess.summary()
        print(f"[ws] session {stamp} closed: {summ['turns']} turns, word_end_to_ear p50 {summ['word_end_to_ear']['p50']} ms", flush=True)
        if not ws.closed:
            await ws.close()
    return ws


async def on_startup(app):
    global HUB
    if not ARGS.stub:
        from cascade import TTSHub
        HUB = TTSHub(asyncio.get_running_loop(), ARGS.voice)
        await HUB.wait_ready()
    url = MEMORY.url if MEMORY else f'http://{ARGS.host}:{ARGS.port}/'
    print(f"speakrail{' (stub mode, no models)' if ARGS.stub else ''}: open {url}", flush=True)


def alignment_service():
    global ALIGNMENT
    from lipsync import AlignmentService, available
    if not available():
        return None
    if ALIGNMENT is None:
        ALIGNMENT = AlignmentService()
    return ALIGNMENT


def request_pace(request):
    from speech_pacing import speech_pace
    try:
        return speech_pace(request.query.get("pace", "0.85"))
    except ValueError as error:
        raise web.HTTPBadRequest(text=str(error))


async def avatar_preview(request):
    """Audible, phoneme-timed preview using the locally rendered Astra greeting."""
    service = alignment_service()
    if service is None:
        return web.json_response({"error": "Install the optional lip-sync package; see mac/LIP_SYNC.md."}, status=503)
    cache = request.app[PREVIEW_CACHE]
    pace = request_pace(request)
    if pace not in cache:
        with wave.open(os.path.join(HERE, "voices", "astra_intro.wav")) as sample:
            pcm = sample.readframes(sample.getnframes())
        with open(os.path.join(HERE, "voices", "astra_intro.txt")) as transcript:
            text = transcript.read().strip()
        try:
            from speech_pacing import pace_pcm
            pcm = await pace_pcm(pcm, pace)
            result = await service.align(pcm, text)
        except Exception:
            return web.json_response({"error": "The local preview alignment failed. See the server log."}, status=503)
        cache[pace] = {"text": text, "sample_rate": 24000, "pace": pace,
                         "pcm": base64.b64encode(pcm).decode("ascii"), **result}
    return web.json_response(cache[pace])


async def on_cleanup(app):
    if ALIGNMENT is not None:
        ALIGNMENT.close()


def env_int(name, default):
    return int(os.environ.get(name, default))


def main():
    global ARGS, MEMORY
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true", help="no models: fake ASR / turn head / LLM / TTS, to try the UI")
    ap.add_argument("--preview-only", action="store_true", help="sample playback only; no microphone sessions or models")
    ap.add_argument("--conversation-url", default="", help="optional link from the preview to a separately running conversation trial")
    ap.add_argument("--port", type=int, default=env_int("UI_PORT", 8080))
    ap.add_argument("--host", default=os.environ.get("UI_HOST", "127.0.0.1"))
    ap.add_argument("--voice", default=os.environ.get("VOICE", ""), help="Breeze reference wav; its transcript sits next to it as .txt")
    ap.add_argument("--persona", default=os.environ.get("PERSONA", "astra"), choices=["nova", "astra"])
    ap.add_argument('--memory-dir', default='', help='opt-in local memory directory outside the checkout (off by default)')
    ap.add_argument("--sessions-dir", default=os.environ.get("SESSIONS_DIR", ""),
                    help="save each session's event log, context and audio recording here ('' = off, the default)")
    # turn taking
    ap.add_argument("--silence-ms", type=int, default=env_int("SILENCE_MS", 1000),
                    help="silence fallback in ms after words with no head fire (0 = only the turn head ends a turn)")
    ap.add_argument("--barge", default="duck", choices=["off", "duck", "word", "head"],
                    help="user speaks over a reply: duck = lower our volume, the model decides")
    ap.add_argument("--safety-yield-s", type=float, default=1.5, help="yield if the model keeps listening through this much speech (0 = off)")
    ap.add_argument("--undo-words", type=int, default=2, help="undo a reply if the user goes on while <= this many of its words played")
    # the model
    ap.add_argument("--mt-url", default=os.environ.get("LLM_URL", "http://127.0.0.1:8001/v1/completions"))
    ap.add_argument("--notes", action="store_true", default=os.environ.get("NOTES", "1") == "1",
                    help="listening notes: the base model takes notes while the user speaks")
    ap.add_argument("--no-notes", dest="notes", action="store_false")
    ap.add_argument("--no-interject", action="store_true", default=os.environ.get("INTERJECT", "1") == "0",
                    help="never offer <interject> (short remarks while the user keeps talking)")
    ap.add_argument("--no-phrase-cache", action="store_true", help="never play a first clause from pre-rendered clips")
    # tools
    ap.add_argument("--no-tools", action="store_true", help="disable local conversation tools")
    ap.add_argument("--tool-hold-ms", type=int, default=env_int("TOOL_HOLD_MS", 600), help="run tool calls only after this much quiet (0 = off)")
    ap.add_argument("--search", default=os.environ.get("SEARCH", "off"), choices=["searxng", "serper", "brave", "off"],
                    help="web search backend for the web_search tool (off by default)")
    ap.add_argument("--frontier", action="store_true", default=bool(os.environ.get("FIREWORKS_API_KEY")),
                    help="offer ask_frontier (a larger model on Fireworks, paid; on when FIREWORKS_API_KEY is set)")
    ap.add_argument("--claude", action="store_true", help="offer claude_code (Claude Code on this machine: a shell!) to sessions "
                    "whose page URL carries ?ck=<SPEAKRAIL_ACCESS_KEY>")
    ap.add_argument("--claude-model", default="", help="claude -p --model (empty: the CLI default)")
    ap.add_argument("--claude-mode", default="auto", help="claude -p --permission-mode")
    ap.add_argument("--claude-cwd", default="~")
    ARGS = ap.parse_args()
    if ARGS.preview_only:
        ARGS.stub = True
    if not ARGS.stub and not ARGS.voice:
        ap.error("--voice (or VOICE) is required unless --stub")
    from memory_web import MemoryAccess, validate_options
    try:
        validate_options(ARGS)
        MEMORY = MemoryAccess(ARGS.memory_dir, ARGS.port, os.environ.get('SPEAKRAIL_MEMORY_KEY')) if ARGS.memory_dir else None
    except ValueError as error:
        ap.error(str(error))
    app = web.Application()
    if ARGS.host == '127.0.0.1':
        from local_browser import local_page_only
        app.middlewares.append(local_page_only)
    if MEMORY:
        MEMORY.install(app)
    app[PREVIEW_CACHE] = {}
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/", page("live/index.html"))
    app.router.add_get("/avatar-preview", avatar_preview)
    app.router.add_get("/ws", ws_handler)
    app.router.add_static("/static", os.path.join(HERE, "web", "live"))
    # the same UI under /live/, for reverse proxies that mount it there
    app.router.add_get("/live/", page("live/index.html"))
    app.router.add_get("/live/avatar-preview", avatar_preview)
    app.router.add_get("/live/ws", ws_handler)
    app.router.add_static("/live/static", os.path.join(HERE, "web", "live"))
    app.router.add_get("/debug", lambda r: web.HTTPFound("/debug/"))
    app.router.add_get("/debug/", page("index.html"))
    app.router.add_get("/debug/ws", ws_handler)
    app.router.add_static("/debug/static", os.path.join(HERE, "web"))
    web.run_app(app, host=ARGS.host, port=ARGS.port, print=None)


if __name__ == "__main__":
    main()
