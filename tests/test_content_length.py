import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import Request
from fastapi.responses import StreamingResponse
import json

from app.proxy import OpenAIProxy, BaseAPIProxy
from app.config import Settings

@pytest.fixture
def proxy():
    """Create a proxy instance for testing"""
    settings = Settings()
    return OpenAIProxy(settings)

@pytest.mark.asyncio
async def test_streaming_content_length_handling(proxy):
    """Test that Content-Length header is properly handled in streaming responses"""
    # Create request data
    request_data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True
    }

    # Mock request
    mock_request = MagicMock(spec=Request)
    mock_request.method = "POST"
    mock_request.headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Content-Length": "123"  # Add Content-Length to test its removal
    }
    mock_request.query_params = {}
    mock_request.body = AsyncMock(return_value=json.dumps(request_data).encode('utf-8'))
    mock_request.json = AsyncMock(return_value=request_data)

    # Mock streaming response
    mock_stream_response = MagicMock()
    mock_stream_response.status_code = 200
    mock_stream_response.headers = {
        "Content-Type": "text/event-stream",
        "Content-Length": "456"  # Add Content-Length to test its removal
    }

    # Mock client for streaming
    mock_client = MagicMock()

    # Mock _handle_streaming_request to return a StreamingResponse
    async def mock_stream_generator():
        yield b'data: {"id":"chatcmpl-123","object":"chat.completion.chunk"}\n\n'
        yield b'data: {"id":"chatcmpl-123","object":"chat.completion.chunk"}\n\n'
        yield b'data: [DONE]\n\n'

    proxy._handle_streaming_request = AsyncMock(return_value=StreamingResponse(
        content=mock_stream_generator(),
        media_type="text/event-stream"
    ))

    # Mock security filter to return allowed=True
    proxy.security_filter.check_request = MagicMock(return_value={"allowed": True})

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

            # Verify response is a StreamingResponse
            assert isinstance(response, StreamingResponse)
            assert response.media_type == "text/event-stream"

            # Verify Content-Length is not in headers
            assert "Content-Length" not in response.headers

            # Verify Transfer-Encoding is set to chunked
            assert response.headers.get("Transfer-Encoding") == "chunked"

            # Verify other required headers are present
            assert response.headers.get("Content-Type") == "text/event-stream"
            assert response.headers.get("Cache-Control") == "no-cache"
            assert response.headers.get("Connection") == "keep-alive"

            # Verify _handle_streaming_request was called
            proxy._handle_streaming_request.assert_called_once() 