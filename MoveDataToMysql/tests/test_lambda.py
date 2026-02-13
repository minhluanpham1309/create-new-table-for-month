import pytest
import json
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import lambda_function


@pytest.fixture
def mock_secret():
    """Mock RDS secret from Secrets Manager"""
    return {
        'host': 'test-db.amazonaws.com',
        'port': 3306,
        'username': 'testuser',
        'password': 'testpass',
        'dbname': 'testdb'
    }


@pytest.fixture
def mock_event():
    """Mock Lambda event"""
    return {
        'redis_key_pattern': 'test:*',
        'operation': 'transfer'
    }


@pytest.fixture
def mock_context():
    """Mock Lambda context"""
    context = Mock()
    context.function_name = 'move-data-to-mysql'
    context.memory_limit_in_mb = 512
    context.invoked_function_arn = 'arn:aws:lambda:ap-northeast-1:123456789012:function:move-data-to-mysql'
    return context


class TestLambdaFunction:
    
    @patch.dict(os.environ, {
        'RDS_SECRET_NAME': 'rds/db-test-private',
        'REDIS_HOST': 'localhost',
        'REDIS_PORT': '6379',
        'AWS_REGION': 'ap-northeast-1'
    })
    def test_get_region(self):
        """Test get_region function"""
        region = lambda_function.get_region()
        assert region == 'ap-northeast-1'
    
    @patch('boto3.session.Session')
    def test_get_secret_success(self, mock_session, mock_secret):
        """Test successful secret retrieval"""
        mock_client = Mock()
        mock_client.get_secret_value.return_value = {
            'SecretString': json.dumps(mock_secret)
        }
        mock_session.return_value.client.return_value = mock_client
        
        result = lambda_function.get_secret('ap-northeast-1')
        
        assert result == mock_secret
        mock_client.get_secret_value.assert_called_once()
    
    @patch('pymysql.connect')
    @patch('ssl.create_default_context')
    def test_get_mysql_connection_success(self, mock_ssl_context, mock_connect, mock_secret):
        """Test successful MySQL connection"""
        mock_connection = Mock()
        mock_connect.return_value = mock_connection
        
        result = lambda_function.get_mysql_connection(mock_secret)
        
        assert result == mock_connection
        mock_connect.assert_called_once()
    
    @patch('redis.Redis')
    @patch.dict(os.environ, {
        'REDIS_HOST': 'valkey.example.com',
        'REDIS_PORT': '6379',
        'REDIS_DB': '0'
    })
    def test_get_redis_connection_success(self, mock_redis):
        """Test successful Redis connection"""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.return_value = True
        mock_redis.return_value = mock_redis_instance
        
        result = lambda_function.get_redis_connection()
        
        assert result == mock_redis_instance
        mock_redis_instance.ping.assert_called_once()
    
    @patch('redis.Redis')
    @patch.dict(os.environ, {
        'REDIS_HOST': 'valkey.example.com',
        'REDIS_PORT': '6379'
    })
    def test_get_redis_connection_failure(self, mock_redis):
        """Test Redis connection failure"""
        mock_redis_instance = Mock()
        mock_redis_instance.ping.side_effect = Exception("Connection failed")
        mock_redis.return_value = mock_redis_instance
        
        with pytest.raises(Exception) as exc_info:
            lambda_function.get_redis_connection()
        
        assert "Connection failed" in str(exc_info.value)
    
    @patch('lambda_function.process_data_transfer')
    @patch('lambda_function.get_redis_connection')
    @patch('lambda_function.get_mysql_connection')
    @patch('lambda_function.get_secret')
    @patch('lambda_function.get_region')
    def test_lambda_handler_success(
        self,
        mock_get_region,
        mock_get_secret,
        mock_get_mysql,
        mock_get_redis,
        mock_process,
        mock_event,
        mock_context,
        mock_secret
    ):
        """Test successful lambda handler execution"""
        # Setup mocks
        mock_get_region.return_value = 'ap-northeast-1'
        mock_get_secret.return_value = mock_secret
        
        mock_mysql_conn = Mock()
        mock_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_cursor
        mock_get_mysql.return_value = mock_mysql_conn
        
        mock_redis_conn = Mock()
        mock_get_redis.return_value = mock_redis_conn
        
        # Execute
        result = lambda_function.lambda_handler(mock_event, mock_context)
        
        # Verify
        assert result['statusCode'] == 200
        assert 'message' in json.loads(result['body'])
        mock_cursor.close.assert_called_once()
        mock_mysql_conn.close.assert_called_once()
        mock_redis_conn.close.assert_called_once()
    
    @patch('lambda_function.get_region')
    def test_lambda_handler_failure(self, mock_get_region, mock_event, mock_context):
        """Test lambda handler with error"""
        mock_get_region.side_effect = Exception("Test error")
        
        result = lambda_function.lambda_handler(mock_event, mock_context)
        
        assert result['statusCode'] == 500
        assert 'error' in json.loads(result['body'])
    
    def test_process_data_transfer(self):
        """Test data transfer process"""
        mock_mysql_conn = Mock()
        mock_cursor = Mock()
        mock_mysql_conn.cursor.return_value = mock_cursor
        
        mock_redis_conn = Mock()
        mock_redis_conn.keys.return_value = ['key1', 'key2', 'key3']
        mock_redis_conn.get.return_value = 'test_value'
        
        event = {'redis_key_pattern': 'test:*'}
        
        lambda_function.process_data_transfer(mock_mysql_conn, mock_redis_conn, event)
        
        mock_redis_conn.keys.assert_called_once_with('test:*')
        assert mock_cursor.execute.called
        mock_mysql_conn.commit.assert_called_once()
    
    def test_run_step_success(self):
        """Test run_step with successful execution"""
        def sample_func(x, y):
            return x + y
        
        result = lambda_function.run_step("test_step", sample_func, 2, 3)
        assert result == 5
    
    def test_run_step_failure(self):
        """Test run_step with exception"""
        def failing_func():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError) as exc_info:
            lambda_function.run_step("failing_step", failing_func)
        
        assert "Test error" in str(exc_info.value)
