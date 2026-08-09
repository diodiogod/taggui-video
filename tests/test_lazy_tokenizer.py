import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "taggui"))

from utils.lazy_tokenizer import LazyTokenizer


def test_lazy_tokenizer_uses_fast_backend_with_clip_compatible_ids():
    tokenizer = LazyTokenizer(ROOT / "clip-vit-base-patch32")

    assert tokenizer("one, two").input_ids == [49406, 637, 267, 1237, 49407]
    assert tokenizer(
        ["one", "two"],
        add_special_tokens=False,
    ).input_ids == [[637], [1237]]
    assert tokenizer._tokenizer.__class__.__module__.startswith("tokenizers")
