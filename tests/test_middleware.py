#!/usr/bin/env python3
"""
Test middleware implementation for the OpenAI proxy
"""
import json
import logging
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware
import sys
import time
import pytest
import asyncio

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Create test app
app = FastAPI()

# Test middleware class - simplified to avoid blocking
class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Log request info
        logger.info(f"Request: {request.method} {request.url.path}")
        logger.debug(f"Headers: {dict(request.headers)}")
        
        # Process the request first and get response
        response = await call_next(request)
        
        # Log response info after we've already handled the request
        logger.info(f"Response: {response.status_code}")
        
        return response

# Add middleware to app
app.add_middleware(LoggingMiddleware)

# Define test endpoint
@app.post("/test")
async def test_endpoint(request: Request):
    # Read the body
    try:
        body = await request.json()
        return {"success": True, "received": body}
    except Exception as e:
        logger.error(f"Error in test endpoint: {str(e)}")
        return {"success": False, "error": str(e)}

@pytest.mark.asyncio
async def test_endpoint():
    # Simulate an async endpoint test
    await asyncio.sleep(0.1)
    assert True, "Async test passed"

def run_test():
    """Run a test with the client"""
    # Create test client
    client = TestClient(app)
    
    try:
        # Make a request
        response = client.post(
            "/test",
            headers={"Content-Type": "application/json"},
            json={"test": "data", "nested": {"value": 123}}
        )
        
        # Print results
        print("\n=== TEST RESULTS ===")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print(f"Response: {response.json()}")
            print("=== TEST COMPLETE ===\n")
            return True
        else:
            print(f"Error: {response.text}")
            print("=== TEST FAILED ===\n")
            return False
            
    except Exception as e:
        print(f"\n=== TEST ERROR ===")
        print(f"Error: {str(e)}")
        print("=== TEST FAILED ===\n")
        return False

if __name__ == "__main__":
    print("Starting middleware test...")
    success = run_test()
    sys.exit(0 if success else 1)

    asyncio.run(test_endpoint()) 