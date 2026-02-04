"""
Unit tests for MonthlyAddingSiteTablesConsumer Lambda function

This test suite provides comprehensive coverage for the Lambda function
that creates monthly tables for sites based on scheduled site lists.

Test Categories:
- Lambda Handler: Main execution flow, error handling, empty data scenarios
- AWS Services: Secrets Manager integration
- Edge Cases: Missing records, invalid data, connection errors

All tests use mocks to avoid external dependencies (no real DB/AWS connections).
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime
from botocore.exceptions import ClientError
import pytz

# Import Lambda function
import lambda_function


class TestGetSecret:
    """Test AWS Secrets Manager"""
    
    @patch('boto3.client')
    def test_get_secret_success(self, mock_boto_client):
        """Test successful secret retrieval"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        
        mock_client.get_secret_value.return_value = {
            'SecretString': json.dumps({
                'host': 'test-db.rds.amazonaws.com',
                'username': 'admin',
                'password': 'secret123'
            })
        }
        
        result = lambda_function.get_secret('ap-northeast-1')
        
        assert result['host'] == 'test-db.rds.amazonaws.com'
        assert result['username'] == 'admin'
        mock_boto_client.assert_called_once()
    
    @patch('boto3.client')
    def test_get_secret_access_denied(self, mock_boto_client):
        """Test Secrets Manager access denied"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        
        error_response = {
            'Error': {
                'Code': 'AccessDeniedException',
                'Message': 'User is not authorized'
            }
        }
        mock_client.get_secret_value.side_effect = ClientError(
            error_response, 'GetSecretValue'
        )
        
        with pytest.raises(ClientError) as exc_info:
            lambda_function.get_secret('ap-northeast-1')
        
        assert 'AccessDeniedException' in str(exc_info.value)
    
    @patch('boto3.client')
    def test_get_secret_not_found(self, mock_boto_client):
        """Test secret not found"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        
        error_response = {
            'Error': {
                'Code': 'ResourceNotFoundException',
                'Message': 'Secret not found'
            }
        }
        mock_client.get_secret_value.side_effect = ClientError(
            error_response, 'GetSecretValue'
        )
        
        with pytest.raises(ClientError) as exc_info:
            lambda_function.get_secret('ap-northeast-1')
        
        assert 'ResourceNotFoundException' in str(exc_info.value)


class TestGetDBConnection:
    """Test database connection"""
    
    @patch('lambda_function.get_ssl_context')
    @patch('pymysql.connect')
    def test_get_db_connection_success(self, mock_connect, mock_ssl):
        """Test successful DB connection"""
        mock_ssl.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        
        secret = {
            'host': 'test-db.rds.amazonaws.com',
            'port': 3306,
            'username': 'admin',
            'password': 'secret',
            'dbname': 'HEAT_MAP'
        }
        
        result = lambda_function.get_db_connection(secret)
        
        assert result == mock_conn
        mock_connect.assert_called_once()
    
    @patch('lambda_function.get_ssl_context')
    @patch('pymysql.connect')
    def test_get_db_connection_operational_error(self, mock_connect, mock_ssl):
        """Test DB connection operational error"""
        import pymysql
        
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(2003, "Can't connect")
        
        secret = {'host': 'test', 'username': 'user', 'password': 'pass'}
        
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)
    
    @patch('lambda_function.get_ssl_context')
    @patch('pymysql.connect')
    def test_db_connection_access_denied(self, mock_connect, mock_ssl):
        """Test access denied (wrong credentials)"""
        import pymysql
        
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(
            1045, "Access denied for user"
        )
        
        secret = {
            'host': 'db.amazonaws.com',
            'username': 'wrong_user',
            'password': 'wrong_pass'
        }
        
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)
    
    @patch('lambda_function.get_ssl_context')
    @patch('pymysql.connect')
    def test_db_connection_other_operational_error(self, mock_connect, mock_ssl):
        """Test other operational errors"""
        import pymysql
        
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(
            2006, "MySQL server has gone away"
        )
        
        secret = {
            'host': 'db.amazonaws.com',
            'username': 'user',
            'password': 'pass'
        }
        
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)
    
    @patch('lambda_function.get_ssl_context')
    @patch('pymysql.connect')
    def test_db_connection_generic_exception(self, mock_connect, mock_ssl):
        """Test generic exception"""
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = Exception("Unexpected error")
        
        secret = {
            'host': 'db.amazonaws.com',
            'username': 'user',
            'password': 'pass'
        }
        
        with pytest.raises(Exception, match="Unexpected error"):
            lambda_function.get_db_connection(secret)


class TestGetSSLContext:
    """Test SSL context creation"""
    
    @patch('os.path.exists')
    @patch('ssl.SSLContext')
    def test_get_ssl_context_region_bundle(self, mock_ssl_context, mock_exists):
        """Test SSL context with region-specific bundle"""
        mock_exists.return_value = True
        mock_ctx = MagicMock()
        mock_ssl_context.return_value = mock_ctx
        
        result = lambda_function.get_ssl_context('ap-northeast-1')
        
        assert result == mock_ctx
        mock_ctx.load_verify_locations.assert_called_once()
    
    @patch('os.path.exists')
    def test_get_ssl_context_missing_bundle(self, mock_exists):
        """Test SSL context with missing bundle"""
        mock_exists.return_value = False
        
        with pytest.raises(FileNotFoundError, match="CA bundle not found"):
            lambda_function.get_ssl_context('ap-northeast-1')


class TestGetRegion:
    """Test get_region function"""
    
    @patch.dict('os.environ', {}, clear=True)
    def test_default_region_when_not_set(self):
        """Test default region when AWS_REGION not set"""
        import os
        if 'AWS_REGION' in os.environ:
            del os.environ['AWS_REGION']
        
        result = lambda_function.get_region()
        assert result == 'ap-northeast-1'
    
    @patch.dict('os.environ', {'AWS_REGION': 'us-west-2'})
    def test_region_from_environment(self):
        """Test region from environment variable"""
        result = lambda_function.get_region()
        assert result == 'us-west-2'


class TestRunStep:
    """Test step execution wrapper"""
    
    def test_run_step_success(self):
        """Test successful step execution"""
        
        def dummy_func(a, b):
            return a + b
        
        result = lambda_function.run_step("test_step", dummy_func, 2, 3)
        assert result == 5
    
    def test_run_step_with_error(self):
        """Test step execution with error"""
        
        def error_func():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError, match="Test error"):
            lambda_function.run_step("error_step", error_func)
    
    def test_run_step_with_kwargs(self):
        """Test step execution with keyword arguments"""
        
        def func_with_kwargs(a, b=10):
            return a * b
        
        result = lambda_function.run_step("test_step", func_with_kwargs, 5, b=3)
        assert result == 15


class TestLambdaHandler:
    """Test main Lambda handler"""
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_all_sites')
    @patch('lambda_function.find_by_apply_on')
    @patch('lambda_function.create_tables_for_sites')
    @patch('lambda_function.update_log')
    @patch('lambda_function.SearchDate.now')
    def test_lambda_handler_success(
            self, mock_now, mock_update, mock_create, mock_find,
            mock_get_sites, mock_db_conn, mock_secret, mock_region
    ):
        """Test successful Lambda execution"""
        # Setup mocks
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test-host'}
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn
        
        # Mock current date
        jst = pytz.timezone('Asia/Tokyo')
        mock_date = lambda_function.SearchDate(datetime(2024, 1, 15, tzinfo=jst))
        mock_now.return_value = mock_date
        
        mock_get_sites.return_value = [1, 2, 3, 4, 5]
        
        mock_find.return_value = {
            'ID': 1,
            'LIST_SITES': json.dumps([1, 2, 3])
        }
        
        mock_result = lambda_function.ResultCreatedTable()
        mock_result.total_sites = 3
        mock_result.total_sites_success = 3
        mock_result.total_sites_failed = 0
        mock_create.return_value = mock_result
        
        # Execute
        response = lambda_function.lambda_handler()
        
        # Verify response structure
        assert response['statusCode'] == 200
        
        # Parse and validate JSON body
        body = json.loads(response['body'])
        assert body['message'] == 'Monthly tables created successfully'
        
        # Verify result structure
        assert 'result' in body
        result = body['result']
        assert result['total_sites'] == 3
        assert result['total_sites_success'] == 3
        assert result['total_sites_failed'] == 0
        assert result['failed_items'] == []
        
        # Verify execute_time is present and is a number
        assert 'execute_time' in body
        assert isinstance(body['execute_time'], (int, float))
        assert body['execute_time'] >= 0
        
        # Verify all mocked functions were called
        assert mock_secret.called
        assert mock_db_conn.called
        assert mock_get_sites.called
        assert mock_find.called
        assert mock_create.called
        assert mock_update.called
        mock_conn.commit.assert_called_once()
        
        # Verify cleanup: both cursor and connection are closed in finally block
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_all_sites')
    @patch('lambda_function.find_by_apply_on')
    @patch('lambda_function.SearchDate.now')
    def test_lambda_handler_no_record_found(
            self, mock_now, mock_find, mock_get_sites,
            mock_db_conn, mock_secret, mock_region
    ):
        """Test Lambda when no record found for current date
        Note: Mock parameters are in reverse order of decorators (bottom-to-top)
        """
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test-host'}
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn
        
        jst = pytz.timezone('Asia/Tokyo')
        mock_date = lambda_function.SearchDate(datetime(2024, 1, 15, tzinfo=jst))
        mock_now.return_value = mock_date
        
        mock_get_sites.return_value = [1, 2, 3]
        mock_find.return_value = None  # No record found
        
        # Execute
        response = lambda_function.lambda_handler()
        
        # Verify response
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'No record to process'
        assert body['result']['total_sites'] == 0
        
        # Verify cleanup: cursor and connection are closed even when no record found
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_all_sites', side_effect=Exception("DB error"))
    def test_lambda_handler_error_rollback(
            self, mock_get_sites, mock_db_conn, mock_secret, mock_region
    ):
        """Test Lambda handles errors and rollbacks
        Note: Mock parameters are in reverse order of decorators (bottom-to-top)
        """
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn
        
        # Execute and verify
        with pytest.raises(Exception, match="DB error"):
            lambda_function.lambda_handler()
        
        # Verify error handling: rollback is called
        mock_conn.rollback.assert_called_once()
        
        # Verify cleanup: cursor and connection are closed even on error
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()


class TestResultCreatedTable:
    """Test ResultCreatedTable class"""
    
    def test_result_created_table_initialization(self):
        """Test ResultCreatedTable initialization"""
        result = lambda_function.ResultCreatedTable()
        
        assert result.total_sites == 0
        assert result.total_sites_success == 0
        assert result.total_sites_failed == 0
        assert result.failed_items == []
    
    def test_result_to_dict(self):
        """Test ResultCreatedTable.to_dict()"""
        result = lambda_function.ResultCreatedTable()
        result.total_sites = 10
        result.total_sites_success = 8
        result.total_sites_failed = 2
        result.failed_items = [5, 9]
        
        result_dict = result.to_dict()
        
        assert result_dict['total_sites'] == 10
        assert result_dict['total_sites_success'] == 8
        assert result_dict['total_sites_failed'] == 2
        assert result_dict['failed_items'] == [5, 9]


class TestSearchDate:
    """Test SearchDate class"""
    
    def test_search_date_initialization(self):
        """Test SearchDate initialization"""
        jst = pytz.timezone('Asia/Tokyo')
        test_date = datetime(2024, 1, 15, 10, 30, tzinfo=jst)
        search_date = lambda_function.SearchDate(test_date)
        
        assert search_date.date == test_date
    
    @patch('lambda_function.datetime')
    def test_search_date_now(self, mock_datetime_class):
        """Test SearchDate.now() method with JST timezone
        
        Note: Since lambda_function uses 'from datetime import datetime',
        we need to patch the datetime reference in lambda_function module.
        """
        jst = pytz.timezone('Asia/Tokyo')
        expected_now = datetime(2024, 1, 15, 10, 30, tzinfo=jst)
        
        # Configure the mock datetime class
        mock_datetime_class.now.return_value = expected_now
        
        search_date = lambda_function.SearchDate.now()
        
        # Verify datetime.now was called with jst timezone
        mock_datetime_class.now.assert_called_once_with(jst)
        
        # Verify the returned SearchDate contains the expected datetime
        assert search_date.date == expected_now
    
    def test_original_format(self):
        """Test original_format() returns YYYY-MM-DD"""
        jst = pytz.timezone('Asia/Tokyo')
        test_date = datetime(2024, 1, 15, 10, 30, tzinfo=jst)
        search_date = lambda_function.SearchDate(test_date)
        
        result = search_date.original_format()
        
        assert result == '2024-01-15'
    
    def test_year_month_format(self):
        """Test year_month_format() returns YYYYMM"""
        jst = pytz.timezone('Asia/Tokyo')
        test_date = datetime(2024, 1, 15, 10, 30, tzinfo=jst)
        search_date = lambda_function.SearchDate(test_date)
        
        result = search_date.year_month_format()
        
        assert result == '202401'
    
    def test_plus_months(self):
        """Test plus_months() adds months correctly"""
        jst = pytz.timezone('Asia/Tokyo')
        test_date = datetime(2024, 1, 15, 10, 30, tzinfo=jst)
        search_date = lambda_function.SearchDate(test_date)
        
        next_month = search_date.plus_months(1)
        
        assert next_month.original_format() == '2024-02-15'
        assert next_month.year_month_format() == '202402'
    
    def test_plus_months_year_boundary(self):
        """Test plus_months() across year boundary"""
        jst = pytz.timezone('Asia/Tokyo')
        test_date = datetime(2024, 12, 15, tzinfo=jst)
        search_date = lambda_function.SearchDate(test_date)
        
        next_month = search_date.plus_months(1)
        
        assert next_month.original_format() == '2025-01-15'
        assert next_month.year_month_format() == '202501'
    
    def test_plus_months_multiple(self):
        """Test plus_months() with multiple months"""
        jst = pytz.timezone('Asia/Tokyo')
        test_date = datetime(2024, 1, 15, tzinfo=jst)
        search_date = lambda_function.SearchDate(test_date)
        
        future_date = search_date.plus_months(6)
        
        assert future_date.original_format() == '2024-07-15'
        assert future_date.year_month_format() == '202407'


class TestGetAllSites:
    """Test site retrieval"""
    
    def test_get_all_sites_success(self):
        """Test successful site retrieval"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_cursor.fetchall.return_value = [
            {'site_id': 1},
            {'site_id': 2},
            {'site_id': 3}
        ]
        
        result = lambda_function.get_all_sites(mock_conn)
        
        assert len(result) == 3
        assert result == [1, 2, 3]
        mock_cursor.execute.assert_called_once()
    
    def test_get_all_sites_large_dataset(self):
        """Test with large number of sites"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Simulate 1,000 sites
        large_dataset = [{'site_id': i} for i in range(1, 1001)]
        mock_cursor.fetchall.return_value = large_dataset
        
        result = lambda_function.get_all_sites(mock_conn)
        
        assert len(result) == 1000
        assert result[0] == 1
        assert result[-1] == 1000
    
    def test_get_all_sites_empty_result(self):
        """Test when no sites exist"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_cursor.fetchall.return_value = []
        
        result = lambda_function.get_all_sites(mock_conn)
        
        assert result == []
    
    def test_get_all_sites_error(self):
        """Test error handling in site retrieval"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Query failed")
        
        with pytest.raises(Exception, match="Query failed"):
            lambda_function.get_all_sites(mock_conn)


class TestFindByApplyOn:
    """Test find_by_apply_on function"""
    
    def test_find_by_apply_on_success(self):
        """Test successful record retrieval"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_cursor.fetchone.return_value = {
            'ID': 1,
            'LIST_SITES': json.dumps([1, 2, 3])
        }
        
        result = lambda_function.find_by_apply_on(mock_conn, '2024-01-15')
        
        assert result['ID'] == 1
        assert result['LIST_SITES'] == json.dumps([1, 2, 3])
        # Verify execute was called with the date parameter
        assert mock_cursor.execute.called
        call_args = mock_cursor.execute.call_args
        assert call_args[0][1] == ('2024-01-15',)
    
    def test_find_by_apply_on_not_found(self):
        """Test when no record found"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_cursor.fetchone.return_value = None
        
        result = lambda_function.find_by_apply_on(mock_conn, '2024-01-15')
        
        assert result is None
    
    def test_find_by_apply_on_error(self):
        """Test error handling"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Query failed")
        
        with pytest.raises(Exception, match="Query failed"):
            lambda_function.find_by_apply_on(mock_conn, '2024-01-15')


class TestCreateMonthlyTable:
    """Test create_monthly_table function"""
    
    def test_create_monthly_table_success(self):
        """Test successful table creation with complete SQL verification"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        target_date = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        lambda_function.create_monthly_table(mock_conn, '12345', 'referrer', target_date)
        
        # Verify SQL was executed exactly once
        mock_cursor.execute.assert_called_once()
        
        # Get the actual SQL that was executed
        actual_sql = mock_cursor.execute.call_args[0][0]
        
        # Verify the exact SQL structure
        expected_sql = (
            "CREATE TABLE IF NOT EXISTS `12345`.`202402_referrer` "
            "LIKE `monthly_heatmap_table_template`.`template_referrer`;"
        )
        assert actual_sql == expected_sql
        
        # Additional assertions to verify key components
        assert 'CREATE TABLE IF NOT EXISTS' in actual_sql
        assert '`12345`.`202402_referrer`' in actual_sql
        assert 'LIKE `monthly_heatmap_table_template`.`template_referrer`' in actual_sql
    
    def test_create_monthly_table_different_suffix(self):
        """Test table creation with different table suffixes"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        target_date = lambda_function.SearchDate(datetime(2024, 3, 15, tzinfo=jst))
        
        # Test with 'click' suffix
        lambda_function.create_monthly_table(mock_conn, '67890', 'click', target_date)
        
        actual_sql = mock_cursor.execute.call_args[0][0]
        expected_sql = (
            "CREATE TABLE IF NOT EXISTS `67890`.`202403_click` "
            "LIKE `monthly_heatmap_table_template`.`template_click`;"
        )
        assert actual_sql == expected_sql
    
    def test_create_monthly_table_year_boundary(self):
        """Test table creation across year boundary"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        # December 2024
        target_date = lambda_function.SearchDate(datetime(2024, 12, 31, tzinfo=jst))
        
        lambda_function.create_monthly_table(mock_conn, '999', 'scroll', target_date)
        
        actual_sql = mock_cursor.execute.call_args[0][0]
        
        # Should be December 2024 (202412)
        assert '`202412_scroll`' in actual_sql
        assert '`999`.`202412_scroll`' in actual_sql
    
    def test_create_monthly_table_backtick_escaping(self):
        """Test that database and table names are properly wrapped in backticks"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        target_date = lambda_function.SearchDate(datetime(2024, 5, 1, tzinfo=jst))
        
        lambda_function.create_monthly_table(mock_conn, 'site_db_123', 'read', target_date)
        
        actual_sql = mock_cursor.execute.call_args[0][0]
        
        # Verify backticks are used correctly
        assert '`site_db_123`.`202405_read`' in actual_sql
        assert '`monthly_heatmap_table_template`.`template_read`' in actual_sql
    
    def test_create_monthly_table_error(self):
        """Test error handling when table creation fails"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Simulate a database error (e.g., table already exists with different structure, or permission denied)
        import pymysql
        mock_cursor.execute.side_effect = pymysql.err.OperationalError(
            1050, "Table already exists"
        )
        
        jst = pytz.timezone('Asia/Tokyo')
        target_date = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        # Should raise the exception
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.create_monthly_table(mock_conn, '12345', 'referrer', target_date)
    
    def test_create_monthly_table_generic_error(self):
        """Test error handling for generic database errors"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        mock_cursor.execute.side_effect = Exception("Database connection lost")
        
        jst = pytz.timezone('Asia/Tokyo')
        target_date = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        with pytest.raises(Exception, match="Database connection lost"):
            lambda_function.create_monthly_table(mock_conn, '12345', 'referrer', target_date)


class TestCreateTablesForSites:
    """Test create_tables_for_sites function"""
    
    def test_create_tables_for_sites_success(self):
        """Test successful table creation for multiple sites"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        site_list = [1, 2, 3]
        list_hm_site = [1, 2, 3, 4, 5]
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, site_list, list_hm_site, next_month
        )
        
        assert result.total_sites == 3
        assert result.total_sites_success == 3
        assert result.total_sites_failed == 0
        assert len(result.failed_items) == 0
        
        # 3 sites * 4 tables = 12 table creations
        assert mock_cursor.execute.call_count == 12
    
    def test_create_tables_for_sites_with_filtering(self):
        """Test that only sites in hm_site_set are processed"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        # Site 99 is not in hm_site list
        site_list = [1, 2, 99]
        list_hm_site = [1, 2, 3, 4, 5]
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, site_list, list_hm_site, next_month
        )
        
        assert result.total_sites == 3
        # Current implementation treats all requested sites as "success"
        # because no DB errors occurred, even though one site was filtered out.
        assert result.total_sites_success == 3
        assert result.total_sites_failed == 0
        # Only 2 sites should be processed at the DB level (1 and 2)
        # 2 sites * 4 tables = 8 table creations
        assert mock_cursor.execute.call_count == 8
    
    def test_create_tables_for_sites_empty_list(self):
        """Test with empty site list"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, [], [1, 2, 3], next_month
        )
        
        assert result.total_sites == 0
        assert result.total_sites_success == 0
        assert result.total_sites_failed == 0
    
    def test_create_tables_for_sites_with_error(self):
        """Test error handling during table creation"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # First site succeeds (4 tables), second fails on first table
        mock_cursor.execute.side_effect = [
            None, None, None, None,  # Site 1 success (4 tables)
            Exception("Table creation failed")  # Site 2 fails on first table
        ]
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        site_list = [1, 2]
        list_hm_site = [1, 2, 3]
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, site_list, list_hm_site, next_month
        )
        
        # Verify site 1 was counted as successful
        assert result.total_sites == 2
        assert result.total_sites_success == 1
        assert result.total_sites_failed == 1
        assert 2 in result.failed_items
        assert 1 not in result.failed_items
        
        # Verify execute was called 5 times (4 for site 1, 1 failed attempt for site 2)
        assert mock_cursor.execute.call_count == 5
    
    def test_create_tables_for_sites_error_on_second_table(self):
        """Test that partial table creation for a site results in site being marked as failed"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Site fails on the 2nd table (after 'referrer' succeeds, 'click' fails)
        mock_cursor.execute.side_effect = [
            None,  # Site 1: referrer table created
            Exception("Table creation failed on click table")  # Site 1: click table fails
        ]
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        site_list = [1]
        list_hm_site = [1, 2, 3]
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, site_list, list_hm_site, next_month
        )
        
        # Even though 1 table was created successfully, the entire site should be marked as failed
        assert result.total_sites == 1
        assert result.total_sites_success == 0
        assert result.total_sites_failed == 1
        assert 1 in result.failed_items
        
        # Only 2 execute calls: one success, one failure
        assert mock_cursor.execute.call_count == 2
    
    def test_create_tables_for_sites_multiple_failures(self):
        """Test multiple sites with different failure scenarios"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        # Site 1: success (4 tables)
        # Site 2: fails on 3rd table
        # Site 3: success (4 tables)
        # Site 4: fails on 1st table
        mock_cursor.execute.side_effect = [
            None, None, None, None,  # Site 1: all 4 tables succeed
            None, None, Exception("Failed on scroll"),  # Site 2: 2 succeed, 1 fails
            None, None, None, None,  # Site 3: all 4 tables succeed
            Exception("Failed immediately")  # Site 4: fails on first table
        ]
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        site_list = [1, 2, 3, 4]
        list_hm_site = [1, 2, 3, 4, 5]
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, site_list, list_hm_site, next_month
        )
        
        assert result.total_sites == 4
        assert result.total_sites_success == 2  # Sites 1 and 3
        assert result.total_sites_failed == 2  # Sites 2 and 4
        assert result.failed_items == [2, 4]
        assert 1 not in result.failed_items
        assert 3 not in result.failed_items


class TestUpdateLog:
    """Test update_log function"""
    
    def test_update_log_success_all(self):
        """Test update log with all successful"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        result = lambda_function.ResultCreatedTable()
        result.total_sites = 5
        result.total_sites_success = 5
        result.total_sites_failed = 0
        
        lambda_function.update_log(mock_conn, result, 123)
        
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        log_message = call_args[1][0]
        assert 'Success all' in log_message
        assert call_args[1][1] == 123
    
    def test_update_log_with_errors(self):
        """Test update log with some failures"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        result = lambda_function.ResultCreatedTable()
        result.total_sites = 5
        result.total_sites_success = 3
        result.total_sites_failed = 2
        result.failed_items = [7, 9]
        
        lambda_function.update_log(mock_conn, result, 456)
        
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0]
        log_message = call_args[1][0]
        assert 'Errors:' in log_message
        assert '[7, 9]' in log_message
        assert call_args[1][1] == 456
    
    def test_update_log_error(self):
        """Test error handling in update_log"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("Update failed")
        
        result = lambda_function.ResultCreatedTable()
        
        with pytest.raises(Exception, match="Update failed"):
            lambda_function.update_log(mock_conn, result, 1)
