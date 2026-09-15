from __future__ import annotations

import hashlib
import hmac
import threading
import time
from contextlib import closing
from dataclasses import dataclass

from app.db import get_conn


@dataclass(frozen=True)
class Limit:
    key: str
    maximum: int
    seconds: int = 60


class DatabaseRateLimiter:
    """Atomic fixed-window counters shared by workers; only keyed hashes persist."""

    def __init__(self, secret: str):
        self.secret = secret.encode()
        self._cleanup_lock = threading.Lock()
        self._last_cleanup = 0

    def consume(self, limits: list[Limit], now: int | None = None) -> int:
        timestamp = int(time.time()) if now is None else now
        with closing(get_conn()) as conn:
            with self._cleanup_lock:
                if timestamp - self._last_cleanup >= 60:
                    conn.execute("DELETE FROM rate_limit_buckets WHERE expires_at <= ?", (timestamp,))
                    conn.commit()
                    self._last_cleanup = timestamp
            retry_after = 0
            for limit in limits:
                start = timestamp // limit.seconds * limit.seconds
                key = hmac.new(self.secret, f"{limit.key}:{limit.seconds}:{start}".encode(), hashlib.sha256).hexdigest()
                row = conn.execute(
                    """
                    INSERT INTO rate_limit_buckets (bucket_key, hits, expires_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(bucket_key) DO UPDATE SET hits = rate_limit_buckets.hits + 1
                    WHERE rate_limit_buckets.hits < ?
                    RETURNING hits
                    """, (key, start + limit.seconds, limit.maximum),
                ).fetchone()
                if row is None:
                    retry_after = max(1, start + limit.seconds - timestamp)
                    break
            conn.commit()
        return retry_after
