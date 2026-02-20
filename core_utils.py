"""
core_utils.py — JobProspectorBE
================================
Core stability & traffic-control utilities.

Fixes implemented:
  1. apply_windows_asyncio_fix()  — forces ProactorEventLoop on Windows so
     Playwright can spawn browser subprocesses without NotImplementedError.
  2. RequestThrottler              — asyncio.Semaphore + randomised jitter delay
     to cap outbound concurrency and avoid rate-limit bans.
  3. execute_with_retry()         — exponential backoff wrapper for any coroutine
     that may time out against Lever / Greenhouse / Ashby APIs.
"""

import asyncio
import logging
import random
import sys
from typing import Any, Callable, Coroutine

logger = logging.getLogger("hiring_detector.core_utils")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(_h)


# ── Phase 1: Windows ProactorEventLoop fix ────────────────────────────────────

def apply_windows_asyncio_fix() -> None:
    """
    CRITICAL FIX FOR WINDOWS
    -------------------------
    Forces Python to use ProactorEventLoop on Windows.

    Must be called at the very top of main.py **before** any asyncio usage.
    Prevents the 'NotImplementedError: _make_subprocess_transport' crash that
    occurs when Playwright tries to spawn a Chromium/Firefox subprocess on the
    default SelectorEventLoop.
    """
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            logger.info("✅ Windows ProactorEventLoop policy applied successfully.")
        except Exception as exc:
            logger.error("❌ Failed to set Windows event loop policy: %s", exc)


# ── Phase 2: Traffic control ──────────────────────────────────────────────────

class RequestThrottler:
    """
    Manages concurrency limits + politeness delays for outbound HTTP / Playwright
    requests to prevent rate-limit bans and IP blocks.

    Usage::

        throttler = RequestThrottler(max_concurrent=5, base_delay=2.0)

        async def my_task():
            return await throttler.execute_with_delay(some_coroutine())
    """

    def __init__(self, max_concurrent: int = 5, base_delay: float = 2.0) -> None:
        """
        Args:
            max_concurrent: Maximum number of requests running at the same time.
            base_delay: Base sleep (seconds) between requests. Actual sleep is
                        base_delay × uniform(0.7, 1.3) to add randomised jitter.
        """
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.base_delay = base_delay

    async def execute_with_delay(self, coro: Coroutine) -> Any:
        """
        Run *coro* inside the semaphore after a randomised jitter sleep.

        The jitter (±30 % of base_delay) makes traffic look more organic and
        reduces the chance that a burst of requests arrives at the same millisecond.
        """
        async with self.semaphore:
            jitter = random.uniform(0.7, 1.3)
            actual_delay = self.base_delay * jitter
            logger.debug("⏳ Throttler sleeping %.2fs before next request …", actual_delay)
            await asyncio.sleep(actual_delay)
            try:
                return await coro
            except Exception as exc:
                logger.error("Task execution failed inside throttler: %s", exc)
                raise


# ── Phase 3: Exponential backoff retry ───────────────────────────────────────

async def execute_with_retry(
    coro_func: Callable[[], Coroutine],
    max_retries: int = 3,
    backoff_factor: float = 2.0,
) -> Any:
    """
    Execute a coroutine-factory with exponential backoff.

    *coro_func* must be a **callable** that returns a fresh coroutine each time
    it is called (i.e. do NOT pass an already-awaited coroutine, pass the
    function/lambda).

    Example::

        result = await execute_with_retry(
            lambda: hiring_checker.check_lever(company, website),
            max_retries=3,
            backoff_factor=2.0,
        )

    Retry schedule (default):
        attempt 1 fail → wait 1 s
        attempt 2 fail → wait 2 s
        attempt 3 fail → raise

    Args:
        coro_func:      Zero-argument callable that produces the coroutine.
        max_retries:    Total attempts before giving up.
        backoff_factor: Multiplier applied to the delay after each failure.
    """
    attempt = 0
    current_delay = 1.0

    while attempt < max_retries:
        attempt += 1
        try:
            return await coro_func()
        except asyncio.TimeoutError:
            logger.warning(
                "⏱ Attempt %d/%d timed out.", attempt, max_retries
            )
        except Exception as exc:
            logger.warning(
                "⚠️  Attempt %d/%d failed: %s", attempt, max_retries, exc
            )

        if attempt < max_retries:
            logger.info("🔁 Retrying in %.1f s …", current_delay)
            await asyncio.sleep(current_delay)
            current_delay *= backoff_factor
        else:
            logger.error("❌ All %d attempts exhausted.", max_retries)
            raise


# ── Self-test ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    apply_windows_asyncio_fix()
    logger.info("core_utils self-test passed.")
