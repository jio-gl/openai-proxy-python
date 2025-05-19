import requests
import json
import os

# Firewall proxy URL (local server)
PROXY_URL = "http://localhost:8000"

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
    if response.status_code == 200:
        try:
            resp_json = response.json()
            print("\nResponse:")
            print(json.dumps(resp_json, indent=2))
        except:
            print("\nCouldn't parse JSON, raw content:")
            print(response.text[:500])  # Print just the first 500 chars
    else:
        print("\nError:")
        print(response.text)

if __name__ == "__main__":
    test_openai_completion() 