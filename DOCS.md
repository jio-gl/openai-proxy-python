# OpenAI Proxy Documentation

## Overview

OpenAI Proxy is a secure proxy server that sits between your application and the OpenAI API. It provides:

1. **Enhanced Privacy**: Masks your local network identity when accessing OpenAI APIs
2. **Request/Response Logging**: Logs all API interactions for analysis
3. **Security Filtering**: Validates API requests against security rules
4. **Cost Control**: Monitors and potentially limits API usage

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/jio-gl/openai-proxy.git
cd openai-proxy

# Install dependencies
pip install -r requirements.txt

# Copy and edit the example environment file
cp .env-example .env
# Edit .env with your OpenAI API key and settings
```

### Running the Server

```bash
# Start the server
python run.py
```

By default, the server will run on `http://localhost:8000`.

### Using with API Clients

Configure your OpenAI API client to use the proxy URL:

```
http://localhost:8000/v1
```

For example, with the OpenAI Python library:

```python
import openai

# Set the API base URL to your proxy
openai.api_base = "http://localhost:8000/v1"
openai.api_key = "your-api-key"

# Make API calls normally
response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[
        {"role": "user", "content": "Hello, how are you?"}
    ]
)
```

## Features

### Private Network Masking

The firewall adds a layer of protection by masking your local network identity when accessing OpenAI APIs, thereby working around the "Access to private networks is forbidden" restriction. This is particularly useful for:

- Local development environments
- Testing applications behind firewalls
- Environments where direct API access is problematic

### Request/Response Logging

All API interactions are logged to `logs/api-firewall.log` for analysis, including:

- Request IDs, timestamps, and methods
- Request headers and body (with sensitive information redacted)
- Response status codes and body
- Error messages and types

### Advanced Browser Emulation

The proxy employs several techniques to make requests appear as if they're coming from a legitimate browser:

- Proper headers, including User-Agent rotation
- Browser-like security headers (sec-fetch-*, sec-ch-ua-*)
- TLS/SNI handling to ensure proper domain identification
- Random request IDs and parameters to avoid pattern detection

## Configuration Options

### Environment Variables

Edit the `.env` file to configure the proxy:

```
# OpenAI API settings
OPENAI_API_KEY=your-openai-api-key
OPENAI_API_BASE_URL=https://api.openai.com/v1
OPENAI_ORG_ID=your-organization-id  # Optional: Your OpenAI organization ID

# Anthropic API settings (optional)
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_API_BASE_URL=https://api.anthropic.com

# Logging settings
LOG_REQUESTS=true
LOG_RESPONSES=true

# Security settings
ALLOWED_MODELS=gpt-3.5-turbo,gpt-4,text-embedding-ada-002
MAX_TOKENS=4000
FORBIDDEN_INSTRUCTIONS="system:*jailbreak*,system:*ignore previous instructions*"
```

## Organization ID Handling

The proxy passes your Organization ID in the following order of precedence:

1. Uses the Organization ID from your request headers (if provided)
2. Falls back to the Organization ID from your environment variables (if set)
3. Omits the Organization ID header if neither is available

This ensures that your API key and Organization ID are always correctly matched, preventing "mismatched_organization" errors.

## Security Filtering

The proxy can filter requests based on:

- Allowed models
- Maximum token limits
- Forbidden instructions in prompts
- Request rate limiting

Edit the `app/security.py` file to customize security rules.

## Troubleshooting

### API Key and Organization Mismatches

If you see "OpenAI-Organization header should match organization for API key" errors:

1. Set your correct organization ID in the `.env` file as `OPENAI_ORG_ID`
2. Ensure you're not setting a different organization ID in your client
3. Restart the proxy server

### Connection Issues

If you cannot connect to the proxy:

1. Verify the server is running (`python run.py`)
2. Check if the port is already in use (`lsof -i :8000`)
3. Ensure your client is configured to use the correct URL

## Docker Support

Run with Docker for easier deployment:

```bash
docker-compose up -d
```

## Recent Changes

### Version 1.1.0

- Fixed "Content-Length" discrepancy errors causing HTTP 500 responses
- Added proper Organization ID handling to prevent API key/org mismatches
- Changed default port from 8088 to 8000 to match OpenAI and Anthropic APIs
- Enhanced browser fingerprinting for more reliable access
- Fixed compression handling issues with Brotli responses

## Architecture

The proxy is built with FastAPI and uses:

- `httpx` for making HTTP requests
- `uvicorn` as the ASGI server
- Custom middleware for request/response handling

## License

[Apache License 2.0](LICENSE) 