#!/usr/bin/env python
"""
Run script for the OpenAI Proxy
"""
import uvicorn
import os
import argparse
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def main():
    """Main function to run the proxy server"""
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Run OpenAI Proxy server')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode with full request/response logging')
    parser.add_argument('--port', type=int, default=int(os.environ.get("PORT", 8000)), 
                        help='Port to run the server on (default: 8000)')
    args = parser.parse_args()
    
    # If debug mode is enabled, set environment variables for debugging
    if args.debug:
        os.environ["LOG_LEVEL"] = "DEBUG"
        # In DEBUG mode, we still redact sensitive tokens in logs for security
        print("Debug mode enabled: Full request/response logging activated")
    
    # Run server
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=args.port,
            reload=True,
            log_level=os.environ.get("LOG_LEVEL", "info").lower()
        )
    except Exception as e:
        print(f"Error starting server: {str(e)}")
        sys.exit(1)
    
    print(f"OpenAI Proxy is running on port {args.port}")

if __name__ == "__main__":
    main() 