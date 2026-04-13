from datetime import datetime

import pytest
import json
from unittest.mock import patch, MagicMock, call
from botocore.exceptions import ClientError

import lambda_function
from lambda_function import HeatMapUrlConfigurationDTO


class TestLambdaHandler:

    @patch("lambda_function.RedisUtils")
    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.auto_update_site_setup")
    @patch("lambda_function.auto_check_limit")
    @patch("lambda_function.make_key_url")
    def test_lambda_handler_success(
            self, mock_make_key_url, mock_auto_check_limit, mock_auto_update_site_setup,
            mock_get_db_connection, mock_get_secret, mock_get_region, mock_redis_utils
    ):
        """Test successful Lambda execution"""
        mock_get_region.return_value = "ap-northeast-1"
        mock_get_secret.return_value = {"host": "test-db"}

        mock_conn = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_redis_utils.return_value = MagicMock()

        result = lambda_function.lambda_handler()

        assert result["statusCode"] == 200
        assert "Check Limit successfully executed" in result["body"]
        mock_get_secret.assert_called_once()
        mock_get_db_connection.assert_called_once()
        mock_auto_update_site_setup.assert_called_once()
        mock_auto_check_limit.assert_called_once()
        mock_make_key_url.assert_called_once()
        mock_redis_utils.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret", side_effect=Exception("secret error"))
    def test_lambda_handler_error_before_db_connection(self, mock_secret, mock_region):
        """If error occurs before DB connection, should still raise and not crash on close"""
        mock_region.return_value = "ap-northeast-1"

        with pytest.raises(Exception, match="secret error"):
            lambda_function.lambda_handler(event={"x": 1}, context=None)

    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection", side_effect=Exception("DB connection error"))
    def test_lambda_handler_error_on_db_connection(
            self, mock_get_db_connection, mock_get_secret, mock_get_region
    ):
        """Test Lambda handles errors when DB connection fails"""
        mock_get_region.return_value = "ap-northeast-1"
        mock_get_secret.return_value = {"host": "test-db"}

        with pytest.raises(Exception, match="DB connection error"):
            lambda_function.lambda_handler()

    @patch("lambda_function.RedisUtils")
    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.auto_update_site_setup")
    @patch("lambda_function.auto_check_limit")
    @patch("lambda_function.make_key_url")
    def test_lambda_handler_returns_execution_time(
            self, mock_make_key_url, mock_auto_check_limit, mock_auto_update_site_setup,
            mock_get_db_connection, mock_get_secret, mock_get_region, mock_redis_utils
    ):
        """Test Lambda returns execution time in response"""
        mock_get_region.return_value = "ap-northeast-1"
        mock_get_secret.return_value = {"host": "test-db"}

        mock_conn = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_redis_utils.return_value = MagicMock()

        result = lambda_function.lambda_handler()

        body = json.loads(result["body"])
        assert "execute_time" in body
        assert isinstance(body["execute_time"], (int, float))

    @patch("lambda_function.RedisUtils")
    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.auto_update_site_setup")
    @patch("lambda_function.auto_check_limit")
    @patch("lambda_function.make_key_url")
    def test_lambda_handler_with_event_and_context(
            self, mock_make_key_url, mock_auto_check_limit, mock_auto_update_site_setup,
            mock_get_db_connection, mock_get_secret, mock_get_region, mock_redis_utils
    ):
        """Test Lambda handler accepts event and context parameters"""
        mock_get_region.return_value = "ap-northeast-1"
        mock_get_secret.return_value = {"host": "test-db"}

        mock_conn = MagicMock()
        mock_get_db_connection.return_value = mock_conn
        mock_redis_utils.return_value = MagicMock()

        mock_context = MagicMock()
        mock_context.function_name = "CheckLimitLambda"

        result = lambda_function.lambda_handler(event={"key": "value"}, context=mock_context)

        assert result["statusCode"] == 200


class TestGetSecret:
    """Test AWS Secrets Manager"""

    @patch("boto3.client")
    def test_get_secret_success(self, mock_boto_client):
        """Test successful secret retrieval"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({
                "host": "test-db.rds.amazonaws.com",
                "username": "root",
                "password": "root",
                "port": 3306,
                "dbname": "HEAT_MAP",
            })
        }

        result = lambda_function.get_secret("ap-northeast-1")

        assert result["host"] == "test-db.rds.amazonaws.com"
        assert result["username"] == "root"
        assert result["dbname"] == "HEAT_MAP"
        mock_boto_client.assert_called_once()

    @patch("boto3.client")
    def test_get_secret_access_denied(self, mock_boto_client):
        """Test Secrets Manager access denied"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        error_response = {
            "Error": {"Code": "AccessDeniedException", "Message": "User is not authorized"}
        }
        mock_client.get_secret_value.side_effect = ClientError(error_response, "GetSecretValue")

        with pytest.raises(ClientError) as exc_info:
            lambda_function.get_secret("ap-northeast-1")

        assert "AccessDeniedException" in str(exc_info.value)

    @patch("boto3.client")
    def test_get_secret_not_found(self, mock_boto_client):
        """Test secret not found"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        error_response = {
            "Error": {"Code": "ResourceNotFoundException", "Message": "Secret not found"}
        }
        mock_client.get_secret_value.side_effect = ClientError(error_response, "GetSecretValue")

        with pytest.raises(ClientError) as exc_info:
            lambda_function.get_secret("ap-northeast-1")

        assert "ResourceNotFoundException" in str(exc_info.value)


class TestGetDBConnection:
    """Test database connection"""

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_get_db_connection_success(self, mock_connect, mock_ssl):
        """Test successful DB connection"""
        mock_ssl.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        secret = {
            "host": "test-db.rds.amazonaws.com",
            "port": 3306,
            "username": "heatmap_admin",
            "password": "secret",
            "dbname": "HEAT_MAP",
        }

        result = lambda_function.get_db_connection(secret)

        assert result == mock_conn
        mock_connect.assert_called_once()

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_get_db_connection_operational_error(self, mock_connect, mock_ssl):
        """Test DB connection operational error"""
        import pymysql

        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(2003, "Can't connect")

        secret = {"host": "test", "username": "user", "password": "pass"}

        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_db_connection_access_denied(self, mock_connect, mock_ssl):
        """Test access denied (wrong credentials)"""
        import pymysql

        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(1045, "Access denied for user")

        secret = {"host": "db.amazonaws.com", "username": "wrong", "password": "wrong"}

        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_db_connection_other_error(self, mock_connect, mock_ssl):
        """Test generic DB operational error"""
        import pymysql

        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(500, "Generic database error")

        secret = {"host": "db.amazonaws.com", "username": "wrong", "password": "wrong"}

        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_db_connection_generic_exception(self, mock_connect, mock_ssl):
        """Test generic exception"""
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = Exception("Unexpected error")

        secret = {"host": "db.amazonaws.com", "username": "user", "password": "pass"}

        with pytest.raises(Exception, match="Unexpected error"):
            lambda_function.get_db_connection(secret)


class TestGetSSLContext:
    """Test SSL context creation"""

    @patch("os.path.exists")
    @patch("ssl.SSLContext")
    def test_get_ssl_context_region_bundle(self, mock_ssl_context, mock_exists):
        """Test SSL context with region-specific bundle"""
        mock_exists.return_value = True
        mock_ctx = MagicMock()
        mock_ssl_context.return_value = mock_ctx

        result = lambda_function.get_ssl_context("ap-northeast-1")

        assert result == mock_ctx
        mock_ctx.load_verify_locations.assert_called_once()

    @patch("os.path.exists")
    def test_get_ssl_context_missing_bundle(self, mock_exists):
        """Test SSL context with missing bundle"""
        mock_exists.return_value = False

        with pytest.raises(FileNotFoundError, match="CA bundle not found"):
            lambda_function.get_ssl_context("ap-northeast-1")

    @patch.dict("os.environ", {}, clear=True)
    def test_default_region_when_not_set(self):
        """Test default region when AWS_REGION not set"""
        result = lambda_function.get_region()
        assert result == "ap-northeast-1"


class TestRunStep:
    """Test step execution wrapper"""

    def test_run_step_success(self):
        """Test successful step execution"""
        result = lambda_function.run_step("test_step", lambda: 5)
        assert result == 5

    def test_run_step_with_error(self):
        """Test step execution with error"""
        def error_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            lambda_function.run_step("error_step", error_func)


class TestGetRedisClient:
    """Test Redis client creation in lambda_handler"""

    @patch("lambda_function.auto_update_site_setup")
    @patch("lambda_function.auto_check_limit")
    @patch("lambda_function.make_key_url")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_region")
    @patch("lambda_function.RedisUtils")
    def test_lambda_handler_passes_redis_env(
            self, mock_redis_utils, mock_get_region, mock_get_secret, mock_get_db_connection,
            mock_make_key_url, mock_auto_check_limit, mock_auto_update_site_setup, monkeypatch
    ):
        monkeypatch.setenv("REDIS_HOST", "redis.local")
        monkeypatch.setenv("REDIS_PORT", "6380")
        monkeypatch.setenv("REDIS_PASSWORD", "pw")
        monkeypatch.setenv("REDIS_DB", "2")

        mock_get_region.return_value = "ap-northeast-1"
        mock_get_secret.return_value = {"host": "test-db"}
        mock_get_db_connection.return_value = MagicMock()

        lambda_function.lambda_handler()

        mock_redis_utils.assert_called_once_with("redis.local", 6380, "pw", 2)


class TestRefreshRedisBySite:
    """Test Redis refresh by site"""

    def test_refresh_redis_by_site_success_sorted_and_written(self):
        domain_id = "d1"
        urls = [
            HeatMapUrlConfigurationDTO(url_id=2, url="https://example.com/b", expression="-",
                                       param_config="-", sort_item="example.com/b"),
            HeatMapUrlConfigurationDTO(url_id=10, url="https://example.com/z", expression="-",
                                       param_config="-", sort_item="example.com/z"),
            HeatMapUrlConfigurationDTO(url_id=5, url="https://example.com/m", expression="-",
                                       param_config="-", sort_item="example.com/m"),
        ]

        dao = MagicMock()
        dao.get_list_heat_map_url_configuration_by_domain_id.return_value = urls
        rds = MagicMock()

        result = lambda_function.refresh_redis_by_site(dao, rds, domain_id)

        assert result == 3
        rds.delete.assert_called_once_with(f"url_{domain_id}")
        dao.get_list_heat_map_url_configuration_by_domain_id.assert_called_once_with(domain_id)

        expected_calls = [
            call(f"url_{domain_id}", "10;_;https://example.com/z;_;-;_;-", 0),
            call(f"url_{domain_id}", "5;_;https://example.com/m;_;-;_;-", 1),
            call(f"url_{domain_id}", "2;_;https://example.com/b;_;-;_;-", 2),
        ]
        rds.zadd.assert_has_calls(expected_calls, any_order=False)

    def test_refresh_redis_by_site_empty_list(self):
        domain_id = "d2"
        dao = MagicMock()
        dao.get_list_heat_map_url_configuration_by_domain_id.return_value = []
        rds = MagicMock()

        result = lambda_function.refresh_redis_by_site(dao, rds, domain_id)

        assert result == 0
        rds.delete.assert_called_once_with(f"url_{domain_id}")
        rds.zadd.assert_not_called()


class TestHeatMapUrlConfigurationDTO:
    """Test HeatMapUrlConfigurationDTO"""

    @pytest.mark.parametrize("url,expected_sort_item", [
        ("https://example.com/path", "example.com/path"),
        ("https://www.example.com/path", "example.com/path"),
        ("https://www2.example.com/path", "example.com/path"),
        ("example.com/path", "example.com/path"),
        ("", ""),
        (None, ""),
    ])
    def test_from_row_sort_item_strip_domain_prefix(self, url, expected_sort_item):
        dto = HeatMapUrlConfigurationDTO.from_row(
            url_id=1, url=url, expression="exp", param_config="pc"
        )
        assert dto.sort_item == expected_sort_item

    def test_from_row_defaults_when_none(self):
        dto = HeatMapUrlConfigurationDTO.from_row(
            url_id="123", url=None, expression=None, param_config=None
        )
        assert dto.url_id == 123
        assert dto.url == ""
        assert dto.expression == "-"
        assert dto.param_config == "-"
        assert dto.sort_item == ""

    def test_to_redis_member_format(self):
        dto = HeatMapUrlConfigurationDTO(
            url_id=7, url="https://www.example.com/a", expression="^/a$",
            param_config="k=v", sort_item="example.com/a"
        )
        assert dto.to_redis_member() == "7;_;https://www.example.com/a;_;^/a$;_;k=v"

    def test_dataclass_is_frozen(self):
        dto = HeatMapUrlConfigurationDTO.from_row(
            url_id=1, url="https://example.com", expression="exp", param_config="pc"
        )
        with pytest.raises((AttributeError, TypeError)):
            dto.url = "changed"


class TestGetRegion:
    """Test region retrieval"""

    def test_get_region_default(self, monkeypatch):
        monkeypatch.delenv("AWS_REGION", raising=False)
        assert lambda_function.get_region() == "ap-northeast-1"

    def test_get_region_from_env(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-west-2")
        assert lambda_function.get_region() == "us-west-2"


class FixedDateTime(datetime):
    """Helper class to monkeypatch datetime.now()"""
    @classmethod
    def now(cls, tz=None):
        return cls._now


class TestAutoUpdateSiteSetup:
    """Test auto_update_site_setup"""

    def test_auto_update_site_setup_updates_and_deletes(self, monkeypatch):
        FixedDateTime._now = datetime(2026, 2, 24, 10, 30, 0)
        monkeypatch.setattr(lambda_function, "datetime", FixedDateTime)

        sites = [
            lambda_function.HMSiteDTO(site_id="1", package_code="", ip_block="", is_delete=1),
            lambda_function.HMSiteDTO(site_id="2", package_code="PKG", ip_block="mock-ip", is_delete=0),
            lambda_function.HMSiteDTO(site_id="3", package_code="", ip_block="", is_delete=0),
        ]
        dao = MagicMock()
        dao.get_list_heat_map_site_modify.return_value = sites
        rds = MagicMock()

        lambda_function.auto_update_site_setup(dao, rds)

        dao.get_list_heat_map_site_modify.assert_called_once_with("09")
        rds.hdel.assert_has_calls([call("list_sites_setup", "1"), call("list_ip_block", "1")], any_order=False)
        rds.delete.assert_called_once_with("url_1")
        rds.hset_str.assert_has_calls([
            call("list_sites_setup", "2", "PKG"),
            call("list_ip_block", "2", "mock-ip"),
            call("list_sites_setup", "3", ""),
            call("list_ip_block", "3", ""),
        ], any_order=False)

    def test_auto_update_site_setup_exception_re_raises(self, monkeypatch):
        FixedDateTime._now = datetime(2026, 2, 24, 10, 0, 0)
        monkeypatch.setattr(lambda_function, "datetime", FixedDateTime)

        dao = MagicMock()
        dao.get_list_heat_map_site_modify.side_effect = Exception("boom")
        rds = MagicMock()

        with pytest.raises(Exception, match="boom"):
            lambda_function.auto_update_site_setup(dao, rds)


class TestAutoCheckLimit:
    """Test auto_check_limit"""

    def test_auto_check_limit_within_and_exceeded(self, monkeypatch):
        FixedDateTime._now = datetime(2026, 2, 24, 12, 0, 0)
        monkeypatch.setattr(lambda_function, "datetime", FixedDateTime)

        packages = [
            lambda_function.PackageLimitDTO(package_code="A", limit_request=100, time_delete_data=30, profile_id=""),
            lambda_function.PackageLimitDTO(package_code="B", limit_request=10, time_delete_data=30, profile_id=""),
        ]
        dao = MagicMock()
        dao.get_list_package_limit.return_value = packages
        rds = MagicMock()

        def get_int_side_effect(key):
            return {"pageview_A_202602": 50, "pageview_B_202602": 10}.get(key, 0)

        rds.get_int.side_effect = get_int_side_effect

        lambda_function.auto_check_limit(dao, rds)

        rds.hset_str.assert_has_calls([
            call("list_packages_quota", "A", "100"),
            call("list_packages_quota", "B", "10"),
            call("list_packages_limit", "B", "1"),
        ], any_order=False)
        rds.hdel.assert_called_once_with("list_packages_limit", "A")

    def test_auto_check_limit_exception_re_raises(self):
        dao = MagicMock()
        dao.get_list_package_limit.side_effect = Exception("boom")
        rds = MagicMock()

        with pytest.raises(Exception, match="boom"):
            lambda_function.auto_check_limit(dao, rds)


class TestMakeKeyUrl:
    """Test make_key_url"""

    def test_make_key_url_calls_refresh_for_each_domain(self, monkeypatch):
        cnx = MagicMock()
        dao = MagicMock()
        dao.get_list_heat_map_site_update.return_value = ["d1", "d2", "d3"]
        rds = MagicMock()

        refresh = MagicMock(side_effect=[2, 0, 5])
        monkeypatch.setattr(lambda_function, "refresh_redis_by_site", refresh)

        lambda_function.make_key_url(dao, rds)

        refresh.assert_has_calls([call(dao, rds, "d1"), call(dao, rds, "d2"), call(dao, rds, "d3")], any_order=False)
        assert refresh.call_count == 3

    def test_make_key_url_exception_re_raises(self):
        dao = MagicMock()
        dao.get_list_heat_map_site_update.side_effect = Exception("boom")
        rds = MagicMock()
        cnx = MagicMock()

        with pytest.raises(Exception, match="boom"):
            lambda_function.make_key_url(dao, rds)


def _mock_db_with_rows(rows):
    """Create a fake db_conn with cursor context manager returning rows."""
    cur = MagicMock()
    cur.fetchall.return_value = rows

    cm = MagicMock()
    cm.__enter__.return_value = cur
    cm.__exit__.return_value = False

    db = MagicMock()
    db.cursor.return_value = cm
    return db, cur


class TestHeatMapDAO:
    """Test HeatMapDAO methods"""

    def test_get_list_heat_map_site_modify_dict_rows(self):
        rows = [
            {"SITE_ID": 1, "PACKAGE_CODE": "PKG1", "IP_BLOCK": "mock-ip", "IS_DELETE": 0},
            {"SITE_ID": "2", "PACKAGE_CODE": None, "IP_BLOCK": None, "IS_DELETE": None},
        ]
        db, cur = _mock_db_with_rows(rows)

        dao = lambda_function.HeatMapDAO(db)
        out = dao.get_list_heat_map_site_modify(hour="09")

        assert cur.execute.call_args[0][1] == ("09",)
        assert len(out) == 2
        assert out[0].site_id == "1"
        assert out[0].package_code == "PKG1"
        assert out[1].package_code == ""

    def test_get_list_heat_map_site_modify_tuple_rows(self):
        rows = [(1, "PKG1", "mock-ip", 1), ("2", None, None, None)]
        db, cur = _mock_db_with_rows(rows)

        dao = lambda_function.HeatMapDAO(db)
        out = dao.get_list_heat_map_site_modify(hour="13")

        assert len(out) == 2
        assert out[0].is_delete == 1
        assert out[1].is_delete == 0

    def test_get_list_package_limit_dict_rows(self, monkeypatch):
        rows = [{"PACKAGE_CODE": "A", "LIMIT_REQUEST": 100, "TIME_DELETE_DATA": 7, "PROFILE_ID": "p1"}]
        db, cur = _mock_db_with_rows(rows)

        monkeypatch.setattr(lambda_function, "DEFAULT_LIMIT_REQUEST", 999, raising=False)
        monkeypatch.setattr(lambda_function, "DEFAULT_TIME_DELETE_DATA", 30, raising=False)
        monkeypatch.setattr(lambda_function, "DEFAULT_PROFILE_ID", "default_profile", raising=False)

        dao = lambda_function.HeatMapDAO(db)
        out = dao.get_list_package_limit()

        assert len(out) == 1
        assert out[0].package_code == "A"
        assert out[0].limit_request == 100

    def test_get_list_heat_map_site_update_dict_rows(self):
        rows = [{"DOMAIN_ID": 1}, {"DOMAIN_ID": "abc"}]
        db, cur = _mock_db_with_rows(rows)

        dao = lambda_function.HeatMapDAO(db)
        out = dao.get_list_heat_map_site_update()

        assert out == ["1", "abc"]

    def test_get_list_heat_map_url_configuration_by_domain_id_dict_rows(self, monkeypatch):
        rows = [
            {"URL_ID": "10", "URL": "https://www.example.com/a", "EXPRESSION": None, "PARAM_CONFIG": "pc"},
            {"URL_ID": 11, "URL": "https://example.com/b", "EXPRESSION": "^/b$", "PARAM_CONFIG": None},
        ]
        db, cur = _mock_db_with_rows(rows)

        from_row_spy = MagicMock(side_effect=HeatMapUrlConfigurationDTO.from_row)
        monkeypatch.setattr(HeatMapUrlConfigurationDTO, "from_row", from_row_spy)

        dao = lambda_function.HeatMapDAO(db)
        out = dao.get_list_heat_map_url_configuration_by_domain_id("d1")

        assert cur.execute.call_args[0][1] == ("d1",)
        assert len(out) == 2


class TestRedisUtils:
    """Redis wrapper is tested in tests/test_redis_wrapper.py; keep alias contract here."""

    def test_redis_utils_alias(self):
        from redis_utils import RedisWrapper

        assert lambda_function.RedisUtils is RedisWrapper
