"""Local chat model backed by llama.cpp and an NVIDIA Nemotron GGUF."""
import shutil

from Nexus.config import settings as default_settings

DEFAULT_STOP_TOKENS = ["<|eot_id|>"]


def detect_gpu_layers() -> int:
    """GPU layers to offload at runtime: -1 (all) on CUDA boxes, 0 on CPU-only.

    Prefers llama.cpp's own capability check when the build exposes one, and
    falls back to probing for `nvidia-smi` so CPU-only machines don't pay for
    offload attempts.
    """
    try:
        import llama_cpp
    except ImportError:
        return 0

    supports_offload = getattr(llama_cpp, "llama_supports_gpu_offload", None)
    if callable(supports_offload):
        try:
            return -1 if supports_offload() else 0
        except Exception:
            pass  # fall through to the nvidia-smi probe
    return -1 if shutil.which("nvidia-smi") else 0


class LocalLLM:
    """Thin wrapper around llama_cpp.Llama for chat completions."""

    def __init__(self, model_path: str, n_ctx=4096, n_gpu_layers=None, stop=None,
                 settings=None):
        # Imported here so importing this module does not require the native build.
        from llama_cpp import Llama

        cfg = settings or default_settings
        if n_gpu_layers is None:
            n_gpu_layers = detect_gpu_layers()
        if stop is None:
            stop = list(getattr(cfg, "stop_tokens", None) or DEFAULT_STOP_TOKENS)
        self.stop = stop

        self.llm = Llama(
            model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            verbose=False,
        )

    def chat(self, messages: list[dict], temperature=0.7) -> str:
        output = self.llm.create_chat_completion(
            messages=messages,
            temperature=temperature,
            stop=self.stop,
        )
        return output["choices"][0]["message"]["content"]
