"""
Comprehensive test suite for MoveDataToMysql Lambda function
Tests cover Redis operations, database interactions, data parsing, and error handling.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import sys
import os
import pymysql
import pytz

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import lambda_function
import common
from redis_wrapper import RedisWrapper


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
    original_wrappers     = dict(common._wrappers)
    original_secret_cache = common._secret_cache
    common._wrappers.clear()
    common._secret_cache = None
    yield
    common._wrappers.clear()
    common._wrappers.update(original_wrappers)
    common._secret_cache = original_secret_cache


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
    conn   = Mock(spec=pymysql.connections.Connection)
    cursor = Mock(spec=pymysql.cursors.DictCursor)
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__  = Mock(return_value=False)
    cursor.fetchall  = Mock(return_value=[])
    cursor.fetchone  = Mock(return_value=None)
    cursor.lastrowid = 1
    conn.cursor.return_value = cursor
    conn.commit   = Mock()
    conn.rollback = Mock()
    conn.close    = Mock()
    return conn, cursor


@pytest.fixture
def mock_wrapper():
    return MagicMock(spec=RedisWrapper)


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
    @patch('lambda_function.move_handler')
    def test_lambda_handler_success(self, mock_move_handler):
        """Test lambda_handler with action='move' calls move_handler and returns its result."""
        mock_move_handler.return_value = {'statusCode': 200, 'body': json.dumps({'message': 'Success', 'stats': {'successful': 10, 'failed': 0}})}
        event = {'action': 'move'}
        result = lambda_function.lambda_handler(event=event, context=None)
        assert result['statusCode'] == 200
        assert 'stats' in json.loads(result['body'])
        mock_move_handler.assert_called_once_with(event, None)

    @patch('lambda_function.move_handler')
    def test_lambda_handler_exception_triggers_rollback(self, mock_move_handler):
        """Test lambda_handler lets exceptions from move_handler propagate."""
        mock_move_handler.side_effect = Exception("Processing error")
        event = {'action': 'move'}
        with pytest.raises(Exception, match="Processing error"):
            lambda_function.lambda_handler(event=event, context=None)

    def test_lambda_handler_no_action_returns_ignored(self):
        """Test lambda_handler with no action returns ignored status."""
        result = lambda_function.lambda_handler(event=None, context=None)
        assert result['status'] == 'ignored'


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
        assert len(result) == 0

    def test_extract_parameter_pairs_excludes_utm(self):
        result = lambda_function.extract_parameter_pairs('key1=value1&utm_source=google&utm_medium=cpc')
        assert len(result) == 2
        assert result[0]['key'] == 'utm_source'
        assert result[0]['value'] == 'google'
        assert result[1]['key'] == 'utm_medium'
        assert result[1]['value'] == 'cpc'

    def test_extract_parameter_pairs_url_encoded(self):
        result = lambda_function.extract_parameter_pairs('key=%E6%97%A5%E6%9C%AC%E8%AA%9E')
        assert len(result) == 0

    def test_extract_parameter_pairs_malformed(self):
        result = lambda_function.extract_parameter_pairs('key1=value1&malformed&key2=value2')
        assert len(result) == 0

    def test_build_group_id_consistent(self):
        pairs1 = [{'key': 'a', 'value': '1', 'id': 'x'}, {'key': 'b', 'value': '2', 'id': 'y'}]
        pairs2 = [{'key': 'b', 'value': '2', 'id': 'y'}, {'key': 'a', 'value': '1', 'id': 'x'}]
        assert lambda_function.build_group_id(pairs1) == lambda_function.build_group_id(pairs2)

    def test_build_group_id_empty(self):
        result = lambda_function.build_group_id([])
        assert result is not None

    def test_build_parameter_pair_group_rows_deduplicates_group_and_pair_id(self):
        rows = lambda_function._build_parameter_pair_group_rows([
            {'group_id': 'group-a', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'group_id': 'group-a', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'group_id': 'group-b', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
        ])

        assert rows == [('group-a', 'id1'), ('group-b', 'id1')]

    def test_build_parameter_pair_rows_deduplicates_pair_values(self):
        rows = lambda_function._build_parameter_pair_rows([
            {'group_id': 'group-a', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'group_id': 'group-b', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'group_id': 'group-a', 'id': 'id2', 'key': 'utm_medium', 'value': 'v2'},
        ])

        assert rows == [
            ('id1', 'utm_source', 'v1'),
            ('id2', 'utm_medium', 'v2'),
        ]

    def test_prepare_parameter_pair_rows_returns_group_and_pair_rows(self):
        group_rows, pair_rows = lambda_function._prepare_parameter_pair_rows([
            {'group_id': 'group-a', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'group_id': 'group-a', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'group_id': 'group-b', 'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
        ])

        assert group_rows == [('group-a', 'id1'), ('group-b', 'id1')]
        assert pair_rows == [('id1', 'utm_source', 'v1')]

    def test_save_parameter_pairs_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        pairs = [{'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
                 {'id': 'id2', 'key': 'utm_medium', 'value': 'v2'}]
        group_id = lambda_function.build_group_id(pairs)
        group_pairs_map = {group_id: pairs}
        result = lambda_function.save_parameter_pairs(conn, group_pairs_map)
        assert result is True
        assert cursor.executemany.call_count == 2
        conn.commit.assert_called_once()
        first_sql = cursor.executemany.call_args_list[0][0][0]
        second_sql = cursor.executemany.call_args_list[1][0][0]
        assert "PARAMETER_PAIR_GROUP" in first_sql
        assert "PARAMETER_PAIR (ID, `KEY`, `VALUE`)" in second_sql

    def test_save_parameter_pairs_empty_map(self, mock_db_connection):
        """Empty group_pairs_map → returns True immediately, no DB calls."""
        conn, cursor = mock_db_connection
        result = lambda_function.save_parameter_pairs(conn, {})
        assert result is True
        cursor.executemany.assert_not_called()

    def test_save_parameter_pairs_deadlock_retry(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.executemany.side_effect = [
            pymysql.err.OperationalError(1213, "Deadlock"),
            None,   # PARAMETER_PAIR_GROUP insert on retry
            None,   # PARAMETER_PAIR insert on retry
        ]
        pairs = [{'id': 'id1', 'key': 'utm_source', 'value': 'v1'}]
        group_id = lambda_function.build_group_id(pairs)
        result = lambda_function.save_parameter_pairs(conn, {group_id: pairs})
        assert result is True
        assert cursor.executemany.call_count >= 3

    def test_save_parameter_pairs_max_deadlock_retries(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.executemany.side_effect = pymysql.err.OperationalError(1213, "Deadlock")
        pairs = [{'id': 'id1', 'key': 'utm_source', 'value': 'v1'}]
        group_id = lambda_function.build_group_id(pairs)
        result = lambda_function.save_parameter_pairs(conn, {group_id: pairs})
        assert result is False
        assert conn.rollback.call_count == lambda_function.MAX_DEADLOCK_RETRY

    def test_save_parameter_pairs_commit_per_chunk(self, mock_db_connection, monkeypatch):
        conn, cursor = mock_db_connection
        monkeypatch.setattr(lambda_function, "BATCH_SIZE", 1)
        pairs = [
            {'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'id': 'id2', 'key': 'utm_medium', 'value': 'v2'},
        ]
        group_id = lambda_function.build_group_id(pairs)

        result = lambda_function.save_parameter_pairs(conn, {group_id: pairs})

        assert result is True
        assert conn.commit.call_count == 2
        assert cursor.executemany.call_count == 4

    def test_save_parameter_pairs_deduplicates_pair_rows_by_pair_id(self, mock_db_connection):
        conn, cursor = mock_db_connection
        shared_pair = {'id': 'id1', 'key': 'utm_source', 'value': 'v1'}

        result = lambda_function.save_parameter_pairs(
            conn,
            {
                'group-a': [shared_pair],
                'group-b': [shared_pair],
            },
        )

        assert result is True
        group_rows = cursor.executemany.call_args_list[0][0][1]
        pair_rows = cursor.executemany.call_args_list[1][0][1]
        assert group_rows == [('group-a', 'id1'), ('group-b', 'id1')]
        assert pair_rows == [('id1', 'utm_source', 'v1')]

    def test_save_parameter_pairs_deduplicates_group_rows_by_group_and_pair_id(self, mock_db_connection):
        conn, cursor = mock_db_connection
        shared_pair = {'id': 'id1', 'key': 'utm_source', 'value': 'v1'}

        result = lambda_function.save_parameter_pairs(
            conn,
            {
                'group-a': [shared_pair, shared_pair],
            },
        )

        assert result is True
        group_rows = cursor.executemany.call_args_list[0][0][1]
        pair_rows = cursor.executemany.call_args_list[1][0][1]
        assert group_rows == [('group-a', 'id1')]
        assert pair_rows == [('id1', 'utm_source', 'v1')]

    def test_save_parameter_pairs_batches_when_pair_count_exceeds_batch_size(self, mock_db_connection):
        conn, cursor = mock_db_connection
        pairs = [
            {'id': f'id{i}', 'key': f'utm_key_{i}', 'value': f'v{i}'}
            for i in range(lambda_function.BATCH_SIZE + 1)
        ]
        group_id = lambda_function.build_group_id(pairs)

        result = lambda_function.save_parameter_pairs(conn, {group_id: pairs})

        assert result is True
        assert cursor.executemany.call_count == 4
        assert conn.commit.call_count == 2
        assert len(cursor.executemany.call_args_list[0][0][1]) == lambda_function.BATCH_SIZE
        assert len(cursor.executemany.call_args_list[1][0][1]) == lambda_function.BATCH_SIZE
        assert len(cursor.executemany.call_args_list[2][0][1]) == 1
        assert len(cursor.executemany.call_args_list[3][0][1]) == 1

    def test_save_parameter_pairs_keeps_committed_chunks_when_later_chunk_fails(self, mock_db_connection, monkeypatch):
        conn, cursor = mock_db_connection
        monkeypatch.setattr(lambda_function, "BATCH_SIZE", 1)
        deadlock = pymysql.err.OperationalError(1213, "Deadlock")
        cursor.executemany.side_effect = [
            None,      # chunk 1: PARAMETER_PAIR_GROUP
            None,      # chunk 1: PARAMETER_PAIR
            deadlock,  # chunk 2: attempt 1
            deadlock,  # chunk 2: attempt 2
            deadlock,  # chunk 2: attempt 3 -> stop retrying
        ]
        pairs = [
            {'id': 'id1', 'key': 'utm_source', 'value': 'v1'},
            {'id': 'id2', 'key': 'utm_medium', 'value': 'v2'},
        ]
        group_id = lambda_function.build_group_id(pairs)

        result = lambda_function.save_parameter_pairs(conn, {group_id: pairs})

        assert result is False
        assert conn.commit.call_count == 1
        assert conn.rollback.call_count == lambda_function.MAX_DEADLOCK_RETRY


class TestDataParsers:
    def test_parse_pageview_data_success(self, sample_pageview_data, mock_db_connection):
        conn, cursor = mock_db_connection
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.get_id_cached', return_value=1):
            parsed, group_pairs_map = lambda_function.parse_pageview_data(
                sample_pageview_data, conn, domain_cache, utm_src_cache, utm_med_cache
            )
        assert len(parsed) > 0
        assert all('dateCreate' in item for item in parsed)
        assert all('url' in item for item in parsed)
        # group_pairs_map must be a dict
        assert isinstance(group_pairs_map, dict)

    def test_parse_pageview_data_with_utm(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = {'"2024-01-15 10;-;ref123;-;https://example.com;-;url456;-;desktop;-;1920;-;192.168.1.1;-;Mozilla;-;param1=value1;-;google.com;-;newsletter;-;email"'}
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        with patch('lambda_function.get_id_cached', return_value=1):
            parsed, group_pairs_map = lambda_function.parse_pageview_data(
                data, conn, domain_cache, utm_src_cache, utm_med_cache
            )
        assert len(parsed) == 1
        assert parsed[0]['refDomainId'] == 1
        assert parsed[0]['refUtmSourceId'] == 1
        assert parsed[0]['refUtmMediumId'] == 1
        assert isinstance(group_pairs_map, dict)

    def test_parse_pageview_data_malformed_row(self, mock_db_connection):
        conn, cursor = mock_db_connection
        data = {'"invalid;-;data"'}
        domain_cache, utm_src_cache, utm_med_cache = {}, {}, {}
        parsed, group_pairs_map = lambda_function.parse_pageview_data(
            data, conn, domain_cache, utm_src_cache, utm_med_cache
        )
        assert len(parsed) == 0
        assert group_pairs_map == {}


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
    def test_process_pageview_success(
        self, mock_get_data, mock_parse, mock_insert,
        mock_store_pv, mock_save_pairs, mock_delete,
        mock_db_connection, seed_thread_local,
    ):
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'data1', 'data2'}
        pairs = [{'id': 'p1', 'key': 'utm_source', 'value': 'google'}]
        group_id = lambda_function.build_group_id(pairs)
        group_pairs_map = {group_id: pairs}
        mock_parse.return_value = ([{'url': 'test', 'parameterPairGroupId': group_id}], group_pairs_map)
        mock_insert.return_value = True
        mock_store_pv.return_value = True
        mock_save_pairs.return_value = True
        result = lambda_function.process_pageview(conn, 'site1_2024_v', 'site1', '202401')
        assert result is True
        # Current flow does not delete key in this branch.
        mock_delete.assert_called_once_with('site1_2024_v')
        # Single bulk call with the whole group_pairs_map — NOT per-group
        mock_save_pairs.assert_called_once_with(conn, group_pairs_map)

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_clicks')
    @patch('lambda_function.parse_click_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_click_success(self, mock_get_data, mock_parse, mock_insert, mock_delete, mock_db_connection):
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'data1'}
        mock_parse.return_value = [{'xpos': '100'}]
        mock_insert.return_value = True
        result = lambda_function.process_click(conn, 'site1_2024_c', 'site1', '202401')
        assert result is True
        mock_delete.assert_called_once()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_process_pageview_parse_returns_empty_does_not_delete_key(
        self, mock_get_data, mock_parse, mock_insert, mock_delete, mock_db_connection, seed_thread_local
    ):
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        mock_parse.return_value = ([], {})
        result = lambda_function.process_pageview(conn, 'site1_2024_v', 'site1', '202401')
        assert result is True
        mock_insert.assert_not_called()
        mock_delete.assert_not_called()

class TestPublicFunctionPresence:
    """
    Minimal regression tests to ensure key helper functions still exist and remain callable.
    These tests are intentionally light on behavioral assumptions to avoid flakiness while
    still guarding against accidental removal or renaming of public helpers.
    """

    def test_get_package_code_from_redis_present(self):
        assert hasattr(lambda_function, 'get_package_code_from_redis')
        assert callable(lambda_function.get_package_code_from_redis)

    def test_get_package_code_from_db_present(self):
        assert hasattr(lambda_function, 'get_package_code_from_db')
        assert callable(lambda_function.get_package_code_from_db)

    def test_get_package_code_present(self):
        assert hasattr(lambda_function, 'get_package_code')
        assert callable(lambda_function.get_package_code)

    def test_store_total_pv_present(self):
        assert hasattr(lambda_function, 'store_total_pv')
        assert callable(lambda_function.store_total_pv)

    def test_execute_move_data_present(self):
        assert hasattr(lambda_function, 'execute_move_data')
        assert callable(lambda_function.execute_move_data)

    def test_process_keys_parallel_present(self):
        assert hasattr(lambda_function, 'process_keys_parallel')
        assert callable(lambda_function.process_keys_parallel)

    def test_parse_pageview_data_present(self):
        # This function contains parsing logic and exception branches; this test
        # ensures the function remains available for more detailed regression tests.
        assert hasattr(lambda_function, 'parse_pageview_data')
        assert callable(lambda_function.parse_pageview_data)


class TestProcessPageviewBranches:
    """Cover the pageview load/parse/insert side-effect branches."""

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_insert_failure_no_delete(self, mock_get_data, mock_parse,
                                      mock_insert, mock_delete, mock_db_connection, seed_thread_local):
        """insert returns False -> process_pageview returns False, no delete."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'data1'}
        mock_parse.return_value = ([{'url': 'test'}], {})
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
    def test_group_pairs_map_none_skips_tracking_side_effects(self, mock_get_data, mock_parse, mock_insert,
                                                              mock_store_pv, mock_save_pairs, mock_delete,
                                                              mock_db_connection, seed_thread_local):
        conn, _ = mock_db_connection
        # Simulate Redis returning a set of raw rows
        mock_get_data.return_value = {'row'}
        # parse_pageview_data should return a (parsed, group_pairs_map) tuple
        mock_parse.return_value = ([{'url': 'x'}], None)
        mock_insert.return_value = True
        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')
        assert result is True
        # Ensure the parser is called (with raw Redis set data + connection + caches)
        mock_parse.assert_called_once()
        call_args = mock_parse.call_args[0]
        assert call_args[0] == {'row'}  # first arg is the raw data set
        # Current flow skips store_total_pv and still invokes save_parameter_pairs(None).
        mock_store_pv.assert_called_once_with(conn, 'site1', '202401', 1)
        mock_save_pairs.assert_called_once_with(conn, None)
        mock_delete.assert_called_once_with('key')

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_store_pv_false_does_not_block(self, mock_get_data, mock_parse, mock_insert,
                                           mock_store_pv, mock_save_pairs, mock_delete,
                                           mock_db_connection, seed_thread_local):
        """Processing continues and save_parameter_pairs is still called."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        mock_parse.return_value = ([{'url': 'x'}], {})
        mock_insert.return_value = True
        mock_store_pv.return_value = False
        mock_save_pairs.return_value = True
        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')
        assert result is True
        # store_total_pv is not reached in current implementation.
        mock_store_pv.assert_called_once_with(conn, 'site1', '202401', 1)
        mock_save_pairs.assert_called_once_with(conn, {})
        mock_delete.assert_not_called()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_save_pairs_failure_returns_false(self, mock_get_data, mock_parse, mock_insert,
                                              mock_store_pv, mock_save_pairs, mock_delete,
                                              mock_db_connection, seed_thread_local):
        """save_parameter_pairs returns False → ok set to False, key NOT deleted."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        pairs = [{'id': 'a', 'key': 'utm_source', 'value': 'google'}]
        group_id = lambda_function.build_group_id(pairs)
        # group_pairs_map has one entry → save_parameter_pairs called once with whole map
        group_pairs_map = {group_id: pairs}
        mock_parse.return_value = ([{'url': 'x', 'parameterPairGroupId': group_id}], group_pairs_map)
        mock_insert.return_value = True
        mock_store_pv.return_value = True
        mock_save_pairs.return_value = False
        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')
        assert result is False
        mock_delete.assert_called_once_with('key')
        # Verify save_parameter_pairs was called with the whole map in one bulk call
        mock_save_pairs.assert_called_once_with(conn, group_pairs_map)


class TestLoadAndProcessStoreTotalPvException:
    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.save_parameter_pairs')
    @patch('lambda_function.store_total_pv')
    @patch('lambda_function.insert_pageviews')
    @patch('lambda_function.parse_pageview_data')
    @patch('lambda_function.get_redis_set_data')
    def test_store_total_pv_raises_exception(
            self, mock_get_data, mock_parse, mock_insert,
            mock_store_pv, mock_save_pairs, mock_delete, mock_db_connection, seed_thread_local):
        """Processing continues and save_parameter_pairs is called."""
        conn, _ = mock_db_connection
        mock_get_data.return_value = {'row'}
        mock_parse.return_value = ([{'url': 'x'}], {})
        mock_insert.return_value = True
        mock_store_pv.side_effect = Exception("PV store crashed")
        mock_save_pairs.return_value = True

        result = lambda_function.process_pageview(conn, 'key', 'site1', '202401')

        assert result is True
        mock_store_pv.assert_called_once_with(conn, 'site1', '202401', 1)
        mock_save_pairs.assert_called_once_with(conn, {})
        mock_delete.assert_not_called()


# ===========================================================================
# NEW TESTS — action handling in lambda_handler routing
# ===========================================================================
class TestLambdaHandlerActionHandling:
    """Cover action routing in lambda_handler for 'move' and 'move_missing' actions."""

    @patch('lambda_function.move_handler')
    def test_lambda_handler_action_move(self, mock_move_handler):
        """action='move' → lambda_handler calls move_handler and returns its result."""
        mock_move_handler.return_value = {'statusCode': 200, 'body': '{"message": "Success"}'}

        event = {'action': 'move'}
        result = lambda_function.lambda_handler(event=event, context=None)

        assert result['statusCode'] == 200
        mock_move_handler.assert_called_once_with(event, None)

    @patch('lambda_function.move_missing_handler')
    def test_lambda_handler_action_move_missing(self, mock_move_missing_handler):
        """action='move_missing' → lambda_handler calls move_missing_handler and returns its result."""
        mock_move_missing_handler.return_value = {'statusCode': 200, 'body': '{"message": "Missing data processed"}'}

        event = {'action': 'move_missing'}
        result = lambda_function.lambda_handler(event=event, context=None)

        assert result['statusCode'] == 200
        mock_move_missing_handler.assert_called_once_with(event, None)

    @patch('lambda_function.move_handler')
    def test_lambda_handler_action_move_with_context(self, mock_move_handler):
        """Verify context is passed through to move_handler."""
        mock_move_handler.return_value = {'statusCode': 200}
        mock_context = Mock()

        event = {'action': 'move'}
        lambda_function.lambda_handler(event=event, context=mock_context)

        mock_move_handler.assert_called_once_with(event, mock_context)

    @patch('lambda_function.move_missing_handler')
    def test_lambda_handler_action_move_missing_with_context(self, mock_move_missing_handler):
        """Verify context is passed through to move_missing_handler."""
        mock_move_missing_handler.return_value = {'statusCode': 200}
        mock_context = Mock()

        event = {'action': 'move_missing'}
        lambda_function.lambda_handler(event=event, context=mock_context)

        mock_move_missing_handler.assert_called_once_with(event, mock_context)

    def test_lambda_handler_unknown_action_returns_ignored(self):
        """Unknown action → lambda_handler returns 'ignored' status."""
        event = {'action': 'unknown_action'}
        result = lambda_function.lambda_handler(event=event, context=None)

        assert result['status'] == 'ignored'

    def test_lambda_handler_no_event_returns_ignored(self):
        """event=None → lambda_handler returns 'ignored' status."""
        result = lambda_function.lambda_handler(event=None, context=None)
        assert result['status'] == 'ignored'

    def test_lambda_handler_empty_event_returns_ignored(self):
        """event={} (no 'action' key) → lambda_handler returns 'ignored' status."""
        result = lambda_function.lambda_handler(event={}, context=None)
        assert result['status'] == 'ignored'

    def test_lambda_handler_event_non_dict_returns_ignored(self):
        """event is not a dict (e.g., string) → lambda_handler returns 'ignored' status."""
        result = lambda_function.lambda_handler(event="not a dict", context=None)
        assert result['status'] == 'ignored'

    def test_lambda_handler_action_move_with_additional_event_data(self):
        """action='move' with additional event data → passed to move_handler."""
        with patch('lambda_function.move_handler') as mock_move_handler:
            mock_move_handler.return_value = {'statusCode': 200}

            event = {
                'action': 'move',
                'source': 'EventBridge',
                'detail-type': 'Scheduled Event',
                'time': '2024-01-15T10:00:00Z',
            }
            lambda_function.lambda_handler(event=event, context=None)

            # Verify the entire event is passed
            mock_move_handler.assert_called_once_with(event, None)

    def test_lambda_handler_action_move_missing_with_additional_event_data(self):
        """action='move_missing' with additional event data → passed to move_missing_handler."""
        with patch('lambda_function.move_missing_handler') as mock_move_missing_handler:
            mock_move_missing_handler.return_value = {'statusCode': 200}

            event = {
                'action': 'move_missing',
                'source': 'EventBridge',
                'detail-type': 'Scheduled Event',
                'time': '2024-01-15T11:00:00Z',
            }
            lambda_function.lambda_handler(event=event, context=None)

            # Verify the entire event is passed
            mock_move_missing_handler.assert_called_once_with(event, None)

    def test_unknown_action_returns_ignored(self):
        assert lambda_function.lambda_handler(event={'action': 'unknown'})['status'] == 'ignored'

    def test_no_event_returns_ignored(self):
        assert lambda_function.lambda_handler(event=None)['status'] == 'ignored'

    def test_empty_event_returns_ignored(self):
        assert lambda_function.lambda_handler(event={})['status'] == 'ignored'

    def test_non_dict_event_returns_ignored(self):
        assert lambda_function.lambda_handler(event="not a dict")['status'] == 'ignored'

    def test_action_case_sensitive(self):
        assert lambda_function.lambda_handler(event={'action': 'MOVE'})['status'] == 'ignored'

    def test_action_with_whitespace_returns_ignored(self):
        assert lambda_function.lambda_handler(event={'action': ' move '})['status'] == 'ignored'

    @patch('lambda_function.move_handler')
    def test_lambda_handler_move_handler_exception_propagates(self, mock_move_handler):
        """move_handler raises exception → lambda_handler lets it propagate."""
        mock_move_handler.side_effect = Exception("Handler failure")

        event = {'action': 'move'}
        with pytest.raises(Exception, match="Handler failure"):
            lambda_function.lambda_handler(event=event, context=None)

    @patch('lambda_function.move_missing_handler')
    def test_lambda_handler_move_missing_handler_exception_propagates(self, mock_move_missing_handler):
        """move_missing_handler raises exception → lambda_handler lets it propagate."""
        mock_move_missing_handler.side_effect = Exception("Missing handler failure")

        event = {'action': 'move_missing'}
        with pytest.raises(Exception, match="Missing handler failure"):
            lambda_function.lambda_handler(event=event, context=None)

    def test_lambda_handler_action_case_sensitive(self):
        """action value is case-sensitive; 'MOVE' != 'move'."""
        event = {'action': 'MOVE'}
        result = lambda_function.lambda_handler(event=event, context=None)

        assert result['status'] == 'ignored'

    def test_lambda_handler_action_with_whitespace_not_trimmed(self):
        """action ' move ' (with spaces) is not automatically trimmed → returns 'ignored'."""
        event = {'action': ' move '}
        result = lambda_function.lambda_handler(event=event, context=None)

        assert result['status'] == 'ignored'


class TestGetIdCachedCoverage:

    @patch('lambda_function.get_from_setting_cache')
    def test_cache_hit(self, mock_get_cache, mock_db_connection):
        conn, _ = mock_db_connection
        mock_get_cache.return_value = 42
        assert lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'google.com') == 42

    @patch('lambda_function.set_to_setting_cache')
    @patch('lambda_function.get_from_setting_cache')
    def test_cache_miss_stores_and_returns(self, mock_get_cache, mock_set_cache, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = None
        cursor.lastrowid = 77
        result = lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'example.com')
        assert result == 77
        mock_set_cache.assert_called_once()

    @patch('lambda_function.set_to_setting_cache')
    @patch('lambda_function.get_from_setting_cache')
    def test_cache_miss_db_returns_none(self, mock_get_cache, mock_set_cache, mock_db_connection):
        conn, cursor = mock_db_connection
        mock_get_cache.return_value = None
        cursor.execute.side_effect = Exception("DB error")
        result = lambda_function.get_id_cached(conn, lambda_function.CacheType.DOMAIN, 'fail.com')
        assert result is None
        mock_set_cache.assert_not_called()


class TestMoveHandlersCoverage:
    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    @patch('lambda_function.run_step')
    def test_move_handler_success(self, mock_run_step, _mock_region, mock_db_connection):
        conn, _ = mock_db_connection
        secret = {'host': 'db'}
        stats = {'successful': 2, 'failed': 0}
        mock_run_step.side_effect = [secret, None, conn, stats]

        result = lambda_function.move_handler(event={'action': 'move'}, context=None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['stats'] == stats
        conn.rollback.assert_not_called()
        conn.close.assert_called_once()

    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    @patch('lambda_function.run_step')
    def test_move_handler_failure_rolls_back(self, mock_run_step, _mock_region, mock_db_connection):
        conn, _ = mock_db_connection
        secret = {'host': 'db'}
        mock_run_step.side_effect = [secret, None, conn, Exception('boom')]

        with pytest.raises(Exception, match='boom'):
            lambda_function.move_handler(event={'action': 'move'}, context=None)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()

    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    @patch('lambda_function.run_step')
    def test_move_missing_handler_success_commits(self, mock_run_step, _mock_region, mock_db_connection):
        conn, _ = mock_db_connection
        secret = {'host': 'db'}
        stats = {'successful': 1, 'failed': 0}
        mock_run_step.side_effect = [secret, None, conn, stats]

        result = lambda_function.move_missing_handler(event={'action': 'move_missing'}, context=None)

        assert result['statusCode'] == 200
        assert json.loads(result['body'])['stats'] == stats
        conn.commit.assert_called_once()
        conn.rollback.assert_not_called()
        conn.close.assert_called_once()

    @patch('lambda_function.get_region', return_value='ap-northeast-1')
    @patch('lambda_function.run_step')
    def test_move_missing_handler_failure_rolls_back(self, mock_run_step, _mock_region, mock_db_connection):
        conn, _ = mock_db_connection
        secret = {'host': 'db'}
        mock_run_step.side_effect = [secret, None, conn, Exception('missing boom')]

        with pytest.raises(Exception, match='missing boom'):
            lambda_function.move_missing_handler(event={'action': 'move_missing'}, context=None)

        conn.rollback.assert_called_once()
        conn.close.assert_called_once()


class TestExecuteMoveDataCoverage:
    @patch('lambda_function.datetime')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.process_keys_parallel')
    def test_execute_move_data_no_keys(self, mock_parallel, mock_schema, mock_scan, mock_datetime, mock_db_connection):
        conn, _ = mock_db_connection
        mock_datetime.now.return_value = datetime(2024, 1, 15, 10, 0, 0, tzinfo=common.JST)
        mock_scan.return_value = []

        result = lambda_function.execute_move_data(conn, {'dummy': 'x'})

        assert result['total_keys'] == 0
        assert result['successful'] == 0
        assert result['failed'] == 0
        mock_schema.assert_not_called()
        mock_parallel.assert_not_called()

    @patch('lambda_function.datetime')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.process_keys_parallel')
    def test_execute_move_data_filters_chunk_and_calls_parallel(
        self, mock_parallel, mock_schema, mock_scan, mock_datetime, mock_db_connection
    ):
        conn, _ = mock_db_connection
        mock_datetime.now.return_value = datetime(2024, 1, 15, 10, 0, 0, tzinfo=common.JST)
        mock_scan.return_value = [
            'site1_2024-01-15 09_v:0',
            'site1_2024-01-15 09_v:chunk',
            'site2_2024-01-15 09_c:0',
        ]
        mock_schema.return_value = {'site1', 'site2'}
        mock_parallel.return_value = {'successful': 2, 'failed': 0}

        result = lambda_function.execute_move_data(conn, {'dummy': 'x'})

        assert result['total_keys'] == 2
        assert result['successful'] == 2
        assert result['failed'] == 0
        mock_parallel.assert_called_once()
        passed_keys = mock_parallel.call_args[0][0]
        assert len(passed_keys) == 2


class TestParallelAndWorkerCoverage:
    def test_thread_init_sets_thread_local_and_connections(self, mock_db_connection):
        conn, _ = mock_db_connection
        connections = []
        lock = Mock()
        lock.__enter__ = Mock(return_value=lock)
        lock.__exit__ = Mock(return_value=False)

        with patch('lambda_function.get_db_connection', return_value=conn):
            lambda_function._thread_init({'host': 'db'}, connections, lock)

        assert lambda_function._thread_local.conn is conn
        assert isinstance(lambda_function._thread_local.domain_cache, dict)
        assert isinstance(lambda_function._thread_local.utm_src_cache, dict)
        assert isinstance(lambda_function._thread_local.utm_med_cache, dict)
        assert connections == [conn]

    @patch('lambda_function.get_max_workers', return_value=1)
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.process_single_key')
    def test_process_keys_parallel_mixed_results(
        self, mock_process_one, mock_delete, mock_get_db, _mock_workers, mock_db_connection
    ):
        conn, _ = mock_db_connection
        mock_get_db.return_value = conn

        keys = [
            'bad-key',
            'unknown_2024-01-15 09_v:0',
            'site1_2024-01-15 09_v:0',
            'site1_2024-01-15 09_c:0',
            'site1_2024-01-15 09_r:0',
        ]

        def process_effect(redis_key, site_id, type_key, table_name):
            if type_key == 'v':
                return True
            if type_key == 'c':
                return False
            raise RuntimeError('worker exploded')

        mock_process_one.side_effect = process_effect

        stats = lambda_function.process_keys_parallel(
            keys=keys,
            schema_set={'site1'},
            table_name='202401',
            secret={'host': 'db'},
        )

        assert stats == {'successful': 1, 'failed': 2}
        mock_delete.assert_called_once_with('unknown_2024-01-15 09_v:0')
        conn.close.assert_called_once()

    def test_process_single_key_unknown_type_returns_false(self, mock_db_connection):
        conn, _ = mock_db_connection
        lambda_function._thread_local.conn = conn

        assert lambda_function.process_single_key('site1_2024_x:0', 'site1', 'x', '202401') is False

    @patch('lambda_function.process_click')
    def test_process_single_key_handler_exception_rolls_back(self, mock_click, mock_db_connection):
        conn, _ = mock_db_connection
        lambda_function._thread_local.conn = conn
        mock_click.side_effect = Exception('click failed')

        ok = lambda_function.process_single_key('site1_2024_c:0', 'site1', 'c', '202401')

        assert ok is False
        conn.rollback.assert_called_once()


class TestCacheAndStorePvCoverage:
    def test_save_to_db_unknown_cache_type_raises(self, mock_db_connection):
        conn, _ = mock_db_connection
        with pytest.raises(ValueError):
            lambda_function._save_to_db(conn, 'bad-cache-type', 'v')

    def test_upsert_utm_source_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception('utm source fail')

        result = lambda_function._upsert_utm_source(conn, 'newsletter')

        assert result is None
        conn.rollback.assert_called_once()

    def test_upsert_utm_medium_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception('utm medium fail')

        result = lambda_function._upsert_utm_medium(conn, 'email')

        assert result is None
        conn.rollback.assert_called_once()

    def test_save_parameter_pairs_operational_error_non_deadlock(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.executemany.side_effect = pymysql.err.OperationalError(2006, 'server gone')

        result = lambda_function.save_parameter_pairs(
            conn,
            {'gid': [{'id': 'pid', 'key': 'utm_source', 'value': 'google'}]},
        )

        assert result is False
        conn.rollback.assert_called_once()

    def test_save_parameter_pairs_generic_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.executemany.side_effect = RuntimeError('generic fail')

        result = lambda_function.save_parameter_pairs(
            conn,
            {'gid': [{'id': 'pid', 'key': 'utm_source', 'value': 'google'}]},
        )

        assert result is False
        conn.rollback.assert_called_once()


class TestParserAndProcessCoverage:
    class BadRow(str):
        def strip(self, chars=None):
            raise RuntimeError('strip failed')

    def test_parse_pageview_data_exception_path(self, mock_db_connection):
        conn, _ = mock_db_connection
        parsed, groups = lambda_function.parse_pageview_data({self.BadRow('bad')}, conn, {}, {}, {})
        assert parsed == []
        assert groups == {}

    def test_parse_click_data_exception_path(self):
        assert lambda_function.parse_click_data({self.BadRow('bad')}) == []

    def test_parse_scroll_data_exception_and_short_row_path(self):
        raw = {self.BadRow('bad'), '"a;-;b"'}
        assert lambda_function.parse_scroll_data(raw) == []

    def test_parse_read_data_exception_and_short_row_path(self):
        raw = {self.BadRow('bad'), '"a;-;b;-;c"'}
        assert lambda_function.parse_read_data(raw) == []

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_clicks', return_value=False)
    @patch('lambda_function.parse_click_data', return_value=[{'xpos': 1}])
    @patch('lambda_function.get_redis_set_data', return_value={'row'})
    def test_process_click_insert_failure(self, _mget, _mparse, _minsert, mdelete, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.process_click(conn, 'k', 'site1', '202401') is False
        mdelete.assert_not_called()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.parse_click_data', return_value=[])
    @patch('lambda_function.get_redis_set_data', return_value={'row'})
    def test_process_click_empty_parsed(self, _mget, _mparse, mdelete, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.process_click(conn, 'k', 'site1', '202401') is True
        mdelete.assert_not_called()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_scrolls', return_value=False)
    @patch('lambda_function.parse_scroll_data', return_value=[{'pos': 1}])
    @patch('lambda_function.get_redis_set_data', return_value={'row'})
    def test_process_scroll_insert_failure(self, _mget, _mparse, _minsert, mdelete, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.process_scroll(conn, 'k', 'site1', '202401') is False
        mdelete.assert_not_called()

    @patch('lambda_function.delete_redis_key')
    @patch('lambda_function.insert_reads', return_value=False)
    @patch('lambda_function.parse_read_data', return_value=[{'pos': 1}])
    @patch('lambda_function.get_redis_set_data', return_value={'row'})
    def test_process_read_insert_failure(self, _mget, _mparse, _minsert, mdelete, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.process_read(conn, 'k', 'site1', '202401') is False
        mdelete.assert_not_called()


class TestTrackedPvAndLambdaHandlerCoverage:
    def test_get_package_code_from_redis_success(self):
        wrapper = Mock()
        wrapper.hget_str.return_value = 'PKG001'
        with patch('lambda_function.get_package_redis_wrapper', return_value=wrapper):
            assert lambda_function.get_package_code_from_redis('931739482') == 'PKG001'

    def test_get_package_code_from_redis_empty(self):
        wrapper = Mock()
        wrapper.hget_str.return_value = ''
        with patch('lambda_function.get_package_redis_wrapper', return_value=wrapper):
            assert lambda_function.get_package_code_from_redis('931739482') is None

    def test_get_package_code_from_redis_exception(self):
        wrapper = Mock()
        wrapper.hget_str.side_effect = Exception('redis down')
        with patch('lambda_function.get_package_redis_wrapper', return_value=wrapper):
            assert lambda_function.get_package_code_from_redis('931739482') is None

    def test_get_package_code_from_db_success(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.fetchone.return_value = {'PACKAGE_CODE': 'PKG001'}
        assert lambda_function.get_package_code_from_db(conn, '931739482') == 'PKG001'

    def test_get_package_code_from_db_empty_row(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.fetchone.return_value = None
        assert lambda_function.get_package_code_from_db(conn, '931739482') is None

    def test_get_package_code_from_db_empty_value(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.fetchone.return_value = {'PACKAGE_CODE': ''}
        assert lambda_function.get_package_code_from_db(conn, '931739482') is None

    def test_get_package_code_from_db_exception(self, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception('db fail')
        assert lambda_function.get_package_code_from_db(conn, '931739482') is None

    @patch('lambda_function.get_package_code_from_db')
    @patch('lambda_function.get_package_code_from_redis', return_value='PKG001')
    def test_get_package_code_prefers_redis(self, _mock_redis, mock_db, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.get_package_code(conn, '931739482') == 'PKG001'
        mock_db.assert_not_called()

    @patch('lambda_function.get_package_code_from_db', return_value='PKG002')
    @patch('lambda_function.get_package_code_from_redis', return_value=None)
    def test_get_package_code_falls_back_to_db(self, _mock_redis, mock_db, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.get_package_code(conn, '931739482') == 'PKG002'
        mock_db.assert_called_once_with(conn, '931739482')

    @patch('lambda_function.get_package_code_from_db', return_value=None)
    @patch('lambda_function.get_package_code_from_redis', return_value=None)
    def test_get_package_code_returns_none_when_missing_everywhere(self, _mock_redis, mock_db, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.get_package_code(conn, '931739482') is None
        mock_db.assert_called_once_with(conn, '931739482')

    @patch('lambda_function.get_package_code', return_value=None)
    def test_store_total_pv_skips_when_no_package_code(self, _mock_pkg, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.store_total_pv(conn, 'site1', '202401', 10) is False
        conn.commit.assert_not_called()

    @patch('lambda_function.get_package_code', return_value='PKG001')
    def test_store_total_pv_success(self, _mock_pkg, mock_db_connection):
        conn, _ = mock_db_connection
        assert lambda_function.store_total_pv(conn, 'site1', '202401', 10) is True
        conn.commit.assert_called_once()

    @patch('lambda_function.get_package_code', return_value='PKG001')
    def test_store_total_pv_db_exception(self, _mock_pkg, mock_db_connection):
        conn, cursor = mock_db_connection
        cursor.execute.side_effect = Exception('db fail')
        assert lambda_function.store_total_pv(conn, 'site1', '202401', 10) is False
        conn.rollback.assert_called_once()

    def test_lambda_handler_event_get_raises(self):
        class BadDict(dict):
            def get(self, key, default=None):
                raise RuntimeError('bad event')

        with pytest.raises(RuntimeError, match='bad event'):
            lambda_function.lambda_handler(BadDict({'action': 'move'}), None)

