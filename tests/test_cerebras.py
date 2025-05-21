import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi.responses import JSONResponse, StreamingResponse
import json
import os
import asyncio

from app.main import app
from app.proxy import CerebrasProxy, OpenAIProxy
from app.config import Settings

@pytest.fixture
def client():
    """Create test client for the API"""
    return TestClient(app)

def test_cerebras_completion_routing(client):
    """Test that completions requests are routed to Cerebras AI"""
    # Mock the Cerebras and OpenAI forward_request methods
    with patch.object(CerebrasProxy, 'forward_request') as mock_cerebras, \
         patch.object(OpenAIProxy, 'forward_request') as mock_openai:
        
        # Set up the mocks to return success responses
        mock_cerebras.return_value = JSONResponse(
            content={"id": "test-completion", "model": "llama-3.3-70b"},
            status_code=200
        )
        
        mock_openai.return_value = JSONResponse(
            content={"error": "Should not call OpenAI"},
            status_code=200
        )
        
        # Make a request to the completions endpoint
        response = client.post(
            "/v1/completions",
            json={
                "model": "gpt-3.5-turbo",  # Even if we specify OpenAI model, it should go to Cerebras
                "prompt": "Hello world",
                "max_tokens": 50
            }
        )
        
        # Verify the response and that the right proxy was called
        assert response.status_code == 200
        assert mock_cerebras.called
        assert not mock_openai.called

def test_cerebras_chat_completions_routing(client):
    """Test that chat completions requests are routed to Cerebras AI"""
    # Mock the Cerebras and OpenAI forward_request methods
    with patch.object(CerebrasProxy, 'forward_request') as mock_cerebras, \
         patch.object(OpenAIProxy, 'forward_request') as mock_openai:
        
        # Set up the mocks to return success responses
        mock_cerebras.return_value = JSONResponse(
            content={"id": "test-chat-completion", "model": "llama-3.3-70b"},
            status_code=200
        )
        
        mock_openai.return_value = JSONResponse(
            content={"error": "Should not call OpenAI"},
            status_code=200
        )
        
        # Make a request to the chat completions endpoint
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",  # Even if we specify OpenAI model, it should go to Cerebras
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 50
            }
        )
        
        # Verify the response and that the right proxy was called
        assert response.status_code == 200
        assert mock_cerebras.called
        assert not mock_openai.called

def test_cerebras_streaming_routing(client):
    """Test that streaming requests are routed to Cerebras AI"""
    # Mock the Cerebras and OpenAI forward_request methods
    with patch.object(CerebrasProxy, 'forward_request') as mock_cerebras, \
         patch.object(OpenAIProxy, 'forward_request') as mock_openai:
        
        # Create a simple async generator for streaming
        async def mock_stream_generator():
            yield b"data: {}\n\n"
            yield b"data: {\"id\":\"chatcmpl-123\"}\n\n"
            yield b"data: [DONE]\n\n"

        # Set up the mock to return a streaming response
        mock_cerebras.return_value = StreamingResponse(
            mock_stream_generator(),
            media_type="text/event-stream"
        )
        
        # Make a streaming request to chat completions
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True
            },
            headers={"Accept": "text/event-stream"}
        )
        
        # Verify the response headers indicate streaming
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")
        assert mock_cerebras.called
        assert not mock_openai.called

def test_cerebras_health_check(client):
    """Test the Cerebras health check endpoint"""
    # Mock httpx.AsyncClient.post to avoid real API calls
    with patch('httpx.AsyncClient.post') as mock_post:
        # Setup mock to return a successful response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "test-id", "model": "llama-3.3-70b"}
        mock_post.return_value = mock_response
        
        # Make a request to the health endpoint
        response = client.get("/health/cerebras")
        
        # Verify the response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "Cerebras backend is responding" in data["message"]
        assert data["model"] == "llama-3.3-70b"
        
        # Test unhealthy scenario
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "test error"}
        
        response = client.get("/health/cerebras")
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "500" in data["message"] 