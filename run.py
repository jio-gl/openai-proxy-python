#!/usr/bin/env python
"""
Run script for the OpenAI Proxy
"""
import uvicorn
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

if __name__ == "__main__":
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