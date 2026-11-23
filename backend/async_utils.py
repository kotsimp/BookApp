"""async_utils.py - Small asyncio helpers shared by the pipelines."""

import asyncio
from typing import Any, Coroutine, Iterable, List


async def gather_or_cancel(coros: Iterable[Coroutine]) -> List[Any]:
    """
    asyncio.gather that does not leave workers behind: when one fails, the others are cancelled and awaited first.
    Orphaned workers would otherwise keep spending API quota, or see the closed HTTP session as a failed batch and
    save a lower-quality fallback into the resume checkpoint.
    """
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
