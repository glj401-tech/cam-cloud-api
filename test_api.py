"""Quick DashScope API diagnosis script."""
import os
import dashscope
from dashscope import Generation

# Same logic as cam_cloud_api.py
key = os.getenv("DASHSCOPE_API_KEY", "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
dashscope.api_key = key

print(f"API Key: {key[:8]}****{key[-4:]}")
print(f"Is placeholder: {key.startswith('sk-xxx')}")
print()

print("Testing DashScope API connectivity...")
try:
    resp = Generation.call(
        model="qwen2.5-14b-instruct",
        messages=[{"role": "user", "content": "say OK"}],
        temperature=0.1,
        max_tokens=10,
        result_format="message",
    )
    print(f"HTTP status_code: {resp.status_code}")
    if resp.status_code == 200:
        print(f"Response: {resp.output.choices[0].message.content}")
        print(">>> SUCCESS: API Key is valid, DashScope is reachable <<<")
    else:
        print(f"ERROR: code={resp.status_code}, message={resp.message}")
except dashscope.error.AuthenticationError as e:
    print(f">>> AUTH FAILED: API Key is invalid or expired <<<")
    print(f"    {e}")
except Exception as e:
    print(f">>> CONNECTION FAILED: {type(e).__name__}: {e} <<<")
