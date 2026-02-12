import pytest
import sys
import os
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
import pytz

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import lambda_function


@pytest.fixture
def mock_connection():
    """Mock database connection"""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    return mock_conn, mock_cursor


@pytest.fixture
def mock_secret():
    """Mock AWS Secrets Manager secret"""
    return {
        'host': 'test-db.amazonaws.com',
        'port': 3306,
        'username': 'test_user',
        'password': 'test_password',
        'dbname': 'HEAT_MAP'
    }


class TestGetListPackageLimit:
    """Test get_list_package_limit function"""
    
    def test_get_list_package_limit_success(self, mock_connection):
        """Test successful retrieval of package limits"""
        mock_conn, mock_cursor = mock_connection
        
        # Mock data
        expected_results = [
            {'package_code': 'STANDARD_30', 'time_delete_data': 30},
            {'package_code': 'PREMIUM_90', 'time_delete_data': 90}
        ]
        mock_cursor.fetchall.return_value = expected_results
        
        # Execute
        result = lambda_function.get_list_package_limit(mock_conn)
        
        # Verify
        assert result == expected_results
        assert len(result) == 2
        mock_cursor.execute.assert_called_once()
    
    def test_get_list_package_limit_empty(self, mock_connection):
        """Test when no package limits found"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.fetchall.return_value = []
        
        result = lambda_function.get_list_package_limit(mock_conn)
        
        assert result == []
        assert len(result) == 0
    
    def test_get_list_package_limit_error(self, mock_connection):
        """Test error handling in get_list_package_limit"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.execute.side_effect = Exception("Database query error")
        
        with pytest.raises(Exception):
            lambda_function.get_list_package_limit(mock_conn)


class TestGetListHeatmapSiteByPackageCode:
    """Test get_list_heatmap_site_by_package_code function"""
    
    def test_get_sites_by_package_success(self, mock_connection):
        """Test successful retrieval of sites by package code"""
        mock_conn, mock_cursor = mock_connection
        
        expected_results = [
            {'site_id': 12345, 'date_min': '2024-01-01 00:00:00'},
            {'site_id': 12346, 'date_min': '2024-01-15 00:00:00'}
        ]
        mock_cursor.fetchall.return_value = expected_results
        
        result = lambda_function.get_list_heatmap_site_by_package_code(mock_conn, 'STANDARD_30')
        
        assert result == expected_results
        assert len(result) == 2
        mock_cursor.execute.assert_called_once()
    
    def test_get_sites_by_package_empty(self, mock_connection):
        """Test when no sites found for package"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.fetchall.return_value = []
        
        result = lambda_function.get_list_heatmap_site_by_package_code(mock_conn, 'NONEXISTENT')
        
        assert result == []
    
    def test_get_sites_by_package_error(self, mock_connection):
        """Test error handling in get_list_heatmap_site_by_package_code"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.execute.side_effect = Exception("Database query error")
        
        with pytest.raises(Exception):
            lambda_function.get_list_heatmap_site_by_package_code(mock_conn, 'TEST')


class TestUpdateDateMin:
    """Test update_date_min function"""
    
    def test_update_date_min_success(self, mock_connection):
        """Test successful date_min update"""
        mock_conn, mock_cursor = mock_connection
        
        lambda_function.update_date_min(mock_conn, 12345, '2024-02-01 00:00:00')
        
        # Verify query was executed with correct parameters
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        assert 'UPDATE HEAT_MAP.HEATMAP_SITE' in call_args[0][0]
        assert call_args[0][1] == ('2024-02-01 00:00:00', 12345)
    
    def test_update_date_min_error(self, mock_connection):
        """Test update_date_min raises error on failure"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.execute.side_effect = Exception("Database error")
        
        with pytest.raises(Exception):
            lambda_function.update_date_min(mock_conn, 12345, '2024-02-01 00:00:00')


class TestLambdaHandler:
    """Test lambda_handler function"""
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.auto_delete_old_data_heatmap')
    def test_lambda_handler_success(self, mock_auto_delete, mock_db, mock_secret, mock_region):
        """Test successful lambda execution"""
        # Setup mocks
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        
        # Execute
        result = lambda_function.lambda_handler()
        
        # Verify
        assert result['statusCode'] == 200
        assert 'successfully' in result['body']
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.auto_delete_old_data_heatmap')
    def test_lambda_handler_error_rollback(self, mock_auto_delete, mock_db, 
                                           mock_secret, mock_region):
        """Test lambda handler rolls back on error"""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        
        # Simulate error
        mock_auto_delete.side_effect = Exception("Processing error")
        
        with pytest.raises(Exception):
            lambda_function.lambda_handler()
        
        # Verify rollback was called
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


class TestHelperFunctions:
    """Test helper functions"""
    
    def test_get_region(self):
        """Test get_region function"""
        with patch.dict(os.environ, {'AWS_REGION': 'us-east-1'}):
            region = lambda_function.get_region()
            assert region == 'us-east-1'
    
    def test_get_region_default(self):
        """Test get_region returns default"""
        with patch.dict(os.environ, {}, clear=True):
            region = lambda_function.get_region()
            assert region == 'ap-northeast-1'
    
    @patch('lambda_function.boto3.client')
    def test_get_secret(self, mock_boto_client):
        """Test get_secret function"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_client.get_secret_value.return_value = {
            'SecretString': '{"host": "test", "password": "secret"}'
        }
        
        result = lambda_function.get_secret('ap-northeast-1')
        
        assert result['host'] == 'test'
        assert result['password'] == 'secret'
    
    def test_run_step_success(self):
        """Test run_step executes function successfully"""
        def test_func(x, y):
            return x + y
        
        result = lambda_function.run_step("add", test_func, 2, 3)
        assert result == 5
    
    def test_run_step_error(self):
        """Test run_step propagates errors"""
        def error_func():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            lambda_function.run_step("error", error_func)


class TestGetSSLContext:
    """Test get_ssl_context function"""
    
    @patch('lambda_function.os.path.exists')
    @patch('lambda_function.ssl.SSLContext')
    def test_get_ssl_context_success(self, mock_ssl_context, mock_exists):
        """Test successful SSL context creation"""
        mock_exists.return_value = True
        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        
        result = lambda_function.get_ssl_context('ap-northeast-1')
        
        assert result == mock_context
        mock_context.load_verify_locations.assert_called_once()
    
    @patch('lambda_function.os.path.exists')
    @patch('lambda_function.ssl.SSLContext')
    def test_get_ssl_context_fallback_to_global(self, mock_ssl_context, mock_exists):
        """Test fallback to global bundle"""
        # First call (region-specific) returns False, second (global) returns True
        mock_exists.side_effect = [False, True]
        mock_context = MagicMock()
        mock_ssl_context.return_value = mock_context
        
        result = lambda_function.get_ssl_context('us-east-1')
        
        assert result == mock_context
        assert mock_exists.call_count == 2
    
    @patch('lambda_function.os.path.exists')
    def test_get_ssl_context_no_bundle_found(self, mock_exists):
        """Test error when no CA bundle found"""
        mock_exists.return_value = False
        
        with pytest.raises(FileNotFoundError):
            lambda_function.get_ssl_context('ap-northeast-1')
    
    @patch('lambda_function.os.path.exists')
    @patch('lambda_function.ssl.SSLContext')
    def test_get_ssl_context_load_error(self, mock_ssl_context, mock_exists):
        """Test error during SSL context creation"""
        mock_exists.return_value = True
        mock_ssl_context.side_effect = Exception("SSL error")
        
        with pytest.raises(Exception):
            lambda_function.get_ssl_context('ap-northeast-1')


class TestGetDBConnection:
    """Test get_db_connection function"""
    
    @patch('lambda_function.get_ssl_context')
    @patch('lambda_function.pymysql.connect')
    @patch.dict(os.environ, {
        'DB_HOST': 'test-host',
        'DB_PORT': '3306',
        'DB_USER': 'test-user',
        'DB_PASSWORD': 'test-pass',
        'DB_NAME': 'HEAT_MAP'
    })
    def test_get_db_connection_success(self, mock_connect, mock_ssl):
        """Test successful database connection"""
        mock_ssl.return_value = MagicMock()
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        
        result = lambda_function.get_db_connection({'host': 'test'})
        
        assert result == mock_conn
        mock_connect.assert_called_once()
    
    @patch('lambda_function.get_ssl_context')
    @patch('lambda_function.pymysql.connect')
    @patch.dict(os.environ, {
        'DB_HOST': 'test-host',
        'DB_USER': 'test-user',
        'DB_PASSWORD': 'test-pass'
    })
    def test_get_db_connection_operational_error_2003(self, mock_connect, mock_ssl):
        """Test connection error - cannot connect to server"""
        import pymysql
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(2003, "Connection refused")
        
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection({'host': 'test'})
    
    @patch('lambda_function.get_ssl_context')
    @patch('lambda_function.pymysql.connect')
    @patch.dict(os.environ, {
        'DB_HOST': 'test-host',
        'DB_USER': 'test-user',
        'DB_PASSWORD': 'wrong-pass'
    })
    def test_get_db_connection_operational_error_1045(self, mock_connect, mock_ssl):
        """Test connection error - access denied"""
        import pymysql
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(1045, "Access denied")
        
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection({'host': 'test'})
    
    @patch('lambda_function.get_ssl_context')
    @patch('lambda_function.pymysql.connect')
    @patch.dict(os.environ, {
        'DB_HOST': 'test-host',
        'DB_USER': 'test-user',
        'DB_PASSWORD': 'test-pass'
    })
    def test_get_db_connection_operational_error_other(self, mock_connect, mock_ssl):
        """Test other operational errors"""
        import pymysql
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(9999, "Other error")
        
        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection({'host': 'test'})
    
    @patch('lambda_function.get_ssl_context')
    @patch('lambda_function.pymysql.connect')
    @patch.dict(os.environ, {
        'DB_HOST': 'test-host',
        'DB_USER': 'test-user',
        'DB_PASSWORD': 'test-pass'
    })
    def test_get_db_connection_generic_error(self, mock_connect, mock_ssl):
        """Test generic connection error"""
        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = Exception("Generic error")
        
        with pytest.raises(Exception):
            lambda_function.get_db_connection({'host': 'test'})


class TestCalculateRetentionDates:
    """Test calculate_retention_dates function"""
    
    def test_30_days_retention(self):
        """Test calculation for 30-day retention policy"""
        jst = pytz.timezone('Asia/Tokyo')
        base_date = datetime(2024, 3, 15, 10, 30, 0, tzinfo=jst)
        
        result = lambda_function.calculate_retention_dates(30, base_date)
        
        assert result is not None
        assert 'threshold' in result
        assert 'new_date_min' in result
        
        # 30 days: threshold = 2 months ago
        assert result['threshold'].year == 2024
        assert result['threshold'].month == 1
        assert result['threshold'].day == 15
        
        # new_date_min = 1 month ago, day=1
        assert result['new_date_min'].year == 2024
        assert result['new_date_min'].month == 2
        assert result['new_date_min'].day == 1
    
    def test_90_days_retention(self):
        """Test calculation for 90-day retention policy"""
        jst = pytz.timezone('Asia/Tokyo')
        base_date = datetime(2024, 5, 20, 14, 0, 0, tzinfo=jst)
        
        result = lambda_function.calculate_retention_dates(90, base_date)
        
        assert result is not None
        assert 'threshold' in result
        assert 'new_date_min' in result
        
        # 90 days: threshold = 4 months ago
        assert result['threshold'].year == 2024
        assert result['threshold'].month == 1
        assert result['threshold'].day == 20
        
        # new_date_min = 3 months ago, day=1
        assert result['new_date_min'].year == 2024
        assert result['new_date_min'].month == 2
        assert result['new_date_min'].day == 1
    
    def test_unsupported_retention_days(self):
        """Test that unsupported retention days return None"""
        jst = pytz.timezone('Asia/Tokyo')
        base_date = datetime(2024, 3, 15, tzinfo=jst)
        
        # Test various unsupported values
        for retention_days in [0, 7, 15, 60, 120, 365, -30]:
            result = lambda_function.calculate_retention_dates(retention_days, base_date)
            assert result is None, f"Expected None for retention_days={retention_days}"
    
    def test_default_base_date(self):
        """Test that function uses current_date when base_date is None"""
        result = lambda_function.calculate_retention_dates(30)
        
        assert result is not None
        assert 'threshold' in result
        assert 'new_date_min' in result
    
    def test_edge_case_year_boundary(self):
        """Test calculation crossing year boundary"""
        jst = pytz.timezone('Asia/Tokyo')
        base_date = datetime(2024, 1, 15, tzinfo=jst)
        
        result = lambda_function.calculate_retention_dates(90, base_date)
        
        # 4 months ago from Jan 2024 = Sep 2023
        assert result['threshold'].year == 2023
        assert result['threshold'].month == 9
        
        # 3 months ago from Jan 2024 = Oct 2023
        assert result['new_date_min'].year == 2023
        assert result['new_date_min'].month == 10
        assert result['new_date_min'].day == 1
    
    def test_new_date_min_always_day_1(self):
        """Test that new_date_min is always set to day 1"""
        jst = pytz.timezone('Asia/Tokyo')
        
        # Test with various days of month
        for day in [1, 15, 28, 31]:
            base_date = datetime(2024, 3, min(day, 28), tzinfo=jst)
            
            result_30 = lambda_function.calculate_retention_dates(30, base_date)
            result_90 = lambda_function.calculate_retention_dates(90, base_date)
            
            assert result_30['new_date_min'].day == 1
            assert result_90['new_date_min'].day == 1


class TestAutoDeleteOldDataHeatmap:
    """Test auto_delete_old_data_heatmap function with new logic"""
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.get_list_heatmap_site_by_package_code')
    @patch('lambda_function.update_date_min')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_with_30_day_retention(self, mock_calc_dates, mock_update, 
                                                mock_get_sites, mock_get_packages):
        """Test auto delete with 30-day retention package"""
        jst = pytz.timezone('Asia/Tokyo')
        
        # Mock package data
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'STANDARD_30', 'TIME_DELETE_DATA': 30}
        ]
        
        # Mock date calculation
        mock_calc_dates.return_value = {
            'threshold': datetime(2024, 1, 15, tzinfo=jst),
            'new_date_min': datetime(2024, 2, 1, tzinfo=jst)
        }
        
        # Mock site data with old date
        mock_get_sites.return_value = [
            {'SITE_ID': 12345, 'DATE_MIN': datetime(2024, 1, 1, tzinfo=jst)}
        ]
        
        mock_conn = MagicMock()
        
        # Execute
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Verify
        mock_calc_dates.assert_called_once_with(30)
        mock_get_sites.assert_called_once_with(mock_conn, 'STANDARD_30')
        mock_update.assert_called_once()
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_skips_unsupported_retention(self, mock_calc_dates, mock_get_packages):
        """Test that unsupported retention days are skipped"""
        # Mock package with unsupported retention
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'CUSTOM_60', 'TIME_DELETE_DATA': 60}
        ]
        
        # Mock returns None for unsupported retention
        mock_calc_dates.return_value = None
        
        mock_conn = MagicMock()
        
        # Execute - should not raise error
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Verify calculate was called but no further processing
        mock_calc_dates.assert_called_once_with(60)
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.get_list_heatmap_site_by_package_code')
    @patch('lambda_function.update_date_min')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_skips_recent_sites(self, mock_calc_dates, mock_update,
                                            mock_get_sites, mock_get_packages):
        """Test that sites with recent data are not updated"""
        jst = pytz.timezone('Asia/Tokyo')
        
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'STANDARD_30', 'TIME_DELETE_DATA': 30}
        ]
        
        # Threshold is 2 months ago
        mock_calc_dates.return_value = {
            'threshold': datetime(2024, 1, 15, tzinfo=jst),
            'new_date_min': datetime(2024, 2, 1, tzinfo=jst)
        }
        
        # Site date_min is newer than threshold
        mock_get_sites.return_value = [
            {'SITE_ID': 12345, 'DATE_MIN': datetime(2024, 2, 1, tzinfo=jst)}
        ]
        
        mock_conn = MagicMock()
        
        # Execute
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Verify update was NOT called
        mock_update.assert_not_called()
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.get_list_heatmap_site_by_package_code')
    @patch('lambda_function.update_date_min')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_handles_string_date_min(self, mock_calc_dates, mock_update,
                                                  mock_get_sites, mock_get_packages):
        """Test handling of DATE_MIN as string"""
        jst = pytz.timezone('Asia/Tokyo')
        
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'STANDARD_30', 'TIME_DELETE_DATA': 30}
        ]
        
        mock_calc_dates.return_value = {
            'threshold': datetime(2024, 1, 15, tzinfo=jst),
            'new_date_min': datetime(2024, 2, 1, tzinfo=jst)
        }
        
        # Site with DATE_MIN as string
        mock_get_sites.return_value = [
            {'SITE_ID': 12345, 'DATE_MIN': '2024-01-01 00:00:00'}
        ]
        
        mock_conn = MagicMock()
        
        # Execute - should not raise error
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Verify update was called
        mock_update.assert_called_once()
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.get_list_heatmap_site_by_package_code')
    @patch('lambda_function.update_date_min')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_handles_naive_datetime(self, mock_calc_dates, mock_update,
                                                 mock_get_sites, mock_get_packages):
        """Test handling of DATE_MIN as naive datetime (no timezone)"""
        jst = pytz.timezone('Asia/Tokyo')
        
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'STANDARD_30', 'TIME_DELETE_DATA': 30}
        ]
        
        mock_calc_dates.return_value = {
            'threshold': datetime(2024, 1, 15, tzinfo=jst),
            'new_date_min': datetime(2024, 2, 1, tzinfo=jst)
        }
        
        # Site with DATE_MIN as naive datetime
        mock_get_sites.return_value = [
            {'SITE_ID': 12345, 'DATE_MIN': datetime(2024, 1, 1)}
        ]
        
        mock_conn = MagicMock()
        
        # Execute - should not raise error
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Verify update was called
        mock_update.assert_called_once()
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.get_list_heatmap_site_by_package_code')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_handles_site_processing_error(self, mock_calc_dates,
                                                        mock_get_sites, mock_get_packages):
        """Test that site processing errors are caught and logged"""
        jst = pytz.timezone('Asia/Tokyo')
        
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'STANDARD_30', 'TIME_DELETE_DATA': 30}
        ]
        
        mock_calc_dates.return_value = {
            'threshold': datetime(2024, 1, 15, tzinfo=jst),
            'new_date_min': datetime(2024, 2, 1, tzinfo=jst)
        }
        
        # Site with invalid DATE_MIN that will cause error
        mock_get_sites.return_value = [
            {'SITE_ID': 12345, 'DATE_MIN': 'invalid-date-format'}
        ]
        
        mock_conn = MagicMock()
        
        # Execute - should not raise error, just log and continue
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Should complete without raising exception
        assert True
    
    @patch('lambda_function.get_list_package_limit')
    def test_auto_delete_handles_top_level_error(self, mock_get_packages):
        """Test that top-level errors are raised"""
        mock_get_packages.side_effect = Exception("Database connection failed")
        
        mock_conn = MagicMock()
        
        # Execute - should raise error
        with pytest.raises(Exception):
            lambda_function.auto_delete_old_data_heatmap(mock_conn)
    
    @patch('lambda_function.get_list_package_limit')
    @patch('lambda_function.get_list_heatmap_site_by_package_code')
    @patch('lambda_function.update_date_min')
    @patch('lambda_function.calculate_retention_dates')
    def test_auto_delete_with_multiple_packages(self, mock_calc_dates, mock_update,
                                                 mock_get_sites, mock_get_packages):
        """Test auto delete with multiple packages (30 and 90 day retention)"""
        jst = pytz.timezone('Asia/Tokyo')
        
        # Mock multiple packages
        mock_get_packages.return_value = [
            {'PACKAGE_CODE': 'STANDARD_30', 'TIME_DELETE_DATA': 30},
            {'PACKAGE_CODE': 'PREMIUM_90', 'TIME_DELETE_DATA': 90}
        ]
        
        # Mock date calculation for both
        mock_calc_dates.side_effect = [
            {
                'threshold': datetime(2024, 1, 15, tzinfo=jst),
                'new_date_min': datetime(2024, 2, 1, tzinfo=jst)
            },
            {
                'threshold': datetime(2023, 11, 15, tzinfo=jst),
                'new_date_min': datetime(2023, 12, 1, tzinfo=jst)
            }
        ]
        
        # Mock sites for both packages
        mock_get_sites.side_effect = [
            [{'SITE_ID': 12345, 'DATE_MIN': datetime(2024, 1, 1, tzinfo=jst)}],
            [{'SITE_ID': 67890, 'DATE_MIN': datetime(2023, 11, 1, tzinfo=jst)}]
        ]
        
        mock_conn = MagicMock()
        
        # Execute
        lambda_function.auto_delete_old_data_heatmap(mock_conn)
        
        # Verify both packages were processed
        assert mock_calc_dates.call_count == 2
        assert mock_get_sites.call_count == 2
        assert mock_update.call_count == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=lambda_function', '--cov-report=html'])
