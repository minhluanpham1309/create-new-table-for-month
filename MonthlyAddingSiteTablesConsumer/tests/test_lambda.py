"""
Unit tests for MonthlyAddingSiteTablesConsumer Lambda function

This test suite provides comprehensive coverage for the Lambda function
that creates monthly tables for sites based on scheduled site lists.

Test Categories:
- Lambda Handler: Main execution flow, error handling, empty data scenarios
- Database Operations: Site retrieval, schedule lookup, table creation, log updates
- Business Logic: Table creation logic, site filtering, result aggregation
- Date Handling: SearchDate class, date formatting, month calculations
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
        
        # Verify
        assert response['statusCode'] == 200
        assert 'Monthly tables created successfully' in response['body']
        assert mock_secret.called
        assert mock_db_conn.called
        assert mock_get_sites.called
        assert mock_find.called
        assert mock_create.called
        assert mock_update.called
        mock_conn.commit.assert_called_once()
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
        """Test Lambda when no record found for current date"""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test-host'}
        
        mock_conn = MagicMock()
        mock_db_conn.return_value = mock_conn
        
        jst = pytz.timezone('Asia/Tokyo')
        mock_date = lambda_function.SearchDate(datetime(2024, 1, 15, tzinfo=jst))
        mock_now.return_value = mock_date
        
        mock_get_sites.return_value = [1, 2, 3]
        mock_find.return_value = None  # No record found
        
        # Execute
        response = lambda_function.lambda_handler()
        
        # Verify
        assert response['statusCode'] == 200
        body = json.loads(response['body'])
        assert body['message'] == 'No record to process'
        assert body['result']['total_sites'] == 0
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.get_all_sites', side_effect=Exception("DB error"))
    def test_lambda_handler_error_rollback(
            self, mock_get_sites, mock_db_conn, mock_secret, mock_region
    ):
        """Test Lambda handles errors and rollbacks"""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        
        mock_conn = MagicMock()
        mock_db_conn.return_value = mock_conn
        
        # Execute and verify
        with pytest.raises(Exception, match="DB error"):
            lambda_function.lambda_handler()
        
        mock_conn.rollback.assert_called_once()
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
    def test_search_date_now(self, mock_datetime):
        """Test SearchDate.now() method"""
        jst = pytz.timezone('Asia/Tokyo')
        mock_now = datetime(2024, 1, 15, 10, 30, tzinfo=jst)
        mock_datetime.now.return_value = mock_now
        
        search_date = lambda_function.SearchDate.now()
        
        assert search_date.date == mock_now
    
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
        """Test successful table creation"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        
        jst = pytz.timezone('Asia/Tokyo')
        target_date = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        lambda_function.create_monthly_table(mock_conn, '12345', 'referrer', target_date)
        
        # Verify SQL was executed
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0][0]
        assert '202402_referrer' in call_args
        assert '12345' in call_args
        assert 'template_referrer' in call_args

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
        # Only 2 sites should be processed (1 and 2)
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
        
        # First site succeeds (4 tables), second fails
        mock_cursor.execute.side_effect = [
            None, None, None, None,  # Site 1 success (4 tables)
            Exception("Table creation failed")  # Site 2 fails
        ]
        
        jst = pytz.timezone('Asia/Tokyo')
        next_month = lambda_function.SearchDate(datetime(2024, 2, 1, tzinfo=jst))
        
        site_list = [1, 2]
        list_hm_site = [1, 2, 3]
        
        result = lambda_function.create_tables_for_sites(
            mock_conn, site_list, list_hm_site, next_month
        )
        
        assert result.total_sites == 2
        assert result.total_sites_success == 1
        assert result.total_sites_failed == 1
        assert 2 in result.failed_items


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
        assert 'Success all' in call_args[1]
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
