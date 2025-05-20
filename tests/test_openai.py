import requests
import json
import os
import pytest
import socket

# Firewall proxy URL (local server)
PROXY_URL = "http://localhost:8000"

def is_server_running(host="localhost", port=8000):
    """Check if the server is running on the specified port"""
    try:
        # Create a socket and try to connect
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)  # Set a timeout of 1 second
            result = s.connect_ex((host, port))
            return result == 0  # 0 means success (port is open)
    except:
        return False

@pytest.mark.skipif(not is_server_running(), reason="Server not running on port 8000")
def test_openai_completion():
    """Test a simple chat completion request through the firewall"""
    url = f"{PROXY_URL}/v1/chat/completions"
    
    headers = {
        "Content-Type": "application/json",
        # We don't need to provide the API key to the firewall
        # as it uses the configured one from the server
    }
    
    data = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Say hello!"}
        ],
        "max_tokens": 50
    }
    
    print("Sending request to OpenAI through firewall...")
    # Use a Session to control decompression
    session = requests.Session()
    session.headers.update(headers)
    session.mount('http://', requests.adapters.HTTPAdapter())
    # Disable automatic content decompression
    response = session.post(url, json=data, stream=False)
    
    print(f"Status code: {response.status_code}")
    assert response.status_code in (200, 401, 403, 429), f"Unexpected status code: {response.status_code}"
    
    if response.status_code == 200:
        try:
            resp_json = response.json()
            print("\nResponse:")
            print(json.dumps(resp_json, indent=2))
            assert "choices" in resp_json, "Missing 'choices' in response"
        except Exception as e:
            print(f"\nCouldn't parse JSON: {str(e)}")
            print(response.text[:500])  # Print just the first 500 chars
            pytest.fail("Failed to parse JSON response")
    else:
        print("\nReceived error status code (expected for tests without valid API keys):")
        print(response.text[:200])

if __name__ == "__main__":
    if is_server_running():
        test_openai_completion()
    else:
        print("Server not running on port 8000. Start the server before running this test.") 