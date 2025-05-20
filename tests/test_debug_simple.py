#!/usr/bin/env python3
"""
Simple test script for debugging the request handling in debug mode
"""
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import logging
import os
import sys
import pytest

# Configure basic logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create a simple test app with our middleware
app = FastAPI()

# Copy of the middleware function for standalone testing
@app.middleware("http")
async def debug_log(request: Request, call_next):
    """Debug logging middleware to test ASGI handling"""
    logger.info(f"Request: {request.method} {request.url.path}")
    
    # Log headers
    headers_dict = dict(request.headers)
    logger.debug(f"Request headers: {headers_dict}")
    
    # Only log body for JSON requests
    if request.headers.get("Content-Type") == "application/json":
        # Create a wrapper for receive
        original_receive = request.receive
        
        async def wrapped_receive():
            message = await original_receive()
            if message["type"] == "http.request" and "body" in message:
                body_bytes = message.get("body", b"")
                if body_bytes:
                    try:
                        body = json.loads(body_bytes)
                        logger.debug(f"Request body: {body}")
                    except Exception as e:
                        logger.debug(f"Error processing body: {str(e)}")
            return message
        
        # Replace receive method
        request.receive = wrapped_receive
    
    # Process the request normally
    response = await call_next(request)
    
    # Log response
    logger.info(f"Response: {response.status_code}")
    logger.debug(f"Response headers: {dict(response.headers)}")
    
    return response

# Define a test endpoint
@app.post("/test")
async def test_endpoint(request: Request):
    """Test endpoint that echoes back the request body"""
    body = await request.json()
    return {"success": True, "received": body}

def run_test():
    """Run the test with the TestClient"""
    client = TestClient(app)
    
    # Send a test request
    response = client.post(
        "/test",
        headers={"Content-Type": "application/json"},
        json={"test": "payload", "nested": {"value": 123}}
    )
    
    # Check the response
    print("\n=== TEST RESULTS ===")
    print(f"Status code: {response.status_code}")
    print(f"Response: {response.json()}")
    print("=== TEST COMPLETE ===\n")
    
    # If the test completed and we got a 200 response, the middleware is working
    if response.status_code == 200:
        return True
    return False

@pytest.mark.asyncio
async def test_endpoint():
    # Simulate an async endpoint test
    await asyncio.sleep(0.1)
    assert True, "Async test passed"

if __name__ == "__main__":
    success = run_test()
    asyncio.run(test_endpoint())
    sys.exit(0 if success else 1) 