import pytest
import json
from unittest.mock import Mock, patch, call
import sys
import os
import pymysql

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))
import lambda_function


# ===========================================================================
# FIXTURES
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_redis_client():
    original = lambda_function.redis_client
    yield
    lambda_function.redis_client = original


@pytest.fixture
def mock_secret():
    return {
        'host': 'test-db.amazonaws.com', 'port': 3306,
        'username': 'testuser', 'password': 'testpass', 'dbname': 'testdb'
    }


@pytest.fixture
def mock_db_connection():
    conn = Mock()
    cur = Mock()
    conn.cursor.return_value.__enter__ = Mock(return_value=cur)
    conn.cursor.return_value.__exit__ = Mock(return_value=False)
    conn.autocommit = Mock()
    conn.commit = Mock()
    conn.rollback = Mock()
    return conn, cur


@pytest.fixture
def mock_redis():
    mock_r = Mock()
    lambda_function.redis_client = mock_r
    return mock_r


# ===========================================================================
# LAMBDA HANDLER
# ===========================================================================

class TestLambdaHandler:

    @patch.dict(os.environ, {'AWS_REGION': 'ap-northeast-1'})
    def test_get_region(self):
        assert lambda_function.get_region() == 'ap-northeast-1'

    @patch.dict(os.environ, {}, clear=True)
    def test_get_region_default(self):
        assert lambda_function.get_region() == 'ap-northeast-1'

    @patch('boto3.client')
    def test_get_secret_success(self, mock_boto_client, mock_secret):
        mock_client = Mock()
        mock_client.get_secret_value.return_value = {'SecretString': json.dumps(mock_secret)}
        mock_boto_client.return_value = mock_client
        assert lambda_function.get_secret('ap-northeast-1') == mock_secret

    def test_run_step_success(self):
        assert lambda_function.run_step("test", lambda x, y: x + y, 2, 3) == 5

    def test_run_step_failure(self):
        with pytest.raises(ValueError):
            lambda_function.run_step("test", lambda: (_ for _ in ()).throw(ValueError("err")))

    @patch('lambda_function.execute_move_data', return_value={'successful': 1, 'failed': 0})
    @patch('lambda_function.init_redis_connection')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_secret', return_value={})
    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    def test_lambda_handler_success(self, mock_region, mock_secret_fn, mock_db,
                                    mock_redis_init, mock_move):
        mock_conn = Mock()
        mock_db.return_value = mock_conn
        result = lambda_function.lambda_handler()
        assert result['statusCode'] == 200
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch('lambda_function.get_secret', side_effect=Exception("secret error"))
    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    def test_lambda_handler_exception_triggers_rollback(self, mock_region, mock_secret_fn):
        with pytest.raises(Exception):
            lambda_function.lambda_handler()

    @patch('lambda_function.execute_move_data', side_effect=Exception("move error"))
    @patch('lambda_function.init_redis_connection')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_secret', return_value={})
    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    def test_lambda_handler_cleanup_in_finally(self, mock_region, mock_secret_fn,
                                               mock_db, mock_redis_init, mock_move):
        mock_conn = Mock()
        mock_db.return_value = mock_conn
        with pytest.raises(Exception):
            lambda_function.lambda_handler()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


# ===========================================================================
# SSL / DB CONNECTION
# ===========================================================================

class TestSSLAndDBConnection:

    def test_get_ssl_context_region_specific_exists(self):
        with patch('os.path.exists', return_value=True):
            with patch('ssl.SSLContext') as mock_ctx:
                mock_ctx.return_value = Mock()
                lambda_function.get_ssl_context('ap-northeast-1')
                mock_ctx.assert_called_once()

    def test_get_ssl_context_falls_back_to_global(self):
        with patch('os.path.exists', side_effect=[False, True]):
            with patch('ssl.SSLContext') as mock_ctx:
                mock_ctx.return_value = Mock()
                lambda_function.get_ssl_context('ap-northeast-1')
                mock_ctx.assert_called_once()

    def test_get_ssl_context_no_bundle_raises(self):
        with patch('os.path.exists', return_value=False):
            with pytest.raises(FileNotFoundError):
                lambda_function.get_ssl_context()

    def test_get_ssl_context_ssl_exception(self):
        with patch('os.path.exists', return_value=True):
            with patch('ssl.SSLContext', side_effect=Exception("ssl err")):
                with pytest.raises(Exception):
                    lambda_function.get_ssl_context()

    def test_get_db_connection_success(self, mock_secret):
        with patch('lambda_function.get_ssl_context', return_value=Mock()):
            with patch('pymysql.connect', return_value=Mock()):
                conn = lambda_function.get_db_connection(mock_secret)
                assert conn is not None

    @pytest.mark.parametrize("error_code", [2003, 1045, 2013])
    def test_get_db_connection_operational_errors(self, mock_secret, error_code):
        with patch('lambda_function.get_ssl_context', return_value=Mock()):
            with patch('pymysql.connect',
                       side_effect=pymysql.err.OperationalError(error_code, "err")):
                with pytest.raises(pymysql.err.OperationalError):
                    lambda_function.get_db_connection(mock_secret)

    def test_get_db_connection_generic_exception(self, mock_secret):
        with patch('lambda_function.get_ssl_context', return_value=Mock()):
            with patch('pymysql.connect', side_effect=Exception("generic")):
                with pytest.raises(Exception):
                    lambda_function.get_db_connection(mock_secret)


# ===========================================================================
# REDIS CONNECTION
# ===========================================================================

class TestRedisConnection:

    def test_init_redis_connection_success(self, mock_redis):
        with patch('redis.Redis', return_value=mock_redis):
            lambda_function.init_redis_connection()
            mock_redis.ping.assert_called_once()

    def test_init_redis_connection_with_password(self, mock_redis):
        with patch.dict(os.environ, {'REDIS_PASSWORD': 'secret'}):
            with patch('redis.Redis', return_value=mock_redis) as mock_cls:
                lambda_function.init_redis_connection()
                call_kwargs = mock_cls.call_args[1]
                assert call_kwargs['password'] == 'secret'

    def test_init_redis_connection_failure(self, mock_redis):
        with patch('redis.Redis', side_effect=Exception("conn refused")):
            with pytest.raises(Exception):
                lambda_function.init_redis_connection()


# ===========================================================================
# REDIS KEY OPERATIONS
# ===========================================================================

class TestRedisOperations:

    def test_get_redis_keys_success(self, mock_redis):
        mock_redis.keys.return_value = ['k1', 'k2']
        assert lambda_function.get_redis_keys('*pattern*') == ['k1', 'k2']

    def test_get_redis_keys_error(self, mock_redis):
        mock_redis.keys.side_effect = Exception("err")
        assert lambda_function.get_redis_keys('*') == []

    def test_filter_out_chunk_index_keys(self):
        keys = ['site1_2024_v', 'site1_2024_v:chunk', 'site2_2024_c']
        assert lambda_function.filter_out_chunk_index_keys(keys) == [
            'site1_2024_v', 'site2_2024_c']

    def test_get_redis_set_data_success(self, mock_redis):
        mock_redis.smembers.return_value = {'a', 'b'}
        assert lambda_function.get_redis_set_data('key') == {'a', 'b'}

    def test_get_redis_set_data_empty(self, mock_redis):
        mock_redis.smembers.return_value = set()
        assert lambda_function.get_redis_set_data('key') == set()

    def test_get_redis_set_data_error(self, mock_redis):
        mock_redis.smembers.side_effect = Exception("err")
        assert lambda_function.get_redis_set_data('key') == set()

    def test_delete_redis_key_success(self, mock_redis):
        assert lambda_function.delete_redis_key('key') is True

    def test_delete_redis_key_error(self, mock_redis):
        mock_redis.delete.side_effect = Exception("err")
        assert lambda_function.delete_redis_key('key') is False


# ===========================================================================
# DATABASE SCHEMA OPERATIONS
# ===========================================================================

class TestSchemaOperations:

    def test_get_list_schema_name_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.fetchall.return_value = [{'SCHEMA_NAME': 'db1'}, {'SCHEMA_NAME': 'db2'}]
        result = lambda_function.get_list_schema_name(conn)
        assert result == {'db1': 1, 'db2': 1}

    def test_get_list_schema_name_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("db err")
        with pytest.raises(Exception):
            lambda_function.get_list_schema_name(conn)

    def test_check_schema_exist_true(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.fetchone.return_value = {'SCHEMA_NAME': 'site1'}
        assert lambda_function.check_schema_exist(conn, 'site1') is True

    def test_check_schema_exist_false(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.fetchone.return_value = None
        assert lambda_function.check_schema_exist(conn, 'site99') is False

    def test_check_schema_exist_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("err")
        assert lambda_function.check_schema_exist(conn, 'site1') is False


# ===========================================================================
# DOMAIN / UTM CACHING
# ===========================================================================

class TestDomainUtmCaching:

    @pytest.mark.parametrize("domain,expected", [
        ('www.google.co.jp', lambda_function.ReferrerDomainType.ORGANIC),
        ('www.bing.com', lambda_function.ReferrerDomainType.ORGANIC),
        ('facebook.com', lambda_function.ReferrerDomainType.SOCIAL),
        ('t.co', lambda_function.ReferrerDomainType.SOCIAL),
        ('example.com', lambda_function.ReferrerDomainType.NONE),
        ('', lambda_function.ReferrerDomainType.NONE),
    ])
    def test_resolve_domain_type(self, domain, expected):
        assert lambda_function.resolve_domain_type(domain) == expected

    @pytest.mark.parametrize("cache_type,expected", [
        (lambda_function.CacheType.DOMAIN, lambda_function.CACHE_DOMAIN),
        (lambda_function.CacheType.UTM_SOURCE, lambda_function.CACHE_UTM_SOURCE),
        (lambda_function.CacheType.UTM_MEDIUM, lambda_function.CACHE_UTM_MEDIUM),
    ])
    def test_get_cache_key(self, cache_type, expected):
        assert lambda_function.get_cache_key(cache_type) == expected

    def test_get_cache_key_invalid_raises(self):
        class Fake:
            value = 'x'
        with pytest.raises(ValueError):
            lambda_function.get_cache_key(Fake())

    def test_get_from_redis_cache_hit(self, mock_redis):
        mock_redis.hget.return_value = '42'
        assert lambda_function.get_from_redis_cache('key', 'val') == 42

    def test_get_from_redis_cache_miss(self, mock_redis):
        mock_redis.hget.return_value = None
        assert lambda_function.get_from_redis_cache('key', 'val') is None

    def test_get_from_redis_cache_error(self, mock_redis):
        mock_redis.hget.side_effect = Exception("err")
        assert lambda_function.get_from_redis_cache('key', 'val') is None

    def test_set_to_redis_cache_success(self, mock_redis):
        lambda_function.set_to_redis_cache('key', 'val', 1)
        mock_redis.hset.assert_called_once()

    def test_set_to_redis_cache_error(self, mock_redis):
        mock_redis.hset.side_effect = Exception("err")
        lambda_function.set_to_redis_cache('key', 'val', 1)  # should not raise

    def test_get_id_cached_empty_value(self, mock_db_connection, mock_redis):
        conn, _ = mock_db_connection
        assert lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, '') is None

    def test_get_id_cached_cache_hit(self, mock_db_connection, mock_redis):
        conn, _ = mock_db_connection
        mock_redis.hget.return_value = '10'
        assert lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'x') == 10

    def test_get_id_cached_cache_miss_db_hit(self, mock_db_connection, mock_redis):
        conn, cur = mock_db_connection
        mock_redis.hget.return_value = None
        cur.lastrowid = 99
        result = lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'x.com')
        assert result == 99
        mock_redis.hset.assert_called_once()

    def test_get_id_cached_exception_propagates(self, mock_db_connection, mock_redis):
        """get_id_cached re-raises if get_cache_key or inner logic throws"""
        conn, cur = mock_db_connection
        mock_redis.hget.return_value = None
        with patch('lambda_function.save_value_to_database', side_effect=Exception("db err")):
            with pytest.raises(Exception):
                lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'x.com')

    def test_save_value_to_database_domain(self, mock_db_connection):
        conn, _ = mock_db_connection
        with patch('lambda_function.save_referrer_domain', return_value=1) as m:
            assert lambda_function.save_value_to_database(conn, lambda_function.CacheType.DOMAIN, 'g.com') == 1

    def test_save_value_to_database_utm_source(self, mock_db_connection):
        conn, _ = mock_db_connection
        with patch('lambda_function.save_utm_source', return_value=2):
            assert lambda_function.save_value_to_database(conn, lambda_function.CacheType.UTM_SOURCE, 'g') == 2

    def test_save_value_to_database_utm_medium(self, mock_db_connection):
        conn, _ = mock_db_connection
        with patch('lambda_function.save_utm_medium', return_value=3):
            assert lambda_function.save_value_to_database(conn, lambda_function.CacheType.UTM_MEDIUM, 'cpc') == 3

    def test_save_value_to_database_invalid_type(self, mock_db_connection):
        conn, _ = mock_db_connection
        class Fake:
            value = 'x'
        with pytest.raises(ValueError):
            lambda_function.save_value_to_database(conn, Fake(), 'val')

    def test_get_referrer_domain_id(self, mock_db_connection, mock_redis):
        conn, _ = mock_db_connection
        mock_redis.hget.return_value = '10'
        assert lambda_function.get_referrer_domain_id(conn, 'x.com') == 10

    def test_get_utm_source_id(self, mock_db_connection, mock_redis):
        conn, _ = mock_db_connection
        mock_redis.hget.return_value = '20'
        assert lambda_function.get_utm_source_id(conn, 'google') == 20

    def test_get_utm_medium_id(self, mock_db_connection, mock_redis):
        conn, _ = mock_db_connection
        mock_redis.hget.return_value = '30'
        assert lambda_function.get_utm_medium_id(conn, 'cpc') == 30


# ===========================================================================
# SAVE REFERRER DOMAIN / UTM SOURCE / UTM MEDIUM
# ===========================================================================

class TestSaveFunctions:

    def test_save_referrer_domain_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.lastrowid = 42
        assert lambda_function.save_referrer_domain(conn, 'google.com') == 42

    def test_save_referrer_domain_no_lastrowid(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.lastrowid = 0
        cur.fetchone.return_value = {'id': 7}
        assert lambda_function.save_referrer_domain(conn, 'example.com') == 7

    def test_save_referrer_domain_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("db err")
        assert lambda_function.save_referrer_domain(conn, 'fail.com') is None

    def test_save_utm_source_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.lastrowid = 5
        assert lambda_function.save_utm_source(conn, 'google') == 5

    def test_save_utm_source_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("utm source error")
        assert lambda_function.save_utm_source(conn, 'google') is None

    def test_save_utm_medium_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.lastrowid = 6
        assert lambda_function.save_utm_medium(conn, 'cpc') == 6

    def test_save_utm_medium_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("utm medium error")
        assert lambda_function.save_utm_medium(conn, 'cpc') is None


# ===========================================================================
# PARAMETER PAIRS
# ===========================================================================

class TestParameterPairs:

    def test_extract_empty_or_none(self):
        assert lambda_function.extract_and_create_parameter_pairs('') == []
        assert lambda_function.extract_and_create_parameter_pairs(None) == []

    def test_extract_valid_pairs(self):
        result = lambda_function.extract_and_create_parameter_pairs('page=1&limit=20')
        assert len(result) == 2
        keys = [p['key'] for p in result]
        assert 'page' in keys and 'limit' in keys
        for p in result:
            assert 'id' in p and 'key' in p and 'value' in p

    def test_extract_filters_utm(self):
        result = lambda_function.extract_and_create_parameter_pairs('page=1&utm_source=google&filter=x')
        assert len(result) == 2
        assert all(not p['key'].startswith('utm_') for p in result)

    def test_extract_url_decoded(self):
        result = lambda_function.extract_and_create_parameter_pairs('name=John%20Doe')
        assert result[0]['value'] == 'John Doe'

    def test_extract_pair_without_value(self):
        assert len(lambda_function.extract_and_create_parameter_pairs('key1=&key2=val')) == 2

    def test_extract_no_equals_sign(self):
        result = lambda_function.extract_and_create_parameter_pairs('justkey&page=1')
        assert len(result) == 1
        assert result[0]['key'] == 'page'

    def test_extract_unquote_exception_falls_back(self):
        with patch('lambda_function.unquote', side_effect=Exception("decode err")):
            result = lambda_function.extract_and_create_parameter_pairs('key=value')
            assert len(result) == 1
            assert result[0]['key'] == 'key'

    def test_extract_outer_exception_returns_empty(self):
        with patch('lambda_function.hashlib.md5', side_effect=Exception("hash err")):
            assert lambda_function.extract_and_create_parameter_pairs('key=value') == []

    def test_save_parameter_pairs_empty(self, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.save_parameter_pairs(conn, []) is True

    def test_save_parameter_pairs_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        pairs = [{'id': 'abc', 'key': 'page', 'value': '1'}]
        assert lambda_function.save_parameter_pairs(conn, pairs) is True

    def test_save_parameter_pairs_deadlock_then_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = [
            pymysql.err.OperationalError(1213, "Deadlock"),
            None, None
        ]
        pairs = [{'id': 'abc', 'key': 'page', 'value': '1'}]
        assert lambda_function.save_parameter_pairs(conn, pairs) is True

    def test_save_parameter_pairs_deadlock_retry_exceeded(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = pymysql.err.OperationalError(1213, "Deadlock")
        pairs = [{'id': 'abc', 'key': 'page', 'value': '1'}]
        assert lambda_function.save_parameter_pairs(conn, pairs) is False
        assert cur.execute.call_count == 4

    def test_save_parameter_pairs_other_operational_error(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = pymysql.err.OperationalError(2006, "Gone away")
        pairs = [{'id': 'abc', 'key': 'page', 'value': '1'}]
        assert lambda_function.save_parameter_pairs(conn, pairs) is False
        assert cur.execute.call_count == 1

    def test_save_parameter_pairs_after_deadlock_then_other_error(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = [
            pymysql.err.OperationalError(1213, "Deadlock"),
            pymysql.err.OperationalError(2006, "Gone away"),
        ]
        pairs = [{'id': 'abc', 'key': 'page', 'value': '1'}]
        assert lambda_function.save_parameter_pairs(conn, pairs) is False
        assert cur.execute.call_count == 2

    def test_save_parameter_pairs_general_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("generic")
        pairs = [{'id': 'abc', 'key': 'page', 'value': '1'}]
        assert lambda_function.save_parameter_pairs(conn, pairs) is False


# ===========================================================================
# DATA PARSING
# ===========================================================================

class TestDataParsing:

    VALID_PV = ('2024-01-01 10:00:00;-;ref123;-;http://example.com;-;url123;-;desktop'
                ';-;1920;-;192.168.1.1;-;Mozilla/5.0;-;page=1;-;google.com;-;google;-;cpc')

    def test_parse_pageview_empty(self, mock_db_connection):
        conn, _ = mock_db_connection
        result, params = lambda_function.parse_pageview_data(set(), conn)
        assert result == [] and params == []

    def test_parse_pageview_too_short(self, mock_db_connection):
        conn, _ = mock_db_connection
        result, params = lambda_function.parse_pageview_data({'a;-;b'}, conn)
        assert result == []

    def test_parse_pageview_valid_full(self, mock_db_connection):
        conn, _ = mock_db_connection
        with patch('lambda_function.get_referrer_domain_id', return_value=1):
            with patch('lambda_function.get_utm_source_id', return_value=2):
                with patch('lambda_function.get_utm_medium_id', return_value=3):
                    result, params = lambda_function.parse_pageview_data({self.VALID_PV}, conn)
        assert len(result) == 1
        assert result[0]['dateCreate'] == '2024-01-01 10:00:00'
        assert result[0]['refDomainId'] == 1
        assert result[0]['refUtmSourceId'] == 2
        assert result[0]['refUtmMediumId'] == 3

    def test_parse_pageview_domain_cached(self, mock_db_connection):
        conn, _ = mock_db_connection
        with patch('lambda_function.get_referrer_domain_id', return_value=5) as mock_domain:
            with patch('lambda_function.get_utm_source_id', return_value=6):
                with patch('lambda_function.get_utm_medium_id', return_value=7):
                    result, _ = lambda_function.parse_pageview_data({self.VALID_PV, self.VALID_PV}, conn)
        assert mock_domain.call_count == 1  # cached after first call

    def test_parse_pageview_exception_in_row(self, mock_db_connection):
        conn, _ = mock_db_connection
        with patch('lambda_function.extract_and_create_parameter_pairs',
                   side_effect=Exception("boom")):
            result, params = lambda_function.parse_pageview_data({self.VALID_PV}, conn)
        assert result == []

    def test_parse_pageview_no_domain_utm(self, mock_db_connection):
        conn, _ = mock_db_connection
        row = '2024-01-01;-;ref;-;http://x.com;-;uid;-;desktop;-;1024;-;1.2.3.4;-;ua;-;p=1'
        result, _ = lambda_function.parse_pageview_data({row}, conn)
        assert len(result) == 1
        assert 'refDomainId' not in result[0]

    def test_parse_pageview_long_ip_uses_default(self, mock_db_connection):
        conn, _ = mock_db_connection
        row = '2024-01-01;-;ref;-;http://x.com;-;uid;-;desktop;-;1024;-;' + 'x' * 60 + ';-;ua'
        result, _ = lambda_function.parse_pageview_data({row}, conn)
        assert result[0]['ipA'] == '0.0.0.0'

    def test_parse_click_empty_and_too_short(self):
        assert lambda_function.parse_click_data(set()) == []
        assert lambda_function.parse_click_data({'a;-;b'}) == []

    def test_parse_click_valid(self):
        row = ('2024-01-01;-;desktop;-;1920;-;1080;-;1200;-;ref123'
               ';-;100;-;200;-;http://link.com;-;Title;-;url123')
        result = lambda_function.parse_click_data({row})
        assert len(result) == 1
        assert result[0]['device'] == 'desktop'
        assert result[0]['urlId'] == 'url123'

    def test_parse_click_exception_in_row(self):
        bad_row = Mock()
        bad_row.split = Mock(side_effect=Exception("split error"))
        assert lambda_function.parse_click_data({bad_row}) == []

    def test_parse_scroll_empty_and_too_short(self):
        assert lambda_function.parse_scroll_data(set()) == []
        assert lambda_function.parse_scroll_data({'a;-;b;-;c'}) == []

    def test_parse_scroll_valid(self):
        row = '2024-01-01;-;desktop;-;1920;-;5000;-;ref123;-;50;-;url123'
        result = lambda_function.parse_scroll_data({row})
        assert len(result) == 1
        assert result[0]['pos'] == '50'

    def test_parse_scroll_exception_in_row(self):
        bad_row = Mock()
        bad_row.split = Mock(side_effect=Exception("split error"))
        assert lambda_function.parse_scroll_data({bad_row}) == []

    def test_parse_read_empty_and_too_short(self):
        assert lambda_function.parse_read_data(set()) == []
        assert lambda_function.parse_read_data({'a;-;b;-;c'}) == []

    def test_parse_read_valid(self):
        row = '2024-01-01;-;desktop;-;1920;-;1080;-;5000;-;ref123;-;50;-;url123'
        result = lambda_function.parse_read_data({row})
        assert len(result) == 1
        assert result[0]['dateCreate'] == '2024-01-01'
        assert result[0]['winHeight'] == '1080'
        assert result[0]['pos'] == '50'
        assert result[0]['urlId'] == 'url123'

    def test_parse_read_exception_in_row(self):
        bad_row = Mock()
        bad_row.split = Mock(side_effect=Exception("split error"))
        assert lambda_function.parse_read_data({bad_row}) == []


# ===========================================================================
# PROCESS SINGLE KEY
# ===========================================================================

class TestProcessSingleKey:

    @pytest.mark.parametrize("type_key,func", [
        ('v', 'process_pageview'),
        ('c', 'process_click'),
        ('s', 'process_scroll'),
        ('r', 'process_read'),
    ])
    def test_process_all_types(self, type_key, func, mock_redis):
        conn = Mock()
        with patch('lambda_function.check_schema_exist', return_value=True):
            with patch(f'lambda_function.{func}', return_value=True) as mf:
                result = lambda_function.process_single_key(
                    conn, f'site1_2024_{type_key}:data', 'site1', type_key, '202401')
                assert result is True
                mf.assert_called_once()

    def test_process_unknown_type(self, mock_redis):
        with patch('lambda_function.check_schema_exist', return_value=True):
            assert lambda_function.process_single_key(
                Mock(), 'key', 'site1', 'z', '202401') is False

    def test_process_schema_not_exist(self, mock_redis):
        with patch('lambda_function.check_schema_exist', return_value=False):
            with patch('lambda_function.delete_redis_key') as mock_del:
                result = lambda_function.process_single_key(Mock(), 'key', 'site1', 'v', '202401')
                assert result is False
                mock_del.assert_called_once_with('key')

    def test_process_single_key_exception(self):
        with patch('lambda_function.check_schema_exist', side_effect=Exception("boom")):
            assert lambda_function.process_single_key(
                Mock(), 'key', 'site1', 'v', '202401') is False


# ===========================================================================
# PROCESS PAGEVIEW / CLICK / SCROLL / READ
# ===========================================================================

class TestProcessFunctions:

    # --- process_pageview ---

    def test_process_pageview_empty_data(self, mock_redis):
        mock_redis.smembers.return_value = set()
        assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is True

    def test_process_pageview_parsed_empty(self, mock_redis):
        mock_redis.smembers.return_value = {'bad'}
        with patch('lambda_function.parse_pageview_data', return_value=([], [])):
            assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is True

    def test_process_pageview_add_fails(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_pageview_data', return_value=([{'x': 1}], [])):
            with patch('lambda_function.add_page_view', return_value=False):
                assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is False

    def test_process_pageview_success_with_params(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        pairs = [{'id': 'p1', 'key': 'a', 'value': 'b'}]
        with patch('lambda_function.parse_pageview_data', return_value=([{'x': 1}], pairs)):
            with patch('lambda_function.add_page_view', return_value=True):
                with patch('lambda_function.store_total_pv', return_value=True):
                    with patch('lambda_function.save_parameter_pairs', return_value=True):
                        assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is True

    def test_process_pageview_param_save_fails(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        pairs = [{'id': 'p1', 'key': 'a', 'value': 'b'}]
        with patch('lambda_function.parse_pageview_data', return_value=([{'x': 1}], pairs)):
            with patch('lambda_function.add_page_view', return_value=True):
                with patch('lambda_function.store_total_pv', return_value=True):
                    with patch('lambda_function.save_parameter_pairs', return_value=False):
                        assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is False

    def test_process_pageview_param_exception(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        pairs = [{'id': 'p1', 'key': 'a', 'value': 'b'}]
        with patch('lambda_function.parse_pageview_data', return_value=([{'x': 1}], pairs)):
            with patch('lambda_function.add_page_view', return_value=True):
                with patch('lambda_function.store_total_pv', return_value=True):
                    with patch('lambda_function.save_parameter_pairs',
                               side_effect=Exception("param err")):
                        assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is False

    def test_process_pageview_store_pv_fails(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_pageview_data', return_value=([{'x': 1}], [])):
            with patch('lambda_function.add_page_view', return_value=True):
                with patch('lambda_function.store_total_pv', return_value=False):
                    assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is True

    def test_process_pageview_store_pv_exception(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_pageview_data', return_value=([{'x': 1}], [])):
            with patch('lambda_function.add_page_view', return_value=True):
                with patch('lambda_function.store_total_pv', side_effect=Exception("pv err")):
                    assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is True

    def test_process_pageview_outer_exception(self, mock_redis):
        with patch('lambda_function.get_redis_set_data', side_effect=Exception("redis down")):
            assert lambda_function.process_pageview(Mock(), 'k', 'site1', '202401') is False

    # --- process_click ---

    def test_process_click_empty_data(self, mock_redis):
        mock_redis.smembers.return_value = set()
        assert lambda_function.process_click(Mock(), 'k', 'site1', '202401') is True

    def test_process_click_parsed_empty(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_click_data', return_value=[]):
            assert lambda_function.process_click(Mock(), 'k', 'site1', '202401') is True

    def test_process_click_success(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_click_data', return_value=[{'dateCreate': '2024'}]):
            with patch('lambda_function.add_click', return_value=True):
                assert lambda_function.process_click(Mock(), 'k', 'site1', '202401') is True

    def test_process_click_failure(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_click_data', return_value=[{'dateCreate': '2024'}]):
            with patch('lambda_function.add_click', return_value=False):
                assert lambda_function.process_click(Mock(), 'k', 'site1', '202401') is False

    def test_process_click_outer_exception(self, mock_redis):
        with patch('lambda_function.get_redis_set_data', side_effect=Exception("err")):
            assert lambda_function.process_click(Mock(), 'k', 'site1', '202401') is False

    # --- process_scroll ---

    def test_process_scroll_empty_data(self, mock_redis):
        mock_redis.smembers.return_value = set()
        assert lambda_function.process_scroll(Mock(), 'k', 'site1', '202401') is True

    def test_process_scroll_parsed_empty(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_scroll_data', return_value=[]):
            assert lambda_function.process_scroll(Mock(), 'k', 'site1', '202401') is True

    def test_process_scroll_success(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_scroll_data', return_value=[{'dateCreate': '2024'}]):
            with patch('lambda_function.add_scroll', return_value=True) as mock_add:
                assert lambda_function.process_scroll(Mock(), 'k', 'site1', '202401') is True
                mock_add.assert_called_once()

    def test_process_scroll_failure_no_delete(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_scroll_data', return_value=[{'dateCreate': '2024'}]):
            with patch('lambda_function.add_scroll', return_value=False):
                with patch('lambda_function.delete_redis_key') as mock_del:
                    assert lambda_function.process_scroll(Mock(), 'k', 'site1', '202401') is False
                    mock_del.assert_not_called()

    def test_process_scroll_outer_exception(self, mock_redis):
        with patch('lambda_function.get_redis_set_data', side_effect=Exception("err")):
            assert lambda_function.process_scroll(Mock(), 'k', 'site1', '202401') is False

    # --- process_read ---

    def test_process_read_empty_data(self, mock_redis):
        mock_redis.smembers.return_value = set()
        assert lambda_function.process_read(Mock(), 'k', 'site1', '202401') is True

    def test_process_read_parsed_empty(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_read_data', return_value=[]):
            assert lambda_function.process_read(Mock(), 'k', 'site1', '202401') is True

    def test_process_read_success(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_read_data', return_value=[{'dateCreate': '2024'}]):
            with patch('lambda_function.add_read', return_value=True):
                with patch('lambda_function.delete_redis_key') as mock_del:
                    assert lambda_function.process_read(Mock(), 'k', 'site1', '202401') is True
                    mock_del.assert_called_once_with('k')

    def test_process_read_failure_no_delete(self, mock_redis):
        mock_redis.smembers.return_value = {'data'}
        with patch('lambda_function.parse_read_data', return_value=[{'dateCreate': '2024'}]):
            with patch('lambda_function.add_read', return_value=False):
                with patch('lambda_function.delete_redis_key') as mock_del:
                    assert lambda_function.process_read(Mock(), 'k', 'site1', '202401') is False
                    mock_del.assert_not_called()

    def test_process_read_outer_exception(self, mock_redis):
        with patch('lambda_function.get_redis_set_data', side_effect=Exception("err")):
            assert lambda_function.process_read(Mock(), 'k', 'site1', '202401') is False


# ===========================================================================
# DATABASE INSERT FUNCTIONS
# ===========================================================================

class TestDatabaseInserts:

    # --- add_page_view ---

    def test_add_page_view_empty(self, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.add_page_view(conn, 'site1', [], '202401') is True

    def test_add_page_view_normal(self, mock_db_connection):
        conn, cur = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'referrerId': 'r', 'url': 'u',
                 'urlId': 'uid', 'device': 'desktop', 'winWidth': '1920',
                 'ipA': '1.2.3.4', 'userAgent': 'Mozilla/5.0'}]
        assert lambda_function.add_page_view(conn, 'site1', data, '202401') is True
        conn.commit.assert_called()

    def test_add_page_view_long_user_agent_truncated(self, mock_db_connection):
        conn, cur = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'userAgent': 'A' * 600}]
        assert lambda_function.add_page_view(conn, 'site1', data, '202401') is True
        cur.execute.assert_called()

    def test_add_page_view_batch_500(self, mock_db_connection):
        conn, _ = mock_db_connection
        data = [{'dateCreate': f'2024-01-{i:02d}', 'userAgent': 'ua'} for i in range(1, 502)]
        assert lambda_function.add_page_view(conn, 'site1', data, '202401') is True
        assert conn.commit.call_count >= 2

    def test_add_page_view_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("insert fail")
        data = [{'dateCreate': '2024-01-01', 'userAgent': 'ua'}]
        assert lambda_function.add_page_view(conn, 'site1', data, '202401') is False
        conn.rollback.assert_called_once()

    # --- add_click ---

    def test_add_click_empty(self, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.add_click(conn, 'site1', [], '202401') is True

    def test_add_click_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'device': 'desktop', 'winWidth': '1920',
                 'docWidth': '1080', 'docHeight': '1200', 'referrerId': 'ref',
                 'xpos': '100', 'ypos': '200', 'link': 'http://x.com',
                 'title': 'T', 'urlId': 'uid'}]
        assert lambda_function.add_click(conn, 'site1', data, '202401') is True
        conn.commit.assert_called()

    def test_add_click_batch_500(self, mock_db_connection):
        conn, _ = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'device': 'd', 'winWidth': '1920',
                 'docWidth': '1080', 'docHeight': '1200', 'referrerId': 'r',
                 'xpos': '0', 'ypos': '0', 'link': 'l', 'title': 't', 'urlId': 'u'}
                for _ in range(501)]
        assert lambda_function.add_click(conn, 'site1', data, '202401') is True
        assert conn.commit.call_count >= 2

    def test_add_click_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("click fail")
        data = [{'dateCreate': '2024-01-01', 'device': 'desktop'}]
        assert lambda_function.add_click(conn, 'site1', data, '202401') is False
        conn.rollback.assert_called_once()

    # --- add_scroll ---

    def test_add_scroll_empty(self, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.add_scroll(conn, 'site1', [], '202401') is True

    def test_add_scroll_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'device': 'desktop',
                 'winWidth': '1920', 'docHeight': '5000',
                 'referrerId': 'ref123', 'pos': '50', 'urlId': 'uid'}]
        assert lambda_function.add_scroll(conn, 'site1', data, '202401') is True
        values = cur.execute.call_args[0][1]
        assert values[4] == 'ref123'
        assert values[5] == '50'

    def test_add_scroll_batch_500(self, mock_db_connection):
        conn, _ = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'device': 'd', 'winWidth': '1920',
                 'docHeight': '5000', 'referrerId': 'r', 'pos': '10', 'urlId': 'u'}
                for _ in range(501)]
        assert lambda_function.add_scroll(conn, 'site1', data, '202401') is True
        assert conn.commit.call_count >= 2

    def test_add_scroll_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("scroll fail")
        assert lambda_function.add_scroll(conn, 'site1', [{'dateCreate': '2024-01-01'}], '202401') is False
        conn.rollback.assert_called_once()

    # --- add_read ---

    def test_add_read_empty(self, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.add_read(conn, 'site1', [], '202401') is True

    def test_add_read_success(self, mock_db_connection):
        conn, cur = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'device': 'desktop', 'winWidth': '1920',
                 'winHeight': '1080', 'docHeight': '5000',
                 'referrerId': 'ref', 'pos': '25', 'urlId': 'uid'}]
        assert lambda_function.add_read(conn, 'site1', data, '202401') is True
        cur.execute.assert_called()

    def test_add_read_batch_500(self, mock_db_connection):
        conn, _ = mock_db_connection
        data = [{'dateCreate': '2024-01-01', 'device': 'd', 'winWidth': '1920',
                 'winHeight': '1080', 'docHeight': '5000',
                 'referrerId': 'r', 'pos': '10', 'urlId': 'u'}
                for _ in range(501)]
        assert lambda_function.add_read(conn, 'site1', data, '202401') is True
        assert conn.commit.call_count >= 2

    def test_add_read_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("read fail")
        assert lambda_function.add_read(conn, 'site1', [{'dateCreate': '2024-01-01'}], '202401') is False
        conn.rollback.assert_called_once()

    # --- store_total_pv ---

    def test_store_total_pv_success(self, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.store_total_pv(conn, 'site1', '202401', 100) is True

    def test_store_total_pv_exception(self, mock_db_connection):
        conn, cur = mock_db_connection
        cur.execute.side_effect = Exception("pv err")
        assert lambda_function.store_total_pv(conn, 'site1', '202401', 100) is False


# ===========================================================================
# PROCESS KEYS PARALLEL
# ===========================================================================

class TestProcessKeysParallel:

    @patch.dict(os.environ, {'MAX_WORKERS': '2'})
    def test_invalid_key_format_skipped(self, mock_redis):
        result = lambda_function.process_keys_parallel(Mock(), ['invalid', 'alsoInvalid'], {}, '202401')
        assert result == {'successful': 0, 'failed': 0}

    @patch.dict(os.environ, {'MAX_WORKERS': '2'})
    def test_site_not_in_schema_deleted(self, mock_redis):
        with patch('lambda_function.delete_redis_key') as mock_del:
            lambda_function.process_keys_parallel(Mock(), ['site99_2024_v:data'], {}, '202401')
            mock_del.assert_called_once_with('site99_2024_v:data')

    @patch.dict(os.environ, {'MAX_WORKERS': '2'})
    def test_successful_processing(self, mock_redis):
        with patch('lambda_function.process_single_key', return_value=True):
            result = lambda_function.process_keys_parallel(
                Mock(), ['site1_2024_v:data', 'site1_2024_c:data'], {'site1': 1}, '202401')
            assert result == {'successful': 2, 'failed': 0}

    @patch.dict(os.environ, {'MAX_WORKERS': '2'})
    def test_failed_processing(self, mock_redis):
        with patch('lambda_function.process_single_key', return_value=False):
            result = lambda_function.process_keys_parallel(
                Mock(), ['site1_2024_v:data'], {'site1': 1}, '202401')
            assert result['failed'] == 1

    @patch.dict(os.environ, {'MAX_WORKERS': '2'})
    def test_exception_in_future(self, mock_redis):
        with patch('lambda_function.process_single_key', side_effect=Exception("boom")):
            result = lambda_function.process_keys_parallel(
                Mock(), ['site1_2024_v:data'], {'site1': 1}, '202401')
            assert result['failed'] == 1


# ===========================================================================
# EXECUTE MOVE DATA
# ===========================================================================

class TestExecuteMoveData:

    @patch('lambda_function.get_redis_keys', return_value=[])
    def test_no_keys(self, mock_keys, mock_redis):
        result = lambda_function.execute_move_data(Mock())
        assert result['total_keys'] == 0
        assert result['successful'] == 0

    @patch('lambda_function.process_keys_parallel', return_value={'successful': 3, 'failed': 0})
    @patch('lambda_function.get_list_schema_name', return_value={'site1': 1})
    @patch('lambda_function.filter_out_chunk_index_keys', return_value=['k1', 'k2', 'k3'])
    @patch('lambda_function.get_redis_keys', return_value=['k1', 'k2', 'k3'])
    def test_with_keys(self, mock_keys, mock_filter, mock_schema, mock_process, mock_redis):
        result = lambda_function.execute_move_data(Mock())
        assert result['successful'] == 3
        assert result['total_keys'] == 3

    @patch('lambda_function.get_redis_keys', side_effect=Exception("redis down"))
    def test_exception_propagates(self, mock_keys, mock_redis):
        with pytest.raises(Exception):
            lambda_function.execute_move_data(Mock())