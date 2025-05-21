import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi.responses import JSONResponse
import json
import os

from app.main import app
from app.proxy import OpenAIProxy, CerebrasProxy
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
    # Mock both proxies to handle Cerebras routing
    with patch.object(CerebrasProxy, 'forward_request') as mock_cerebras, \
         patch.object(OpenAIProxy, 'forward_request') as mock_openai:
        
        # Set up the mocks to return a successful response
        response_content = {"message": "success"}
        
        mock_cerebras.return_value = JSONResponse(
            content=response_content,
            status_code=200
        )
        
        mock_openai.return_value = JSONResponse(
            content=response_content,
            status_code=200
        )
        
        # Test regular OpenAI endpoint
        response = client.post("/v1/embeddings", json={"model": "text-embedding-ada-002", "input": "hello"})
        assert response.status_code == 200
        assert response.json() == {"message": "success"}
        mock_openai.assert_called_once()
        
        # Reset the mock
        mock_openai.reset_mock()
        
        # Test completions endpoint (should go to Cerebras)
        response = client.post("/v1/completions", json={"model": "llama-3.3-70b", "prompt": "hello"})
        assert response.status_code == 200
        assert response.json() == {"message": "success"}
        mock_cerebras.assert_called_once()
        assert not mock_openai.called

def test_openai_proxy_endpoint_error(client):
    """Test the OpenAI proxy endpoint with an error"""
    # Mock the forward_request method of both proxies
    with patch.object(CerebrasProxy, 'forward_request') as mock_cerebras, \
         patch.object(OpenAIProxy, 'forward_request') as mock_openai:
        
        # Set up the mock to raise an exception
        mock_cerebras.side_effect = Exception("Cerebras test error")
        mock_openai.side_effect = Exception("OpenAI test error")
        
        # Make a request to a standard OpenAI endpoint
        response = client.post("/v1/embeddings", json={"model": "text-embedding-ada-002", "input": "hello"})
        assert response.status_code == 500
        assert "error" in response.json()
        assert "OpenAI test error" in response.json()["error"]["message"]
        
        # Make a request to a Cerebras endpoint
        response = client.post("/v1/completions", json={"model": "llama-3.3-70b", "prompt": "hello"})
        assert response.status_code == 500
        assert "error" in response.json()
        # Check if we get Cerebras error
        assert "test error" in response.json()["error"]["message"]

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