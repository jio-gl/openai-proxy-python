import json
import httpx
import logging
import uuid
import os
import asyncio
import random
from fastapi import Request, Response, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from starlette.background import BackgroundTask

from app.config import Settings
from app.logging import RequestResponseLogger
from app.security import SecurityFilter

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
        self.client = httpx.AsyncClient(timeout=60.0)
        # Check if we're in mock mode
        self.mock_mode = os.environ.get("MOCK_RESPONSES", "false").lower() == "true"
    
    async def forward_request(self, request: Request, path: str):
        """Forward request to API"""
        raise NotImplementedError("Subclasses must implement this method")
    
    def _get_mock_response(self, body: dict):
        """Generate a mock response for testing"""
        raise NotImplementedError("Subclasses must implement this method")
    
    async def _handle_streaming_request(self, client, method, url, headers, body, request_id):
        """Handle streaming responses from API"""
        self.logger.info(f"Handling streaming request {request_id} to {url}")
        
        async def stream_generator():
            # Use a fresh client for streaming
            stream_client = httpx.AsyncClient(
                timeout=httpx.Timeout(300.0),
                verify=True
            )
            
            # Create a copy of headers that's safe to modify
            stream_headers = headers.copy()
            
            # Ensure any content-length header is removed for streaming requests
            if 'content-length' in stream_headers:
                del stream_headers['content-length']
            
            try:
                # Make the streaming request
                self.logger.info(f"Sending streaming request to: {url}")
                async with stream_client.stream(
                    method=method,
                    url=url,
                    headers=stream_headers,
                    json=body
                ) as response:
                    response_headers = dict(response.headers)
                    
                    # Remove content-length from response headers to prevent mismatch
                    if 'content-length' in response_headers:
                        del response_headers['content-length']
                    
                    self.request_logger.log_response(
                        request_id, 
                        response.status_code, 
                        response_headers, 
                        {"streaming": True}
                    )
                    
                    # Stream the bytes directly
                    async for chunk in response.aiter_bytes():
                        yield chunk
                        
            except Exception as e:
                self.logger.error(f"Error in streaming response: {str(e)}")
                # Return error message in SSE format
                error_msg = json.dumps({"error": {"message": str(e), "type": "stream_error"}})
                yield f"data: {error_msg}\n\n".encode("utf-8")
            
            finally:
                # Ensure the client is closed properly
                await stream_client.aclose()
        
        # Get response content type and essential headers for streaming
        response_headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, HEAD, PATCH",
            "Access-Control-Allow-Headers": "Content-Type, Authorization, OpenAI-Organization",
            "Access-Control-Allow-Private-Network": "true",
            "Access-Control-Expose-Headers": "*"
        }
        
        # Important: Do not set Content-Length for streaming responses
        # This is crucial to avoid the "Too much data for declared Content-Length" error
        
        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers=response_headers
        )

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
    
    async def forward_request(self, request: Request, path: str):
        """Forward request to OpenAI API"""
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Remove leading v1/ if present, since base_url already includes /v1
        if path.startswith('v1/'):
            path = path[3:]
            
        # Use a randomized approach for domains to avoid pattern detection
        # Sometimes we'll use direct URL, sometimes third-party domains
        
        # Always use the real OpenAI domain for reliability
        target_host = "api.openai.com"
        target_url = f"https://{target_host}/v1/{path.lstrip('/')}"
        self.logger.info(f"Target URL: {target_url}")
        
        # Get request data
        method = request.method
        orig_headers = dict(request.headers)

        # Log debug information about auth header presence
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        if debug_mode:
            auth_header = orig_headers.get("Authorization", "")
            self.logger.debug(f"Authorization header present: {bool(auth_header)}")
            self.logger.debug(f"Authorization header from settings present: {bool(self.headers.get('Authorization'))}")

        # Pick a random real browser user agent
        browser_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0"
        ]
        
        # Create completely browser-like headers
        headers = {
            "Authorization": orig_headers.get("Authorization", self.headers.get("Authorization")),
            "Content-Type": "application/json",
            "User-Agent": random.choice(browser_agents),
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
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
            
        # Use Accept header from the original request if present
        if "accept" in orig_headers:
            headers["Accept"] = orig_headers["accept"]
            
        # For streaming requests from clients, ensure proper headers
        if "accept" in orig_headers and orig_headers["accept"] == "text/event-stream":
            headers["Accept"] = "text/event-stream"
            
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
                # Log the request reading to help diagnose issues
                if debug_mode:
                    self.logger.debug(f"Attempting to read request body for {request_id}")
                
                # Get the request body
                body_bytes = await request.body()
                if debug_mode:
                    self.logger.debug(f"Successfully read request body: {len(body_bytes)} bytes")
                    
                # Parse the JSON
                body = json.loads(body_bytes)
                self.request_logger.log_request(request_id, method, path, headers, body)
            except Exception as e:
                self.logger.error(f"Error parsing request body: {str(e)}")
                if debug_mode:
                    self.logger.debug(f"Request body error details: {type(e).__name__}: {str(e)}")
                empty_body = {}
                self.request_logger.log_request(request_id, method, path, headers, empty_body)
                return SafeJSONResponse(
                    status_code=400,
                    content={"error": {"message": f"Invalid request body: {str(e)}", "type": "invalid_request_error"}}
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
            return await self._handle_streaming_request(self.client, method, target_url, headers, body, request_id)
            
        # Regular API call
        try:
            # Log the client creation attempt
            if debug_mode:
                self.logger.debug(f"Creating HTTP client for request to {target_url}")
                
            # Simplify the client configuration for reliability
            async with httpx.AsyncClient(
                timeout=300.0,  # 5 minute timeout
                verify=True,    # Use system certificates for verification
                follow_redirects=True,
                headers=headers,
            ) as client:
                # Handle regular responses - pass full URL directly
                self.logger.info(f"Sending request to: {target_url}")
                if debug_mode:
                    self.logger.debug(f"Request body to OpenAI: {json.dumps(body)}")
                    
                # Make the actual request
                response = await client.request(
                    method=method,
                    url=target_url,  # Use full target URL to ensure proper SNI
                    headers=headers,
                    json=body if method in ("POST", "PUT", "PATCH") else None,
                    params=request.query_params,
                )
                
                # Get response data
                status_code = response.status_code
                response_headers = dict(response.headers)
                
                if debug_mode:
                    self.logger.debug(f"Response received: status={status_code}, headers={response_headers}")
                
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
                
            # Fallback to HTTP/1.1 if HTTP/2 fails
            try:
                if debug_mode:
                    self.logger.debug("Falling back to HTTP/1.1")
                async with httpx.AsyncClient(
                    timeout=300.0,
                    verify=True,
                    trust_env=True,
                    follow_redirects=True,
                    headers=headers,
                    cookies={},
                    http2=False,  # Fallback to HTTP/1.1
                ) as client:
                    if is_streaming:
                        return await self._handle_streaming_request(client, method, target_url, headers, body, request_id)
                    
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
                    except:
                        # Just return the raw response content with the modified headers
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
        """Handle mock streaming responses for testing"""
        self.logger.info(f"Handling mock streaming request {request_id}")
        
        async def mock_stream_generator():
            # Create mock chunks
            chunks = [
                {
                    "id": "chatcmpl-mockstream123",
                    "object": "chat.completion.chunk",
                    "created": 1620831688,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant"
                            },
                            "finish_reason": None
                        }
                    ]
                },
                {
                    "id": "chatcmpl-mockstream123",
                    "object": "chat.completion.chunk",
                    "created": 1620831688,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": "Hi"
                            },
                            "finish_reason": None
                        }
                    ]
                },
                {
                    "id": "chatcmpl-mockstream123",
                    "object": "chat.completion.chunk",
                    "created": 1620831688,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "content": "!"
                            },
                            "finish_reason": None
                        }
                    ]
                },
                {
                    "id": "chatcmpl-mockstream123",
                    "object": "chat.completion.chunk",
                    "created": 1620831688,
                    "model": "gpt-4o-mini",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop"
                        }
                    ]
                }
            ]
            
            # Stream each chunk
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n".encode("utf-8")
                # Add a small delay between chunks for realism
                await asyncio.sleep(0.1)
            
            # End the stream
            yield "data: [DONE]\n\n".encode("utf-8")
        
        return StreamingResponse(
            mock_stream_generator(),
            media_type="text/event-stream"
        )

class AnthropicProxy(BaseAPIProxy):
    """Proxy for Anthropic API requests"""
    
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self.base_url = settings.anthropic_base_url
        self.headers = settings.get_anthropic_headers()
    
    async def forward_request(self, request: Request, path: str):
        """Forward request to Anthropic API"""
        # Generate request ID
        request_id = str(uuid.uuid4())
        
        # Get request method
        method = request.method
        
        # Check if we're in debug mode
        debug_mode = os.environ.get("LOG_LEVEL", "").upper() == "DEBUG"
        
        # Build target URL - Anthropic has no v1 in base URL unlike OpenAI
        target_url = f"{self.settings.anthropic_base_url}/{path.lstrip('/')}"
        
        # For OpenAI compatibility - intercept chat/completions
        if path == "chat/completions" or path == "v1/chat/completions":
            self.logger.info("Redirecting to Anthropic API: https://api.anthropic.com/v1/messages")
            # Client is using OpenAI format but targeting Anthropic
            target_url = "https://api.anthropic.com/v1/messages"
        
        # Get original headers
        orig_headers = dict(request.headers)
        
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
                    self.logger.debug(f"Attempting to read Anthropic request body for {request_id}")
                
                # Get the request body
                body_bytes = await request.body()
                if debug_mode:
                    self.logger.debug(f"Successfully read Anthropic request body: {len(body_bytes)} bytes")
                    
                # Parse the JSON
                body = json.loads(body_bytes)
                self.request_logger.log_request(request_id, method, path, headers, body)
            except Exception as e:
                self.logger.error(f"Error parsing request body: {str(e)}")
                if debug_mode:
                    self.logger.debug(f"Request body error details: {type(e).__name__}: {str(e)}")
                empty_body = {}
                self.request_logger.log_request(request_id, method, path, headers, empty_body)
                return SafeJSONResponse(
                    status_code=400,
                    content={"error": {"message": f"Invalid request body: {str(e)}", "type": "invalid_request_error"}}
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
            return await self._handle_streaming_request(self.client, method, target_url, headers, body, request_id)
        
        # Regular API call
        try:
            # Log the client creation attempt
            if debug_mode:
                self.logger.debug(f"Creating HTTP client for Anthropic request to {target_url}")
                
            # Simplify the client configuration for reliability
            async with httpx.AsyncClient(
                timeout=300.0,  # 5 minute timeout
                verify=True,    # Use system certificates for verification
                follow_redirects=True,
                headers=headers,
            ) as client:
                # Handle streaming responses
                if body and body.get("stream", False):
                    return await self._handle_streaming_request(client, method, target_url, headers, body, request_id)
                
                try:
                    # Handle regular responses - pass full URL directly
                    self.logger.info(f"Sending request to: {target_url}")
                    if debug_mode:
                        self.logger.debug(f"Request body to Anthropic: {json.dumps(body)}")
                        
                    # Make the actual request
                    response = await client.request(
                        method=method,
                        url=target_url,  # Use full target URL to ensure proper SNI
                        headers=headers,
                        json=body if method in ("POST", "PUT", "PATCH") else None,
                        params=request.query_params,
                    )
                    
                    # Get response data
                    status_code = response.status_code
                    response_headers = dict(response.headers)
                    
                    if debug_mode:
                        self.logger.debug(f"Anthropic response received: status={status_code}, headers={response_headers}")
                    
                    # Remove content-encoding to prevent decoding issues
                    if "content-encoding" in response_headers:
                        del response_headers["content-encoding"]
                    
                    # Pass through binary response by default
                    try:
                        response_body = response.json()
                        if debug_mode:
                            self.logger.debug(f"Anthropic response body: {json.dumps(response_body)}")
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
                            self.logger.debug(f"Non-JSON Anthropic response, returning raw content: {str(json_error)}")
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
                    self.logger.error(f"Error making request to Anthropic API: {str(e)}")
                    if debug_mode:
                        self.logger.debug(f"Detailed Anthropic error: {type(e).__name__}: {str(e)}")
                    error_content = {"error": {"message": f"Error communicating with Anthropic API: {str(e)}", "type": "proxy_error"}}
                    error_json = json.dumps(error_content).encode('utf-8')
                    return SafeJSONResponse(
                        status_code=500,
                        content=error_content,
                        headers={"Content-Length": str(len(error_json))}
                    )
        except Exception as e:
            self.logger.error(f"Error creating client or making request: {str(e)}")
            if debug_mode:
                self.logger.debug(f"Detailed error: {type(e).__name__}: {str(e)}")
                
            # Fallback to HTTP/1.1 if HTTP/2 fails
            try:
                if debug_mode:
                    self.logger.debug("Falling back to HTTP/1.1 for Anthropic")
                async with httpx.AsyncClient(
                    timeout=300.0,
                    verify=True,
                    trust_env=True,
                    follow_redirects=True,
                    headers=headers,
                    cookies={},
                    http2=False,  # Fallback to HTTP/1.1
                ) as client:
                    if body and body.get("stream", False):
                        return await self._handle_streaming_request(client, method, target_url, headers, body, request_id)
                    
                    if debug_mode:
                        self.logger.debug(f"Sending fallback request to Anthropic: {target_url}")
                        
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
                        self.logger.debug(f"Fallback Anthropic response received: status={status_code}")
                    
                    # Remove content-encoding to prevent decoding issues
                    if "content-encoding" in response_headers:
                        del response_headers["content-encoding"]
                    
                    # Pass through binary response by default
                    try:
                        response_body = response.json()
                        if debug_mode:
                            self.logger.debug(f"Fallback Anthropic response body: {json.dumps(response_body)}")
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
                            self.logger.debug(f"Non-JSON fallback Anthropic response: {str(json_error)}")
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
        """Handle mock streaming responses for testing Anthropic API"""
        self.logger.info(f"Handling mock Anthropic streaming request {request_id}")
        
        async def mock_stream_generator():
            # Create the chunks with proper line endings
            chunks = [
                {"type": "message_start", "message": {"id": "msg_mockanthropicstream123", "type": "message", "role": "assistant", "content": [], "model": "claude-3-sonnet-20240229", "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 10}}},
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "! This is a mock "}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "response from the Anthropic API Firewall."}},
                {"type": "content_block_stop", "index": 0},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None, "usage": {"output_tokens": 10}}},
                {"type": "message_stop"}
            ]
            
            # Yield each chunk properly formatted as a server-sent event with proper newlines
            for chunk in chunks:
                # Format the chunk as a proper server-sent event
                chunk_str = json.dumps(chunk)
                yield f"data: {chunk_str}\r\n\r\n".encode('utf-8')
                await asyncio.sleep(0.1)
            
            # End of the stream
            yield b"data: [DONE]\r\n\r\n"
        
        # Use proper content type for EventStream
        return StreamingResponse(
            mock_stream_generator(),
            media_type="text/event-stream"
        ) 