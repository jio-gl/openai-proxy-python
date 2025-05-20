# OpenAI Proxy

A secure proxy for OpenAI and Anthropic APIs that provides:
- Request/response logging
- Configurable security filters
- Rate limiting
- Monitoring capabilities

## Installation

### Standard Installation

1. Clone the repository:
```bash
git clone https://github.com/jio-gl/openai-proxy.git
cd openai-proxy
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file with your configuration:
```bash
cp .env-example .env
# Edit the .env file with your settings
```

### Docker Installation

1. Clone the repository:
```bash
git clone https://github.com/jio-gl/openai-proxy.git
cd openai-proxy
```

2. Create a `.env` file with your configuration:
```bash
cp .env-example .env
# Edit the .env file with your settings
```

3. Build and run with Docker Compose:
```bash
docker-compose up -d
```

## Configuration

The `.env` file supports the following settings:

```
# OpenAI API key
OPENAI_API_KEY=your_openai_api_key_here

# Anthropic API key
ANTHROPIC_API_KEY=your_anthropic_api_key_here
ANTHROPIC_VERSION=2023-06-01

# Logging configuration
LOG_LEVEL=INFO
LOG_FILE=logs/api-firewall.log

# Filter configuration
# Set to "false" to disable security filters
FILTERS_ENABLED=true

# Maximum tokens allowed in a request
FILTERS_MAX_TOKENS=8192

# Comma-separated list of allowed models
FILTERS_ALLOWED_MODELS=gpt-3.5-turbo,gpt-4,gpt-4-turbo,gpt-4o-mini,text-embedding-ada-002,claude-3-opus-20240229,claude-3-sonnet-20240229,claude-3-haiku-20240307,claude-3-5-sonnet-20240620

# Rate limit (requests per minute)
FILTERS_RATE_LIMIT=100
```

## Usage

### Standard Usage

Start the server:
```bash
python run.py
```

Or using uvicorn directly:
```bash
uvicorn app.main:app --reload --port 8000
```

### Docker Usage

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

Use the proxy by replacing the API base URLs with your local server:

For OpenAI API:
```
http://localhost:8000/v1/
```

For Anthropic API:
```
http://localhost:8000/anthropic/
```

For example, if you're using the OpenAI Python client:
```python
import openai

openai.api_key = "your_api_key"
openai.base_url = "http://localhost:8000/v1/"

response = openai.chat.completions.create(
    model="gpt-3.5-turbo",
    messages=[{"role": "user", "content": "Hello world"}]
)
print(response)
```

For Anthropic's Claude using the Python SDK:
```python
from anthropic import Anthropic

client = Anthropic(
    api_key="your_anthropic_api_key",  
    base_url="http://localhost:8000/anthropic"
)

response = client.messages.create(
    model="claude-3-sonnet-20240229",
    max_tokens=100,
    messages=[
        {"role": "user", "content": "Hello world"}
    ]
)
print(response.content)
```

## Using with Cursor IDE

**Note: Integration with Cursor is currently a work in progress (WIP) as Cursor blocks local API calls to private networks.**

To use this proxy with Cursor IDE:

1. Make sure the proxy is running and accessible on a public URL (not localhost)
   - For local development, use ngrok or SSH tunneling (see `run_proxy_with_ngrok.sh`)
   - For production, deploy on a cloud server with a public domain

2. In Cursor settings:
   - Go to Settings > AI > API Endpoints
   - Set the OpenAI Base URL to your proxy's public URL + "/v1"
   - Example: `https://your-domain.com/v1` or `https://abcd1234.ngrok-free.app/v1`

3. Cursor should now route all OpenAI API requests through your proxy.

> **Important:** Cursor will reject connections to private network URLs (localhost/127.0.0.1).
> You must expose your proxy through a public URL using ngrok, SSH tunneling, or cloud hosting.

## Features

### Transparent Proxying

All endpoints for both OpenAI and Anthropic APIs are supported, including:

#### OpenAI Endpoints:
- `/v1/chat/completions`
- `/v1/completions`
- `/v1/embeddings`
- Any other OpenAI API endpoint

#### Anthropic Endpoints:
- `/anthropic/v1/messages`
- Other Anthropic API endpoints

### Security Filters

The proxy includes several security filters:
- **Model filtering**: Only allow specified models
- **Token limit**: Prevent excessive token usage
- **Content filtering**: Block requests with prohibited content
- **Rate limiting**: Prevent abuse with request rate limits

### Logging

Detailed request and response logging with privacy controls:
- All requests and responses are logged
- Sensitive information (API keys, auth tokens) is automatically redacted
- Logs can be directed to console or file
- Configurable log levels

## Development

### Running Tests

Run the tests with pytest:
```bash
pytest
```

For verbose output:
```bash
pytest -vv
```

#### Integration Tests

The project includes integration tests that use a real OpenAI API key to make actual API calls through the proxy. These tests verify that:
- Chat completions (both streaming and non-streaming) work correctly
- Embeddings can be generated successfully
- Security filters block invalid models
- Sensitive information is handled appropriately

To run the integration tests:

1. Ensure you have a valid OpenAI API key set in your environment:
```bash
export OPENAI_API_KEY="sk-your-api-key"
```

2. Run only the integration tests:
```bash
pytest tests/test_integration.py -v
```

Note: These tests will be skipped if no API key is available.

### Project Structure

- `app/` - Main application code
  - `main.py` - FastAPI application
  - `proxy.py` - API proxies (OpenAI and Anthropic)
  - `security.py` - Security filters
  - `logging.py` - Logging utilities
  - `config.py` - Configuration management
- `tests/` - Test suite
- `examples/` - Example scripts showing usage
- `logs/` - Log files
- `run.py` - Application entry point
- `Dockerfile` - Docker configuration
- `docker-compose.yml` - Docker Compose configuration

## License

Apache License 2.0

## Recent Improvements

### 0.2.0 (18th May 2025) - Public Release

- **Added**: Apache 2.0 License file
- **Added**: Improved setup for public networks via ngrok or SSH tunneling
- **Added**: Proper gitignore file for better repository management
- **Fixed**: Removed sensitive data from example files
- **Improved**: Documentation for direct deployment and cloud hosting options

### 0.1.0 (11th May 2025)

- **Fixed**: Resolved "Too little data for declared Content-Length" error by implementing proper content-length handling for all JSON responses.
- **Fixed**: Created SafeJSONResponse class to ensure consistent content-length headers for all API responses.
- **Changed**: Updated default port from 8088 to 8000 to match OpenAI and Anthropic APIs.
- **Improved**: Enhanced browser emulation headers to better bypass API restrictions.
- **Added**: Explicit OpenAI Organization ID support from environment variables. 
