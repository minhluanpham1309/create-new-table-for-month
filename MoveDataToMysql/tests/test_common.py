"""
Unit tests for common.py

Test categories:
  TestGetRegion            : get_region — env var + default
  TestGetSecret            : get_secret — success, cache, error
  TestGetSSLContext        : get_ssl_context — regional, fallback, not found
  TestGetDbConnection      : get_db_connection — success, env fallbacks, errors
  TestRunStep              : run_step — success, kwargs, exception
  TestGetMaxWorkers        : get_max_workers — default, custom
  TestGetWrapper           : _get_wrapper — singleton, ping failure, pool args
  TestWrapperGetters       : get_data_redis_wrapper / get_package_redis_wrapper /
                             get_setting_wrapper — isolation, db, host
  TestScanRedisKeys        : scan_redis_keys — pagination, empty, exception
  TestGetRedisSetData      : get_redis_set_data — members, empty, exception
  TestDeleteRedisKey       : delete_redis_key — success, exception
  TestGetFromSettingCache  : get_from_setting_cache — int, none, exception
  TestSetToSettingCache    : set_to_setting_cache — hset_int call, exception

All tests use mocks — no real DB/Redis/AWS connections.
"""

import json
import os
import pytest
from unittest.mock import patch, MagicMock, call
import pymysql
from botocore.exceptions import ClientError

import common
from redis_wrapper import RedisWrapper


# ===========================================================================
# Helpers
# ===========================================================================

def _reset_secret_cache():
    common._secret_cache = None


def _reset_wrappers():
    """Clear singleton dict so each test starts fresh."""
    common._wrappers.clear()


def _mock_wrapper():
    """Return a MagicMock that looks like a RedisWrapper."""
    return MagicMock(spec=RedisWrapper)

# ===========================================================================
# AWS HELPERS
# ===========================================================================

class TestGetRegion:
    """Test get_region."""

    def test_default_region_when_not_set(self):
        """Default value is ap-northeast-1."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AWS_REGION", None)
            result = common.get_region()
        assert result == "ap-northeast-1"

    @patch.dict(os.environ, {"AWS_REGION": "us-west-2"})
    def test_region_from_environment(self):
        assert common.get_region() == "us-west-2"


class TestGetSecret:
    def setup_method(self):
        _reset_secret_cache()

    def teardown_method(self):
        _reset_secret_cache()

    @patch("boto3.client")
    def test_get_secret_success(self, mock_boto_client):
        """Fetches and parses the secret JSON correctly."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "host": "test-db.rds.amazonaws.com",
                "username": "admin",
                "password": "mock-password-value",
            })
        }

        result = common.get_secret("ap-northeast-1")

        assert result["host"] == "test-db.rds.amazonaws.com"
        assert result["username"] == "admin"
        assert result["password"] == "mock-password-value"
        mock_boto_client.assert_called_once()

    @patch("boto3.client")
    def test_get_secret_uses_cache_on_second_call(self, mock_boto_client):
        """Second call returns cached value without hitting AWS again."""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"host": "db-host"})
        }

        common.get_secret("ap-northeast-1")
        common.get_secret("ap-northeast-1")

        assert mock_client.get_secret_value.call_count == 1

    @patch("boto3.client")
    def test_get_secret_client_error(self, mock_boto_client):
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Not authorized"}},
            "GetSecretValue",
        )

        with pytest.raises(ClientError) as exc_info:
            common.get_secret("ap-northeast-1")

        assert "AccessDeniedException" in str(exc_info.value)


# ===========================================================================
# SSL / DB CONNECTION
# ===========================================================================

class TestGetSSLContext:
    @patch("os.path.exists")
    @patch("ssl.SSLContext")
    def test_uses_region_bundle_when_exists(self, mock_ssl_context, mock_exists):
        mock_exists.return_value = True
        mock_ctx = MagicMock()
        mock_ssl_context.return_value = mock_ctx

        result = common.get_ssl_context("ap-northeast-1")

        assert result == mock_ctx
        mock_ctx.load_verify_locations.assert_called_once()

    @patch("os.path.exists")
    @patch("ssl.SSLContext")
    def test_fallback_to_global_bundle(self, mock_ssl_context, mock_exists):
        """Falls back to global bundle when region-specific is missing."""
        mock_exists.side_effect = [False, True]
        mock_ctx = MagicMock()
        mock_ssl_context.return_value = mock_ctx

        result = common.get_ssl_context("ap-northeast-1")

        assert result == mock_ctx
        mock_ctx.load_verify_locations.assert_called_once()

    @patch("os.path.exists")
    def test_raises_when_no_bundle_found(self, mock_exists):
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="CA bundle not found"):
            common.get_ssl_context("ap-northeast-1")


class TestGetDbConnection:
    """Test get_db_connection."""

    @patch("common.get_ssl_context")
    @patch("pymysql.connect")
    def test_success_returns_connection(self, mock_connect, mock_ssl):
        mock_ssl.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        result = common.get_db_connection({
            "host": "test-db.rds.amazonaws.com",
            "port": 3306,
            "username": "admin",
            "password": "secret",
            "dbname": "HEAT_MAP",
        })

        assert result == mock_conn
        mock_connect.assert_called_once()

    @patch("common.get_ssl_context")
    @patch("pymysql.connect")
    def test_uses_env_fallbacks_when_secret_empty(self, mock_connect, mock_ssl):
        mock_ssl.return_value = MagicMock()
        mock_connect.return_value = MagicMock()

        with patch.dict(os.environ, {
            "DB_HOST": "env-host",
            "DB_PORT": "5432",
            "DB_USER": "env-user",
            "DB_PASSWORD": "env-pass",
            "DB_NAME": "ENV_DB",
        }):
            common.get_db_connection({})

        kw = mock_connect.call_args[1]
        assert kw["host"] == "env-host"
        assert kw["port"] == 5432
        assert kw["user"] == "env-user"
        assert kw["password"] == "env-pass"
        assert kw["database"] == "ENV_DB"

    @patch("common.get_ssl_context")
    @patch("pymysql.connect")
    def test_operational_error_2003_cannot_connect(self, mock_connect, mock_ssl):
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(2003, "Can't connect")

        with pytest.raises(pymysql.err.OperationalError):
            common.get_db_connection({"host": "x", "username": "u", "password": "p"})

    @patch("common.get_ssl_context")
    @patch("pymysql.connect")
    def test_operational_error_1045_access_denied(self, mock_connect, mock_ssl):
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(1045, "Access denied")

        with pytest.raises(pymysql.err.OperationalError):
            common.get_db_connection({"host": "x", "username": "u", "password": "p"})

    @patch("common.get_ssl_context")
    @patch("pymysql.connect")
    def test_operational_error_other_code(self, mock_connect, mock_ssl):
        """Hits the else branch in OperationalError handler (line 219)."""
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(9999, "Some other DB error")

        with pytest.raises(pymysql.err.OperationalError):
            common.get_db_connection({"host": "x", "username": "u", "password": "p"})

    @patch("common.get_ssl_context")
    @patch("pymysql.connect")
    def test_generic_exception_is_reraised(self, mock_connect, mock_ssl):
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = Exception("Unexpected error")

        with pytest.raises(Exception, match="Unexpected error"):
            common.get_db_connection({"host": "x", "username": "u", "password": "p"})


# ===========================================================================
# STEP RUNNER
# ===========================================================================

class TestRunStep:
    """Test run_step wrapper."""

    def test_returns_function_result(self):
        result = common.run_step("add", lambda a, b: a + b, 3, 7)
        assert result == 10

    def test_passes_kwargs(self):
        def multiply(a, b=2):
            return a * b

        result = common.run_step("mul", multiply, 5, b=4)
        assert result == 20

    def test_reraises_exception(self):
        def error_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            common.run_step("error_step", error_func)


# ===========================================================================
# REDIS HELPERS
# ===========================================================================

class TestGetMaxWorkers:
    """Test get_max_workers."""

    def test_default_is_ten(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("MAX_WORKERS", None)
            assert common.get_max_workers() == 10

    @patch.dict(os.environ, {"MAX_WORKERS": "5"})
    def test_custom_value_from_env(self):
        assert common.get_max_workers() == 5


# ============================================================================
# _get_wrapper — singleton factory
# ============================================================================

class TestGetWrapper:
    def setup_method(self):
        _reset_wrappers()

    def teardown_method(self):
        _reset_wrappers()

    @patch.dict(os.environ, {"REDIS_HOST": "localhost", "REDIS_PORT": "6379"})
    @patch("common.RedisWrapper")
    def test_creates_singleton(self, mock_wrapper_cls):
        mock_wrapper_cls.return_value = _mock_wrapper()

        w1 = common._get_wrapper("data", "localhost", 6379, None, db=1)
        w2 = common._get_wrapper("data", "localhost", 6379, None, db=1)

        assert w1 is w2
        mock_wrapper_cls.assert_called_once()

    @patch("common.RedisWrapper")
    def test_passes_correct_args(self, mock_wrapper_cls):
        mock_wrapper_cls.return_value = _mock_wrapper()

        common._get_wrapper("data", "my-host", 6380, "secret", db=2)

        kwargs = mock_wrapper_cls.call_args[1]
        assert kwargs["host"] == "my-host"
        assert kwargs["port"] == 6380
        assert kwargs["password"] == "secret"
        assert kwargs["db"] == 2
        assert kwargs["max_connections"] == 20
        assert kwargs["socket_connect_timeout"] == 5
        assert kwargs["socket_timeout"] == 5

    @patch("common.RedisWrapper")
    def test_ping_failure_does_not_store_singleton(self, mock_wrapper_cls):
        """If RedisWrapper.__init__ raises (ping fails), singleton must NOT be stored."""
        mock_wrapper_cls.side_effect = Exception("Connection refused")

        with pytest.raises(Exception, match="Connection refused"):
            common._get_wrapper("data", "localhost", 6379, None, db=1)

        assert "data" not in common._wrappers


# ============================================================================
# get_data_redis_wrapper / get_package_redis_wrapper / get_setting_wrapper
# ============================================================================

class TestWrapperGetters:
    def setup_method(self):
        _reset_wrappers()

    def teardown_method(self):
        _reset_wrappers()

    @patch.dict(os.environ, {"REDIS_HOST": "main-host", "REDIS_PORT": "6379"})
    @patch("common.RedisWrapper")
    def test_data_wrapper_uses_db1(self, mock_wrapper_cls):
        mock_wrapper_cls.return_value = _mock_wrapper()

        common.get_data_redis_wrapper()

        assert mock_wrapper_cls.call_args[1]["db"] == 1
        assert mock_wrapper_cls.call_args[1]["host"] == "main-host"

    @patch.dict(os.environ, {"REDIS_NETTY_HOST": "pkg-host", "REDIS_PORT": "6379"})
    @patch("common.RedisWrapper")
    def test_package_wrapper_uses_netty_host(self, mock_wrapper_cls):
        mock_wrapper_cls.return_value = _mock_wrapper()

        common.get_package_redis_wrapper()

        assert mock_wrapper_cls.call_args[1]["host"] == "pkg-host"
        assert mock_wrapper_cls.call_args[1]["db"] == 0

    @patch.dict(os.environ, {"REDIS_HOST": "main-host", "REDIS_PORT": "6379"})
    @patch("common.RedisWrapper")
    def test_setting_wrapper_uses_db0(self, mock_wrapper_cls):
        mock_wrapper_cls.return_value = _mock_wrapper()

        common.get_setting_wrapper()

        assert mock_wrapper_cls.call_args[1]["db"] == 0
        assert mock_wrapper_cls.call_args[1]["host"] == "main-host"

    @patch.dict(os.environ, {
        "REDIS_HOST": "main-host", "REDIS_NETTY_HOST": "pkg-host", "REDIS_PORT": "6379"
    })
    @patch("common.RedisWrapper")
    def test_three_wrappers_are_independent(self, mock_wrapper_cls):
        """data / package / setting must be separate singleton instances."""
        mock_wrapper_cls.side_effect = [_mock_wrapper(), _mock_wrapper(), _mock_wrapper()]

        data    = common.get_data_redis_wrapper()
        package = common.get_package_redis_wrapper()
        setting = common.get_setting_wrapper()

        assert data is not package
        assert data is not setting
        assert package is not setting

    @patch.dict(os.environ, {"REDIS_HOST": "main-host", "REDIS_PORT": "6379"})
    @patch("common.RedisWrapper")
    def test_data_and_setting_are_separate_even_with_same_host(self, mock_wrapper_cls):
        """data (db=1) and setting (db=0) share REDIS_HOST but must be different objects."""
        mock_wrapper_cls.side_effect = [_mock_wrapper(), _mock_wrapper()]

        data    = common.get_data_redis_wrapper()
        setting = common.get_setting_wrapper()

        assert data is not setting
        assert mock_wrapper_cls.call_count == 2


# ============================================================================
# scan_redis_keys
# ============================================================================

class TestScanRedisKeys:
    def setup_method(self):
        _reset_wrappers()

    def teardown_method(self):
        _reset_wrappers()

    @patch("common.get_data_redis_wrapper")
    def test_returns_all_pages(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.scan.return_value = ["key:1", "key:2", "key:3"]

        result = common.scan_redis_keys("key:*")

        assert sorted(result) == ["key:1", "key:2", "key:3"]
        w.scan.assert_called_once_with("key:*")

    @patch("common.get_data_redis_wrapper")
    def test_returns_empty_list_on_no_match(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.scan.return_value = []

        assert common.scan_redis_keys("nomatch:*") == []

    @patch("common.get_data_redis_wrapper")
    def test_returns_empty_list_on_exception(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.scan.side_effect = Exception("Redis down")

        assert common.scan_redis_keys("key:*") == []


# ============================================================================
# get_redis_set_data
# ============================================================================

class TestGetRedisSetData:
    @patch("common.get_data_redis_wrapper")
    def test_returns_members(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.smembers.return_value = {"a", "b", "c"}

        assert common.get_redis_set_data("key") == {"a", "b", "c"}
        w.smembers.assert_called_once_with("key")

    @patch("common.get_data_redis_wrapper")
    def test_returns_empty_set_on_exception(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.smembers.side_effect = Exception("Redis error")

        assert common.get_redis_set_data("key") == set()


# ============================================================================
# delete_redis_key
# ============================================================================

class TestDeleteRedisKey:
    @patch("common.get_data_redis_wrapper")
    def test_returns_true_on_success(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w

        assert common.delete_redis_key("key") is True
        w.delete.assert_called_once_with("key")

    @patch("common.get_data_redis_wrapper")
    def test_returns_false_on_exception(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.delete.side_effect = Exception("Redis down")

        assert common.delete_redis_key("key") is False


# ============================================================================
# get_from_setting_cache
# ============================================================================

class TestGetFromSettingCache:
    @patch("common.get_setting_wrapper")
    def test_returns_int(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.hget_int.return_value = 42

        result = common.get_from_setting_cache("cache_key", "domain")

        assert result == 42
        w.hget_int.assert_called_once_with("cache_key", "domain")

    @patch("common.get_setting_wrapper")
    def test_returns_none_when_missing(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.hget_int.return_value = None

        assert common.get_from_setting_cache("cache_key", "missing") is None

    @patch("common.get_setting_wrapper")
    def test_returns_none_on_exception(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.hget_int.side_effect = Exception("Redis error")

        assert common.get_from_setting_cache("cache_key", "field") is None


# ============================================================================
# set_to_setting_cache
# ============================================================================

class TestSetToSettingCache:
    @patch("common.get_setting_wrapper")
    def test_calls_hset_int(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w

        common.set_to_setting_cache("cache_key", "domain", 99)

        w.hset_int.assert_called_once_with("cache_key", "domain", 99)

    @patch("common.get_setting_wrapper")
    def test_returns_none(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w

        assert common.set_to_setting_cache("cache_key", "field", 42) is None

    @patch("common.get_setting_wrapper")
    def test_does_not_raise_on_exception(self, mock_get):
        w = _mock_wrapper()
        mock_get.return_value = w
        w.hset_int.side_effect = Exception("Redis error")

        result = common.set_to_setting_cache("cache_key", "field", 7)

        assert result is None
        w.hset_int.assert_called_once_with("cache_key", "field", 7)