import json
import logging
import pytest
import re
from unittest.mock import MagicMock, patch
from app.logging import setup_logging, RequestResponseLogger, redact_api_key
import os

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
    
    # Mock the debug level environment variable
    with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
        request_logger.log_request(request_id, method, path, headers, body)
    
        # Verify info logger was called with the simplified message
        mock_logger.info.assert_called_once()
        info_message = mock_logger.info.call_args[0][0]
        assert "API Request" in info_message
        assert request_id in info_message
        assert method in info_message
        assert path in info_message
        
        # Verify debug logger was called with the detailed information
        mock_logger.debug.assert_called_once()
        debug_message = mock_logger.debug.call_args[0][0]
        assert "API Request details" in debug_message
        assert request_id in debug_message
        assert "Authorization" in debug_message  # Header should be in debug message

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
    
    # Mock the debug level environment variable
    with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}):
        request_logger.log_response(request_id, status_code, headers, body)
    
        # Verify info logger was called with the simplified message
        mock_logger.info.assert_called_once()
        info_message = mock_logger.info.call_args[0][0]
        assert "API Response" in info_message
        assert request_id in info_message
        assert str(status_code) in info_message
        
        # Verify debug logger was called with the detailed information
        mock_logger.debug.assert_called_once()
        debug_message = mock_logger.debug.call_args[0][0]
        assert "API Response details" in debug_message
        assert request_id in debug_message
        assert "Content-Type" in debug_message  # Header should be in debug message

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
    # The new format doesn't include error_type in the simplified message
    # so we don't assert for it anymore 