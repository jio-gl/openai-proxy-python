import json
import httpx
import logging
import uuid
import os
import asyncio
import random
import copy
import time
from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask
import urllib.parse

from app.config import Settings
from app.logging import RequestResponseLogger, redact_api_key
from app.security import SecurityFilter
from app.rate_limiter import TokenRateLimiter

# Create a custom JSONResponse that always sets a proper content-length header
class SafeJSONResponse(JSONResponse):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ensure content is serialized consistently
        if self.body is None and self.content is not None:
            self.body = self.render(self.content)
        # Always set content-length header based on the actual body length
        if self.body is not None:
            self.headers["content-length"] = str(len(self.body))
            
    def render(self, content):
        # Override render to ensure consistent encoding
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
        ).encode("utf-8")

class BaseAPIProxy:
    """Base class for API proxies"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = logging.getLogger("api-firewall")
        self.request_logger = RequestResponseLogger(self.logger)
        self.security_filter = SecurityFilter(settings)
        
        # Create a persistent client with cookie handling and proper session management
        self.client = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            verify=True,
            cookies=httpx.Cookies(),  # Add cookie jar
            http2=True  # Enable HTTP/2 by default
        )
        
        # Create a separate streaming client with longer timeout and cookie handling
        self.streaming_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=10.0,    # Connection timeout
                read=None,      # No read timeout for streaming
                write=None,     # No write timeout for streaming
                pool=None      # No pool timeout
            ),
            follow_redirects=True,
            verify=True,
            cookies=httpx.Cookies(),  # Separate cookie jar for streaming
            http2=True  # Enable HTTP/2 by default
        )
        
        # Check if we're in mock mode
        self.mock_mode = os.environ.get("MOCK_RESPONSES", "false").lower() == "true"
    
    async def forward_request(self, request: Request, path: str, request_id: str = None):
        """Forward request to API"""
        raise NotImplementedError("Subclasses must implement this method")
    
    def _get_mock_response(self, body: dict):
        """Generate a mock response for testing"""
        raise NotImplementedError("Subclasses must implement this method")
    
    async def _process_stream(self, response, request_id, debug_mode=False):
        """Process a streaming response"""
        try:
            async with response:  # Ensure proper stream cleanup
                async for chunk in response.aiter_bytes():
                    if debug_mode:
                        try:
                            # Try to decode and parse the chunk for logging
                            chunk_str = chunk.decode('utf-8')
                            if chunk_str.startswith('data: '):
                                chunk_data = chunk_str.replace('data: ', '')
                                if chunk_data.strip() != '[DONE]':
                                    try:
                                        chunk_json = json.loads(chunk_data)
                                        # Log the full chunk without redaction
                                        self.logger.debug(f"Streaming response chunk {request_id}: {json.dumps(chunk_json)}")
                                    except json.JSONDecodeError:
                                        pass  # Not all chunks are JSON
                        except Exception as e:
                            self.logger.debug(f"Could not log streaming chunk {request_id}: {str(e)}")
                    yield chunk
                # Ensure proper stream termination
                yield b"data: [DONE]\n\n"
        except httpx.StreamClosed as e:
            self.logger.error(f"Stream closed unexpectedly for request {request_id}: {str(e)}")
            # Return a graceful error message
            error_msg = json.dumps({"error": {"message": "Stream was closed unexpectedly", "type": "stream_error", "details": str(e)}})
            yield f"data: {error_msg}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"
        except httpx.ReadTimeout as e:
            self.logger.error(f"Stream read timeout for request {request_id}: {str(e)}")
            error_msg = json.dumps({"error": {"message": "Stream read timeout", "type": "stream_error", "details": str(e)}})
            yield f"data: {error_msg}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"
        except httpx.WriteTimeout as e:
            self.logger.error(f"Stream write timeout for request {request_id}: {str(e)}")
            error_msg = json.dumps({"error": {"message": "Stream write timeout", "type": "stream_error", "details": str(e)}})
            yield f"data: {error_msg}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"
        except httpx.ConnectTimeout as e:
            self.logger.error(f"Stream connection timeout for request {request_id}: {str(e)}")
            error_msg = json.dumps({"error": {"message": "Stream connection timeout", "type": "stream_error", "details": str(e)}})
            yield f"data: {error_msg}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"
        except httpx.HTTPStatusError as e:
            self.logger.error(f"Stream HTTP error for request {request_id}: {str(e)}")
            error_msg = json.dumps({"error": {"message": f"Stream HTTP error: {e.response.status_code}", "type": "stream_error", "details": str(e)}})
            yield f"data: {error_msg}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"
        except Exception as e:
            self.logger.error(f"Unexpected error processing stream {request_id}: {str(e)}", exc_info=True)
            # Return a graceful error message with more context
            error_msg = json.dumps({
                "error": {
                    "message": f"Unexpected stream error: {str(e)}",
                    "type": "stream_error",
                    "details": str(e),
                    "request_id": request_id
                }
            })
            yield f"data: {error_msg}\n\n".encode('utf-8')
            yield b"data: [DONE]\n\n"

    async def _handle_streaming_request(self, client, method, target_url, headers, body, request_id, log_response):
        """Handle a streaming request"""
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        
        if debug_mode:
            self.logger.debug(f"Handling streaming request to {target_url}")
            # Log streaming request body and cookies
            if body:
                try:
                    body_json = json.dumps(body)
                    self.logger.debug(f"Streaming request body {request_id}: {body_json}")
                    
                    # Log current cookies
                    cookies_str = '; '.join([f"{c.name}={c.value}" for c in client.cookies.jar])
                    self.logger.debug(f"Current cookies for request {request_id}: {cookies_str}")
                except Exception as e:
                    self.logger.debug(f"Could not log streaming request details {request_id}: {str(e)}")
        
        try:
            # Make the streaming request with proper timeout settings
            async with client.stream(
                method=method,
                url=target_url,
                headers=headers,
                json=body if method in ("POST", "PUT", "PATCH") else None,
                timeout=httpx.Timeout(
                    connect=10.0,    # Connection timeout
                    read=None,       # No read timeout for streaming
                    write=60.0,      # Write timeout
                    pool=None        # No pool timeout
                )
            ) as response:
                # Log response details including rate limits
                status_code, response_headers = await log_response(response, request_id, True)
                
                # For 429 responses, get the full error message
                if status_code == 429:
                    self.logger.warning(f"Rate limit exceeded for request {request_id}")
                    try:
                        # Read the full response content for error details
                        error_content = await response.aread()
                        error_body = json.loads(error_content.decode('utf-8'))
                        self.logger.error(f"Rate limit error details: {json.dumps(error_body, indent=2)}")
                        
                        # Create a proper error response
                        return JSONResponse(
                            status_code=429,
                            content=error_body
                        )
                    except Exception as e:
                        self.logger.error(f"Failed to parse rate limit error: {str(e)}")
                        # Fallback error message
                        error_msg = {
                            "error": {
                                "message": f"Rate limit exceeded. Check API key limits.",
                                "type": "rate_limit_error",
                                "headers": {k: v for k, v in response_headers.items() if 'ratelimit' in k.lower()}
                            }
                        }
                        return JSONResponse(
                            status_code=429,
                            content=error_msg
                        )
                
                # Extract and update cookies from response
                if "set-cookie" in response.headers:
                    self.logger.debug(f"Found Set-Cookie header in streaming response {request_id}")
                    client.cookies.extract_cookies(response)
                    
                    if debug_mode:
                        cookies_str = '; '.join([f"{c.name}={c.value}" for c in client.cookies.jar])
                        self.logger.debug(f"Updated cookies after streaming response {request_id}: {cookies_str}")
                
                # Create the streaming response with proper headers
                response_headers = {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Transfer-Encoding": "chunked",
                    "X-Accel-Buffering": "no"  # Disable proxy buffering
                }
                
                # Copy relevant headers from the upstream response
                for header in ["access-control-allow-origin", "access-control-allow-methods",
                             "access-control-allow-headers", "access-control-expose-headers",
                             "access-control-allow-credentials"]:
                    if header in response.headers:
                        response_headers[header] = response.headers[header]
                
                # Copy any Set-Cookie headers
                if "set-cookie" in response.headers:
                    response_headers["set-cookie"] = response.headers["set-cookie"]
                
                return StreamingResponse(
                    self._process_stream(response, request_id, debug_mode),
                    status_code=response.status_code,
                    headers=response_headers
                )
        except httpx.ConnectTimeout as e:
            self.logger.error(f"Connection timeout for streaming request {request_id}: {str(e)}")
            error_content = {
                "error": {
                    "message": "Connection timeout while establishing stream",
                    "type": "stream_error",
                    "details": str(e),
                    "request_id": request_id
                }
            }
            return JSONResponse(status_code=504, content=error_content)
        except httpx.ReadTimeout as e:
            self.logger.error(f"Read timeout for streaming request {request_id}: {str(e)}")
            error_content = {
                "error": {
                    "message": "Read timeout while streaming response",
                    "type": "stream_error",
                    "details": str(e),
                    "request_id": request_id
                }
            }
            return JSONResponse(status_code=504, content=error_content)
        except httpx.WriteTimeout as e:
            self.logger.error(f"Write timeout for streaming request {request_id}: {str(e)}")
            error_content = {
                "error": {
                    "message": "Write timeout while streaming response",
                    "type": "stream_error",
                    "details": str(e),
                    "request_id": request_id
                }
            }
            return JSONResponse(status_code=504, content=error_content)
        except httpx.HTTPStatusError as e:
            self.logger.error(f"HTTP error for streaming request {request_id}: {str(e)}")
            error_content = {
                "error": {
                    "message": f"HTTP error {e.response.status_code} while streaming",
                    "type": "stream_error",
                    "details": str(e),
                    "request_id": request_id,
                    "status_code": e.response.status_code
                }
            }
            return JSONResponse(status_code=e.response.status_code, content=error_content)
        except Exception as e:
            self.logger.error(f"Unexpected error in streaming request {request_id}: {str(e)}", exc_info=True)
            error_content = {
                "error": {
                    "message": f"Unexpected error while streaming: {str(e)}",
                    "type": "stream_error",
                    "details": str(e),
                    "request_id": request_id
                }
            }
            return JSONResponse(status_code=500, content=error_content)

    async def __aenter__(self):
        """Async context manager entry"""
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup clients"""
        await self.client.aclose()
        await self.streaming_client.aclose()

class OpenAIProxy(BaseAPIProxy):
    """Proxy for OpenAI API requests"""
    
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.base_url = settings.openai_base_url
        self.headers = settings.get_openai_headers()
        
        # Add fake domains for request spoofing
        self.real_api_host = "api.openai.com"
        self.openai_domains = [
            self.real_api_host,
            "api-inference.openai.com", 
            "api-beta.openai.com",
            "openai-api.argoapis.com",
            "open-api.ringcredible.com",
        ]
        
        # Rate limit retry settings
        self.max_retries = 3
        self.base_retry_delay = 1.0  # Initial delay in seconds
        
        # Token rate limiter
        self.token_limiter = TokenRateLimiter(tpm_limit=30000)  # 30k TPM limit
    
    async def forward_request(self, request: Request, path: str, request_id: str = None):
        """Forward request to OpenAI API"""
        # Generate request ID
        request_id = request_id or str(uuid.uuid4())
        
        # Remove leading v1/ if present, since base_url already includes /v1
        if path.startswith('v1/'):
            path = path[3:]
            
        # Always use the real OpenAI domain for reliability
        target_host = "api.openai.com"
        target_url = f"https://{target_host}/v1/{path.lstrip('/')}"
        self.logger.info(f"OpenAI request {request_id}: {request.method} {path} -> {target_url}")
        
        # Get request data
        method = request.method
        orig_headers = dict(request.headers)

        # Log debug information about auth header presence
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        if debug_mode:
            auth_header = orig_headers.get("Authorization", "")
            self.logger.debug(f"Authorization header: {auth_header}")
            self.logger.debug(f"Authorization header from settings: {self.headers.get('Authorization')}")

        # Pick a random real browser user agent
        browser_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0"
        ]
        
        # Extract cookies from request if present
        request_cookies = request.cookies
        if request_cookies:
            # Update the client's cookie jar with request cookies
            for name, value in request_cookies.items():
                self.client.cookies.set(name, value, domain=target_host)
                self.streaming_client.cookies.set(name, value, domain=target_host)

        # Create completely browser-like headers
        headers = {
            "Authorization": orig_headers.get("Authorization", self.headers.get("Authorization")),
            "Content-Type": "application/json",
            "User-Agent": random.choice(browser_agents),
            "Accept": orig_headers.get("accept", "application/json"),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://platform.openai.com/",
            "Origin": "https://platform.openai.com",
            "Host": target_host,
            "sec-fetch-site": "same-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "sec-ch-ua": '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
            "Access-Control-Allow-Private-Network": "true"
        }
        
        # For streaming requests, ensure proper headers
        if orig_headers.get("accept") == "text/event-stream":
            headers.update({
                "Accept": "text/event-stream",
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
                "Transfer-Encoding": "chunked"
            })
        
        # Handle organization correctly - get from request first, or use from settings
        client_org_id = orig_headers.get("OpenAI-Organization", "")
        if client_org_id:
            # If client provided org ID, use it
            headers["OpenAI-Organization"] = client_org_id
            self.logger.info(f"Using client-provided organization ID: {client_org_id}")
        elif self.settings.openai_org_id:
            # If settings has org ID, use it
            headers["OpenAI-Organization"] = self.settings.openai_org_id
            self.logger.info(f"Using configured organization ID: {self.settings.openai_org_id}")
        else:
            # Don't add org ID if not specified
            self.logger.info("No organization ID specified")
        
        # Add random request ID to simulate genuine traffic
        if random.random() > 0.5:  # 50% chance to include
            headers["X-Request-ID"] = str(uuid.uuid4())
            
        # Log outgoing headers for debugging
        self.logger.info(f"Outgoing headers to OpenAI: {headers}")

        # Use Authorization header from client if present, else from settings
        if not headers.get("Authorization"):
            self.logger.warning("No OpenAI API key provided in settings or request")
            error_content = {"error": {"message": "OpenAI API key not configured", "type": "api_key_error"}}
            error_json = json.dumps(error_content).encode('utf-8')
            return SafeJSONResponse(
                status_code=401,
                content=error_content,
                headers={"Content-Length": str(len(error_json))}
            )
        
        # Get body
        if method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
                if not body_bytes:
                    self.logger.warning(f"Empty request body for {method} request")
                    empty_obj = {}
                    self.request_logger.log_request(request_id, method, path, headers, empty_obj)
                    return SafeJSONResponse(
                        status_code=400,
                        content={"error": {"message": "Empty request body", "type": "invalid_request_error"}}
                    )

                # Parse the JSON
                try:
                    body = json.loads(body_bytes)
                    
                    # For chat completions, check token limits
                    if path in ["chat/completions", "completions"]:
                        # Calculate approximate token count
                        # For chat/completions, count tokens in messages
                        total_tokens = 0
                        if "messages" in body:
                            for msg in body["messages"]:
                                # Rough estimation: 1 token ≈ 4 characters
                                content = msg.get("content", "")
                                if isinstance(content, str):
                                    total_tokens += len(content) // 4
                        
                        # Add max_tokens if specified
                        max_tokens = body.get("max_tokens", 2000)  # default to 2000 if not specified
                        total_tokens += max_tokens
                        
                        # Check token limit
                        await self.token_limiter.check_token_limit(total_tokens)
                    
                    if debug_mode:
                        # Log the full body without redaction
                        body_json = json.dumps(body)
                        self.logger.debug(f"Request body {request_id}: {body_json}")
                    
                    # Log the request
                    self.request_logger.log_request(request_id, method, path, headers, body)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON in request body: {str(e)}")
                    return SafeJSONResponse(
                        status_code=400,
                        content={"error": {"message": f"Invalid JSON: {str(e)}", "type": "invalid_request_error"}}
                    )
            except Exception as e:
                self.logger.error(f"Error reading request body: {str(e)}")
                if debug_mode:
                    self.logger.debug(f"Request body error details: {type(e).__name__}: {str(e)}")
                return SafeJSONResponse(
                    status_code=400,
                    content={"error": {"message": f"Error processing request: {str(e)}", "type": "request_error"}}
                )
        else:
            body = {}
            self.request_logger.log_request(request_id, method, path, headers, body)
        
        # If in mock mode, return mock response
        if self.mock_mode:
            self.logger.info("Mock mode enabled, returning mock response")
            
            # For chat/completions and completions, handle streaming specially
            if path in ["chat/completions", "completions"] and body.get("stream", False) is True:
                    return await self._handle_mock_streaming_request(request_id)
                
            return SafeJSONResponse(content=self._get_mock_response(body))
            
        # Security checks
        try:
            self.security_filter.validate_request(body, path)
        except HTTPException as exc:
            self.logger.warning(f"Security violation: {exc.detail}")
            return SafeJSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": f"Security violation: {exc.detail}", "type": "security_filter_error"}}
            )
        
        # Handle streaming responses
        is_streaming = "stream" in body and body["stream"] is True
        if is_streaming:
            if debug_mode:
                self.logger.debug(f"Handling streaming request to {target_url}")
            return await self._handle_streaming_request(self.client, method, target_url, headers, body, request_id, self._log_response)
            
        # Regular API call - try with automatic retry for rate limits
        try:
            # Check if rate limit retry is enabled
            use_rate_limit_retry = True  # You can make this configurable
            
            if use_rate_limit_retry:
                response_or_error = await self._handle_rate_limit_retry(request, method, target_url, headers, body, request_id, path)
                
                # If we got a JSONResponse (error case), return it directly
                if isinstance(response_or_error, JSONResponse):
                    return response_or_error
                    
                # Otherwise, we got a valid response
                response = response_or_error
            else:
                # Original code for non-retry path
                async with httpx.AsyncClient(
                    timeout=60.0,
                    verify=True,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    response = await client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
            
            # Process the response
            status_code = response.status_code
            response_headers = dict(response.headers)
            
            if debug_mode:
                self.logger.debug(f"Response received: status={status_code}, headers={response_headers}")
                # Log response body in debug mode
                try:
                    response_body = response.json()
                    response_json = json.dumps(response_body)
                    self.logger.debug(f"Response body {request_id}: {response_json}")
                except Exception as e:
                    self.logger.debug(f"Could not log response body {request_id}: {str(e)}")
            
            # Extract cookies from response and update our cookie jar
            if "set-cookie" in response_headers:
                self.logger.debug("Found Set-Cookie header in response, updating cookie jar")
                self.client.cookies.extract_cookies(response)
                
                # Share cookies with streaming client for future requests
                for cookie in self.client.cookies.jar:
                    self.streaming_client.cookies.set(
                        cookie.name, 
                        cookie.value, 
                        domain=cookie.domain, 
                        path=cookie.path
                    )
            
            # Remove content-encoding to prevent decoding issues
            if "content-encoding" in response_headers:
                del response_headers["content-encoding"]
            
            # Pass through binary response by default
            try:
                response_body = response.json()
                if debug_mode:
                    self.logger.debug(f"Response body: {json.dumps(response_body)}")
                self.request_logger.log_response(request_id, status_code, response_headers, response_body)
                # Add CORS and private network headers
                response_headers.update({
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
                    "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Expose-Headers": "*"
                })
                return SafeJSONResponse(content=response_body, status_code=status_code, headers=response_headers)
            except Exception as json_error:
                # Just return the raw response content with the modified headers
                if debug_mode:
                    self.logger.debug(f"Non-JSON response, returning raw content: {str(json_error)}")
                self.request_logger.log_response(
                    request_id, 
                    status_code, 
                    response_headers, 
                    {"binary": True, "length": len(response.content)}
                )
                # Ensure Content-Length is set correctly
                response_headers["content-length"] = str(len(response.content))
                return Response(
                    content=response.content,
                    status_code=status_code, 
                    headers=response_headers,
                    media_type=response_headers.get("content-type", "application/json")
                )
        except Exception as e:
            self.logger.error(f"Error creating client or making request: {str(e)}")
            if debug_mode:
                self.logger.debug(f"Detailed error: {type(e).__name__}: {str(e)}")
                
            # Find and update the fallback HTTP client section in OpenAIProxy
            # Fallback to HTTP/1.1 if HTTP/2 fails
            try:
                if debug_mode:
                    self.logger.debug("Falling back to HTTP/1.1")
                
                # Use the same timeout as the first attempt
                timeout_seconds = 60.0 if debug_mode else 300.0
                
                async with httpx.AsyncClient(
                    timeout=timeout_seconds,
                    verify=True,
                    trust_env=True,
                    follow_redirects=True,
                    headers=headers,
                    cookies={},
                    http2=False,  # Fallback to HTTP/1.1
                ) as client:
                    if is_streaming:
                        return await self._handle_streaming_request(client, method, target_url, headers, body, request_id, self._log_response)
                    
                    if debug_mode:
                        self.logger.debug(f"Sending fallback request to: {target_url}")
                        
                    response = await client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
                    
                    # Get response data
                    status_code = response.status_code
                    response_headers = dict(response.headers)
                    
                    if debug_mode:
                        self.logger.debug(f"Fallback response received: status={status_code}")
                    
                    # Extract cookies from response and update our cookie jar
                    if "set-cookie" in response_headers:
                        self.logger.debug("Found Set-Cookie header in response, updating cookie jar")
                        self.client.cookies.extract_cookies(response)
                        
                        # Share cookies with streaming client for future requests
                        for cookie in self.client.cookies.jar:
                            self.streaming_client.cookies.set(
                                cookie.name, 
                                cookie.value, 
                                domain=cookie.domain, 
                                path=cookie.path
                            )
                    
                    # Remove content-encoding to prevent decoding issues
                    if "content-encoding" in response_headers:
                        del response_headers["content-encoding"]
                    
                    # Pass through binary response by default
                    try:
                        response_body = response.json()
                        self.request_logger.log_response(request_id, status_code, response_headers, response_body)
                        # Add CORS and private network headers
                        response_headers.update({
                            "Access-Control-Allow-Origin": "*",
                            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
                            "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
                            "Access-Control-Allow-Private-Network": "true",
                            "Access-Control-Expose-Headers": "*"
                        })
                        return SafeJSONResponse(content=response_body, status_code=status_code, headers=response_headers)
                    except Exception as json_error:
                        # Just return the raw response content with the modified headers
                        if debug_mode:
                            self.logger.debug(f"Non-JSON fallback response: {str(json_error)}")
                        self.request_logger.log_response(
                            request_id, 
                            status_code, 
                            response_headers, 
                            {"binary": True, "length": len(response.content)}
                        )
                        # Ensure Content-Length is set correctly
                        response_headers["content-length"] = str(len(response.content))
                        return Response(
                            content=response.content,
                            status_code=status_code, 
                            headers=response_headers,
                            media_type=response_headers.get("content-type", "application/json")
                        )
            except Exception as fallback_error:
                self.logger.error(f"Error in fallback HTTP/1.1 request: {str(fallback_error)}")
                if debug_mode:
                    self.logger.debug(f"Detailed fallback error: {type(fallback_error).__name__}: {str(fallback_error)}")
                error_content = {"error": {"message": f"Error communicating with OpenAI API: {str(fallback_error)}", "type": "proxy_error"}}
                error_json = json.dumps(error_content).encode('utf-8')
                return SafeJSONResponse(
                    status_code=500,
                    content=error_content,
                    headers={"Content-Length": str(len(error_json))}
                )
    
    def _get_mock_response(self, body):
        """Generate a mock response for testing"""
        messages = body.get("messages", [])
        user_message = "Hello"
        
        # Find the last user message
        for message in reversed(messages):
            if message.get("role") == "user":
                user_message = message.get("content", "Hello")
                break
        
        # Generate a simple response
        return {
            "id": "chatcmpl-mockresponse123",
            "object": "chat.completion",
            "created": 1620831688,
            "model": body.get("model", "gpt-4o-mini"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Hi! This is a mock response from the OpenAI Proxy."
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "total_tokens": 60
            }
        }

    def _get_mock_embedding_response(self, body):
        """Generate a mock embedding response for testing"""
        return {
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "embedding": [0.0023064255, -0.009327292, 0.015797398] + [0.0] * 1533,
                    "index": 0
                }
            ],
            "model": body.get("model", "text-embedding-ada-002"),
            "usage": {
                "prompt_tokens": 8,
                "total_tokens": 8
            }
        }
    
    async def _handle_mock_streaming_request(self, request_id):
        """Handle mock streaming responses"""
        self.logger.info(f"Generating mock streaming response for {request_id}")
        
        # Check if we're in debug mode
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        
        async def mock_stream_generator():
            # Create mock chunks
            chunks = [
                {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1694268190, "model": "gpt-3.5-turbo", "system_fingerprint": "fp_123", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]},
                {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1694268190, "model": "gpt-3.5-turbo", "system_fingerprint": "fp_123", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": None}]},
                {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1694268190, "model": "gpt-3.5-turbo", "system_fingerprint": "fp_123", "choices": [{"index": 0, "delta": {"content": " world"}, "finish_reason": None}]},
                {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1694268190, "model": "gpt-3.5-turbo", "system_fingerprint": "fp_123", "choices": [{"index": 0, "delta": {"content": "!"}, "finish_reason": None}]},
                {"id": "chatcmpl-123", "object": "chat.completion.chunk", "created": 1694268190, "model": "gpt-3.5-turbo", "system_fingerprint": "fp_123", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            ]
            
            # In debug mode, use fewer chunks to avoid hanging
            if debug_mode:
                chunks = chunks[:3]
            
            # Log that we're starting to send chunks
            self.logger.info(f"Sending {len(chunks)} mock stream chunks for {request_id}")
            
            # Stream each chunk with proper SSE format
            for i, chunk in enumerate(chunks):
                # Serialize chunk to JSON
                chunk_json = json.dumps(chunk)
                
                # Format as SSE (Server-Sent Event)
                yield f"data: {chunk_json}\n\n".encode("utf-8")
                
                # In debug mode, don't add delays to avoid test timeouts
                if not debug_mode:
                    # Small delay to simulate real streaming
                    await asyncio.sleep(0.05)
                
                # Log progress in debug mode
                if debug_mode:
                    self.logger.debug(f"Sent mock chunk {i+1}/{len(chunks)}")
            
            # Send final [DONE] message
            yield b"data: [DONE]\n\n"
            
            self.logger.info(f"Completed mock streaming response for {request_id}")
        
        # Setup headers for streaming response
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
            # Add CORS headers
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
        }
        
        return StreamingResponse(
            mock_stream_generator(),
            media_type="text/event-stream",
            headers=headers
        )

    async def _log_response(self, response, request_id, is_streaming=False):
        """Log response details including rate limits and errors"""
        status_code = response.status_code
        response_headers = dict(response.headers)
        
        # Log rate limit headers if present
        rate_limit_headers = {k: v for k, v in response_headers.items() if 'ratelimit' in k.lower()}
        if rate_limit_headers:
            self.logger.debug(f"Rate limit info for {request_id}: {json.dumps(rate_limit_headers, indent=2)}")
        
        # Log error response body if status is not 200
        if status_code != 200:
            try:
                error_body = await response.json()
                self.logger.debug(f"Error response body for {request_id}: {json.dumps(error_body, indent=2)}")
                
                # For rate limit errors, log at error level
                if status_code == 429:
                    self.logger.error(f"Rate limit exceeded for {request_id}: {json.dumps(error_body, indent=2)}")
                    
                    # Look for specific rate limit info in the error message
                    if isinstance(error_body, dict) and 'error' in error_body:
                        error_message = error_body['error'].get('message', '')
                        self.logger.error(f"Rate limit reason: {error_message}")
                        
                        # Log suggestions based on error message
                        if 'tokens per min' in error_message.lower():
                            self.logger.error("Consider waiting or implementing token rate limiting")
                        elif 'requests per min' in error_message.lower():
                            self.logger.error("Consider waiting or implementing request rate limiting")
                        elif 'organization' in error_message.lower() and 'quota' in error_message.lower():
                            self.logger.error("Organization quota exceeded. Consider upgrading your plan.")
                
            except Exception as e:
                self.logger.debug(f"Could not parse error response body for {request_id}: {str(e)}")
        
        return status_code, response_headers

    async def _handle_rate_limit_retry(self, request, method, target_url, headers, body, request_id, path):
        """Handle rate-limited requests with exponential backoff retries"""
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        retries = 0
        
        while retries < self.max_retries:
            try:
                # Make the request
                async with httpx.AsyncClient(
                    timeout=60.0,
                    verify=True,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    self.logger.info(f"Attempting request {request_id} (attempt {retries+1}/{self.max_retries})")
                    response = await client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
                    
                    # If not rate limited, return the response
                    if response.status_code != 429:
                        return response
                    
                    # Extract rate limit reset time if available
                    reset_time = None
                    for header_name in response.headers:
                        if 'x-ratelimit-reset' in header_name.lower():
                            try:
                                reset_time = float(response.headers[header_name])
                                break
                            except (ValueError, TypeError):
                                pass
                    
                    # Calculate backoff delay
                    if reset_time and reset_time > 0:
                        # Use the reset time from the headers if available
                        delay = reset_time + 0.5  # Add a small buffer
                    else:
                        # Exponential backoff with jitter
                        delay = self.base_retry_delay * (2 ** retries) * (0.5 + random.random())
                        
                    if debug_mode:
                        self.logger.debug(f"Rate limited. Retrying in {delay:.2f} seconds (attempt {retries+1}/{self.max_retries})")
                    
                    # Wait before retrying
                    await asyncio.sleep(delay)
                    retries += 1
                    
            except Exception as e:
                self.logger.error(f"Error during retry attempt {retries+1}: {str(e)}")
                retries += 1
                # Use a simple backoff for connection errors
                await asyncio.sleep(self.base_retry_delay * (2 ** retries))
        
        # If we've exhausted retries, return the last error response
        self.logger.error(f"Rate limit persisted after {self.max_retries} retries for {request_id}")
        
        # Create a custom error response with detailed information
        error_response = {
            "error": {
                "message": f"Rate limit persisted after {self.max_retries} retries. Please check your API key's rate limits.",
                "type": "rate_limit_error",
                "request_id": request_id,
                "path": path,
                "code": 429
            }
        }
        
        return JSONResponse(
            status_code=429,
            content=error_response
        )

class AnthropicProxy(BaseAPIProxy):
    """Proxy for Anthropic API requests"""
    
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.base_url = settings.anthropic_base_url
        self.headers = settings.get_anthropic_headers()
        
        # Rate limit retry settings
        self.max_retries = 3  
        self.base_retry_delay = 1.0  # Initial delay in seconds
    
    async def forward_request(self, request: Request, path: str, request_id: str = None):
        """Forward request to Anthropic API"""
        # Generate request ID
        request_id = request_id or str(uuid.uuid4())
        
        # Get request method
        method = request.method
        
        # Build the target URL
        target_url = f"{self.base_url}/{path.lstrip('/')}"
        self.logger.info(f"Anthropic request {request_id}: {method} {path} -> {target_url}")
        
        # Extract headers from the original request
        orig_headers = dict(request.headers)
        
        # Check if we're in debug mode
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        
        # For OpenAI compatibility - intercept chat/completions
        if path == "chat/completions" or path == "v1/chat/completions":
            self.logger.info("Redirecting to Anthropic API: https://api.anthropic.com/v1/messages")
            # Client is using OpenAI format but targeting Anthropic
            target_url = "https://api.anthropic.com/v1/messages"
        
        # Log debug information about auth header presence
        if debug_mode:
            auth_header = orig_headers.get("x-api-key", "")
            self.logger.debug(f"x-api-key header present: {bool(auth_header)}")
            self.logger.debug(f"x-api-key from settings present: {bool(self.headers.get('x-api-key'))}")
        
        # Pick a random real browser user agent
        browser_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0"
        ]
        
        # Create completely browser-like headers
        headers = {
            "x-api-key": orig_headers.get("x-api-key", self.headers.get("x-api-key")),
            "anthropic-version": orig_headers.get("anthropic-version", "2023-06-01"),
            "Content-Type": "application/json",
            "User-Agent": random.choice(browser_agents),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://console.anthropic.com/",
            "Origin": "https://console.anthropic.com",
            "Host": "api.anthropic.com",
            "sec-fetch-site": "same-site",
            "sec-fetch-mode": "cors",
            "sec-fetch-dest": "empty",
            "sec-ch-ua": '"Google Chrome";v="124", "Chromium";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
            "Access-Control-Allow-Private-Network": "true"
        }
        
        # Use Accept header from the original request if present
        if "accept" in orig_headers:
            headers["Accept"] = orig_headers["accept"]
            
        # For streaming requests from clients, ensure proper headers
        if "accept" in orig_headers and orig_headers["accept"] == "text/event-stream":
            headers["Accept"] = "text/event-stream"
            
        # Add random request ID to simulate genuine traffic
        if random.random() > 0.5:  # 50% chance to include
            headers["X-Request-ID"] = str(uuid.uuid4())
        
        # Get body
        if method in ("POST", "PUT", "PATCH"):
            try:
                # Log the request reading to help diagnose issues
                if debug_mode:
                    self.logger.debug(f"Reading Anthropic request body for {request_id}")

                # Don't use retries - they may be causing issues
                # Instead, just read the body cleanly once with proper error handling
                body_bytes = await request.body()
                if not body_bytes:
                    self.logger.warning(f"Empty Anthropic request body for {method} request")
                    empty_obj = {}
                    self.request_logger.log_request(request_id, method, path, headers, empty_obj)
                    return SafeJSONResponse(
                        status_code=400,
                        content={"error": {"message": "Empty request body", "type": "invalid_request_error"}}
                    )

                # Parse the JSON
                try:
                    body = json.loads(body_bytes)
                    if debug_mode:
                        # Create a sanitized version for logging
                        sanitized_body = copy.deepcopy(body) if isinstance(body, dict) else body
                        # Redact sensitive fields
                        if isinstance(sanitized_body, dict):
                            if "api_key" in sanitized_body:
                                sanitized_body["api_key"] = "[REDACTED]"
                            # Redact any potential sensitive data in messages
                            if "messages" in sanitized_body:
                                for msg in sanitized_body["messages"]:
                                    if isinstance(msg, dict) and "content" in msg:
                                        msg["content"] = "[CONTENT REDACTED FOR PRIVACY]"
                        # Log the sanitized body
                        body_json = json.dumps(sanitized_body)
                        body_json = redact_api_key(body_json)
                        self.logger.debug(f"Anthropic request body {request_id}: {body_json}")
                    
                    # Log the request
                    self.request_logger.log_request(request_id, method, path, headers, body)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Invalid JSON in Anthropic request body: {str(e)}")
                    return SafeJSONResponse(
                        status_code=400,
                        content={"error": {"message": f"Invalid JSON: {str(e)}", "type": "invalid_request_error"}}
                    )
            except Exception as e:
                self.logger.error(f"Error reading Anthropic request body: {str(e)}")
                if debug_mode:
                    self.logger.debug(f"Anthropic request body error details: {type(e).__name__}: {str(e)}")
                return SafeJSONResponse(
                    status_code=400,
                    content={"error": {"message": f"Error processing request: {str(e)}", "type": "request_error"}}
                )
        else:
            body = {}
            self.request_logger.log_request(request_id, method, path, headers, body)
        
        # If in mock mode, return mock response
        if self.mock_mode:
            self.logger.info("Mock mode enabled, returning mock response")
            
            # For messages endpoints, handle streaming specially
            if (path in ["v1/messages", "messages"] or path in ["chat/completions", "v1/chat/completions"]) and body.get("stream", False) is True:
                return await self._handle_mock_streaming_request(request_id)
                
            return SafeJSONResponse(content=self._get_mock_response(body))
        
        # If we're processing an OpenAI format request but targeting Anthropic,
        # convert the request format
        if path == "chat/completions" or path == "v1/chat/completions":
            try:
                original_body = body.copy()
                body = self._convert_openai_to_anthropic(body)
                self.logger.info(f"Converted OpenAI format to Anthropic format: {body}")
            except Exception as e:
                self.logger.error(f"Error converting OpenAI format to Anthropic: {str(e)}")
                return SafeJSONResponse(
                    status_code=400,
                    content={"error": {"message": f"Error converting to Anthropic format: {str(e)}", "type": "format_error"}}
                )
                
        # Security checks
        try:
            self.security_filter.validate_request(body, path)
        except HTTPException as exc:
            self.logger.warning(f"Security violation: {exc.detail}")
            return SafeJSONResponse(
                status_code=exc.status_code,
                content={"error": {"message": f"Security violation: {exc.detail}", "type": "security_filter_error"}}
            )
        
        # Check if this is a streaming request
        is_streaming = body.get("stream", False) is True
        if is_streaming:
            if debug_mode:
                self.logger.debug(f"Handling Anthropic streaming request to {target_url}")
            return await self._handle_streaming_request(self.client, method, target_url, headers, body, request_id, self._log_response)
        
        # Regular API call - try with automatic retry for rate limits
        try:
            # Check if rate limit retry is enabled
            use_rate_limit_retry = True  # You can make this configurable
            
            if use_rate_limit_retry:
                response_or_error = await self._handle_rate_limit_retry(request, method, target_url, headers, body, request_id, path)
                
                # If we got a JSONResponse (error case), return it directly
                if isinstance(response_or_error, JSONResponse):
                    return response_or_error
                    
                # Otherwise, we got a valid response
                response = response_or_error
            else:
                # Original code for non-retry path
                async with httpx.AsyncClient(
                    timeout=60.0,
                    verify=True,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    response = await client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
            
            # Process the response
            status_code = response.status_code
            response_headers = dict(response.headers)
            
            if debug_mode:
                self.logger.debug(f"Response received: status={status_code}, headers={response_headers}")
                # Log response body in debug mode
                try:
                    response_body = response.json()
                    response_json = json.dumps(response_body)
                    self.logger.debug(f"Response body {request_id}: {response_json}")
                except Exception as e:
                    self.logger.debug(f"Could not log response body {request_id}: {str(e)}")
            
            # Extract cookies from response and update our cookie jar
            if "set-cookie" in response_headers:
                self.logger.debug("Found Set-Cookie header in response, updating cookie jar")
                self.client.cookies.extract_cookies(response)
                
                # Share cookies with streaming client for future requests
                for cookie in self.client.cookies.jar:
                    self.streaming_client.cookies.set(
                        cookie.name, 
                        cookie.value, 
                        domain=cookie.domain, 
                        path=cookie.path
                    )
            
            # Remove content-encoding to prevent decoding issues
            if "content-encoding" in response_headers:
                del response_headers["content-encoding"]
            
            # Pass through binary response by default
            try:
                response_body = response.json()
                if debug_mode:
                    self.logger.debug(f"Response body: {json.dumps(response_body)}")
                self.request_logger.log_response(request_id, status_code, response_headers, response_body)
                # Add CORS and private network headers
                response_headers.update({
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
                    "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
                    "Access-Control-Allow-Private-Network": "true",
                    "Access-Control-Expose-Headers": "*"
                })
                return SafeJSONResponse(content=response_body, status_code=status_code, headers=response_headers)
            except Exception as json_error:
                # Just return the raw response content with the modified headers
                if debug_mode:
                    self.logger.debug(f"Non-JSON response, returning raw content: {str(json_error)}")
                self.request_logger.log_response(
                    request_id, 
                    status_code, 
                    response_headers, 
                    {"binary": True, "length": len(response.content)}
                )
                # Ensure Content-Length is set correctly
                response_headers["content-length"] = str(len(response.content))
                return Response(
                    content=response.content,
                    status_code=status_code, 
                    headers=response_headers,
                    media_type=response_headers.get("content-type", "application/json")
                )
        except Exception as e:
            self.logger.error(f"Error creating client or making request: {str(e)}")
            if debug_mode:
                self.logger.debug(f"Detailed error: {type(e).__name__}: {str(e)}")
                
            # Find and update the fallback HTTP client section in OpenAIProxy
            # Fallback to HTTP/1.1 if HTTP/2 fails
            try:
                if debug_mode:
                    self.logger.debug("Falling back to HTTP/1.1")
                
                # Use the same timeout as the first attempt
                timeout_seconds = 60.0 if debug_mode else 300.0
                
                async with httpx.AsyncClient(
                    timeout=timeout_seconds,
                    verify=True,
                    trust_env=True,
                    follow_redirects=True,
                    headers=headers,
                    cookies={},
                    http2=False,  # Fallback to HTTP/1.1
                ) as client:
                    if is_streaming:
                        return await self._handle_streaming_request(client, method, target_url, headers, body, request_id, self._log_response)
                    
                    if debug_mode:
                        self.logger.debug(f"Sending fallback request to: {target_url}")
                        
                    response = await client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
                    
                    # Get response data
                    status_code = response.status_code
                    response_headers = dict(response.headers)
                    
                    if debug_mode:
                        self.logger.debug(f"Fallback response received: status={status_code}")
                    
                    # Extract cookies from response and update our cookie jar
                    if "set-cookie" in response_headers:
                        self.logger.debug("Found Set-Cookie header in response, updating cookie jar")
                        self.client.cookies.extract_cookies(response)
                        
                        # Share cookies with streaming client for future requests
                        for cookie in self.client.cookies.jar:
                            self.streaming_client.cookies.set(
                                cookie.name, 
                                cookie.value, 
                                domain=cookie.domain, 
                                path=cookie.path
                            )
                    
                    # Remove content-encoding to prevent decoding issues
                    if "content-encoding" in response_headers:
                        del response_headers["content-encoding"]
                    
                    # Pass through binary response by default
                    try:
                        response_body = response.json()
                        self.request_logger.log_response(request_id, status_code, response_headers, response_body)
                        # Add CORS and private network headers
                        response_headers.update({
                            "Access-Control-Allow-Origin": "*",
                            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
                            "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
                            "Access-Control-Allow-Private-Network": "true",
                            "Access-Control-Expose-Headers": "*"
                        })
                        return SafeJSONResponse(content=response_body, status_code=status_code, headers=response_headers)
                    except Exception as json_error:
                        # Just return the raw response content with the modified headers
                        if debug_mode:
                            self.logger.debug(f"Non-JSON fallback response: {str(json_error)}")
                        self.request_logger.log_response(
                            request_id, 
                            status_code, 
                            response_headers, 
                            {"binary": True, "length": len(response.content)}
                        )
                        # Ensure Content-Length is set correctly
                        response_headers["content-length"] = str(len(response.content))
                        return Response(
                            content=response.content,
                            status_code=status_code, 
                            headers=response_headers,
                            media_type=response_headers.get("content-type", "application/json")
                        )
            except Exception as fallback_error:
                self.logger.error(f"Error in fallback HTTP/1.1 request: {str(fallback_error)}")
                if debug_mode:
                    self.logger.debug(f"Detailed fallback error: {type(fallback_error).__name__}: {str(fallback_error)}")
                error_content = {"error": {"message": f"Error communicating with Anthropic API: {str(fallback_error)}", "type": "proxy_error"}}
                error_json = json.dumps(error_content).encode('utf-8')
                return SafeJSONResponse(
                    status_code=500,
                    content=error_content,
                    headers={"Content-Length": str(len(error_json))}
                )
    
    def _get_mock_response(self, body):
        """Generate a mock response for testing"""
        messages = body.get("messages", [])
        user_message = "Hello"
        
        # Find the last user message
        for message in reversed(messages):
            if message.get("role") == "user":
                user_message = message.get("content", "Hello")
                break
        
        # Generate a simple response in Anthropic format
        return {
            "id": "msg_mockanthropicresponse123",
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": "Hi! This is a mock response from the Anthropic API Firewall."
                }
            ],
            "model": body.get("model", "claude-3-7-sonnet-20250219"),
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 50,
                "output_tokens": 10
            }
        }
        
    async def _handle_mock_streaming_request(self, request_id):
        """Handle mock streaming responses for Anthropic API"""
        self.logger.info(f"Generating mock Anthropic streaming response for {request_id}")
        
        # Check if we're in debug mode
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        
        async def mock_stream_generator():
            # Create the chunks with proper line endings
            chunks = [
                {"type": "message_start", "message": {"id": "msg_mock123", "type": "message", "role": "assistant", "content": [], "model": "claude-3-opus-20240229", "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 0}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " world"}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "!"}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": null}},
                {"type": "message_stop"}
            ]
            
            # In debug mode, use fewer chunks to avoid hanging
            if debug_mode:
                chunks = chunks[:4]
            
            # Log that we're starting to send chunks
            self.logger.info(f"Sending {len(chunks)} mock Anthropic stream chunks for {request_id}")
            
            # Stream each chunk
            for i, chunk in enumerate(chunks):
                # Serialize and send
                chunk_data = json.dumps(chunk)
                yield f"data: {chunk_data}\n\n".encode("utf-8")
                
                # In debug mode, don't add delays to avoid test timeouts
                if not debug_mode:
                    # Small delay to simulate real streaming (shorter than OpenAI)
                    await asyncio.sleep(0.05)
                
                # Log progress in debug mode
                if debug_mode:
                    self.logger.debug(f"Sent Anthropic mock chunk {i+1}/{len(chunks)}")
            
            self.logger.info(f"Completed mock Anthropic streaming response for {request_id}")
        
        # Setup headers for streaming response
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, X-API-Key, Anthropic-Version",
        }
        
        return StreamingResponse(
            mock_stream_generator(),
            media_type="text/event-stream",
            headers=headers
        )

    async def _handle_rate_limit_retry(self, request, method, target_url, headers, body, request_id, path):
        """Handle rate-limited requests with exponential backoff retries"""
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        retries = 0
        
        while retries < self.max_retries:
            try:
                # Make the request
                async with httpx.AsyncClient(
                    timeout=60.0,
                    verify=True,
                    follow_redirects=True,
                    headers=headers,
                ) as client:
                    self.logger.info(f"Attempting request {request_id} (attempt {retries+1}/{self.max_retries})")
                    response = await client.request(
                        method=method,
                        url=target_url,
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
                    
                    # If not rate limited, return the response
                    if response.status_code != 429:
                        return response
                    
                    # Extract rate limit reset time if available
                    reset_time = None
                    for header_name in response.headers:
                        if 'x-ratelimit-reset' in header_name.lower():
                            try:
                                reset_time = float(response.headers[header_name])
                                break
                            except (ValueError, TypeError):
                                pass
                    
                    # Calculate backoff delay
                    if reset_time and reset_time > 0:
                        # Use the reset time from the headers if available
                        delay = reset_time + 0.5  # Add a small buffer
                    else:
                        # Exponential backoff with jitter
                        delay = self.base_retry_delay * (2 ** retries) * (0.5 + random.random())
                        
                    if debug_mode:
                        self.logger.debug(f"Rate limited. Retrying in {delay:.2f} seconds (attempt {retries+1}/{self.max_retries})")
                    
                    # Wait before retrying
                    await asyncio.sleep(delay)
                    retries += 1
                    
            except Exception as e:
                self.logger.error(f"Error during retry attempt {retries+1}: {str(e)}")
                retries += 1
                # Use a simple backoff for connection errors
                await asyncio.sleep(self.base_retry_delay * (2 ** retries))
        
        # If we've exhausted retries, return the last error response
        self.logger.error(f"Rate limit persisted after {self.max_retries} retries for {request_id}")
        
        # Create a custom error response with detailed information
        error_response = {
            "error": {
                "message": f"Rate limit persisted after {self.max_retries} retries. Please check your API key's rate limits.",
                "type": "rate_limit_error",
                "request_id": request_id,
                "path": path,
                "code": 429
            }
        }
        
        return JSONResponse(
            status_code=429,
            content=error_response
        ) 