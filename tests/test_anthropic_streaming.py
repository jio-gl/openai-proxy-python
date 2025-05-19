import requests
import json
import os
import sseclient

# Firewall proxy URL (local server)
PROXY_URL = "http://localhost:8000"

def test_anthropic_streaming():
    """Test a streaming message request through the Anthropic API firewall"""
    # The correct endpoint for Anthropic's v1 messages
    url = f"{PROXY_URL}/anthropic/v1/messages"
    
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    
    data = {
        "model": "claude-3-sonnet-20240229",
        "messages": [
            {"role": "user", "content": "Say hello world"}
        ],
        "max_tokens": 50,
        "stream": True
    }
    
    print("Sending streaming request to Anthropic through firewall...")
    print(f"URL: {url}")
    
    try:
        # Request with streaming enabled but handle the response differently
        response = requests.post(url, headers=headers, json=data, stream=True)
        print(f"Status code: {response.status_code}")
        
        if response.status_code == 200:
            print("\nStreaming response content:")
            
            # Read raw content instead of using iter_lines
            content = response.content.decode('utf-8')
            print(f"\nContent length: {len(content)} bytes")
            
            # Split by data: to find individual events
            events = content.split("data: ")
            
            for event in events:
                if not event.strip():
                    continue
                    
                print(f"\n--- Event ---\n{event.strip()}")
                
                # Try to parse JSON if it's valid
                try:
                    json_data = json.loads(event.strip())
                    # Check for content block delta
                    if json_data.get("type") == "content_block_delta":
                        delta = json_data.get("delta", {})
                        if delta.get("type") == "text_delta":
                            print(f"Content: {delta.get('text', '')}")
                except json.JSONDecodeError:
                    # Just print the event if it's not JSON
                    if event.strip() == "[DONE]":
                        print("Stream complete")
        else:
            print("\nError:")
            print(response.text)
    except Exception as e:
        print(f"Error during streaming request: {str(e)}")

if __name__ == "__main__":
    test_anthropic_streaming() 