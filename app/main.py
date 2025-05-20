import logging
import os
import socket
from fastapi import FastAPI, Request, Response, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from dotenv import load_dotenv
import json

from app.proxy import OpenAIProxy, AnthropicProxy, SafeJSONResponse
from app.config import Settings
from app.logging import setup_logging, redact_api_key

# Load environment variables
load_dotenv()

# Setup logging
logger = setup_logging()

# Load settings
settings = Settings()

# Debug log to check settings - with masked API key
if settings.openai_api_key:
    masked_api_key = settings.openai_api_key[:5] + "..." if len(settings.openai_api_key) > 5 else "not set"
    logger.info(f"OpenAI API Key: {masked_api_key} [masked]")
else:
    logger.info("OpenAI API Key: not set")
    
logger.info(f"OpenAI Base URL: {settings.openai_base_url}")

# Mask organization ID if present
masked_org_id = settings.openai_org_id[:4] + "..." if settings.openai_org_id and len(settings.openai_org_id) > 4 else settings.openai_org_id
logger.info(f"OpenAI Organization ID: {masked_org_id}")

# Create FastAPI app
app = FastAPI(
    title="OpenAI Proxy",
    description="A proxy server that provides additional security and logging for OpenAI API calls",
    version="0.1.0"
)

# Add CORS middleware with permissive settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
    expose_headers=["*"]  # Expose all headers
)

# Add middleware to modify network behavior
@app.middleware("http")
async def mask_private_network(request: Request, call_next):
    """Middleware to mask the private network nature of requests"""
    # Add headers to make the request look like it's coming from a public network
    request.scope["client"] = ("104.18.7.192", request.scope["client"][1])  # Fake client IP
    
    # Continue with the request
    response = await call_next(request)
    return response

# Create proxies
openai_proxy = OpenAIProxy(settings)
anthropic_proxy = AnthropicProxy(settings)

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "status": "ok",
        "message": "OpenAI Proxy is running"
    }

@app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def openai_proxy_endpoint(request: Request, path: str):
    """Proxy all requests to OpenAI API"""
    # Handle OPTIONS requests directly for CORS preflight
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
                "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Request-ID",
                "Access-Control-Max-Age": "3600",
            },
        )
    
    try:
        return await openai_proxy.forward_request(request, path)
    except Exception as e:
        error_message = str(e)
        # Redact any API keys that might be in error messages
        error_message = redact_api_key(error_message)
        logger.error(f"Error proxying OpenAI request: {error_message}")
        error_content = {"error": {"message": f"Proxy error: {error_message}", "type": "proxy_error"}}
        error_json = json.dumps(error_content).encode('utf-8')
        return SafeJSONResponse(
            status_code=500,
            content=error_content,
            headers={"Content-Length": str(len(error_json))}
        )

@app.api_route("/anthropic/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"])
async def anthropic_proxy_endpoint(request: Request, path: str):
    """Proxy all requests to Anthropic API"""
    # Handle OPTIONS requests directly for CORS preflight
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
                "Access-Control-Allow-Headers": "x-api-key, anthropic-version, Content-Type, X-Request-ID",
                "Access-Control-Max-Age": "3600",
            },
        )
    
    try:
        return await anthropic_proxy.forward_request(request, path)
    except Exception as e:
        error_message = str(e)
        # Redact any API keys that might be in error messages
        error_message = redact_api_key(error_message)
        logger.error(f"Error proxying Anthropic request: {error_message}")
        error_content = {"error": {"message": f"Proxy error: {error_message}", "type": "proxy_error"}}
        error_json = json.dumps(error_content).encode('utf-8')
        return SafeJSONResponse(
            status_code=500,
            content=error_content,
            headers={"Content-Length": str(len(error_json))}
        )

# Simplified logging middleware that won't interfere with response handling
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests and responses"""
    request_id = request.headers.get("X-Request-ID", "unknown")
    logger.info(f"Request {request_id}: {request.method} {request.url.path}")
    
    # In debug mode, log more details of the request
    original_body = None
    if os.environ.get("LOG_LEVEL", "").upper() == "DEBUG":
        try:
            # Log sanitized headers
            headers_dict = dict(request.headers)
            # Redact sensitive headers
            if "authorization" in headers_dict:
                headers_dict["authorization"] = "[REDACTED]"
            if "x-api-key" in headers_dict:
                headers_dict["x-api-key"] = "[REDACTED]"
                
            logger.debug(f"Request headers {request_id}: {headers_dict}")
            
            # Try to get and log body for non-streaming requests
            if request.headers.get("Content-Type") == "application/json":
                # Store the original request body
                body_bytes = await request.body()
                if body_bytes:
                    # Save the body so we can restore it
                    original_body = body_bytes
                    try:
                        body = json.loads(body_bytes)
                        
                        # Sanitize sensitive fields before logging
                        sanitized_body = body.copy() if isinstance(body, dict) else body
                        if isinstance(sanitized_body, dict):
                            if "api_key" in sanitized_body:
                                sanitized_body["api_key"] = "[REDACTED]"
                            if "messages" in sanitized_body and isinstance(sanitized_body["messages"], list):
                                # Keep the structure but redact content if needed
                                pass  # We're keeping content in debug mode
                                
                        # Convert to JSON and apply final redaction pass
                        body_json = json.dumps(sanitized_body)
                        body_json = redact_api_key(body_json)
                        logger.debug(f"Request body {request_id}: {body_json}")
                    except json.JSONDecodeError:
                        logger.debug(f"Request body {request_id}: Could not parse JSON body")
        except Exception as e:
            logger.debug(f"Error logging request details: {str(e)}")
    
    # Restore the request body if needed
    if original_body is not None:
        # Replace the body getter to return our saved body
        async def get_body():
            return original_body
        request._body = original_body
        request.body = get_body
    
    # Process the request normally
    response = await call_next(request)
    
    # Log the response without accessing its body
    logger.info(f"Response {request_id}: Status {response.status_code}")
    
    # In debug mode, try to log response headers
    if os.environ.get("LOG_LEVEL", "").upper() == "DEBUG":
        # Redact any sensitive headers
        response_headers = dict(response.headers)
        if "authorization" in response_headers:
            response_headers["authorization"] = "[REDACTED]"
        if "x-api-key" in response_headers:
            response_headers["x-api-key"] = "[REDACTED]"
            
        logger.debug(f"Response headers {request_id}: {response_headers}")
    
    # For streaming responses, ensure we don't modify Content-Length
    if response.headers.get("Content-Type") == "text/event-stream":
        # For streaming responses, ensure Transfer-Encoding is set and Content-Length is removed
        response.headers["Transfer-Encoding"] = "chunked"
        if "Content-Length" in response.headers:
            del response.headers["Content-Length"]
    
    # Return response unmodified
    return response

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)  # Changed port to 8000 