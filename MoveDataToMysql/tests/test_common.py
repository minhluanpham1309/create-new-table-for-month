"""
Unit tests for MoveDataToMysql common.py

Test Categories:
- Constants & Enums: ReferrerDomainType, CacheType, constant values
- AWS Helpers: get_region, get_secret
- SSL / DB Connection: get_ssl_context, get_db_connection
- Step Runner: run_step
- Redis Helpers: get_redis_client, get_max_workers, scan_redis_keys,
                 get_redis_set_data, delete_redis_key,
                 get_from_redis_cache, set_to_redis_cache

All tests use mocks to avoid external dependencies (no real DB/Redis/AWS connections).
"""

import json
import os
import ssl
import pytest
from unittest.mock import patch, MagicMock
import pymysql
from botocore.exceptions import ClientError

import common


# ===========================================================================
# Helpers
# ===========================================================================

def _reset_secret_cache():
    common._secret_cache = None


def _reset_redis_singletons():
    common._redis_client = None
    common._package_redis_client = None


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
    """Test get_secret – AWS Secrets Manager helper."""

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
                "password": "secret123",
            })
        }

        result = common.get_secret("ap-northeast-1")

        assert result["host"] == "test-db.rds.amazonaws.com"
        assert result["username"] == "admin"
        assert result["password"] == "secret123"
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
    """Test get_ssl_context."""

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


class TestGetRedisClient:
    """Test get_redis_client singleton."""

    def setup_method(self):
        _reset_redis_singletons()

    def teardown_method(self):
        _reset_redis_singletons()

    @patch.dict(os.environ, {"REDIS_HOST": "localhost", "REDIS_PORT": "6379"})
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_creates_singleton(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_rc = MagicMock()
        mock_redis_cls.return_value = mock_rc

        c1 = common.get_redis_client()
        c2 = common.get_redis_client()

        assert c1 is c2
        mock_pool_cls.assert_called_once()
        mock_redis_cls.assert_called_once()

    @patch.dict(os.environ, {"REDIS_HOST": "localhost"})
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_raises_on_ping_failure(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_rc = MagicMock()
        mock_rc.ping.side_effect = Exception("Connection refused")
        mock_redis_cls.return_value = mock_rc

        with pytest.raises(Exception, match="Connection refused"):
            common.get_redis_client()

    @patch.dict(os.environ, {"REDIS_HOST": "main-redis", "REDIS_PORT": "6380", "REDIS_PASSWORD": "pass"})
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_uses_correct_env_vars(self, mock_pool_cls, mock_redis_cls):
        """get_redis_client passes REDIS_HOST/PORT/PASSWORD with db=1."""
        mock_pool_cls.return_value = MagicMock()
        mock_redis_cls.return_value = MagicMock()

        common.get_redis_client()

        call_kwargs = mock_pool_cls.call_args[1]
        assert call_kwargs["host"] == "main-redis"
        assert call_kwargs["port"] == 6380
        assert call_kwargs["password"] == "pass"
        assert call_kwargs["db"] == 1


class TestGetPackageRedisClient:
    """Test get_package_redis_client singleton."""

    def setup_method(self):
        _reset_redis_singletons()

    def teardown_method(self):
        _reset_redis_singletons()

    @patch.dict(os.environ, {"PACKAGE_REDIS_HOST": "pkg-redis", "PACKAGE_REDIS_PORT": "6379"})
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_creates_singleton(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_rc = MagicMock()
        mock_redis_cls.return_value = mock_rc

        c1 = common.get_package_redis_client()
        c2 = common.get_package_redis_client()

        assert c1 is c2
        mock_pool_cls.assert_called_once()
        mock_redis_cls.assert_called_once()

    @patch.dict(os.environ, {"PACKAGE_REDIS_HOST": "pkg-redis"})
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_raises_on_ping_failure(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_rc = MagicMock()
        mock_rc.ping.side_effect = Exception("Connection refused")
        mock_redis_cls.return_value = mock_rc

        with pytest.raises(Exception, match="Connection refused"):
            common.get_package_redis_client()

    @patch.dict(os.environ, {
        "PACKAGE_REDIS_HOST": "pkg-redis",
        "PACKAGE_REDIS_PORT": "6379",
        "PACKAGE_REDIS_PASSWORD": "pkgpass",
    })
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_uses_correct_env_vars(self, mock_pool_cls, mock_redis_cls):
        """get_package_redis_client passes PACKAGE_REDIS_HOST/PORT/PASSWORD with db=0."""
        mock_pool_cls.return_value = MagicMock()
        mock_redis_cls.return_value = MagicMock()

        common.get_package_redis_client()

        call_kwargs = mock_pool_cls.call_args[1]
        assert call_kwargs["host"] == "pkg-redis"
        assert call_kwargs["port"] == 6379
        assert call_kwargs["password"] == "pkgpass"
        assert call_kwargs["db"] == 0

    @patch.dict(os.environ, {"PACKAGE_REDIS_HOST": "pkg-redis", "REDIS_HOST": "main-redis"})
    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_independent_from_main_redis(self, mock_pool_cls, mock_redis_cls):
        """Package Redis client is a separate singleton from the main Redis client."""
        mock_pool_cls.return_value = MagicMock()
        main_rc = MagicMock()
        pkg_rc = MagicMock()
        mock_redis_cls.side_effect = [main_rc, pkg_rc]

        main = common.get_redis_client()
        pkg = common.get_package_redis_client()

        assert main is not pkg


class TestCreateRedisClient:
    """Test _create_redis_client shared factory."""

    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_creates_pool_with_correct_params(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_redis_cls.return_value = MagicMock()

        common._create_redis_client("my-host", 6379, "secret", 2, "Test")

        call_kwargs = mock_pool_cls.call_args[1]
        assert call_kwargs["host"] == "my-host"
        assert call_kwargs["port"] == 6379
        assert call_kwargs["password"] == "secret"
        assert call_kwargs["db"] == 2
        assert call_kwargs["decode_responses"] is True
        assert call_kwargs["max_connections"] == 20

    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_calls_ping_on_new_client(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_rc = MagicMock()
        mock_redis_cls.return_value = mock_rc

        common._create_redis_client("host", 6379, None, 0, "Label")

        mock_rc.ping.assert_called_once()

    @patch("redis.Redis")
    @patch("redis.ConnectionPool")
    def test_returns_redis_client(self, mock_pool_cls, mock_redis_cls):
        mock_pool_cls.return_value = MagicMock()
        mock_rc = MagicMock()
        mock_redis_cls.return_value = mock_rc

        result = common._create_redis_client("host", 6379, None, 1, "Main")

        assert result is mock_rc


class TestScanRedisKeys:
    """Test scan_redis_keys."""

    @patch("common.get_redis_client")
    def test_accumulates_all_pages(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.scan.side_effect = [
            (1, ["key:1", "key:2"]),
            (0, ["key:3"]),
        ]

        result = common.scan_redis_keys("key:*")

        assert sorted(result) == ["key:1", "key:2", "key:3"]
        assert mock_rc.scan.call_count == 2

    @patch("common.get_redis_client")
    def test_returns_empty_list_when_no_match(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.scan.return_value = (0, [])

        result = common.scan_redis_keys("nonexistent:*")

        assert result == []


class TestGetRedisSetData:
    """Test get_redis_set_data."""

    @patch("common.get_redis_client")
    def test_returns_members(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.smembers.return_value = {"a", "b", "c"}

        result = common.get_redis_set_data("my_key")

        assert result == {"a", "b", "c"}
        mock_rc.smembers.assert_called_once_with("my_key")

    @patch("common.get_redis_client")
    def test_returns_empty_set_when_key_empty(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.smembers.return_value = set()

        assert common.get_redis_set_data("empty_key") == set()

    @patch("common.get_redis_client")
    def test_returns_empty_set_on_exception(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.smembers.side_effect = Exception("Redis error")

        assert common.get_redis_set_data("err_key") == set()


class TestDeleteRedisKey:
    """Test delete_redis_key."""

    @patch("common.get_redis_client")
    def test_returns_true_on_success(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc

        result = common.delete_redis_key("del_key")

        assert result is True
        mock_rc.delete.assert_called_once_with("del_key")

    @patch("common.get_redis_client")
    def test_returns_false_on_exception(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.delete.side_effect = Exception("Redis down")

        assert common.delete_redis_key("bad_key") is False


class TestGetFromRedisCache:
    """Test get_from_redis_cache."""

    @patch("common.get_redis_client")
    def test_returns_int_when_field_exists(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.hget.return_value = "42"

        result = common.get_from_redis_cache("my_cache", "field1")

        assert result == 42
        mock_rc.hget.assert_called_once_with("my_cache", "field1")

    @patch("common.get_redis_client")
    def test_returns_none_when_field_missing(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.hget.return_value = None

        assert common.get_from_redis_cache("my_cache", "missing") is None

    @patch("common.get_redis_client")
    def test_returns_none_on_exception(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.hget.side_effect = Exception("Redis error")

        assert common.get_from_redis_cache("my_cache", "field1") is None


class TestSetToRedisCache:
    """Test set_to_redis_cache."""

    @patch("common.get_redis_client")
    def test_calls_hset_with_string_value(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc

        common.set_to_redis_cache("my_cache", "field1", 99)

        mock_rc.hset.assert_called_once_with("my_cache", "field1", "99")

    @patch("common.get_redis_client")
    def test_swallows_exception_silently(self, mock_get_rc):
        mock_rc = MagicMock()
        mock_get_rc.return_value = mock_rc
        mock_rc.hset.side_effect = Exception("Redis down")

        # Must not raise
        common.set_to_redis_cache("my_cache", "field1", 1)

