import pytest
import time
from fastapi import HTTPException
from app.config import Settings, FilterConfig
from app.security import SecurityFilter, RateLimiter

def test_rate_limiter():
    """Test rate limiter functionality"""
    # Create rate limiter with a limit of 5 requests per minute
    limiter = RateLimiter(5)
    
    # First 5 requests should pass
    for _ in range(5):
        assert limiter.check_rate_limit() is True
    
    # 6th request should be blocked
    assert limiter.check_rate_limit() is False
    
    # Wait for window to expire
    time.sleep(1)
    
    # Manually clear requests to simulate time passing
    limiter.requests = []
    
    # Should be able to make requests again
    assert limiter.check_rate_limit() is True

def test_security_filter_model_validation():
    """Test model validation in security filter"""
    # Create settings with limited allowed models
    filter_config = FilterConfig(allowed_models=["gpt-3.5-turbo"])
    settings = Settings(filters=filter_config)
    
    # Create security filter
    security_filter = SecurityFilter(settings)
    
    # Test with allowed model
    assert security_filter._validate_openai_chat_completion({"model": "gpt-3.5-turbo"}) is True
    
    # Test with disallowed model
    with pytest.raises(HTTPException) as excinfo:
        security_filter._validate_openai_chat_completion({"model": "gpt-4"})
    assert excinfo.value.status_code == 403
    assert "Model gpt-4 is not allowed" in str(excinfo.value.detail)

def test_security_filter_token_validation():
    """Test token validation in security filter"""
    # Create settings with token limit
    filter_config = FilterConfig(max_tokens=100)
    settings = Settings(filters=filter_config)
    
    # Create security filter
    security_filter = SecurityFilter(settings)
    
    # Test with allowed token count
    assert security_filter._validate_openai_chat_completion({"max_tokens": 50}) is True
    
    # Test with excessive token count
    with pytest.raises(HTTPException) as excinfo:
        security_filter._validate_openai_chat_completion({"max_tokens": 150})
    assert excinfo.value.status_code == 403
    assert "Max tokens 150 exceeds limit of 100" in str(excinfo.value.detail)

def test_security_filter_blocked_content():
    """Test blocked content validation in security filter"""
    # Create settings with blocked prompts
    filter_config = FilterConfig(blocked_prompts=["forbidden"])
    settings = Settings(filters=filter_config)
    
    # Create security filter
    security_filter = SecurityFilter(settings)
    
    # Test with allowed content
    assert security_filter._validate_openai_chat_completion({"messages": [{"role": "user", "content": "Hello world"}]}) is True
    
    # Test with blocked content
    with pytest.raises(HTTPException) as excinfo:
        security_filter._validate_openai_chat_completion({"messages": [{"role": "user", "content": "This is forbidden"}]})
    assert excinfo.value.status_code == 403
    assert "The prompt contains prohibited content" in str(excinfo.value.detail)

def test_security_filter_disabled():
    """Test disabled security filter"""
    # Create settings with disabled filters
    filter_config = FilterConfig(enabled=False, blocked_prompts=["forbidden"])
    settings = Settings(filters=filter_config)
    
    # Create security filter
    security_filter = SecurityFilter(settings)
    
    # All validations should pass when filter is disabled
    assert security_filter.validate_request({"messages": [{"role": "user", "content": "This is forbidden content"}]}, "chat/completions") is True 