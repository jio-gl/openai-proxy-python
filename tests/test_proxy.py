import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from httpx import Response as HttpxResponse

from app.config import Settings
from app.proxy import OpenAIProxy

class MockResponse:
    def __init__(self, status_code, json_data, headers=None):
        self.status_code = status_code
        self._json_data = json_data
        self.headers = headers or {}
        self.text = json.dumps(json_data)
    
    def json(self):
        return self._json_data

@pytest.fixture
def settings():
    """Create test settings"""
    return Settings(
        openai_api_key="test-api-key",
        openai_base_url="https://api.openai.com"
    )

@pytest.fixture
def proxy(settings):
    """Create test proxy"""
    return OpenAIProxy(settings)

@pytest.mark.asyncio
async def test_forward_request_success(proxy):
    """Test successful request forwarding"""
    # Create request data
    request_data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    # Mock request with both body and json methods
    mock_request = MagicMock(spec=Request)
    mock_request.method = "POST"
    mock_request.headers = {"Content-Type": "application/json"}
    mock_request.query_params = {}
    
    # Properly mock the body method to return JSON bytes
    mock_request.body = AsyncMock(return_value=json.dumps(request_data).encode('utf-8'))
    mock_request.json = AsyncMock(return_value=request_data)
    
    # Mock response
    mock_response = MockResponse(
        status_code=200,
        json_data={
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "choices": [{"message": {"content": "Hello there!"}}]
        },
        headers={"Content-Type": "application/json"}
    )
    
    # Mock httpx client
    mock_client = AsyncMock()
    mock_client.request.return_value = mock_response
    
    # Mock security filter
    proxy.security_filter.validate_request = MagicMock(return_value=True)
    
    # Mock async context manager
    mock_cm = MagicMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None
    
    # Patch httpx.AsyncClient
    with patch('httpx.AsyncClient', return_value=mock_cm):
        # Also disable mock mode for this test
        with patch.object(proxy, 'mock_mode', False):
            # Call forward_request
            response = await proxy.forward_request(mock_request, "chat/completions")
            
            # Check response
            assert isinstance(response, JSONResponse)
            assert response.status_code == 200
            
            # Convert bytes to string if needed
            response_content = response.body
            if isinstance(response_content, bytes):
                response_content = response_content.decode('utf-8')
                
            assert "Hello there!" in response_content

@pytest.mark.asyncio
async def test_forward_request_security_error(proxy):
    """Test security filter blocking request"""
    # Create request data
    request_data = {
        "model": "gpt-4",  # Disallowed model
        "messages": [{"role": "user", "content": "Hello"}]
    }
    
    # Mock request with both body and json methods
    mock_request = MagicMock(spec=Request)
    mock_request.method = "POST"
    mock_request.headers = {"Content-Type": "application/json"}
    
    # Properly mock the body method to return JSON bytes
    mock_request.body = AsyncMock(return_value=json.dumps(request_data).encode('utf-8'))
    mock_request.json = AsyncMock(return_value=request_data)
    
    # Mock security filter to raise exception
    security_error = HTTPException(status_code=403, detail="Model gpt-4 is not allowed")
    proxy.security_filter.validate_request = MagicMock(side_effect=security_error)
    
    # Disable mock mode for this test
    with patch.object(proxy, 'mock_mode', False):
        # Call forward_request
        response = await proxy.forward_request(mock_request, "chat/completions")
        
        # Check response
        assert isinstance(response, JSONResponse)
        assert response.status_code == 403
        
        # Convert bytes to string if needed
        response_content = response.body
        if isinstance(response_content, bytes):
            response_content = response_content.decode('utf-8')
            
        assert "Model gpt-4 is not allowed" in response_content
        assert "security_filter_error" in response_content

@pytest.mark.asyncio
async def test_streaming_request(proxy):
    """Test streaming request handling"""
    # Create request data
    request_data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }
    
    # Mock request with both body and json methods
    mock_request = MagicMock(spec=Request)
    mock_request.method = "POST"
    mock_request.headers = {"Content-Type": "application/json"}
    mock_request.query_params = {}
    
    # Properly mock the body method to return JSON bytes
    mock_request.body = AsyncMock(return_value=json.dumps(request_data).encode('utf-8'))
    mock_request.json = AsyncMock(return_value=request_data)
    
    # Mock streaming response
    mock_stream_response = MagicMock()
    mock_stream_response.status_code = 200
    mock_stream_response.headers = {"Content-Type": "text/event-stream"}
    
    # Mock client for streaming
    mock_client = MagicMock()
    
    # Mock _handle_streaming_request
    proxy._handle_streaming_request = AsyncMock(return_value=StreamingResponse(
        content=iter([b'data: {"id":"chatcmpl-123","object":"chat.completion.chunk"}\n\n']),
        media_type="text/event-stream"
    ))
    
    # Mock security filter
    proxy.security_filter.validate_request = MagicMock(return_value=True)
    
    # Mock async context manager
    mock_cm = MagicMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None
    
    # Patch httpx.AsyncClient
    with patch('httpx.AsyncClient', return_value=mock_cm):
        # Disable mock mode for this test
        with patch.object(proxy, 'mock_mode', False):
            # Call forward_request
            response = await proxy.forward_request(mock_request, "chat/completions")
            
            # Check response
            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/event-stream"
            
            # Verify _handle_streaming_request was called
            proxy._handle_streaming_request.assert_called_once()
            call_args = proxy._handle_streaming_request.call_args[0]
            assert call_args[0] is mock_client
            assert call_args[1] == "POST"
            assert call_args[2] == "https://api.openai.com/v1/chat/completions" 