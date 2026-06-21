"""Quick Ollama API diagnosis script."""
import os
from openai import OpenAI

# Same config as cam_cloud_api.py
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")

client = OpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama",
)

print(f"Ollama URL: {OLLAMA_BASE_URL}")
print(f"Model: {OLLAMA_MODEL}")
print()

# Step 1: Check Ollama connectivity
print("Testing Ollama service connectivity...")
try:
    models = client.models.list()
    model_ids = [m.id for m in models]
    print(f"Available models: {model_ids}")
    print(">>> SUCCESS: Ollama is reachable <<<")
except Exception as e:
    print(f">>> CONNECTION FAILED: {type(e).__name__}: {e} <<<")
    print("Make sure Ollama is installed and running: ollama serve")
    exit(1)

print()

# Step 2: Test model inference
print(f"Testing model inference ({OLLAMA_MODEL})...")
try:
    resp = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": "say OK"}],
        temperature=0.1,
        max_tokens=10,
    )
    content = resp.choices[0].message.content
    print(f"Response: {content}")
    print(">>> SUCCESS: Model inference works correctly <<<")
except Exception as e:
    print(f">>> INFERENCE FAILED: {type(e).__name__}: {e} <<<")
    print(f"Make sure the model '{OLLAMA_MODEL}' is pulled: ollama pull {OLLAMA_MODEL}")
    exit(1)

print()
print("=== All checks passed! Ollama service is ready. ===")
