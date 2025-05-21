import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from fastapi.responses import JSONResponse, StreamingResponse
import json
import os
import asyncio
from cerebras.cloud.sdk import Cerebras

from app.main import app
from app.proxy import CerebrasProxy, OpenAIProxy
from app.config import Settings

@pytest.fixture
def client():
    """Create test client for the API"""
    return TestClient(app)

def test_cerebras_completion_routing(client):
    """Test that completions requests are routed to Cerebras AI"""
    # Mock the Cerebras client
    with patch('cerebras.cloud.sdk.Cerebras') as mock_cerebras_class:
        # Create a mock instance
        mock_cerebras = MagicMock()
        mock_cerebras_class.return_value = mock_cerebras
        
        # Set up the mock to return a success response
        mock_response = MagicMock()
        mock_response.to_dict.return_value = {"id": "test-completion", "model": "llama-3.3-70b"}
        mock_cerebras.completions.create.return_value = mock_response
        
        # Make a request to the completions endpoint
        response = client.post(
            "/v1/completions",
            json={
                "model": "gpt-3.5-turbo",  # Even if we specify OpenAI model, it should go to Cerebras
                "prompt": "Hello world",
                "max_tokens": 50
            }
        )
        
        # Verify the response and that the right client was called
        assert response.status_code == 200
        assert mock_cerebras.completions.create.called
        mock_cerebras.completions.create.assert_called_once_with(
            prompt="Hello world",
            model="llama-3.3-70b",
            max_tokens=50
        )

def test_cerebras_chat_completions_routing(client):
    """Test that chat completions requests are routed to Cerebras AI"""
    # Mock the Cerebras client
    with patch('cerebras.cloud.sdk.Cerebras') as mock_cerebras_class:
        # Create a mock instance
        mock_cerebras = MagicMock()
        mock_cerebras_class.return_value = mock_cerebras
        
        # Set up the mock to return a success response
        mock_response = MagicMock()
        mock_response.to_dict.return_value = {"id": "test-chat-completion", "model": "llama-3.3-70b"}
        mock_cerebras.chat.completions.create.return_value = mock_response
        
        # Make a request to the chat completions endpoint
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-3.5-turbo",  # Even if we specify OpenAI model, it should go to Cerebras
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 50
            }
        )
        
        # Verify the response and that the right client was called
        assert response.status_code == 200
        assert mock_cerebras.chat.completions.create.called
        mock_cerebras.chat.completions.create.assert_called_once_with(
            messages=[{"role": "user", "content": "Hello"}],
            model="llama-3.3-70b",
            max_tokens=50
        )

def test_cerebras_streaming_routing(client):
    """Test that streaming requests are routed to Cerebras AI"""
    # Mock the Cerebras client
    with patch('cerebras.cloud.sdk.Cerebras') as mock_cerebras_class:
        # Create a mock instance
        mock_cerebras = MagicMock()
        mock_cerebras_class.return_value = mock_cerebras
        
        # Create a mock stream
        mock_stream = [
            MagicMock(id="chunk1", choices=[MagicMock(delta=MagicMock(content="Hello"))]),
            MagicMock(id="chunk2", choices=[MagicMock(delta=MagicMock(content=" world"))]),
            MagicMock(id="chunk3", choices=[MagicMock(delta=MagicMock(content="!"))])
        ]
        mock_cerebras.chat.completions.create.return_value = mock_stream
        
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
        assert mock_cerebras.chat.completions.create.called
        mock_cerebras.chat.completions.create.assert_called_once_with(
            messages=[{"role": "user", "content": "Hello"}],
            model="llama-3.3-70b",
            stream=True
        )

def test_cerebras_health_check(client):
    """Test the Cerebras health check endpoint"""
    # Mock the Cerebras client
    with patch('cerebras.cloud.sdk.Cerebras') as mock_cerebras_class:
        # Create a mock instance
        mock_cerebras = MagicMock()
        mock_cerebras_class.return_value = mock_cerebras
        
        # Set up the mock to return a success response
        mock_response = MagicMock()
        mock_response.to_dict.return_value = {"id": "test-id", "model": "llama-3.3-70b"}
        mock_cerebras.completions.create.return_value = mock_response
        
        # Make a request to the health endpoint
        response = client.get("/health/cerebras")
        
        # Verify the response
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "Cerebras backend is responding" in data["message"]
        assert data["model"] == "llama-3.3-70b"
        
        # Test unhealthy scenario
        mock_cerebras.completions.create.side_effect = Exception("test error")
        
        response = client.get("/health/cerebras")
        data = response.json()
        assert data["status"] == "unhealthy"
        assert "test error" in data["message"] 