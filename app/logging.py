import logging
import os
import sys
import json
import re
from datetime import datetime
import copy

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

def redact_api_key(text):
    """No longer redacts API keys - returns text as is"""
    return text

class RequestResponseLogger:
    """Logger for API requests and responses"""
    
    def __init__(self, logger):
        self.logger = logger
    
    def log_request(self, request_id, method, path, headers, body=None):
        """Log API request"""
        try:
            log_data = {
                "timestamp": datetime.now().isoformat(),
                "request_id": request_id,
                "method": method,
                "path": path,
                "headers": headers,
                "body": body
            }
            
            # Convert to JSON with error handling
            try:
                log_message = json.dumps(log_data)
                self.logger.info(f"API Request {request_id}: {method} {path}")
                
                # Log details only in debug mode
                if os.environ.get("LOG_LEVEL", "").upper() == "DEBUG":
                    self.logger.debug(f"API Request details {request_id}: {log_message}")
            except Exception as e:
                # Fallback logging if JSON conversion fails
                self.logger.info(f"API Request {request_id}: {method} {path} (Error logging full details: {str(e)})")
        except Exception as log_error:
            # Absolute fallback for any error during logging
            self.logger.error(f"Error logging request {request_id}: {str(log_error)}")
    
    def log_response(self, request_id, status_code, headers, body=None):
        """Log API response"""
        try:
            log_data = {
                "timestamp": datetime.now().isoformat(),
                "request_id": request_id,
                "status_code": status_code
            }
            
            # Only add headers if they are valid
            if headers and isinstance(headers, dict):
                try:
                    log_data["headers"] = self._sanitize_headers(headers)
                except Exception as e:
                    log_data["headers"] = {"error": f"Failed to sanitize headers: {str(e)}"}
            
            # Only log body if it's not None
            if body is not None:
                try:
                    # Handle special cases for streaming and binary responses
                    if isinstance(body, dict) and "streaming" in body and body["streaming"] is True:
                        log_data["body"] = {"streaming": True, "content": "[STREAMING CONTENT]"}
                    elif isinstance(body, dict) and "binary" in body and body["binary"] is True:
                        log_data["body"] = {"binary": True, "length": body.get("length", "unknown")}
                    else:
                        # Sanitize sensitive information
                        sanitized_body = self._sanitize_body(body)
                        log_data["body"] = sanitized_body
                except Exception as e:
                    log_data["body"] = {"error": f"Failed to sanitize body: {str(e)}"}
            
            # Convert to JSON with error handling
            try:
                log_message = json.dumps(log_data)
                # Final redaction pass on the entire message
                log_message = redact_api_key(log_message)
                self.logger.info(f"API Response {request_id}: Status {status_code}")
                
                # Log details only in debug mode
                if os.environ.get("LOG_LEVEL", "").upper() == "DEBUG":
                    self.logger.debug(f"API Response details {request_id}: {log_message}")
            except Exception as e:
                # Fallback logging if JSON conversion fails
                self.logger.info(f"API Response {request_id}: Status {status_code} (Error logging full details: {str(e)})")
        except Exception as log_error:
            # Absolute fallback for any error during logging
            self.logger.error(f"Error logging response {request_id}: {str(log_error)}")
    
    def log_error(self, request_id, error_message, error_type=None):
        """Log API error"""
        # Redact any API keys that might be in error messages
        error_message = redact_api_key(error_message)
        
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "error_message": error_message,
            "error_type": error_type
        }
        
        log_message = json.dumps(log_data)
        self.logger.error(f"API Error {request_id}: {error_message}")
    
    def _sanitize_headers(self, headers):
        """No longer sanitizes headers - returns them as is"""
        return headers
    
    def _sanitize_body(self, body):
        """No longer sanitizes body - returns it as is"""
        return body 