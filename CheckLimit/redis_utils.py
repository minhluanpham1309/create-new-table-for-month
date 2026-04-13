import json
import logging
import redis
from redis.backoff import ExponentialBackoff
from redis.retry import Retry
from typing import List, Optional, Set, Union

logger = logging.getLogger()

_RETRY_ERRORS = [
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
]


# ============================================================================
# CODEC
# ============================================================================

def _enc(value: str) -> str:
    """Encode a plain string to Jackson JSON format.
    'hello'      → '"hello"'
    'say "hi"'   → '"say \\"hi\\""'
    '東京'        → '"東京"'   (ensure_ascii=False keeps unicode as-is)
    """
    return json.dumps(value, ensure_ascii=False)


def _dec(raw: Optional[Union[str, bytes]]) -> Optional[str]:
    """Decode a Jackson JSON string back to plain str.
    '"hello"'  → 'hello'
    b'"hello"' → 'hello'   (redis-py returns bytes when decode_responses=False)
    'plain'    → 'plain'   (non-JSON falls back to raw text)
    None       → None
    Always returns Optional[str] — never bytes.
    """
    if raw is None:
        return None
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    try:
        decoded = json.loads(text)
        return decoded if isinstance(decoded, str) else text
    except (json.JSONDecodeError, ValueError):
        return text


# ============================================================================
# RedisWrapper
# ============================================================================

class RedisWrapper:
    """
    Thin codec wrapper around a raw redis.Redis client.

    All field/value arguments are encoded with _enc() before being sent to
    Redis, and all return values are decoded with _dec() before being returned
    to the caller.

    Only the operations actually used in this project are wrapped.
    Add new methods here as needed — never bypass this class to call the raw
    client directly.
    """

    def __init__(
            self,
            host: str,
            port: int,
            password: Optional[str],
            db: int = 0,
            max_connections: int = 20,
            socket_connect_timeout: int = 5,
            socket_timeout: int = 5,
    ) -> None:
        pool = redis.ConnectionPool(
            host=host,
            port=port,
            password=password,
            db=db,
            decode_responses=True,
            max_connections=max_connections,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
            retry=Retry(ExponentialBackoff(cap=10), retries=5),
            retry_on_timeout=True,
            retry_on_error=_RETRY_ERRORS,
        )
        self._client = redis.Redis(connection_pool=pool)
        self._client.ping()
        logger.info(f"RedisWrapper connected to {host}:{port} db={db}")

    # ------------------------------------------------------------------
    # Hash
    # ------------------------------------------------------------------

    def hget_str(self, key: str, field: str) -> Optional[str]:
        """hget → decode value as str."""
        raw = self._client.hget(key, _enc(field))
        return _dec(raw)

    def hset_str(self, key: str, field: str, value: str) -> None:
        """hset with encoded field and value."""
        self._client.hset(key, _enc(field), _enc(value))

    def hget_int(self, key: str, field: str) -> Optional[int]:
        """hget → plain int (Jackson stores ints as unquoted numeric strings)."""
        raw = self._client.hget(key, _enc(field))
        return int(raw) if raw is not None else None

    def hset_int(self, key: str, field: str, value: int) -> None:
        """hset int as plain numeric string (no JSON quotes)."""
        self._client.hset(key, _enc(field), str(value))

    def hdel(self, key: str, field: str) -> None:
        """Delete an encoded field from a hash."""
        self._client.hdel(key, _enc(field))

    # ------------------------------------------------------------------
    # Set
    # ------------------------------------------------------------------

    def smembers(self, key: str) -> Set[str]:
        """smembers → decode each member, drop non-str results."""
        raw_members = self._client.smembers(key)
        if not raw_members:
            return set()
        decoded: Set[str] = set()
        for m in raw_members:
            v = _dec(m)
            if isinstance(v, str):
                decoded.add(v)
        return decoded

    # ------------------------------------------------------------------
    # Sorted set
    # ------------------------------------------------------------------

    def zadd(self, key: str, member: str, score: int) -> None:
        """zadd with encoded member."""
        self._client.zadd(key, {_enc(member): score})

    # ------------------------------------------------------------------
    # Key ops
    # ------------------------------------------------------------------

    def scan(self, pattern: str, count: int = 1000) -> List[str]:
        """Full SCAN (cursor loop) → always returns List[str]."""
        keys: List[str] = []
        cursor = 0
        while True:
            cursor, batch = self._client.scan(cursor=cursor, match=pattern, count=count)
            keys.extend(k.decode("utf-8") if isinstance(k, bytes) else k for k in batch)
            if cursor == 0:
                break
        return keys

    def delete(self, key: str) -> None:
        """Delete a key."""
        self._client.delete(key)

    def get_int(self, key: str) -> int:
        """GET key → int, 0 if missing. Equivalent to Redisson RAtomicLong.get()."""
        raw = self._client.get(key)
        return int(raw) if raw is not None else 0

    def ping(self) -> bool:
        return self._client.ping()
