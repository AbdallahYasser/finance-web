"""Tiny in-memory rate limiter — single-user app, low volume."""
import time

from fastapi import HTTPException


_BUCKETS: dict[tuple[str, int], list[float]] = {}


def rate_limit(scope: str, user_id: int, *, max_per_minute: int = 30) -> None:
    """Allow up to `max_per_minute` calls per (scope, user_id) per 60s window.

    Raises HTTPException(429) when over budget.
    """
    key = (scope, user_id)
    now = time.time()
    cutoff = now - 60.0

    history = _BUCKETS.setdefault(key, [])
    # Drop entries older than the window
    while history and history[0] < cutoff:
        history.pop(0)
    if len(history) >= max_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded ({max_per_minute}/min). Try again shortly.",
        )
    history.append(now)
