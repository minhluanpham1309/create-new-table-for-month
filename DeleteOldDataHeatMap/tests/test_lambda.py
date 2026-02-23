import pytest
import os
from unittest.mock import MagicMock, patch

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



class TestLambdaHandler:
    """Test lambda_handler function"""
    
    @patch('lambda_function.get_region')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_db_connection')
    @patch('lambda_function.auto_update_date_min_heatmap_site')
    def test_lambda_handler_success(self, mock_auto_update, mock_db, mock_secret, mock_region):
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
    @patch('lambda_function.auto_update_date_min_heatmap_site')
    def test_lambda_handler_error_rollback(self, mock_auto_update, mock_db, 
                                           mock_secret, mock_region):
        """Test lambda handler rolls back on error"""
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test'}
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        
        # Simulate error
        mock_auto_update.side_effect = Exception("Processing error")
        
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


class TestAutoUpdateDateMinHeatmapSite:
    """Test auto_update_date_min_heatmap_site function"""
    
    def test_update_date_min_success(self, mock_connection):
        """Test successful update of date_min"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.rowcount = 5
        
        # Execute
        lambda_function.auto_update_date_min_heatmap_site(mock_conn)
        
        # Verify SQL was executed
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args[0][0]
        
        # Verify it's an UPDATE query
        assert 'UPDATE HEAT_MAP.HEATMAP_SITE' in call_args
        assert 'LEFT JOIN HEAT_MAP.A_LIMIT_QUANTITY' in call_args
        assert 'DATE_SUB' in call_args
        assert 'TIME_DELETE_DATA' in call_args
        assert 'IS_DELETED = 0' in call_args
    
    def test_update_date_min_no_rows_affected(self, mock_connection):
        """Test when no rows need updating"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.rowcount = 0
        
        # Execute - should not raise error
        lambda_function.auto_update_date_min_heatmap_site(mock_conn)
        
        # Verify query was still executed
        mock_cursor.execute.assert_called_once()
    
    def test_update_date_min_database_error(self, mock_connection):
        """Test handling of database errors"""
        mock_conn, mock_cursor = mock_connection
        mock_cursor.execute.side_effect = Exception("Database error")
        
        # Execute - should raise error
        with pytest.raises(Exception):
            lambda_function.auto_update_date_min_heatmap_site(mock_conn)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--cov=lambda_function', '--cov-report=html'])
