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

# Start with debug mode (dumps all request/response content to console)
python run.py --debug
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

### Command Line Parameters

The following command line parameters are available when starting the server:

- `--debug`: Enables debug mode with full request/response logging to the console. This is useful for debugging API issues and seeing exact request/response content.

Example usage:
```bash
python run.py --debug
```

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
LOG_LEVEL=INFO  # Set to DEBUG for more detailed logs
LOG_REQUESTS=true
LOG_RESPONSES=true
LOG_TOKENS=false  # Set to true to log full token content (similar to --debug flag)

# Security settings
ALLOWED_MODELS=gpt-3.5-turbo,gpt-4,text-embedding-ada-002
MAX_TOKENS=4000
FORBIDDEN_INSTRUCTIONS="system:*jailbreak*,system:*ignore previous instructions*"
```

### Debug Mode

Debug mode provides detailed request and response information, useful for troubleshooting. When enabled:

1. All request headers and bodies will be logged to the console
2. All response headers will be logged to the console
3. API keys and other sensitive information are automatically redacted for security

To enable debug mode:
- Use the `--debug` command line flag when starting the server
- OR set `LOG_LEVEL=DEBUG` in your `.env` file

Debug mode is designed to work seamlessly with the OpenAI API, allowing you to see exactly what is being sent and received without interfering with the request/response flow.

**Note**: While debug mode redacts sensitive information like API keys, exercise caution when sharing logs as they may contain prompt content or other potentially sensitive data.

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

### Debug Mode Issues

If you encounter issues with debug mode:

1. Make sure you're using the latest version of the proxy
2. Check that your environment does not have conflicting `LOG_LEVEL` settings
3. If streaming responses aren't working correctly in debug mode, try setting `LOG_LEVEL=INFO` in your `.env` file

### Connection Issues

If you cannot connect to the proxy:

1. Verify the server is running (`python run.py`)
2. Check if the port is already in use (`lsof -i :8000`)
3. Ensure your client is configured to use the correct URL
4. If using a custom port, update your client URL to match (e.g., `http://localhost:8000/v1`)

### Rate Limiting or Timeout Errors

If you receive rate limiting or timeout errors from OpenAI:

1. Check your OpenAI API usage dashboard for any account limitations
2. Verify your API key has sufficient quota remaining
3. Try increasing the timeout settings in the proxy (edit `app/proxy.py`)
4. Run the proxy with debug mode to see the exact error messages from OpenAI

## Docker Support

Run with Docker for easier deployment:

```bash
docker-compose up -d
```

## Recent Changes

### Version 1.2.0

- Completely redesigned debug mode for improved reliability
- Fixed issues with request body handling in middleware
- Added robust error handling throughout the codebase
- Added API key redaction to protect sensitive data in logs
- Added enhanced support for streaming responses in debug mode

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