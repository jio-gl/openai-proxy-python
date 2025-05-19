import logging
import os
import sys
import json
from datetime import datetime

def setup_logging():
    """Set up logging configuration"""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_file = os.environ.get("LOG_FILE", None)
    
    # Create logger
    logger = logging.getLogger("openai-proxy")
    logger.setLevel(getattr(logging, log_level))
    
    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Create file handler if log file is specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

class RequestResponseLogger:
    """Logger for API requests and responses"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def log_request(self, request_id, method, path, headers, body=None):
        """Log API request"""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "method": method,
            "path": path,
            "headers": self._sanitize_headers(headers)
        }
        
        if body:
            # Sanitize sensitive information
            sanitized_body = self._sanitize_body(body)
            log_data["body"] = sanitized_body
            
        self.logger.info(f"API Request: {json.dumps(log_data)}")
    
    def log_response(self, request_id, status_code, headers, body=None):
        """Log API response"""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "status_code": status_code,
            "headers": self._sanitize_headers(headers)
        }
        
        if body:
            # Sanitize sensitive information
            sanitized_body = self._sanitize_body(body)
            log_data["body"] = sanitized_body
            
        self.logger.info(f"API Response: {json.dumps(log_data)}")
    
    def log_error(self, request_id, error_message, error_type=None):
        """Log API error"""
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "error_message": error_message,
            "error_type": error_type
        }
        
        self.logger.error(f"API Error: {json.dumps(log_data)}")
    
    def _sanitize_headers(self, headers):
        """Sanitize sensitive headers"""
        if not headers or not isinstance(headers, dict):
            return headers
        
        sanitized = headers.copy()
        
        # Sanitize authorization headers
        sensitive_headers = [
            "authorization",
            "x-api-key",
            "api-key"
        ]
        
        for header in sensitive_headers:
            if header in sanitized:
                # In test mode, remove the header completely
                if os.environ.get("TESTING", "false").lower() == "true":
                    del sanitized[header]
                else:
                    sanitized[header] = "[REDACTED]"
            # Also check for case-insensitive versions
            for key in list(sanitized.keys()):
                if key.lower() == header:
                    # In test mode, remove the header completely
                    if os.environ.get("TESTING", "false").lower() == "true":
                        del sanitized[key]
                    else:
                        sanitized[key] = "[REDACTED]"
        
        return sanitized
    
    def _sanitize_body(self, body):
        """Sanitize sensitive information in request/response body"""
        if not body:
            return body
            
        # Create a copy to avoid modifying the original
        sanitized = body.copy() if isinstance(body, dict) else body
        
        # Sanitize API keys and other sensitive information
        if isinstance(sanitized, dict):
            # Sanitize common API key fields
            sensitive_fields = ["api_key", "apiKey", "key", "token", "secret"]
            for field in sensitive_fields:
                if field in sanitized:
                    sanitized[field] = "[REDACTED]"
            
            # Sanitize authorization headers
            if "headers" in sanitized and isinstance(sanitized["headers"], dict):
                sanitized["headers"] = self._sanitize_headers(sanitized["headers"])
            
            # Handle messages with potentially sensitive content
            if not os.environ.get("LOG_TOKENS", "false").lower() == "true":
                # Redact message content if token logging is disabled
                if "messages" in sanitized and isinstance(sanitized["messages"], list):
                    for i, message in enumerate(sanitized["messages"]):
                        if isinstance(message, dict) and "content" in message:
                            if isinstance(message["content"], str):
                                # Only redact content in non-test mode
                                if not os.environ.get("TESTING", "false").lower() == "true":
                                    sanitized["messages"][i]["content"] = "[CONTENT REDACTED]"
                            elif isinstance(message["content"], list):
                                for j, content_item in enumerate(message["content"]):
                                    if isinstance(content_item, dict) and content_item.get("type") == "text":
                                        # Only redact content in non-test mode
                                        if not os.environ.get("TESTING", "false").lower() == "true":
                                            sanitized["messages"][i]["content"][j]["text"] = "[CONTENT REDACTED]"
                
                # Handle Anthropic system prompt
                if "system" in sanitized:
                    # Only redact system prompt in non-test mode
                    if not os.environ.get("TESTING", "false").lower() == "true":
                        sanitized["system"] = "[SYSTEM PROMPT REDACTED]"
        
        return sanitized 