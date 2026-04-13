import pytest
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, call
import pymysql
import pytz

from lambda_function import execute_move_missing_data
from common import JST, PATTERN_YYYY_MM_DD_HH, PATTERN_YYYYMM


class TestExecuteMoveMissingData:
    """Test suite for the execute_move_missing_data function."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock(spec=pymysql.connections.Connection)
        return conn

    @pytest.fixture
    def mock_secret(self):
        """Create a mock database secret."""
        return {
            "username": "testuser",
            "password": "mock-password-value",
            "host": "localhost",
            "port": 3306,
            "dbname": "heatmap"
        }

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_success(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test successful execution of execute_move_missing_data.

        Scenario:
        - Current time is 2024-01-15 14:30 JST
        - Keys for 2024-01-13 (now - 2 hours) are processed
        - Keys from current hour and one hour ago are excluded
        """
        # Setup time mock
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        # Setup Redis keys
        current_hour_key = test_time.strftime(PATTERN_YYYY_MM_DD_HH)  # "2024-01-15 14"
        one_hour_before = test_time - timedelta(hours=1)
        one_hour_key = one_hour_before.strftime(PATTERN_YYYY_MM_DD_HH)  # "2024-01-15 13"
        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")  # "2024-01-13"

        # Mock all keys from the month
        all_month_keys = [
            "site1_v_2024-01-13 12:data",
            "site1_v_2024-01-13 13:data",
            "site1_v_2024-01-13 14:data",
            "site1_c_2024-01-15 14:data",  # Current hour - should be excluded
            "site1_c_2024-01-15 13:data",  # One hour before - should be excluded
            "site2_v_2024-01-13 10:data",
            "site2_v_2024-01-13 11:chunk",  # Chunk key - should be filtered
        ]

        current_hour_keys = ["site1_c_2024-01-15 14:data"]
        one_hour_keys = ["site1_c_2024-01-15 13:data"]

        def scan_side_effect(pattern):
            if f"*{current_hour_key}*" in pattern:
                return current_hour_keys
            elif f"*{one_hour_key}*" in pattern:
                return one_hour_keys
            elif f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1", "site2", "site3"}
        mock_process_parallel.return_value = {"successful": 4, "failed": 0}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions
        assert result["date_key"] == f"*{month_pattern}*"
        assert result["table_name"] == two_hours_before.strftime(PATTERN_YYYYMM)
        assert result["total_keys"] == 4  # Excludes 2 current/one-hour keys and 1 chunk key
        assert result["successful"] == 4
        assert result["failed"] == 0

        # Verify schema lookup was called
        mock_get_schema_set.assert_called_once_with(mock_connection)

        # Verify parallel processing was called
        mock_process_parallel.assert_called_once()

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_no_keys(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test when no keys are found after filtering.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        one_hour_before = test_time - timedelta(hours=1)
        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")

        # Empty results
        mock_scan_redis.return_value = []
        mock_get_schema_set.return_value = {"site1", "site2"}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions
        assert result["date_key"] == f"*{month_pattern}*"
        assert result["total_keys"] == 0
        assert result["successful"] == 0
        assert result["failed"] == 0

        # Parallel processing should not be called when no keys
        mock_process_parallel.assert_not_called()

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_filters_chunk_keys(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test that chunk/index keys are properly filtered out.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        current_hour_key = test_time.strftime(PATTERN_YYYY_MM_DD_HH)
        one_hour_before = test_time - timedelta(hours=1)
        one_hour_key = one_hour_before.strftime(PATTERN_YYYY_MM_DD_HH)
        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")

        # Keys with chunk markers
        all_month_keys = [
            "site1_v_2024-01-13 12:chunk",  # Chunk key - filtered
            "site1_v_2024-01-13 12:data",   # Normal key
            "site2_v_2024-01-13 11:chunk",  # Chunk key - filtered
            "site2_v_2024-01-13 11:data",   # Normal key
        ]

        def scan_side_effect(pattern):
            if f"*{current_hour_key}*" in pattern:
                return []
            elif f"*{one_hour_key}*" in pattern:
                return []
            elif f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1", "site2"}
        mock_process_parallel.return_value = {"successful": 2, "failed": 0}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions - only 2 non-chunk keys should be processed
        assert result["total_keys"] == 2
        assert result["successful"] == 2
        assert result["failed"] == 0

        # Verify the keys passed to parallel processing
        call_args = mock_process_parallel.call_args
        processed_keys = call_args[0][0]  # First positional argument
        assert len(processed_keys) == 2
        assert "site1_v_2024-01-13 12:data" in processed_keys
        assert "site2_v_2024-01-13 11:data" in processed_keys

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_excludes_current_and_one_hour_keys(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test that keys from current hour and one hour before are excluded.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        current_hour_key = test_time.strftime(PATTERN_YYYY_MM_DD_HH)  # "2024-01-15 14"
        one_hour_before = test_time - timedelta(hours=1)
        one_hour_key = one_hour_before.strftime(PATTERN_YYYY_MM_DD_HH)  # "2024-01-15 13"
        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")  # "2024-01-13"

        # All keys from the month
        all_month_keys = [
            "site1_v_2024-01-13 10:data",  # 4 hours ago - should be included
            "site1_v_2024-01-13 11:data",  # 3 hours ago - should be included
            "site1_v_2024-01-13 12:data",  # 2 hours ago - should be included
            "site1_v_2024-01-15 13:data",  # 1 hour ago - should be excluded
            "site1_v_2024-01-15 14:data",  # current hour - should be excluded
        ]

        current_hour_keys = ["site1_v_2024-01-15 14:data"]
        one_hour_keys = ["site1_v_2024-01-15 13:data"]

        def scan_side_effect(pattern):
            if f"*{current_hour_key}*" in pattern:
                return current_hour_keys
            elif f"*{one_hour_key}*" in pattern:
                return one_hour_keys
            elif f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1"}
        mock_process_parallel.return_value = {"successful": 3, "failed": 0}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions - only 3 older keys should be processed
        assert result["total_keys"] == 3
        assert result["successful"] == 3

        # Verify the keys passed to parallel processing
        call_args = mock_process_parallel.call_args
        processed_keys = call_args[0][0]
        assert len(processed_keys) == 3
        assert "site1_v_2024-01-13 10:data" in processed_keys
        assert "site1_v_2024-01-13 11:data" in processed_keys
        assert "site1_v_2024-01-13 12:data" in processed_keys

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_with_failures(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test handling of partial failures during parallel processing.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        current_hour_key = test_time.strftime(PATTERN_YYYY_MM_DD_HH)
        one_hour_before = test_time - timedelta(hours=1)
        one_hour_key = one_hour_before.strftime(PATTERN_YYYY_MM_DD_HH)
        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")

        all_month_keys = [
            "site1_v_2024-01-13 12:data",
            "site1_c_2024-01-13 12:data",
            "site1_s_2024-01-13 12:data",
            "site2_r_2024-01-13 11:data",
        ]

        def scan_side_effect(pattern):
            if f"*{current_hour_key}*" in pattern:
                return []
            elif f"*{one_hour_key}*" in pattern:
                return []
            elif f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1", "site2"}
        # 3 successful, 1 failed
        mock_process_parallel.return_value = {"successful": 3, "failed": 1}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions
        assert result["total_keys"] == 4
        assert result["successful"] == 3
        assert result["failed"] == 1

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_table_name_format(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test that the table_name is correctly formatted as YYYYMM from 2 hours ago.
        """
        test_time = datetime(2024, 2, 29, 1, 15, 0, tzinfo=JST)  # End of Feb, early morning
        mock_datetime_class.now.return_value = test_time

        one_hour_before = test_time - timedelta(hours=1)
        two_hours_before = test_time - timedelta(hours=2)  # 2024-02-28 23 (previous day, previous month)
        expected_table_name = two_hours_before.strftime(PATTERN_YYYYMM)  # "202402"
        month_pattern = two_hours_before.strftime("%Y-%m")

        all_month_keys = ["site1_v_2024-02-28 23:data"]

        def scan_side_effect(pattern):
            if f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1"}
        mock_process_parallel.return_value = {"successful": 1, "failed": 0}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions
        assert result["table_name"] == expected_table_name
        assert result["table_name"] == "202402"

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_passes_correct_table_name_to_parallel(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test that the correct table_name is passed to process_keys_parallel.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")
        expected_table_name = two_hours_before.strftime(PATTERN_YYYYMM)

        all_month_keys = ["site1_v_2024-01-13 12:data"]

        def scan_side_effect(pattern):
            if f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1"}
        mock_process_parallel.return_value = {"successful": 1, "failed": 0}

        # Execute
        execute_move_missing_data(mock_connection, mock_secret)

        # Verify the arguments passed to process_keys_parallel
        call_args = mock_process_parallel.call_args
        passed_table_name = call_args[0][2]  # Third positional argument
        assert passed_table_name == expected_table_name

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_passes_schema_set_to_parallel(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test that the correct schema_set is passed to process_keys_parallel.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")

        all_month_keys = ["site1_v_2024-01-13 12:data"]
        expected_schemas = {"site1", "site2", "site3"}

        def scan_side_effect(pattern):
            if f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = expected_schemas
        mock_process_parallel.return_value = {"successful": 1, "failed": 0}

        # Execute
        execute_move_missing_data(mock_connection, mock_secret)

        # Verify the schema_set passed to process_keys_parallel
        call_args = mock_process_parallel.call_args
        passed_schema_set = call_args[0][1]  # Second positional argument
        assert passed_schema_set == expected_schemas

    @patch('lambda_function.process_keys_parallel')
    @patch('lambda_function.get_schema_set')
    @patch('lambda_function.scan_redis_keys')
    @patch('lambda_function.datetime')
    def test_execute_move_missing_data_return_structure(
        self,
        mock_datetime_class,
        mock_scan_redis,
        mock_get_schema_set,
        mock_process_parallel,
        mock_connection,
        mock_secret
    ):
        """
        Test that the return structure contains all required fields.
        """
        test_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=JST)
        mock_datetime_class.now.return_value = test_time

        two_hours_before = test_time - timedelta(hours=2)
        month_pattern = two_hours_before.strftime("%Y-%m")

        all_month_keys = ["site1_v_2024-01-13 12:data"]

        def scan_side_effect(pattern):
            if f"*{month_pattern}*" in pattern:
                return all_month_keys
            return []

        mock_scan_redis.side_effect = scan_side_effect
        mock_get_schema_set.return_value = {"site1"}
        mock_process_parallel.return_value = {"successful": 1, "failed": 0}

        # Execute
        result = execute_move_missing_data(mock_connection, mock_secret)

        # Assertions on return structure
        assert isinstance(result, dict)
        assert "date_key" in result
        assert "table_name" in result
        assert "total_keys" in result
        assert "successful" in result
        assert "failed" in result
        assert len(result) == 5

        # Verify types
        assert isinstance(result["date_key"], str)
        assert isinstance(result["table_name"], str)
        assert isinstance(result["total_keys"], int)
        assert isinstance(result["successful"], int)
        assert isinstance(result["failed"], int)

