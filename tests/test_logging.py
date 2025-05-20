import json
import logging
import pytest
import re
from unittest.mock import MagicMock, patch
from app.logging import setup_logging, RequestResponseLogger, redact_api_key

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

def test_api_key_redaction():
    """Test the API key redaction functionality"""
    # Test OpenAI API key pattern (sk-)
    openai_key = "sk-abcdefg12345ABCDEFG67890"
    redacted = redact_api_key(openai_key)
    assert redacted.startswith("sk-abcde")
    assert "12345ABCDEFG67890" not in redacted
    assert "..." in redacted
    
    # Test OpenAI project API key pattern (sk-proj-)
    openai_proj_key = "sk-proj-abcde12345"
    redacted = redact_api_key(openai_proj_key)
    assert redacted.startswith("sk-proj-")
    assert "12345" not in redacted
    assert "..." in redacted
    
    # Test Bearer token
    bearer_token = "Bearer sk-1234567890abcdefghijk"
    redacted = redact_api_key(bearer_token)
    assert redacted.startswith("Bearer sk-")
    assert "1234567890abcdefghijk" not in redacted
    assert "..." in redacted
    
    # Test API key in JSON
    json_with_key = '{"api_key": "sk-12345abcdef", "model": "gpt-4"}'
    redacted = redact_api_key(json_with_key)
    # Check for the redacted format - may contain "sk-12....." or similar
    assert 'api_key' in redacted
    assert 'sk-' in redacted
    assert 'abcdef' not in redacted  # Make sure the sensitive part is masked
    assert 'gpt-4' in redacted       # Non-sensitive data should remain
    
    # Test Anthropic API key pattern
    anthropic_key = "sk-ant-api03-00000-123456-abcdefghijk"
    redacted = redact_api_key(anthropic_key)
    assert redacted.startswith("sk-ant-")
    assert "abcdefghijk" not in redacted
    assert "..." in redacted
    
    # Test with no API key
    normal_text = "This is a normal text with no API key"
    redacted = redact_api_key(normal_text)
    assert redacted == normal_text
    
    # Test with null or non-string input
    assert redact_api_key(None) is None
    assert redact_api_key(123) == 123

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

def test_api_key_redaction_in_debug_logs():
    """Test that API keys are properly redacted in debug logs"""
    with patch('app.logging.redact_api_key') as mock_redact:
        # Setup mock to pass through the input with a known prefix to verify it was called
        mock_redact.side_effect = lambda x: f"REDACTED:{x}" if isinstance(x, str) else x
        
        # Create mock logger
        mock_logger = MagicMock()
        
        # Create request logger
        request_logger = RequestResponseLogger(mock_logger)
        
        # Create a request with a sensitive API key
        request_id = "test-debug-123"
        method = "POST"
        path = "chat/completions"
        headers = {"Authorization": "Bearer sk-1234567890abcdef", "Content-Type": "application/json"}
        body = {
            "api_key": "sk-secret-key-value",
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "Test with API key sk-embedded-in-content"}]
        }
        
        # Log the request
        request_logger.log_request(request_id, method, path, headers, body)
        
        # Verify redact_api_key was called
        assert mock_redact.called
        
        # Get the log message
        log_message = mock_logger.info.call_args[0][0]
        
        # Verify the log message contains the redacted prefix
        assert "REDACTED:" in log_message, "redact_api_key should have been called" 