#!/bin/bash

# Start the proxy server in the background
echo "Starting OpenAI Proxy server..."
python -m app.main &
PROXY_PID=$!

# Wait for the server to start
sleep 2

echo "Exposing proxy server with ngrok..."
# Start ngrok to expose port 8000 (the port your proxy is running on)
ngrok http 8000 --log=stdout

# If ngrok is stopped, also kill the proxy server
kill $PROXY_PID 