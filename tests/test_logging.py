import json
import logging
import pytest
from unittest.mock import MagicMock, patch
from app.logging import setup_logging, RequestResponseLogger

def test_setup_logging():
    """Test logging setup"""
    # Test with default settings
    logger = setup_logging()
    assert logger.name == "openai-proxy"
    assert logger.level == logging.INFO
    
    # Test with custom log level
    with patch.dict('os.environ', {'LOG_LEVEL': 'DEBUG'}):
        logger = setup_logging()
        assert logger.level == logging.DEBUG

def test_request_logger_sanitization():
    """Test request logger sanitization"""
    # Create mock logger
    mock_logger = MagicMock()
    
    # Create request logger
    request_logger = RequestResponseLogger(mock_logger)
    
    # Test sanitization of API keys
    body = {
        "api_key": "sk-1234567890abcdef",
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    sanitized_body = request_logger._sanitize_body(body)
    
    # API key should be redacted
    assert sanitized_body["api_key"] == "[REDACTED]"
    # Other fields should be preserved
    assert sanitized_body["model"] == "gpt-3.5-turbo"
    # Message content is redacted by default for privacy
    assert sanitized_body["messages"][0]["role"] == "user"
    assert sanitized_body["messages"][0]["content"] == "[CONTENT REDACTED]"

def test_request_logger_log_request():
    """Test request logger log_request method"""
    # Create mock logger
    mock_logger = MagicMock()
    
    # Create request logger
    request_logger = RequestResponseLogger(mock_logger)
    
    # Test log_request
    request_id = "test-123"
    method = "POST"
    path = "chat/completions"
    headers = {"Authorization": "Bearer sk-1234567890", "Content-Type": "application/json"}
    body = {"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello"}]}
    
    request_logger.log_request(request_id, method, path, headers, body)
    
    # Verify logger was called
    mock_logger.info.assert_called_once()
    
    # Verify log message contains expected fields
    log_message = mock_logger.info.call_args[0][0]
    assert "API Request" in log_message
    assert request_id in log_message
    assert method in log_message
    assert path in log_message
    
    # Verify authorization header was redacted but the key is kept
    assert "Bearer sk-1234567890" not in log_message
    assert "Authorization" in log_message
    assert "[REDACTED]" in log_message

def test_request_logger_log_response():
    """Test request logger log_response method"""
    # Create mock logger
    mock_logger = MagicMock()
    
    # Create request logger
    request_logger = RequestResponseLogger(mock_logger)
    
    # Test log_response
    request_id = "test-123"
    status_code = 200
    headers = {"Content-Type": "application/json"}
    body = {"id": "chatcmpl-123", "choices": [{"message": {"content": "Hello there!"}}]}
    
    request_logger.log_response(request_id, status_code, headers, body)
    
    # Verify logger was called
    mock_logger.info.assert_called_once()
    
    # Verify log message contains expected fields
    log_message = mock_logger.info.call_args[0][0]
    assert "API Response" in log_message
    assert request_id in log_message
    assert str(status_code) in log_message
    assert "Content-Type" in log_message
    assert "Hello there!" in log_message

def test_request_logger_log_error():
    """Test request logger log_error method"""
    # Create mock logger
    mock_logger = MagicMock()
    
    # Create request logger
    request_logger = RequestResponseLogger(mock_logger)
    
    # Test log_error
    request_id = "test-123"
    error_message = "Test error message"
    error_type = "test_error"
    
    request_logger.log_error(request_id, error_message, error_type)
    
    # Verify logger was called
    mock_logger.error.assert_called_once()
    
    # Verify log message contains expected fields
    log_message = mock_logger.error.call_args[0][0]
    assert "API Error" in log_message
    assert request_id in log_message
    assert error_message in log_message
    assert error_type in log_message 