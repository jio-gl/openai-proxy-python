import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi.responses import JSONResponse

from app.main import app

@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)

def test_root_endpoint(client):
    """Test root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "message": "OpenAI Proxy is running"}

def test_openai_proxy_endpoint_success(client):
    """Test OpenAI proxy endpoint with successful request"""
    # Mock the proxy.forward_request method
    with patch('app.main.openai_proxy.forward_request') as mock_forward:
        # Set up mock response
        mock_forward.return_value = JSONResponse(
            status_code=200,
            content={"id": "test-123", "choices": [{"message": {"content": "Hello"}}]}
        )
        
        # Make request
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello"}]}
        )
        
        # Check response
        assert response.status_code == 200
        assert response.json()["id"] == "test-123"
        
        # Verify mock was called
        mock_forward.assert_called_once()

def test_openai_proxy_endpoint_error(client):
    """Test OpenAI proxy endpoint with error"""
    # Mock the proxy.forward_request method
    with patch('app.main.openai_proxy.forward_request') as mock_forward:
        # Set up mock to raise exception
        mock_forward.side_effect = Exception("Test error")
        
        # Make request
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-3.5-turbo", "messages": [{"role": "user", "content": "Hello"}]}
        )
        
        # Check response
        assert response.status_code == 500
        assert "error" in response.json()
        assert "proxy_error" in response.json()["error"]["type"]
        
        # Verify mock was called
        mock_forward.assert_called_once()

def test_log_requests_middleware(client):
    """Test log requests middleware"""
    # Mock the logger.info method
    with patch('app.main.logger.info') as mock_logger:
        # Make a request
        response = client.get("/")
        
        # Check that the logger.info method was called twice (request and response)
        assert mock_logger.call_count == 2
        
        # Check that the first call contains "Request"
        assert "Request" in mock_logger.call_args_list[0][0][0]
        
        # Check that the second call contains "Response"
        assert "Response" in mock_logger.call_args_list[1][0][0]
        assert "200" in mock_logger.call_args_list[1][0][0] 