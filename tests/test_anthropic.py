import requests
import json
import os

# Firewall proxy URL (local server)
PROXY_URL = "http://localhost:8000"

def test_anthropic_completion():
    """Test a simple message completion request through the firewall"""
    # The correct endpoint for Anthropic's v1 messages
    url = f"{PROXY_URL}/anthropic/v1/messages"
    
    headers = {
        "Content-Type": "application/json",
        # We don't need to provide the API key to the firewall
        # as it uses the configured one from the server
    }
    
    data = {
        "model": "claude-3-sonnet-20240229",
        "messages": [
            {"role": "user", "content": "Say hello!"}
        ],
        "max_tokens": 50
    }
    
    print("Sending request to Anthropic through firewall...")
    print(f"URL: {url}")
    response = requests.post(url, headers=headers, json=data)
    
    print(f"Status code: {response.status_code}")
    if response.status_code == 200:
        resp_json = response.json()
        print("\nResponse:")
        print(json.dumps(resp_json, indent=2))
    else:
        print("\nError:")
        print(response.text)

if __name__ == "__main__":
    test_anthropic_completion() 