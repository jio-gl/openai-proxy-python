import re
import time
import logging
from fastapi import HTTPException
from typing import Dict, Any, List

from app.config import Settings

class RateLimiter:
    """Rate limiter for API requests"""
    
    def __init__(self, limit: int):
        self.limit = limit  # requests per minute
        self.window_size = 60  # seconds
        self.requests = []
        self.logger = logging.getLogger("api-firewall")
    
    def check_rate_limit(self) -> bool:
        """Check if request is within rate limit"""
        current_time = time.time()
        
        # Remove old requests
        self.requests = [t for t in self.requests if current_time - t < self.window_size]
        
        # Check if we've hit the limit
        if len(self.requests) >= self.limit:
            self.logger.warning(f"Rate limit exceeded: {len(self.requests)} requests in the last minute")
            return False
        
        # Add current request
        self.requests.append(current_time)
        return True

class SecurityFilter:
    """Security filter for AI API requests"""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.logger = logging.getLogger("api-firewall")
        self.rate_limiter = RateLimiter(settings.filters.rate_limit)
    
    def validate_request(self, body: Dict[str, Any], path: str) -> bool:
        """Validate request against security filters"""
        if not self.settings.filters.enabled:
            return True
            
        # Check rate limit
        if not self.rate_limiter.check_rate_limit():
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        # Check for OpenAI chat completions
        if "chat/completions" in path:
            return self._validate_openai_chat_completion(body)
        
        # Check for OpenAI completions
        if "completions" in path and "chat" not in path:
            return self._validate_openai_completion(body)
            
        # Check for OpenAI embeddings
        if "embeddings" in path:
            return self._validate_openai_embedding(body)
        
        # Check for Anthropic messages endpoint
        if "messages" in path:
            return self._validate_anthropic_message(body)
            
        # Allow other endpoints by default
        return True
    
    def _validate_openai_chat_completion(self, body: Dict[str, Any]) -> bool:
        """Validate OpenAI chat completion request"""
        # Check model
        model = body.get("model", "")
        if model and model not in self.settings.filters.allowed_models:
            self.logger.warning(f"Blocked request with disallowed model: {model}")
            raise HTTPException(status_code=403, detail=f"Model {model} is not allowed")
        
        # Check max tokens
        max_tokens = body.get("max_tokens", 0)
        if max_tokens and max_tokens > self.settings.filters.max_tokens:
            self.logger.warning(f"Blocked request with excessive tokens: {max_tokens}")
            raise HTTPException(status_code=403, detail=f"Max tokens {max_tokens} exceeds limit of {self.settings.filters.max_tokens}")
        
        # Check for blocked prompts
        messages = body.get("messages", [])
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str) and self._contains_blocked_content(content):
                self.logger.warning("Blocked request with prohibited content")
                raise HTTPException(status_code=403, detail="The prompt contains prohibited content")
            elif isinstance(content, list):  # Handle OpenAI's multimodal inputs
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text = item.get("text", "")
                        if text and self._contains_blocked_content(text):
                            self.logger.warning("Blocked request with prohibited content")
                            raise HTTPException(status_code=403, detail="The prompt contains prohibited content")
        
        return True
    
    def _validate_openai_completion(self, body: Dict[str, Any]) -> bool:
        """Validate OpenAI completion request"""
        # Check model
        model = body.get("model", "")
        if model and model not in self.settings.filters.allowed_models:
            self.logger.warning(f"Blocked request with disallowed model: {model}")
            raise HTTPException(status_code=403, detail=f"Model {model} is not allowed")
        
        # Check max tokens
        max_tokens = body.get("max_tokens", 0)
        if max_tokens and max_tokens > self.settings.filters.max_tokens:
            self.logger.warning(f"Blocked request with excessive tokens: {max_tokens}")
            raise HTTPException(status_code=403, detail=f"Max tokens {max_tokens} exceeds limit of {self.settings.filters.max_tokens}")
        
        # Check for blocked prompts
        prompt = body.get("prompt", "")
        if prompt and self._contains_blocked_content(prompt):
            self.logger.warning("Blocked request with prohibited content")
            raise HTTPException(status_code=403, detail="The prompt contains prohibited content")
        
        return True
    
    def _validate_openai_embedding(self, body: Dict[str, Any]) -> bool:
        """Validate OpenAI embedding request"""
        # Check model
        model = body.get("model", "")
        if model and model not in self.settings.filters.allowed_models:
            self.logger.warning(f"Blocked request with disallowed model: {model}")
            raise HTTPException(status_code=403, detail=f"Model {model} is not allowed")
        
        return True
    
    def _validate_anthropic_message(self, body: Dict[str, Any]) -> bool:
        """Validate Anthropic message request"""
        # Check model
        model = body.get("model", "")
        if model and model not in self.settings.filters.allowed_models:
            self.logger.warning(f"Blocked request with disallowed model: {model}")
            raise HTTPException(status_code=403, detail=f"Model {model} is not allowed")
        
        # Check max tokens
        max_tokens = body.get("max_tokens", 0)
        if max_tokens and max_tokens > self.settings.filters.max_tokens:
            self.logger.warning(f"Blocked request with excessive tokens: {max_tokens}")
            raise HTTPException(status_code=403, detail=f"Max tokens {max_tokens} exceeds limit of {self.settings.filters.max_tokens}")
        
        # Check for blocked prompts in messages
        messages = body.get("messages", [])
        for message in messages:
            # Handle string content
            content = message.get("content", "")
            if isinstance(content, str) and self._contains_blocked_content(content):
                self.logger.warning("Blocked request with prohibited content")
                raise HTTPException(status_code=403, detail="The prompt contains prohibited content")
            # Handle content blocks (Anthropic format)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text and self._contains_blocked_content(text):
                            self.logger.warning("Blocked request with prohibited content")
                            raise HTTPException(status_code=403, detail="The prompt contains prohibited content")
        
        # Check for blocked content in system prompt
        system = body.get("system", "")
        if system and self._contains_blocked_content(system):
            self.logger.warning("Blocked request with prohibited content in system prompt")
            raise HTTPException(status_code=403, detail="The system prompt contains prohibited content")
        
        return True
    
    def _contains_blocked_content(self, text: str) -> bool:
        """Check if text contains blocked content"""
        for blocked_pattern in self.settings.filters.blocked_prompts:
            if re.search(blocked_pattern, text, re.IGNORECASE):
                return True
        return False 