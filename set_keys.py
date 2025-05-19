import os
import subprocess
import sys

# Set Anthropic API key - replace with your actual key before use
os.environ["ANTHROPIC_API_KEY"] = "your-anthropic-api-key-here"

print("API keys set in environment variables.")

# Run a python script if provided as an argument
if len(sys.argv) > 1:
    script_to_run = sys.argv[1]
    print(f"Running {script_to_run}...")
    result = subprocess.run([sys.executable, script_to_run])
    sys.exit(result.returncode) 