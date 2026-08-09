import time
from pathlib import Path
from types import SimpleNamespace


class LazyTokenizer:
    """Load the CLIP tokenizer only when token counting actually needs it."""

    def __init__(self, tokenizer_path: Path):
        self._tokenizer_path = tokenizer_path
        self._tokenizer = None

    def _load(self):
        if self._tokenizer is None:
            started_at = time.perf_counter()
            backend = "tokenizers"
            try:
                from tokenizers import Tokenizer

                self._tokenizer = Tokenizer.from_file(
                    str(self._tokenizer_path / "tokenizer.json")
                )
            except (ImportError, OSError, ValueError):
                from transformers import AutoTokenizer

                backend = "transformers"
                self._tokenizer = AutoTokenizer.from_pretrained(self._tokenizer_path)
            elapsed_ms = (time.perf_counter() - started_at) * 1000.0
            print(
                f"[STARTUP] Lazy tokenizer loaded in {elapsed_ms:.0f}ms "
                f"({backend})"
            )
        return self._tokenizer

    def __call__(self, *args, **kwargs):
        tokenizer = self._load()
        if tokenizer.__class__.__module__.startswith("tokenizers"):
            if not args:
                raise TypeError("Tokenizer input is required")
            text = args[0]
            add_special_tokens = kwargs.pop("add_special_tokens", True)
            if kwargs:
                unsupported = ", ".join(sorted(kwargs))
                raise TypeError(f"Unsupported tokenizer arguments: {unsupported}")
            if isinstance(text, (list, tuple)):
                input_ids = [
                    encoding.ids
                    for encoding in tokenizer.encode_batch(
                        list(text),
                        add_special_tokens=add_special_tokens,
                    )
                ]
            else:
                input_ids = tokenizer.encode(
                    text,
                    add_special_tokens=add_special_tokens,
                ).ids
            return SimpleNamespace(input_ids=input_ids)
        return tokenizer(*args, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._load(), name)
