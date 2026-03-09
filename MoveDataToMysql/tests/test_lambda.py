"""
Comprehensive test suite for MoveDataToMysql Lambda function
Tests cover Redis operations, database interactions, data parsing, and error handling.
"""

import pytest
import json
from unittest.mock import Mock, patch
from datetime import datetime
import sys
import os
import pymysql
import redis
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import lambda_function


import common

@pytest.fixture
def seed_thread_local():
    """Seed _thread_local with empty cache dicts so tests that call process_pageview()
    directly (outside a ThreadPoolExecutor) don't hit AttributeError."""
    lambda_function._thread_local.domain_cache  = {}
    lambda_function._thread_local.utm_src_cache = {}
    lambda_function._thread_local.utm_med_cache = {}
    yield
    # Clean up so other tests are not affected
    for attr in ('domain_cache', 'utm_src_cache', 'utm_med_cache'):
        try:
            delattr(lambda_function._thread_local, attr)
        except AttributeError:
            pass


@pytest.fixture(autouse=True)
def reset_global_state():
    original_redis_client   = common._redis_client
    original_valkey_client  = common._valkey_client
    original_package_redis_client = common._package_redis_client
    original_secret_cache   = common._secret_cache
    common._redis_client   = None
    common._valkey_client  = None
    common._package_redis_client = None
    common._secret_cache   = None
    yield
    common._redis_client   = original_redis_client
    common._valkey_client  = original_valkey_client
    common._package_redis_client = original_package_redis_client
    common._secret_cache   = original_secret_cache


@pytest.fixture
def mock_secret():
    return {
        'host': 'test-db.rds.amazonaws.com',
        'port': 3306,
        'username': 'testuser',
        'password': 'testpassword',
        'dbname': 'HEAT_MAP'
    }


@pytest.fixture
def mock_db_connection():
    conn = Mock(spec=pymysql.connections.Connection)
    cursor = Mock(spec=pymysql.cursors.DictCursor)
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.fetchall = Mock(return_value=[])
    cursor.fetchone = Mock(return_value=None)
    cursor.lastrowid = 1
    conn.cursor.return_value = cursor
    conn.commit = Mock()
    conn.rollback = Mock()
    conn.close = Mock()
    return conn, cursor


@pytest.fixture
def mock_redis_client():
    client = Mock(spec=redis.Redis)
    client.ping = Mock()
    client.scan = Mock(return_value=(0, []))
    client.smembers = Mock(return_value=set())
    client.delete = Mock()
    client.hget = Mock(return_value=None)
    client.hset = Mock()
    return client


@pytest.fixture
def sample_pageview_data():
    # Real Redis format: leading and trailing " wrapping the entire row string
    return {
        '"2024-01-15 10;-;ref123;-;https://example.com/page;-;url456;-;desktop;-;1920;-;192.168.1.1;-;Mozilla/5.0;-;utm_source=google&param1=value1;-;www.google.com;-;google;-;cpc"',
        '"2024-01-15 11;-;ref124;-;https://example.com/page2;-;url457;-;mobile;-;375;-;192.168.1.2;-;Mobile Safari;-;;-;;-;;-;"',
    }


@pytest.fixture
def sample_click_data():
    return {
        '"2024-01-15 10;-;desktop;-;1920;-;1080;-;2400;-;ref123;-;150;-;250;-;https://example.com/link;-;Link Title;-;url456"',
    }


@pytest.fixture
def sample_scroll_data():
    return {
        '"2024-01-15 10;-;desktop;-;1920;-;3000;-;ref123;-;50;-;url456"',
    }


@pytest.fixture
def sample_read_data():
    return {
        '"2024-01-15 10;-;desktop;-;1920;-;1080;-;3000;-;ref123;-;75;-;url456"',
    }


class TestLambdaHandler:
    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_success(self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_conn = Mock()
        mock_db.return_value = mock_conn
        mock_execute.return_value = {'successful': 10, 'failed': 0}
        result = lambda_function.lambda_handler()
        assert result['statusCode'] == 200
        assert 'stats' in json.loads(result['body'])
        mock_conn.close.assert_called_once()

    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_exception_triggers_rollback(self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_conn = Mock()
        mock_db.return_value = mock_conn
        mock_execute.side_effect = Exception("Processing error")
        with pytest.raises(Exception):
            lambda_function.lambda_handler()
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_secret_fetch_failure(self, mock_region, mock_secret):
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.side_effect = Exception("Secret not found")
        with pytest.raises(Exception):
            lambda_function.lambda_handler()



class TestSchemaHelpers:
    def test_get_schema_set_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.fetchall.return_value = [{'SCHEMA_NAME': 'site1'}, {'SCHEMA_NAME': 'site2'}, {'SCHEMA_NAME': 'HEAT_MAP'}]
        result = lambda_function.get_schema_set(conn)
        assert result == {'site1', 'site2', 'HEAT_MAP'}

    def test_get_schema_set_empty(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.fetchall.return_value = []
        result = lambda_function.get_schema_set(conn)
        assert result == set()


class TestDomainUtmCaching:
    @pytest.mark.parametrize("domain,expected", [
        ('www.google.com',      lambda_function.ReferrerDomainType.ORGANIC),  # organic
        ('facebook.com',        lambda_function.ReferrerDomainType.SOCIAL),   # social
        ('example.com',         lambda_function.ReferrerDomainType.NONE),     # no match
        ('',                    lambda_function.ReferrerDomainType.NONE),     # empty string
        (None,                  lambda_function.ReferrerDomainType.NONE),     # None
    ])
    def test_resolve_domain_type(self, domain, expected):
        result = lambda_function.resolve_domain_type(domain)
        assert result == expected

    @pytest.mark.parametrize("cache_type,expected_key", [
        (lambda_function.CacheType.DOMAIN, lambda_function.CACHE_DOMAIN),
        (lambda_function.CacheType.UTM_SOURCE, lambda_function.CACHE_UTM_SOURCE),
        (lambda_function.CacheType.UTM_MEDIUM, lambda_function.CACHE_UTM_MEDIUM),
    ])
    def test_cache_key_for(self, cache_type, expected_key):
        result = lambda_function._cache_key_for(cache_type)
        assert result == expected_key

    @patch('lambda_function.get_from_valkey_cache')
    def test_get_id_cached_hit(self, mock_get_cache, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = 42
        result = lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'google.com')
        assert result == 42

    @patch('lambda_function.set_to_valkey_cache')
    @patch('lambda_function.get_from_valkey_cache')
    def test_get_id_cached_miss(self, mock_get_cache, mock_set_cache, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = None
        cursor.lastrowid = 99
        result = lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'google.com')
        assert result == 99
        mock_set_cache.assert_called_once()

    @patch('lambda_function.set_to_valkey_cache')
    @patch('lambda_function.get_from_valkey_cache')
    def test_get_id_cached_uses_cache_field_as_valkey_key(self, mock_get_cache, mock_set_cache, mock_db_connection):
        """value (quoted string) is used as the Valkey hash field,
        and the stripped form is passed to DB upsert."""
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = None
        cursor.lastrowid = 7

        result = lambda_function.get_id_cached(
            conn, lambda_function.CacheType.DOMAIN,
            value='"mktran76.github.io"',
        )

        assert result == 7
        # Valkey read uses the value as-is
        mock_get_cache.assert_called_once_with(
            lambda_function.CACHE_DOMAIN, '"mktran76.github.io"'
        )
        # Valkey write uses the value as-is
        mock_set_cache.assert_called_once_with(
            lambda_function.CACHE_DOMAIN, '"mktran76.github.io"', 7
        )
        # DB receives the stripped value
        executed_sql = cursor.execute.call_args[0][0]
        assert 'REFERRER_DOMAIN' in executed_sql

    @patch('lambda_function.set_to_valkey_cache')
    @patch('lambda_function.get_from_valkey_cache')
    def test_get_id_cached_cache_field_defaults_to_value(self, mock_get_cache, mock_set_cache, mock_db_connection):
        """When cache_field is not provided, value is used as the Valkey hash field."""
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = None
        cursor.lastrowid = 5

        lambda_function.get_id_cached(
            conn, lambda_function.CacheType.UTM_SOURCE, 'google'
        )

        mock_get_cache.assert_called_once_with(lambda_function.CACHE_UTM_SOURCE, 'google')
        mock_set_cache.assert_called_once_with(lambda_function.CACHE_UTM_SOURCE, 'google', 5)

    @patch('lambda_function.set_to_valkey_cache')
    @patch('lambda_function.get_from_valkey_cache')
    def test_get_id_cached_hit_with_quoted_cache_field(self, mock_get_cache, mock_set_cache, mock_db_connection):
        """Cache hit with quoted value — returns cached id, no DB call."""
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = 16  # simulates '"mktran76.github.io"' : 16

        result = lambda_function.get_id_cached(
            conn, lambda_function.CacheType.DOMAIN,
            value='"mktran76.github.io"',
        )

        assert result == 16
        mock_set_cache.assert_not_called()  # no write on hit
        mock_get_cache.assert_called_once_with(
            lambda_function.CACHE_DOMAIN, '"mktran76.github.io"'
        )

    def test_get_id_cached_empty_value(self, mock_db_connection):
        conn, cursor = mock_db_connection
        result = lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, '')
        assert result is None

    def test_upsert_referrer_domain_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.lastrowid = 1
        result = lambda_function._upsert_referrer_domain(conn, 'google.com')
        assert result == 1
        conn.commit.assert_called_once()

    def test_upsert_referrer_domain_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception("DB error")
        result = lambda_function._upsert_referrer_domain(conn, 'google.com')
        assert result is None
        conn.rollback.assert_called_once()

    def test_upsert_utm_source_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.lastrowid = 5
        result = lambda_function._upsert_utm_source(conn, 'newsletter')
        assert result == 5
        conn.commit.assert_called_once()

    def test_upsert_utm_medium_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.lastrowid = 10
        result = lambda_function._upsert_utm_medium(conn, 'email')
        assert result == 10
        conn.commit.assert_called_once()


class TestParameterPairs:
    def test_extract_parameter_pairs_empty(self):
        result = lambda_function.extract_parameter_pairs('')
        assert result == []

    def test_extract_parameter_pairs_multiple(self):
        result = lambda_function.extract_parameter_pairs('key1=value1&key2=value2')
        assert len(result) == 2
        assert result[0]['key'] == 'key1'
        assert result[0]['value'] == 'value1'
        assert 'id' in result[0]

    def test_extract_parameter_pairs_excludes_utm(self):
        result = lambda_function.extract_parameter_pairs('key1=value1&utm_source=google&utm_medium=cpc')
        assert len(result) == 1
        assert result[0]['key'] == 'key1'

    def test_extract_parameter_pairs_url_encoded(self):
        result = lambda_function.extract_parameter_pairs('key=%E6%97%A5%E6%9C%AC%E8%AA%9E')
        assert len(result) == 1
        assert result[0]['key'] == 'key'

    def test_extract_parameter_pairs_malformed(self):
        result = lambda_function.extract_parameter_pairs('key1=value1&malformed&key2=value2')
        assert len(result) == 2

    def test_build_group_id_consistent(self):
        pairs1 = [{'key': 'a', 'value': '1', 'id': 'x'}, {'key': 'b', 'value': '2', 'id': 'y'}]
        pairs2 = [{'key': 'b', 'value': '2', 'id': 'y'}, {'key': 'a', 'value': '1', 'id': 'x'}]
        assert lambda_function.build_group_id(pairs1) == lambda_function.build_group_id(pairs2)

    def test_build_group_id_empty(self):
        result = lambda_function.build_group_id([])
        assert result is not None

    def test_save_parameter_pairs_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        pairs = [{'id': 'id1', 'key': 'k1', 'value': 'v1'}, {'id': 'id2', 'key': 'k2', 'value': 'v2'}]
        result = lambda_function.save_parameter_pairs(conn, pairs)
        assert result is True
        conn.commit.assert_called_once()

    def test_save_parameter_pairs_empty(self, mock_db_connection):
        conn, cursor = mock_db_connection
        result = lambda_function.save_parameter_pairs(conn, [])
        assert result is True
        cursor.execute.assert_not_called()

    def test_save_parameter_pairs_deadlock_retry(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = [
            pymysql.err.OperationalError(1213, "Deadlock"),
            None,
            None,
        ]
        pairs = [{'id': 'id1', 'key': 'k1', 'value': 'v1'}]
        result = lambda_function.save_parameter_pairs(conn, pairs)
        assert result is True
        assert cursor.execute.call_count >= 2

    def test_save_parameter_pairs_max_deadlock_retries(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = pymysql.err.OperationalError(1213, "Deadlock")
        pairs = [{'id': 'id1', 'key': 'k1', 'value': 'v1'}]
        result = lambda_function.save_parameter_pairs(conn, pairs)
        assert result is False


class TestDataParsers:
    def test_parse_pageview_data_success(self, sample_pageview_data, mock_db_connection):
        conn, cursor = mock_db_connection
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.get_id_cached', return_value=1):
            parsed, pairs = lambda_function.parse_pageview_data(
                sample_pageview_data, conn, domain_cache, utm_src_cache, utm_med_cache
            )
        assert len(parsed) > 0
        assert all('dateCreate' in item for item in parsed)
        assert all('url' in item for item in parsed)

    def test_parse_pageview_data_with_utm(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = {'"2026-03-09 10;-;ref123;-;https://example.com;-;url456;-;desktop;-;1920;-;192.168.1.1;-;Mozilla;-;param1=value1;-;google.com;-;newsletter;-;email"'}
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.get_id_cached', return_value=1):
            parsed, pairs = lambda_function.parse_pageview_data(
                data, conn, domain_cache, utm_src_cache, utm_med_cache
            )
        assert len(parsed) == 1
        assert parsed[0]['refDomainId'] == 1
        assert parsed[0]['refUtmSourceId'] == 1
        assert parsed[0]['refUtmMediumId'] == 1

    def test_parse_pageview_data_quoted_domain_and_utm(self, mock_db_connection):
        """Fields wrapped in extra quotes — "mktran76.github.io" :
        parse_pageview_data passes the original value (with quotes) to get_id_cached.
        get_id_cached itself strips quotes before sending to DB."""
        conn, cursor = mock_db_connection
        # trailing ;-; prevents outer strip('"') from eating the closing " of "cpc"
        data = {'"2026-03-09 10;-;ref1;-;https://mktran76.github.io/;-;urlA;-;desktop;-;1920;-;1.2.3.4;-;Chrome;-;;-;"mktran76.github.io";-;"google";-;"cpc";-;"'}

        captured_value = {}

        def fake_get_id_cached(conn, cache_type, value):
            captured_value[cache_type.value] = value
            return 99

        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.get_id_cached', side_effect=fake_get_id_cached):
            parsed, _ = lambda_function.parse_pageview_data(
                data, conn, domain_cache, utm_src_cache, utm_med_cache
            )

        assert len(parsed) == 1
        # parse_pageview_data passes the raw (quoted) value; get_id_cached strips internally
        assert captured_value['domain']     == '"mktran76.github.io"'
        assert captured_value['utm_source'] == '"google"'
        assert captured_value['utm_medium'] == '"cpc"'
        # IDs are set correctly
        assert parsed[0]['refDomainId']    == 99
        assert parsed[0]['refUtmSourceId'] == 99
        assert parsed[0]['refUtmMediumId'] == 99

    def test_parse_pageview_domain_cache_key_keeps_quotes(self, mock_db_connection):
        """The in-process cache key is the ORIGINAL string (with "").
        Two rows with the same quoted domain hit the cache after the first row."""
        conn, cursor = mock_db_connection
        row1 = '"2026-03-09 10;-;r1;-;u1;-;id1;-;desktop;-;1920;-;1.1.1.1;-;ua;-;;-;"mktran76.github.io";-;;-;"'
        row2 = '"2026-03-09 11;-;r2;-;u2;-;id2;-;desktop;-;1920;-;1.1.1.1;-;ua;-;;-;"mktran76.github.io";-;;-;"'
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}

        call_count = {'n': 0}
        def fake_get_id_cached(conn, cache_type, value, cache_field=None):
            call_count['n'] += 1
            return 7

        with patch('lambda_function.get_id_cached', side_effect=fake_get_id_cached):
            parsed, _ = lambda_function.parse_pageview_data(
                {row1, row2}, conn, domain_cache, utm_src_cache, utm_med_cache
            )

        # get_id_cached called only ONCE — second row is a cache hit
        assert call_count['n'] == 1
        # Cache key is the ORIGINAL quoted string
        assert '"mktran76.github.io"' in domain_cache

    def test_parse_pageview_data_malformed_row(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = {'"invalid;-;data"'}
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        parsed, pairs = lambda_function.parse_pageview_data(
            data, conn, domain_cache, utm_src_cache, utm_med_cache
        )
        assert len(parsed) == 0

    def test_parse_click_data_success(self, sample_click_data):
        result = lambda_function.parse_click_data(sample_click_data)
        assert len(result) > 0
        assert all('xpos' in item for item in result)
        assert all('ypos' in item for item in result)

    def test_parse_click_data_malformed(self):
        data = {'"invalid;-;data"'}
        result = lambda_function.parse_click_data(data)
        assert len(result) == 0

    def test_parse_scroll_data_success(self, sample_scroll_data):
        result = lambda_function.parse_scroll_data(sample_scroll_data)
        assert len(result) > 0
        assert all('pos' in item for item in result)
        assert all('docHeight' in item for item in result)

    def test_parse_read_data_success(self, sample_read_data):
        result = lambda_function.parse_read_data(sample_read_data)
        assert len(result) > 0
        assert all('pos' in item for item in result)
        assert all('winHeight' in item for item in result)


class TestDatabaseInsertHelpers:
    def test_execute_batch_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        sql = "INSERT INTO table VALUES (%s, %s)"
        rows = [('val1', 'val2'), ('val3', 'val4')]
        result = lambda_function._execute_batch(conn, sql, rows, 'test')
        assert result is True
        cursor.executemany.assert_called_once_with(sql, rows)
        conn.commit.assert_called_once()

    def test_execute_batch_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.executemany.side_effect = Exception("Insert failed")
        sql = "INSERT INTO table VALUES (%s)"
        rows = [('val1',)]
        result = lambda_function._execute_batch(conn, sql, rows, 'test')
        assert result is False
        conn.rollback.assert_called_once()

    def test_insert_pageviews_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = [{'dateCreate': '2024-01-15 10', 'referrerId': 'ref123', 'url': 'https://example.com', 'urlId': 'url456', 'refDomainId': 1, 'refUtmSourceId': 2, 'refUtmMediumId': 3, 'parameterPairGroupId': 'group1', 'device': 'desktop', 'winWidth': '1920', 'ipA': '192.168.1.1', 'userAgent': 'Mozilla/5.0'}]
        result = lambda_function.insert_pageviews(conn, 'site1', data, '202401')
        assert result is True
        cursor.executemany.assert_called_once()

    def test_insert_clicks_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = [{
            'dateCreate': '2024-01-15 10', 'xpos': '150',  'ypos': '250',
            'winWidth':   '1920',          'docWidth': '1080', 'docHeight': '2400',
            'device':     'desktop',       'referrerId': 'ref123',
            'urlId':      'url456',        'link': 'https://example.com/link',
            'title':      'Link Title',
        }]
        result = lambda_function.insert_clicks(conn, 'site1', data, '202401')
        assert result is True

    def test_insert_clicks_parse_to_insert_end_to_end(self, mock_db_connection):
        conn, cursor = mock_db_connection
        raw = {'"2024-01-15 10;-;desktop;-;1920;-;1080;-;2400;-;ref123;-;150;-;250;-;https://link.com;-;My Link;-;url456"'}
        parsed = lambda_function.parse_click_data(raw)
        assert len(parsed) == 1
        lambda_function.insert_clicks(conn, 'site1', parsed, '202401')
        params = cursor.executemany.call_args[0][1][0]  # first row of the batch
        assert params[0] == '2024-01-15 10'
        assert params[1] == '150'
        assert params[2] == '250'
        assert params[3] == '1920'
        assert params[4] == '1080'
        assert params[5] == '2400'
        assert params[6] == 'desktop'
        assert params[7] == 'ref123'
        assert params[8] == 'url456'
        assert params[9] == 'https://link.com'
        assert params[10] == 'My Link'

    def test_insert_scrolls_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = [{'dateCreate': '2024-01-15 10', 'device': 'desktop', 'winWidth': '1920', 'docHeight': '3000', 'referrerId': 'ref123', 'pos': '50', 'urlId': 'url456'}]
        result = lambda_function.insert_scrolls(conn, 'site1', data, '202401')
        assert result is True

    def test_insert_reads_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = [{'dateCreate': '2024-01-15 10', 'device': 'desktop', 'winWidth': '1920', 'winHeight': '1080', 'docHeight': '3000', 'referrerId': 'ref123', 'pos': '75', 'urlId': 'url456'}]
        result = lambda_function.insert_reads(conn, 'site1', data, '202401')
        assert result is True


class TestProcessHandlers:
    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_pageview_success(self, mock_get_data, mock_parse, mock_insert, mock_store_pv, mock_save_pairs, mock_delete, mock_db_connection, seed_thread_local):
        conn, cursor = mock_db_connection
        mock_get_data.return_value = {'data1', 'data2'}
        mock_parse.return_value = ([{'url': 'test'}], [{'id': 'p1', 'key': 'k', 'value': 'v'}])
        mock_insert.return_value = True
        mock_store_pv.return_value = True
        mock_save_pairs.return_value = True
        result = lambda_function.process_pageview(conn, 'site1_2024_v', 'site1', '202401')
        assert result is True
        mock_delete.assert_called_once()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_clicks')
    @patch('lambda_function.parse_click_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_click_success(self, mock_get_data, mock_parse, mock_insert, mock_delete, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_get_data.return_value = {'data1'}
        mock_parse.return_value = [{'xpos': '100'}]
        mock_insert.return_value = True
        result = lambda_function.process_click(conn, 'site1_2024_c', 'site1', '202401')
        assert result is True
        mock_delete.assert_called_once()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.get_redis_set_data')
    def test_process_empty_data(self, mock_get_data, mock_delete, mock_db_connection, seed_thread_local):
        conn, cursor = mock_db_connection
        mock_get_data.return_value = set()
        result = lambda_function.process_pageview(conn, 'site1_2024_v', 'site1', '202401')
        assert result is True
        mock_delete.assert_called_once()


class TestGetPackageCodeFromRedis:

    def test_returns_package_code_when_found(self, mock_redis_client):
        """hget returns a value → function returns it."""
        mock_redis_client.hget.return_value = 'STANDARD_30'
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.get_package_code_from_redis('123')
        assert result == 'STANDARD_30'
        mock_redis_client.hget.assert_called_once_with('list_sites_setup', '123')

    def test_returns_none_when_key_not_found(self, mock_redis_client):
        """hget returns None → function returns None."""
        mock_redis_client.hget.return_value = None
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.get_package_code_from_redis('999')
        assert result is None

    def test_returns_none_when_value_is_empty_string(self, mock_redis_client):
        """hget returns empty string → treated as falsy → returns None."""
        mock_redis_client.hget.return_value = ''
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.get_package_code_from_redis('123')
        assert result is None

    def test_returns_none_on_redis_exception(self, mock_redis_client):
        """Redis raises → exception is caught and None is returned."""
        mock_redis_client.hget.side_effect = Exception('Redis connection error')
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.get_package_code_from_redis('123')
        assert result is None


class TestTotalPVTracking:

    def test_store_total_pv_success(self, mock_db_connection, mock_redis_client):
        """Happy path: package code found in Redis, row inserted, commit called."""
        conn, cursor = mock_db_connection
        mock_redis_client.hget.return_value = 'STANDARD_30'
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.store_total_pv(conn, '42', '202601', 150)
        assert result is True
        cursor.execute.assert_called_once()
        call_args = cursor.execute.call_args[0]
        assert 'PACKAGE_CODE' in call_args[0]
        assert 'SITE_ID'      in call_args[0]
        assert 'YEAR'         in call_args[0]
        assert 'MONTH'        in call_args[0]
        assert 'COUNT'        in call_args[0]
        assert 'CREATED'      in call_args[0]
        assert 'UPDATED'      in call_args[0]
        conn.commit.assert_called_once()

    def test_store_total_pv_correct_year_month_extraction(self, mock_db_connection, mock_redis_client):
        """YEAR and MONTH are correctly extracted from table_name (YYYYMM)."""
        conn, cursor = mock_db_connection
        mock_redis_client.hget.return_value = 'PREMIUM_90'
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            lambda_function.store_total_pv(conn, '10', '202603', 50)
        params = cursor.execute.call_args[0][1]
        assert params[0] == 'PREMIUM_90'
        assert params[1] == '10'
        assert params[2] == 2026
        assert params[3] == 3
        assert params[4] == 50

    def test_store_total_pv_returns_false_when_package_code_is_none(self, mock_db_connection, mock_redis_client):
        """No package code in Redis → return False immediately, no DB call."""
        conn, cursor = mock_db_connection
        mock_redis_client.hget.return_value = None
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.store_total_pv(conn, '99', '202601', 10)
        assert result is False
        cursor.execute.assert_not_called()
        conn.commit.assert_not_called()

    def test_store_total_pv_db_exception_returns_false(self, mock_db_connection, mock_redis_client):
        """DB execute raises → exception caught, rollback called, returns False."""
        conn, cursor = mock_db_connection
        mock_redis_client.hget.return_value = 'STANDARD_30'
        cursor.execute.side_effect = Exception('DB error')
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            result = lambda_function.store_total_pv(conn, '42', '202601', 100)
        assert result is False
        conn.rollback.assert_called_once()
        conn.commit.assert_not_called()

    def test_store_total_pv_uses_on_duplicate_key_update(self, mock_db_connection, mock_redis_client):
        """SQL must contain ON DUPLICATE KEY UPDATE to increment COUNT."""
        conn, cursor = mock_db_connection
        mock_redis_client.hget.return_value = 'STANDARD_30'
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            lambda_function.store_total_pv(conn, '1', '202601', 5)
        sql = cursor.execute.call_args[0][0]
        assert 'ON DUPLICATE KEY UPDATE' in sql
        assert 'COUNT' in sql

    def test_store_total_pv_passes_correct_site_id(self, mock_db_connection, mock_redis_client):
        """site_id passed to hget and to the SQL params."""
        conn, cursor = mock_db_connection
        mock_redis_client.hget.return_value = 'STANDARD_30'
        with patch('lambda_function.get_package_redis_client', return_value=mock_redis_client):
            lambda_function.store_total_pv(conn, '777', '202612', 1)
        mock_redis_client.hget.assert_called_once_with('list_sites_setup', '777')
        params = cursor.execute.call_args[0][1]
        assert params[1] == '777'


class TestExecuteMoveData:
    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    def test_execute_move_data_success(self, mock_scan, mock_get_schemas, mock_process, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_scan.return_value = ['site1_2024-01-15 10_v', 'site1_2024-01-15 10_c', 'site1_2024-01-15 10_v:chunk']
        mock_get_schemas.return_value = {'site1', 'site2'}
        mock_process.return_value = {'successful': 2, 'failed': 0}
        with patch('lambda_function.datetime') as mock_dt:
            mock_now = datetime(2024, 1, 15, 11, 30, tzinfo=pytz.timezone('Asia/Tokyo'))
            mock_dt.now.return_value = mock_now
            result = lambda_function.execute_move_data(conn, {'host': 'test'})
        assert result['successful'] == 2
        assert result['failed'] == 0

    @patch('lambda_function.scan_redis_keys')
    def test_execute_move_data_no_keys(self, mock_scan, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_scan.return_value = []
        result = lambda_function.execute_move_data(conn, {'host': 'test'})
        assert result['total_keys'] == 0


class TestParallelProcessing:
    @patch('lambda_function._thread_init')
    @patch('lambda_function.process_single_key')
    @patch('lambda_function.delete_redis_key')
    def test_process_keys_parallel_success(self, mock_delete, mock_process_single, mock_thread_init):
        keys = ['site1_2024-01-15 10_v', 'site1_2024-01-15 10_c']
        schema_set = {'site1'}
        mock_process_single.return_value = True
        result = lambda_function.process_keys_parallel(keys, schema_set, '202401', {'host': 'test'})
        assert result['successful'] == 2
        assert result['failed'] == 0

    @patch('lambda_function.delete_redis_key')
    def test_process_keys_parallel_schema_not_found(self, mock_delete):
        keys = ['site999_2024-01-15 10_v']
        schema_set = {'site1'}
        result = lambda_function.process_keys_parallel(keys, schema_set, '202401', {'host': 'test'})
        mock_delete.assert_called_once()

    @patch('lambda_function.process_single_key')
    def test_process_keys_parallel_malformed_key(self, mock_process_single):
        keys = ['malformed_key']
        schema_set = {'site1'}
        result = lambda_function.process_keys_parallel(keys, schema_set, '202401', {'host': 'test'})
        mock_process_single.assert_not_called()


class TestEdgeCases:
    def test_parse_pageview_with_long_ip(self, mock_db_connection):
        conn, cursor = mock_db_connection
        long_ip = "1" * 100
        data = {f'"2024-01-15 10;-;ref;-;url;-;urlid;-;desktop;-;1920;-;{long_ip};-;ua;-;;-;;-;;-;"'}
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.get_id_cached', return_value=None):
            parsed, pairs = lambda_function.parse_pageview_data(
                data, conn, domain_cache, utm_src_cache, utm_med_cache
            )
        assert parsed[0]['ipA'] == '0.0.0.0'


class TestProcessScrollAndRead:

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_scrolls')
    @patch('lambda_function.parse_scroll_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_scroll_success(self, mock_get_data, mock_parse,
                                    mock_insert, mock_delete, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_get_data.return_value = {'data1', 'data2'}
        mock_parse.return_value = [{'pos': '50', 'device': 'PC'}]
        mock_insert.return_value = True

        result = lambda_function.process_scroll(conn, 'site1_2024_s', 'site1', '202401')

        assert result is True
        mock_insert.assert_called_once_with(conn, 'site1', [{'pos': '50', 'device': 'PC'}], '202401')
        mock_delete.assert_called_once_with('site1_2024_s')

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.get_redis_set_data')
    def test_process_scroll_empty_data(self, mock_get_data, mock_delete, mock_db_connection):
        conn, _ = mock_db_connection
        mock_get_data.return_value = set()

        result = lambda_function.process_scroll(conn, 'site1_2024_s', 'site1', '202401')

        assert result is True
        mock_delete.assert_called_once()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_scrolls')
    @patch('lambda_function.parse_scroll_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_scroll_insert_failure(self, mock_get_data, mock_parse,
                                           mock_insert, mock_delete, mock_db_connection):
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'data1'}
        mock_parse.return_value = [{'pos': '50'}]
        mock_insert.return_value = False

        result = lambda_function.process_scroll(conn, 'site1_2024_s', 'site1', '202401')

        assert result is False
        mock_delete.assert_not_called()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_scrolls')
    @patch('lambda_function.parse_scroll_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_parse_returns_empty_deletes_key(self, mock_get_data, mock_parse,
                                                      mock_insert, mock_delete, mock_db_connection):
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'bad_data'}
        mock_parse.return_value = []

        result = lambda_function.process_scroll(conn, 'site1_2024_s', 'site1', '202401')

        assert result is True
        mock_insert.assert_not_called()
        mock_delete.assert_called_once()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_reads')
    @patch('lambda_function.parse_read_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_read_success(self, mock_get_data, mock_parse,
                                  mock_insert, mock_delete, mock_db_connection):
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'data1'}
        mock_parse.return_value = [{'pos': '75', 'winHeight': '800'}]
        mock_insert.return_value = True

        result = lambda_function.process_read(conn, 'site1_2024_r', 'site1', '202401')

        assert result is True
        mock_delete.assert_called_once_with('site1_2024_r')


class TestExecuteBatchExtra:
    def test_commit_exactly_twice_for_batch_size_plus_one(self, mock_db_connection):
        conn, cursor = mock_db_connection
        rows = [(i,) for i in range(lambda_function.BATCH_SIZE + 1)]

        lambda_function._execute_batch(conn, "INSERT INTO t VALUES (%s)", rows, "test")

        assert cursor.executemany.call_count == 2
        conn.commit.assert_called_once()

    def test_commit_once_for_exact_batch_size(self, mock_db_connection):
        conn, cursor = mock_db_connection
        rows = [(i,) for i in range(lambda_function.BATCH_SIZE)]

        lambda_function._execute_batch(conn, "INSERT INTO t VALUES (%s)", rows, "test")

        assert cursor.executemany.call_count == 1
        conn.commit.assert_called_once()


# ===========================================================================
# MISSING: upsert UTM exception handling
# ===========================================================================

class TestUpsertExceptionHandling:

    def test_upsert_utm_source_exception_returns_none(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception("DB error")

        result = lambda_function._upsert_utm_source(conn, 'google')

        assert result is None
        conn.rollback.assert_called_once()

    def test_upsert_utm_medium_exception_returns_none(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception("DB error")

        result = lambda_function._upsert_utm_medium(conn, 'cpc')

        assert result is None
        conn.rollback.assert_called_once()


# ===========================================================================
# NEW TESTS — improve coverage for uncovered lines
# ===========================================================================


class TestThreadInit:
    """Cover _thread_init body (lines 149-155)."""

    def test_thread_init_stores_conn_and_caches(self):
        import threading
        mock_conn = Mock()
        connections = []
        lock = threading.Lock()

        with patch('lambda_function.get_db_connection', return_value=mock_conn):
            lambda_function._thread_init({'host': 'test'}, connections, lock)

        assert lambda_function._thread_local.conn is mock_conn
        assert lambda_function._thread_local.domain_cache == {}
        assert lambda_function._thread_local.utm_src_cache == {}
        assert lambda_function._thread_local.utm_med_cache == {}
        assert mock_conn in connections

    def test_thread_init_appends_to_connections_list(self):
        import threading
        mock_conn = Mock()
        connections = []
        lock = threading.Lock()

        with patch('lambda_function.get_db_connection', return_value=mock_conn):
            lambda_function._thread_init({'host': 'test'}, connections, lock)

        assert len(connections) == 1
        assert connections[0] is mock_conn


class TestProcessKeysParallelFutureException:

    @patch('lambda_function._thread_init')
    @patch('lambda_function.process_single_key', side_effect=RuntimeError("Worker crashed"))
    def test_process_keys_parallel_future_raises(self, mock_process_single, mock_thread_init):
        keys = ['site1_2024-01-15 10_v']
        schema_set = {'site1'}

        result = lambda_function.process_keys_parallel(
            keys, schema_set, '202401', {'host': 'test'}
        )

        assert result['failed'] == 1
        assert result['successful'] == 0


class TestProcessPageviewBranches:
    """Cover remaining branches in _load_and_process for pageview."""

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_insert_failure_no_delete(self, mock_get_data, mock_parse,
                                      mock_insert, mock_delete, mock_db_connection, seed_thread_local):
        """insert returns False → _load_and_process returns False, no delete (lines 616-617)."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'data1'}
        mock_parse.return_value = ([{'url': 'test'}], [])
        mock_insert.return_value = False
        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')
        assert result is False
        mock_delete.assert_not_called()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_store_pv_false_does_not_block(self, mock_get_data, mock_parse, mock_insert,
                                           mock_store_pv, mock_save_pairs, mock_delete,
                                           mock_db_connection, seed_thread_local):
        """store_total_pv returns False → warning logged but processing continues (lines 596-597).
        pairs must be non-None (empty list) so the `if pairs is not None` block is entered."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        # Return tuple with empty pairs list — pairs is not None so pv block is entered
        mock_parse.return_value = ([{'url': 'x'}], [])
        mock_insert.return_value = True
        mock_store_pv.return_value = False
        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')
        assert result is True
        mock_store_pv.assert_called_once()
        mock_delete.assert_called_once()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_save_pairs_failure_returns_false(self, mock_get_data, mock_parse, mock_insert,
                                              mock_store_pv, mock_save_pairs, mock_delete,
                                              mock_db_connection, seed_thread_local):
        """save_parameter_pairs returns False → warning logged, ok set to False, key is NOT deleted."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        mock_parse.return_value = ([{'url': 'x'}], [{'id': 'a', 'key': 'k', 'value': 'v'}])
        mock_insert.return_value = True
        mock_store_pv.return_value = True
        mock_save_pairs.return_value = False
        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')
        assert result is False
        mock_delete.assert_not_called()


class TestSaveToDbUnknownCacheType:

    def test_save_to_db_unknown_cache_type_raises(self, mock_db_connection):
        conn, _ = mock_db_connection
        # Create a fake CacheType-like object that won't match any branch
        class FakeCacheType:
            pass
        with pytest.raises((ValueError, AttributeError)):
            lambda_function._save_to_db(conn, FakeCacheType(), 'some_value')


class TestExtractParameterPairsException:

    def test_extract_parameter_pairs_unquote_exception(self):
        with patch('lambda_function.unquote', side_effect=Exception("decode error")):
            result = lambda_function.extract_parameter_pairs('key=value')
        # Falls back to raw k, v — still produces a pair
        assert len(result) == 1
        assert result[0]['key'] == 'key'
        assert result[0]['value'] == 'value'


class TestSaveParameterPairsNon1213OperationalError:

    def test_save_parameter_pairs_non_1213_operational_error(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = pymysql.err.OperationalError(1205, "Lock wait timeout")
        pairs = [{'id': 'id1', 'key': 'k1', 'value': 'v1'}]
        result = lambda_function.save_parameter_pairs(conn, pairs)
        assert result is False
        conn.rollback.assert_called()

    def test_save_parameter_pairs_generic_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = RuntimeError("Unexpected failure")
        pairs = [{'id': 'id1', 'key': 'k1', 'value': 'v1'}]
        result = lambda_function.save_parameter_pairs(conn, pairs)
        assert result is False
        conn.rollback.assert_called()


class TestParseExceptionHandlers:
    """Exception handlers and short-row 'continue' branches in parse_* functions."""

    def test_parse_pageview_data_exception_in_row(self, mock_db_connection):
        conn, _ = mock_db_connection
        valid_row = '"2024-01-15 10;-;ref;-;url;-;urlid;-;desktop;-;1920;-;1.1.1.1;-;ua;-;;-;;-;;-;"'
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.extract_parameter_pairs', side_effect=Exception("Parse error")):
            parsed, pairs = lambda_function.parse_pageview_data(
                {valid_row}, conn, domain_cache, utm_src_cache, utm_med_cache
            )
        assert len(parsed) == 0

    def test_parse_click_data_exception_in_row(self):
        class BadSeq:
            def __len__(self): return 20
            def __getitem__(self, idx):
                if isinstance(idx, slice):
                    return "row_preview"
                raise RuntimeError("Index access failed")
            def split(self, sep): return BadSeq()

        result = lambda_function.parse_click_data([BadSeq()])
        assert result == []

    def test_parse_scroll_data_short_row_skipped(self):
        # Only 3 fields after strip — triggers len(p) < 7 → continue
        short_row = '"f0;-;f1;-;f2"'
        result = lambda_function.parse_scroll_data([short_row])
        assert result == []

    def test_parse_scroll_data_exception_in_row(self):
        class BadSeq:
            def __len__(self): return 20
            def __getitem__(self, idx):
                if isinstance(idx, slice):
                    return "row_preview"
                raise RuntimeError("Index access failed")
            def split(self, sep): return BadSeq()

        result = lambda_function.parse_scroll_data([BadSeq()])
        assert result == []

    def test_parse_read_data_short_row_skipped(self):
        # Only 4 fields after strip — triggers len(p) < 8 → continue
        short_row = '"f0;-;f1;-;f2;-;f3"'
        result = lambda_function.parse_read_data([short_row])
        assert result == []

    def test_parse_read_data_exception_in_row(self):
        class BadSeq:
            def __len__(self): return 20
            def __getitem__(self, idx):
                if isinstance(idx, slice):
                    return "row_preview"
                raise RuntimeError("Index access failed")
            def split(self, sep): return BadSeq()

        result = lambda_function.parse_read_data([BadSeq()])
        assert result == []


class TestProcessKeysParallelFailedBranch:

    @patch('lambda_function.process_single_key')
    def test_process_keys_parallel_worker_returns_false(self, mock_process_single):
        """Line 457: failed incremented when worker returns False."""
        mock_process_single.return_value = False
        keys = ['site1_2024-01-15 10_v']
        schema_set = {'site1'}
        result = lambda_function.process_keys_parallel(keys, schema_set, '202401', {'host': 'test'})
        assert result['failed'] == 1
        assert result['successful'] == 0

    @patch('lambda_function.process_single_key')
    def test_process_keys_parallel_conn_close_raises(self, mock_process_single):
        mock_process_single.return_value = True
        keys = ['site1_2024-01-15 10_v']
        schema_set = {'site1'}

        # Patch _thread_init to inject a connection whose close() raises
        bad_conn = Mock()
        bad_conn.close.side_effect = Exception("close failed")

        def fake_thread_init(secret, connections, lock):
            lambda_function._thread_local.conn = bad_conn
            with lock:
                connections.append(bad_conn)

        with patch('lambda_function._thread_init', side_effect=fake_thread_init):
            # Should NOT raise — exception is swallowed
            result = lambda_function.process_keys_parallel(keys, schema_set, '202401', {'host': 'test'})

        assert result['successful'] == 1
        bad_conn.close.assert_called_once()


class TestProcessSingleKey:

    def _set_thread_conn(self, conn):
        lambda_function._thread_local.conn = conn

    @patch('lambda_function.process_pageview')
    def test_dispatches_pageview(self, mock_handler):
        mock_handler.return_value = True
        conn = Mock()
        self._set_thread_conn(conn)
        result = lambda_function.process_single_key('site1_2024-01-15 10_v', 'site1', 'v', '202401')
        mock_handler.assert_called_once_with(conn, 'site1_2024-01-15 10_v', 'site1', '202401')
        assert result is True

    def test_unknown_type_key_returns_false(self):
        self._set_thread_conn(Mock())
        result = lambda_function.process_single_key('site1_2024-01-15 10_x', 'site1', 'x', '202401')
        assert result is False

    @patch('lambda_function.process_pageview')
    def test_exception_triggers_rollback_returns_false(self, mock_handler):
        mock_handler.side_effect = RuntimeError("db error")
        conn = Mock()
        self._set_thread_conn(conn)
        result = lambda_function.process_single_key('site1_2024-01-15 10_v', 'site1', 'v', '202401')
        conn.rollback.assert_called_once()
        assert result is False

    @patch('lambda_function.process_pageview')
    def test_exception_rollback_itself_raises(self, mock_handler):
        mock_handler.side_effect = RuntimeError("db error")
        conn = Mock()
        conn.rollback.side_effect = Exception("rollback failed")
        self._set_thread_conn(conn)
        result = lambda_function.process_single_key('site1_2024-01-15 10_v', 'site1', 'v', '202401')
        assert result is False


class TestLoadAndProcessStoreTotalPvException:
    """store_total_pv raises an exception in _load_and_process."""

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_store_total_pv_raises_exception(
            self, mock_get_data, mock_parse, mock_insert,
            mock_store_pv, mock_save_pairs, mock_delete, mock_db_connection, seed_thread_local):
        """store_total_pv raises, exception is caught and logged; processing continues."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        mock_parse.return_value = ([{'url': 'x'}], [])
        mock_insert.return_value = True
        mock_store_pv.side_effect = Exception("PV store crashed")
        mock_save_pairs.return_value = True

        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')

        assert result is True
        mock_delete.assert_called_once()


class TestSaveParameterPairsZeroRetry:

    def test_save_parameter_pairs_zero_retry_returns_false(self, mock_db_connection):
        """Patch MAX_DEADLOCK_RETRY to 0 so the for-loop body never executes and falls through."""
        conn, _ = mock_db_connection
        pairs = [{'id': 'id1', 'key': 'k1', 'value': 'v1'}]

        with patch('lambda_function.MAX_DEADLOCK_RETRY', 0):
            result = lambda_function.save_parameter_pairs(conn, pairs)

        assert result is False


# ===========================================================================
# NEW TESTS — mode handling in lambda_handler and execute_move_data
# ===========================================================================
class TestLambdaHandlerModeHandling:
    """Cover mode handling in lambda_handler."""

    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_mode_normal_explicit(
            self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        """mode='normal' passed explicitly → lambda_handler returns 200 and calls execute_move_data."""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_db.return_value = Mock()
        mock_execute.return_value = {'successful': 5, 'failed': 0}

        result = lambda_function.lambda_handler(event={'mode': 'normal'})

        assert result['statusCode'] == 200
        mock_execute.assert_called_once()

    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_mode_miss(
            self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        """mode='miss' passed → lambda_handler returns 200 and calls execute_move_data."""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_db.return_value = Mock()
        mock_execute.return_value = {'successful': 3, 'failed': 0}

        result = lambda_function.lambda_handler(event={'mode': 'miss'})

        assert result['statusCode'] == 200
        mock_execute.assert_called_once()

    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_unknown_mode_falls_back_to_normal(
            self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        """Unknown mode in event → lambda_handler still returns 200."""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_db.return_value = Mock()
        mock_execute.return_value = {'successful': 0, 'failed': 0}

        result = lambda_function.lambda_handler(event={'mode': 'invalid_mode'})

        assert result['statusCode'] == 200
        mock_execute.assert_called_once()

    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_no_event_defaults_to_normal(
            self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        """event=None → lambda_handler returns 200."""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_db.return_value = Mock()
        mock_execute.return_value = {'successful': 0, 'failed': 0}

        result = lambda_function.lambda_handler(event=None)

        assert result['statusCode'] == 200
        mock_execute.assert_called_once()

    @patch('lambda_function.execute_move_data')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_redis_client')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_empty_event_defaults_to_normal(
            self, mock_region, mock_secret, mock_redis, mock_db, mock_execute):
        """event={} (no 'mode' key) → lambda_handler returns 200."""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_redis.return_value = Mock()
        mock_db.return_value = Mock()
        mock_execute.return_value = {'successful': 0, 'failed': 0}

        result = lambda_function.lambda_handler(event={})

        assert result['statusCode'] == 200
        mock_execute.assert_called_once()
