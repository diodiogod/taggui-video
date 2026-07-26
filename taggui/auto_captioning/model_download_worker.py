from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


MODEL_DOWNLOAD_WORKER_FLAG = '--taggui-model-download-worker'


def _download_model(payload: dict) -> str:
    from huggingface_hub import hf_hub_download, snapshot_download

    request = dict(payload)
    mode = request.pop('mode')
    if mode == 'snapshot':
        return str(snapshot_download(**request) or '')
    if mode == 'files':
        repo_id = request.pop('repo_id')
        filenames = request.pop('filenames')
        if not filenames:
            raise RuntimeError('No model files were requested.')
        local_dir = request.get('local_dir')
        last_path = ''
        for filename in filenames:
            last_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                **request,
            )
        return str(local_dir or Path(last_path).parent)
    raise RuntimeError(f'Unsupported download mode: {mode}')


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if len(arguments) != 3:
        print(
            'Expected payload, result, and error file paths.',
            file=sys.stderr,
        )
        return 2

    payload_path, result_path, error_path = map(Path, arguments)
    try:
        payload = json.loads(payload_path.read_text(encoding='utf-8'))
        result = _download_model(payload)
        result_path.write_text(result, encoding='utf-8')
    except Exception:
        error_path.write_text(traceback.format_exc(), encoding='utf-8')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
