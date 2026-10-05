import requests
import time

class AnthropicError(Exception):
    pass

class AuthError(AnthropicError):
    pass

class RateLimitError(AnthropicError):
    pass

class AnthropicClient:
    def __init__(self, api_key):
        if not api_key:
            raise ValueError("API key is required")
        self.api_key = api_key
        self.model = "claude-opus-4-5"

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

    def send_message(self, message=None, system=None, retries=3, max_tokens=1024, messages=None):
        """Send one user message, or a full multi-turn `messages` list."""
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages or [
                {"role": "user", "content": message}
            ]
        }
        if system:
            body["system"] = system
        for attempt in range(retries):
            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=self._headers(),
                json=body
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("stop_reason") == "max_tokens":
                    raise AnthropicError("Response was cut off at the max_tokens limit")
                return data["content"][0]["text"]
            elif response.status_code == 401:
                raise AuthError("Invalid API key")
            elif response.status_code == 429:
                wait = 2 ** attempt
                print(f"Rate limited. Waiting {wait} seconds...")
                time.sleep(wait)
            else:
                raise AnthropicError(f"Error {response.status_code}: {response.text}")
        raise RateLimitError("Rate limit exceeded after retries")

# Test it
if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    client = AnthropicClient(api_key)
    reply = client.send_message("What is an API in one sentence?")
    print(reply)