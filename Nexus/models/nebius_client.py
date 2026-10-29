from openai import OpenAI  # Nebius exposes an OpenAI-compatible API

class NebiusClient:
    def __init__(self, api_key: str, base_url: str):
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def chat(self, messages: list[dict], model: str = "nvidia/Nemotron-3-Ultra-550B"):
        return self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.6
        ).choices[0].message.content
