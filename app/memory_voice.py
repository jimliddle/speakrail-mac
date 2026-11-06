"""Explicit memory commands use the normal turn and speech-output lifecycle."""
import asyncio
import time

from memory_store import SPECS, explicit_request, is_memory_command, model_result, spoken_result, voice_action


async def run_tool(session, reply, name, args):
    while reply.held and not reply.cut:
        await asyncio.sleep(.02)
    if reply.cut:
        return {'error': 'Memory action cancelled.'}
    turn = (session.turn if reply.kind == 'interject' else None) or reply.turn
    try:
        result = voice_action(session.personal_memory, name, args, turn.text())
    except (ValueError, OSError, UnicodeError):
        result = {'error': 'Memory action was not completed. Check Settings, Memory; no success is confirmed.'}
    result = model_result(result)
    session.send({'type': 'tool', 'name': name, 'args': args, 'result': result, 'ms': 0, 'store': {}})
    return result


def tool_summary(session, completed):
    if getattr(session, 'personal_memory', None) and completed and all(name in SPECS for name, _, _ in completed):
        return spoken_result(completed[-1][0], completed[-1][2])
    return None


async def generate(session, reply):
    """Return False for ordinary conversation, without delaying speculation."""
    if not getattr(session, 'personal_memory', None) or not session.m.tools:
        return False
    spoken = reply.turn.text()
    speculation = session.mspec
    if reply.held and speculation is not None and speculation.reply is reply:
        # Scratch turns are empty until adoption; classify the recogniser snapshot.
        spoken = ' '.join(speculation.norm)
    if not is_memory_command(spoken):
        return False
    try:
        while reply.held and not reply.cut:
            await asyncio.sleep(.02)
        if reply.cut:
            return True
        try:
            request = explicit_request(session.personal_memory, reply.turn.text())
            error = None
        except (ValueError, OSError, UnicodeError) as exc:
            request = ('recall_memory', {})
            error = str(exc) if isinstance(exc, ValueError) else 'Memory files could not be read. Check Settings, Memory.'
        if request is None:
            return False
        reply.turn.t_llm_sent = time.monotonic()
        name, args = request
        if error:
            result = {'error': error}
            session.send({'type': 'tool', 'name': name, 'args': args, 'result': result, 'ms': 0, 'store': {}})
        else:
            result = await run_tool(session, reply, name, args)
        reply.units.append(('tool', name, args, result))
        if reply.cut:
            return True
        session._speak_text(reply, spoken_result(name, result) or 'Check the memory result in View details.')
        session._flush(reply, final=True)
        reply.turn.t_llm_done = time.monotonic()
        reply.gen_done = True
        session._hist_reply(reply)
        reply.text = ' '.join(u[1] if u[0] == 'w' else f'[{u[1]}]' for u in reply.units)
        reply.turn.reply = ' '.join(u[1] for u in reply.units if u[0] == 'w')
        session._maybe_finished(reply)
    except asyncio.CancelledError:
        pass
    except Exception:
        session.send({'type': 'error', 'where': 'memory', 'detail': 'Memory reply failed; inspect Settings before retrying.'})
        reply.gen_done = True
        session._maybe_finished(reply)
    return True
