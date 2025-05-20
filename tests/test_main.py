import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi.responses import JSONResponse
import json
import os

from app.main import app
from app.proxy import OpenAIProxy
from app.config import Settings

@pytest.fixture
def client():
    """Create test client for the API"""
    return TestClient(app)

def test_root_endpoint(client):
    """Test the root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "OpenAI Proxy is running"}

def test_openai_proxy_endpoint_success(client):
    """Test the OpenAI proxy endpoint with a successful request"""
    # Mock the forward_request method of OpenAIProxy
    with patch.object(OpenAIProxy, 'forward_request') as mock_forward:
        # Set up the mock to return a JSONResponse instead of a MagicMock
        # This matches what the actual endpoint returns
        response_content = {"message": "success"}
        mock_forward.return_value = JSONResponse(
            content=response_content,
            status_code=200
        )
        
        # Make a request to the endpoint
        response = client.post("/v1/chat/completions", json={"model": "gpt-3.5-turbo"})
        
        # Verify the response
        assert response.status_code == 200
        assert response.json() == {"message": "success"}
        
        # Verify the forward_request method was called
        mock_forward.assert_called_once()

def test_openai_proxy_endpoint_error(client):
    """Test the OpenAI proxy endpoint with an error"""
    # Mock the forward_request method of OpenAIProxy
    with patch.object(OpenAIProxy, 'forward_request') as mock_forward:
        # Set up the mock to raise an exception
        mock_forward.side_effect = Exception("Test error")
        
        # Make a request to the endpoint
        response = client.post("/v1/chat/completions", json={"model": "gpt-3.5-turbo"})
        
        # Verify the response
        assert response.status_code == 500
        assert "error" in response.json()
        assert "Test error" in response.json()["error"]["message"]

def test_log_requests_middleware():
    """Test the log_requests middleware"""
    # Create a mock logger
    mock_logger = MagicMock()
    
    # Patch the logger in app.main
    with patch('app.main.logger', mock_logger):
        # Create a test client
        client = TestClient(app)
        
        # Make a request
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello"}]}
        )
        
        # Verify logger was called
        assert mock_logger.info.called
        
        # Verify request was logged
        request_log_calls = [call for call in mock_logger.info.call_args_list if "Request" in call[0][0]]
        assert len(request_log_calls) > 0
        
        # Verify response was logged
        response_log_calls = [call for call in mock_logger.info.call_args_list if "Response" in call[0][0]]
        assert len(response_log_calls) > 0

def test_debug_mode_api_key_redaction():
    """Test that API keys are properly redacted in debug mode logs"""
    # Create a mock logger
    mock_logger = MagicMock()
    
    # Set up mocks to avoid blocking issues
    with patch('app.main.logger', mock_logger), \
         patch.dict('os.environ', {'LOG_LEVEL': 'DEBUG'}), \
         patch('app.main.openai_proxy.forward_request', side_effect=Exception("Test error")), \
         patch('app.logging.redact_api_key', side_effect=lambda x: f"REDACTED:{x}" if isinstance(x, str) else x):
        
        # Create a test client
        client = TestClient(app)
        
        # Make a request with an API key in the headers
        response = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer sk-1234567890abcdef"},
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Test with API key mentioned: sk-abc123"}]
            }
        )
        
        # Check debug calls
        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list if hasattr(call[0], '__len__') and len(call[0]) > 0]
        
        # Assert that API keys are redacted in request headers
        header_logs = [call for call in debug_calls if isinstance(call, str) and "Request headers" in call]
        assert any(header_logs), "Should have logged request headers in debug mode"
        
        for log in header_logs:
            # Check that the Authorization header is properly redacted
            assert "sk-1234567890abcdef" not in log, "API key should not appear in clear text"
            assert "REDACTED" in log, "Authorization header should be redacted"
            
        # Check if body was redacted
        body_logs = [call for call in debug_calls if isinstance(call, str) and "Request body" in call]
        if body_logs:
            for log in body_logs:
                # Check that any API key in content is redacted
                assert "sk-abc123" not in log, "API key in content should be redacted" 