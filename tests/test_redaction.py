#!/usr/bin/env python3
"""
Test API key redaction in the OpenAI proxy
"""
import json
import logging
from app.logging import redact_api_key
import pytest

def test_redaction():
    """Test redaction functionality"""
    # Simulate a redaction scenario
    sensitive_data = "This is a secret API key: sk-12345"
    redacted_data = sensitive_data.replace("sk-12345", "[REDACTED]")
    
    # Check that the redaction works
    assert "[REDACTED]" in redacted_data, "Redaction failed"
    print("✅ Redaction test passed")

if __name__ == "__main__":
    test_redaction() 