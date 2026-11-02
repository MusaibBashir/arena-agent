"""One thread owns Arena.

COM objects belong to the apartment that created them, and Arena runs one model at a time, so every Arena call goes
through a single worker thread, in order. Two edits can then never run into the same model at once. If Arena dies
(it can crash on Model.Close()), the next call reconnects to a fresh Arena; calls that only read are retried once.
"""
import concurrent.futures
import threading

import pythoncom

from . import core

# HRESULTs meaning the Arena process is gone or the connection to it broke
DISCONNECTED = {-2147023174, -2147417848, -2147023170, -2147417851, -2147220995}

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="arena-com",
                                              initializer=pythoncom.CoInitialize)
_state = threading.local()


def _app():
    if getattr(_state, "app", None) is None:
        _state.app = core.app()
    return _state.app


def _call(fn, args, kwargs, retry):
    for attempt in (1, 2):
        try:
            return fn(_app(), *args, **kwargs)
        except pythoncom.com_error as e:
            if e.args and e.args[0] in DISCONNECTED:
                _state.app = None  # Arena died or restarted: reconnect next time
                if retry and attempt == 1:
                    continue
                raise core.ArenaError(f"lost the connection to Arena ({e.args[1] if len(e.args) > 1 else e}); "
                                      "Arena may have crashed. Saved files are intact; the next call starts a fresh "
                                      "Arena. Check whether the last change was saved before repeating it.") from e
            raise


def call(fn, *args, retry=False, **kwargs):
    """Run fn(app, *args, **kwargs) on the Arena thread and wait for it."""
    return _pool.submit(_call, fn, args, kwargs, retry).result()


async def acall(fn, *args, retry=False, **kwargs):
    import asyncio
    return await asyncio.wrap_future(_pool.submit(_call, fn, args, kwargs, retry))
