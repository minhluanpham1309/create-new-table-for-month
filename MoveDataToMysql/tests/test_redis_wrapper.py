"""
Tests for redis_wrapper.py

Structure:
  TestEnc                              : _enc() — JSON encoding
  TestDec                              : _dec() — JSON decoding
  TestEncDecRoundtrip                  : encode → decode symmetry (Japanese focus)
  TestInit                             : ConnectionPool args, retry config, ping
  TestHgetStr / TestHsetStr            : codec correctness
  TestHgetInt / TestHsetInt            : plain int storage
  TestHdel                             : field encoding
  TestSmembers                         : decode members, filter non-str
  TestZadd                             : member encoding
  TestScan                             : cursor pagination, bytes→str
  TestDelete / TestPing                : pass-through
  TestFakeRedis                        : end-to-end roundtrip with fakeredis
  TestConnectionPoolRetry              : Retry.call_with_retry — transient/permanent failure
  TestFailoverNodeDown                 : node down → ConnectionError
  TestFailoverPrimaryDiesReplicaPromoted : full failover flow — invocation 1 fail, 2 success
"""

import pytest
import fakeredis
import redis as redis_lib
from unittest.mock import MagicMock, patch

from redis_wrapper import RedisWrapper, _enc, _dec


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def wrapper(mock_client):
    with patch("redis_wrapper.redis.ConnectionPool"), \
         patch("redis_wrapper.redis.Redis", return_value=mock_client):
        return RedisWrapper("localhost", 6379, None)


@pytest.fixture
def fake():
    client = fakeredis.FakeRedis(decode_responses=True)
    with patch("redis_wrapper.redis.ConnectionPool"), \
         patch("redis_wrapper.redis.Redis", return_value=client):
        w = RedisWrapper("localhost", 6379, None)
    yield w
    client.flushall()


# ============================================================================
# _enc
# ============================================================================

class TestEnc:
    def test_ascii(self):
        assert _enc("hello") == '"hello"'

    def test_empty(self):
        assert _enc("") == '""'

    def test_embedded_quotes(self):
        assert _enc('say "hi"') == '"say \\"hi\\""'

    def test_japanese_not_escaped(self):
        encoded = _enc("東京")
        assert "東京" in encoded
        assert "\\u" not in encoded


# ============================================================================
# _dec
# ============================================================================

class TestDec:
    def test_none(self):
        assert _dec(None) is None

    def test_quoted_str(self):
        assert _dec('"hello"') == "hello"

    def test_bytes(self):
        assert _dec(b'"hello"') == "hello"

    def test_non_json_passthrough(self):
        assert _dec("plain") == "plain"

    def test_json_number_passthrough(self):
        assert _dec("42") == "42"   # int stored without quotes → str

    def test_json_object_passthrough(self):
        text = '{"city":"東京"}'
        assert _dec(text) == text

    def test_value_error_passthrough(self):
        with patch("redis_wrapper.json.loads", side_effect=ValueError("bad json")):
            assert _dec("plain") == "plain"


# ============================================================================
# _enc / _dec roundtrip — Japanese focus (core use case)
# ============================================================================

class TestEncDecRoundtrip:
    def test_ascii(self):
        assert _dec(_enc("site_key_123")) == "site_key_123"

    def test_kanji(self):
        assert _dec(_enc("東京都渋谷区")) == "東京都渋谷区"

    def test_katakana(self):
        assert _dec(_enc("ページビュー")) == "ページビュー"

    def test_special_chars(self):
        assert _dec(_enc('say "hello" & goodbye')) == 'say "hello" & goodbye'


# ============================================================================
# __init__ / ConnectionPool config
# ============================================================================

class TestInit:
    def test_pool_args(self):
        mock_client = MagicMock()
        with patch("redis_wrapper.redis.ConnectionPool") as mock_pool, \
             patch("redis_wrapper.redis.Redis", return_value=mock_client):
            RedisWrapper("myhost", 6380, "secret", db=2)
            kwargs = mock_pool.call_args.kwargs
            assert kwargs["host"] == "myhost"
            assert kwargs["port"] == 6380
            assert kwargs["password"] == "secret"
            assert kwargs["db"] == 2
            assert kwargs["decode_responses"] is True

    def test_retry_config(self):
        mock_client = MagicMock()
        with patch("redis_wrapper.redis.ConnectionPool") as mock_pool, \
             patch("redis_wrapper.redis.Redis", return_value=mock_client):
            RedisWrapper("localhost", 6379, None)
            kwargs = mock_pool.call_args.kwargs
            assert kwargs["retry_on_timeout"] is True
            assert redis_lib.exceptions.ConnectionError in kwargs["retry_on_error"]
            assert redis_lib.exceptions.TimeoutError in kwargs["retry_on_error"]
            from redis.retry import Retry
            assert isinstance(kwargs["retry"], Retry)
            assert kwargs["retry"]._retries == 10

    def test_custom_pool_options(self):
        mock_client = MagicMock()
        with patch("redis_wrapper.redis.ConnectionPool") as mock_pool, \
             patch("redis_wrapper.redis.Redis", return_value=mock_client):
            RedisWrapper(
                "localhost",
                6379,
                None,
                max_connections=123,
                socket_connect_timeout=9,
                socket_timeout=11,
            )
            kwargs = mock_pool.call_args.kwargs
            assert kwargs["max_connections"] == 123
            assert kwargs["socket_connect_timeout"] == 9
            assert kwargs["socket_timeout"] == 11

    def test_ping_called_on_init(self, mock_client):
        mock_client.ping.reset_mock()
        with patch("redis_wrapper.redis.ConnectionPool"), \
             patch("redis_wrapper.redis.Redis", return_value=mock_client):
            RedisWrapper("localhost", 6379, None)
        mock_client.ping.assert_called_once()

    def test_logs_connection_info(self):
        mock_client = MagicMock()
        with patch("redis_wrapper.redis.ConnectionPool"), \
             patch("redis_wrapper.redis.Redis", return_value=mock_client), \
             patch("redis_wrapper.logger.info") as mock_info:
            RedisWrapper("cache.local", 7000, None, db=5)
        mock_info.assert_called_once_with("RedisWrapper connected to cache.local:7000 db=5")


# ============================================================================
# Hash operations
# ============================================================================

class TestHgetStr:
    def test_encodes_field_decodes_value(self, wrapper, mock_client):
        mock_client.hget.return_value = '"東京"'
        assert wrapper.hget_str("key", "city") == "東京"
        mock_client.hget.assert_called_once_with("key", '"city"')

    def test_returns_none_when_missing(self, wrapper, mock_client):
        mock_client.hget.return_value = None
        assert wrapper.hget_str("key", "field") is None


class TestHsetStr:
    def test_encodes_field_and_value(self, wrapper, mock_client):
        wrapper.hset_str("key", "city", "東京")
        mock_client.hset.assert_called_once_with("key", '"city"', '"東京"')


class TestHgetInt:
    def test_returns_int(self, wrapper, mock_client):
        mock_client.hget.return_value = "99"
        assert wrapper.hget_int("key", "count") == 99

    def test_returns_none_when_missing(self, wrapper, mock_client):
        mock_client.hget.return_value = None
        assert wrapper.hget_int("key", "count") is None

    def test_raises_value_error_for_non_numeric(self, wrapper, mock_client):
        mock_client.hget.return_value = "NaN"
        with pytest.raises(ValueError):
            wrapper.hget_int("key", "count")


class TestHsetInt:
    def test_stores_plain_string(self, wrapper, mock_client):
        wrapper.hset_int("key", "count", 42)
        mock_client.hset.assert_called_once_with("key", '"count"', "42")


class TestHdel:
    def test_encodes_field(self, wrapper, mock_client):
        wrapper.hdel("key", "field")
        mock_client.hdel.assert_called_once_with("key", '"field"')


# ============================================================================
# Set / Sorted set / Key ops
# ============================================================================

class TestSmembers:
    def test_decodes_members(self, wrapper, mock_client):
        mock_client.smembers.return_value = {'"東京"', '"大阪"'}
        assert wrapper.smembers("key") == {"東京", "大阪"}

    def test_empty_set(self, wrapper, mock_client):
        mock_client.smembers.return_value = set()
        assert wrapper.smembers("key") == set()

    def test_none_response(self, wrapper, mock_client):
        mock_client.smembers.return_value = None
        assert wrapper.smembers("key") == set()

    def test_filters_none(self, wrapper, mock_client):
        mock_client.smembers.return_value = {None, b'"valid"'}
        assert wrapper.smembers("key") == {"valid"}


class TestZadd:
    def test_encodes_member(self, wrapper, mock_client):
        wrapper.zadd("ranking", "東京", 100)
        mock_client.zadd.assert_called_once_with("ranking", {'"東京"': 100})


class TestScan:
    def test_single_page(self, wrapper, mock_client):
        mock_client.scan.side_effect = [(0, ["k:1", "k:2"])]
        assert wrapper.scan("k:*") == ["k:1", "k:2"]

    def test_two_pages(self, wrapper, mock_client):
        mock_client.scan.side_effect = [(7, [b"k:1"]), (0, [b"k:2"])]
        assert wrapper.scan("k:*") == ["k:1", "k:2"]

    def test_empty(self, wrapper, mock_client):
        mock_client.scan.side_effect = [(0, [])]
        assert wrapper.scan("nomatch:*") == []

    def test_default_count_1000(self, wrapper, mock_client):
        mock_client.scan.side_effect = [(0, [])]
        wrapper.scan("*")
        mock_client.scan.assert_called_once_with(cursor=0, match="*", count=1000)

    def test_custom_count(self, wrapper, mock_client):
        mock_client.scan.side_effect = [(0, [])]
        wrapper.scan("site:*", count=25)
        mock_client.scan.assert_called_once_with(cursor=0, match="site:*", count=25)


class TestGetInt:
    def test_returns_int(self, wrapper, mock_client):
        mock_client.get.return_value = "9999"
        assert wrapper.get_int("key") == 9999

    def test_returns_zero_when_missing(self, wrapper, mock_client):
        mock_client.get.return_value = None
        assert wrapper.get_int("key") == 0

    def test_raises_value_error_for_non_numeric(self, wrapper, mock_client):
        mock_client.get.return_value = "N/A"
        with pytest.raises(ValueError):
            wrapper.get_int("key")


class TestDelete:
    def test_passes_key(self, wrapper, mock_client):
        wrapper.delete("some:key")
        mock_client.delete.assert_called_once_with("some:key")


class TestPing:
    def test_returns_true(self, wrapper, mock_client):
        mock_client.ping.reset_mock()
        mock_client.ping.return_value = True
        assert wrapper.ping() is True

    def test_returns_false(self, wrapper, mock_client):
        mock_client.ping.reset_mock()
        mock_client.ping.return_value = False
        assert wrapper.ping() is False


# ============================================================================
# End-to-end with fakeredis
# ============================================================================

class TestFakeRedis:
    def test_str_roundtrip(self, fake):
        fake.hset_str("k", "city", "東京都渋谷区")
        assert fake.hget_str("k", "city") == "東京都渋谷区"

    def test_int_roundtrip(self, fake):
        fake.hset_int("k", "count", 9999)
        assert fake.hget_int("k", "count") == 9999

    def test_hdel(self, fake):
        fake.hset_str("k", "f", "v")
        fake.hdel("k", "f")
        assert fake.hget_str("k", "f") is None

    def test_smembers(self, fake):
        for city in ["東京", "大阪", "名古屋"]:
            fake._client.sadd("cities", _enc(city))
        assert fake.smembers("cities") == {"東京", "大阪", "名古屋"}

    def test_zadd(self, fake):
        fake.zadd("ranking", "東京", 100)
        assert fake._client.zscore("ranking", '"東京"') == 100.0

    def test_scan(self, fake):
        for i in range(3):
            fake._client.set(f"site:{i}", "1")
        assert len(fake.scan("site:*")) == 3

    def test_delete(self, fake):
        fake.hset_str("k", "f", "v")
        fake.delete("k")
        assert fake.hget_str("k", "f") is None


class TestConnectionPoolRetry:
    def _make_retry(self, retries=5):
        from redis.retry import Retry
        from redis.backoff import NoBackoff
        return Retry(
            NoBackoff(),
            retries=retries,
            supported_errors=(
                redis_lib.exceptions.ConnectionError,
                redis_lib.exceptions.TimeoutError,
            ),
        )

    def test_succeeds_after_transient_failures(self):
        retry = self._make_retry()
        call_count = 0

        def do():
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise redis_lib.exceptions.ConnectionError("transient")
            return "recovered"

        assert retry.call_with_retry(do, lambda e: None) == "recovered"
        assert call_count == 4  # 3 fail + 1 success

    def test_raises_after_all_retries_exhausted(self):
        retry = self._make_retry(retries=3)

        def do():
            raise redis_lib.exceptions.ConnectionError("permanent")

        with pytest.raises(redis_lib.exceptions.ConnectionError):
            retry.call_with_retry(do, lambda e: None)

    def test_retries_on_timeout_error(self):
        retry = self._make_retry()
        call_count = 0

        def do():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise redis_lib.exceptions.TimeoutError("timeout")
            return "ok"

        assert retry.call_with_retry(do, lambda e: None) == "ok"
        assert call_count == 2


# ============================================================================
# Failover — node down
# ============================================================================

class TestFailoverNodeDown:
    def _make(self, server):
        client = fakeredis.FakeRedis(server=server, decode_responses=True)
        with patch("redis_wrapper.redis.ConnectionPool"), \
             patch("redis_wrapper.redis.Redis", return_value=client):
            return RedisWrapper("localhost", 6379, None)

    def test_raises_connection_error_when_node_down(self):
        server = fakeredis.FakeServer()
        w = self._make(server)
        server.connected = False
        with pytest.raises(redis_lib.exceptions.ConnectionError):
            w.hget_str("k", "f")

    def test_write_also_raises_when_node_down(self):
        server = fakeredis.FakeServer()
        w = self._make(server)
        server.connected = False
        with pytest.raises(redis_lib.exceptions.ConnectionError):
            w.hset_str("k", "f", "v")


# ============================================================================
# Failover — primary dies, replica promoted, next invocation succeeds
#
# Invocation 1: wrapper → server_a (primary) → server_a dies → ConnectionError → Lambda fail
# AWS: server_b promoted, DNS updated
# Invocation 2: new wrapper → server_b (new primary) → success
#
# ============================================================================

class TestFailoverPrimaryDiesReplicaPromoted:
    def _make(self, fake_client):
        with patch("redis_wrapper.redis.ConnectionPool"), \
             patch("redis_wrapper.redis.Redis", return_value=fake_client):
            return RedisWrapper("valkey.cache.amazonaws.com", 6379, None)

    def test_invocation_1_fails_invocation_2_succeeds(self):
        server_a = fakeredis.FakeServer()  # original primary
        server_b = fakeredis.FakeServer()  # replica → promoted

        # Seed data on primary
        client_a = fakeredis.FakeRedis(server=server_a, decode_responses=True)
        client_a.hset("site:1", '"city"', '"東京"')

        # Invocation 1: primary dies
        wrapper_1 = self._make(client_a)
        server_a.connected = False
        with pytest.raises(redis_lib.exceptions.ConnectionError):
            wrapper_1.hget_str("site:1", "city")

        # Invocation 2: DNS → server_b (new primary), data already replicated
        client_b = fakeredis.FakeRedis(server=server_b, decode_responses=True)
        client_b.hset("site:1", '"city"', '"東京"')  # simulate replication

        wrapper_2 = self._make(client_b)
        assert wrapper_2.hget_str("site:1", "city") == "東京"
        wrapper_2.hset_str("site:1", "city", "大阪")
        assert wrapper_2.hget_str("site:1", "city") == "大阪"

