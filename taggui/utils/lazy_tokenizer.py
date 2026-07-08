import time
from pathlib import Path


class LazyTokenizer:
    """Load the CLIP tokenizer only when token counting actually needs it."""

    def __init__(self, tokenizer_path: Path):
        self._tokenizer_path = tokenizer_path
        self._tokenizer = None

    def _load(self):
        if self._tokenizer is None:
            started_at = time.perf_counter()
            from transformers import AutoTokenizer
            self._tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_path)
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            print(f"[STARTUP] Lazy tokenizer loaded in {elapsed_ms:.0f}ms")
        return self._tokenizer

    def __call__(self, *args, **kwargs):
        return self._load()(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._load(), name)

