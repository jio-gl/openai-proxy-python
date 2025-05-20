#!/usr/bin/env python
"""
Run script for the OpenAI Proxy
"""
import uvicorn
import os
import argparse
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Run OpenAI Proxy server')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode with full request/response logging')
    args = parser.parse_args()
    
    # If debug mode is enabled, set environment variables for debugging
    if args.debug:
        os.environ["LOG_LEVEL"] = "DEBUG"
        os.environ["LOG_TOKENS"] = "true"
        print("Debug mode enabled: Full request/response logging activated")
    
    # Get port from environment or use default
    port = int(os.environ.get("PORT", 8000))
    
    # Run server
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level=os.environ.get("LOG_LEVEL", "info").lower()
    )
    
    print(f"OpenAI Proxy is running on port {port}") 