import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
TAGGUI_ROOT = ROOT / "taggui"


def test_lazy_transformers_import_accepts_redirected_stream():
    script = r"""
import gc
import json
import logging
import sys
import weakref

from utils.ModelThread import ModelThreadOutputStream


captured = []


class OutputTarget:
    def write(self, text):
        captured.append(text)


first_target = OutputTarget()
first_target_reference = weakref.ref(first_target)
original_stderr = sys.stderr
original_stdout = sys.stdout
redirected_stderr = ModelThreadOutputStream(original_stderr)
redirected_stdout = ModelThreadOutputStream(original_stdout)
redirected_stderr.attach(first_target)
redirected_stdout.attach(first_target)
sys.stderr = redirected_stderr
sys.stdout = redirected_stdout
try:
    import transformers
    from transformers.utils import logging as transformers_logging
    from transformers.utils.loading_report import _style

    assert _style("plain text", "bold") == "plain text"
    assert sys.stderr.write("direct first\n") == len("direct first\n")
    assert sys.stderr.flush() is None
    assert sys.stderr.isatty() is False

    transformers_handler = logging.getLogger("transformers").handlers[0]
    assert transformers_handler.stream is redirected_stderr
    logger = transformers_logging.get_logger(
        "transformers.redirect-regression"
    )
    logger.warning("first warning")

    redirected_stderr.detach(first_target)
    redirected_stdout.detach(first_target)
    del first_target
    gc.collect()

    second_target = OutputTarget()
    redirected_stderr.attach(second_target)
    redirected_stdout.attach(second_target)
    logger.warning("second warning")
finally:
    sys.stderr = original_stderr
    sys.stdout = original_stdout

print(json.dumps({
    "captured": "".join(captured),
    "first_target_released": first_target_reference() is None,
    "transformers_version": transformers.__version__,
}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(TAGGUI_ROOT)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(result.stdout.strip())
    assert "direct first\n" in state["captured"]
    assert "first warning" in state["captured"]
    assert "second warning" in state["captured"]
    assert state["first_target_released"] is True
    assert state["transformers_version"]
