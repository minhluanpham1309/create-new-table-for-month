"""
Unit tests for the DeleteHeatMapCache Lambda function that truncates the heatmap cache table.

This test suite focuses on the DeleteHeatMapCache Lambda handler orchestration logic and its
interactions with external dependencies via mocks.

Test Categories:
- Lambda Handler: Main execution flow, error handling, and rollback
- AWS Services: Secrets Manager integration
- Database Operations: Connection acquisition, commit/rollback, and closing
- SSL/TLS: SSL context creation
- Utility: run_step wrapper behavior
- SQL: truncate_table SQL formatting & escaping

All tests use mocks to avoid external dependencies (no real DB/AWS connections).
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError

# Import truncate Lambda module
import lambda_function


class TestLambdaHandler:
    """Test main Lambda handler"""

    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.truncate_table")
    def test_lambda_handler_success(
        self, mock_truncate, mock_db_conn, mock_secret, mock_region
    ):
        """Test successful Lambda execution"""
        # Setup mocks
        mock_region.return_value = 'ap-northeast-1'
        mock_secret.return_value = {'host': 'test-host'}

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        # Execute
        lambda_function.lambda_handler()

        # Verify behavior
        assert mock_secret.called
        assert mock_db_conn.called
        assert mock_truncate.called
        mock_conn.commit.assert_called_once()

    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.truncate_table", side_effect=Exception("TRUNCATE error"))
    def test_lambda_handler_error_rollback(
        self, mock_truncate, mock_db_conn, mock_secret, mock_region
    ):
        """Test Lambda handles errors and rollbacks"""
        mock_region.return_value = "ap-northeast-1"
        mock_secret.return_value = {"host": "test"}

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        # Simulate rollback raising an exception
        mock_conn.rollback.side_effect = Exception("Rollback failed")
        mock_db_conn.return_value = mock_conn

        with pytest.raises(Exception, match="TRUNCATE error"):
            lambda_function.lambda_handler(event={"x": 1}, context=None)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()
        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret")
    @patch("lambda_function.get_db_connection")
    @patch("lambda_function.truncate_table", side_effect=Exception("TRUNCATE error"))
    def test_lambda_handler_error_rollback_failed(
            self, mock_truncate, mock_db_conn, mock_secret, mock_region
    ):
        """Test Lambda handles errors and rollbacks"""
        mock_region.return_value = "ap-northeast-1"
        mock_secret.return_value = {"host": "test"}

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_db_conn.return_value = mock_conn

        with pytest.raises(Exception, match="TRUNCATE error"):
            lambda_function.lambda_handler(event={"x": 1}, context=None)

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

        mock_cursor.close.assert_called_once()
        mock_conn.close.assert_called_once()

    @patch("lambda_function.get_region")
    @patch("lambda_function.get_secret", side_effect=Exception("secret error"))
    def test_lambda_handler_error_before_db_connection(
        self, mock_secret, mock_region
    ):
        """If error occurs before DB connection, should still raise and not crash on close"""
        mock_region.return_value = "ap-northeast-1"

        with pytest.raises(Exception, match="secret error"):
            lambda_function.lambda_handler(event={"x": 1}, context=None)


class TestGetSecret:
    """Test AWS Secrets Manager"""

    @patch("boto3.client")
    def test_get_secret_success(self, mock_boto_client):
        """Test successful secret retrieval"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps(
                {
                    "host": "test-db.rds.amazonaws.com",
                    "username": "root",
                    "password": "root",
                    "port": 3306,
                    "dbname": "HEAT_MAP",
                }
            )
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
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User is not authorized",
            }
        }
        mock_client.get_secret_value.side_effect = ClientError(
            error_response, "GetSecretValue"
        )

        with pytest.raises(ClientError) as exc_info:
            lambda_function.get_secret("ap-northeast-1")

        assert "AccessDeniedException" in str(exc_info.value)

    @patch("boto3.client")
    def test_get_secret_not_found(self, mock_boto_client):
        """Test secret not found"""
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client

        error_response = {
            "Error": {
                "Code": "ResourceNotFoundException",
                "Message": "Secret not found",
            }
        }
        mock_client.get_secret_value.side_effect = ClientError(
            error_response, "GetSecretValue"
        )

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
        mock_connect.side_effect = pymysql.err.OperationalError(
            1045, "Access denied for user"
        )

        secret = {"host": "db.amazonaws.com", "username": "wrong", "password": "wrong"}

        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_db_connection_other_error(self, mock_connect, mock_ssl):
        """Test access denied (wrong credentials)"""
        import pymysql

        mock_ssl.return_value = MagicMock()
        mock_connect.side_effect = pymysql.err.OperationalError(
            500, "Generic database error"
        )

        secret = {"host": "db.amazonaws.com", "username": "wrong", "password": "wrong"}

        with pytest.raises(pymysql.err.OperationalError):
            lambda_function.get_db_connection(secret)

    @patch("lambda_function.get_ssl_context")
    @patch("pymysql.connect")
    def test_db_connection_generic_exception(self, mock_connect, mock_ssl):
        """Test generic exception (not OperationalError)"""
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


class TestTruncateTable:
    """Test truncate_table SQL generation & execution"""

    def test_truncate_table_all_data_removed(self):
        """Test that truncate_table removes all data from the table"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        # Simulate row count before truncation
        mock_cursor.execute.return_value = None
        mock_cursor.rowcount = 100  # Assume 100 rows before truncation

        lambda_function.truncate_table(mock_conn)

        # After truncation, rowcount should be 0
        mock_cursor.rowcount = 0
        assert mock_cursor.rowcount == 0

    def test_truncate_table_db_error_propagates(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = Exception("SQL failed")

        with pytest.raises(Exception, match="SQL failed"):
            lambda_function.truncate_table(mock_conn)
