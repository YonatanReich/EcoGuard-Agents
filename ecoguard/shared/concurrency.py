"""Running independent waits at once."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Any, Callable


def concurrently(*calls: Callable[[], Any]) -> tuple[Any, ...]:
    """Run independent calls at once and return their results in order.

    Threads, because every caller here is waiting on the network (the
    database, ~165 ms away, or a model); a copied context per call, because
    the database routing for a collector or a scenario lives in a context
    variable. An exception from a call propagates; callers that must not fail
    catch inside the call.
    """
    if len(calls) <= 1:
        return tuple(call() for call in calls)
    with ThreadPoolExecutor(max_workers=len(calls), thread_name_prefix="concurrent") as pool:
        futures = [pool.submit(copy_context().run, call) for call in calls]
        return tuple(future.result() for future in futures)
