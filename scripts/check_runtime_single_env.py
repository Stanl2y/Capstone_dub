from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(r'C:\movie-dubbing-project')
COSYVOICE_REPO = PROJECT_ROOT / 'third_party' / 'CosyVoice'
MATCHA_PATH = COSYVOICE_REPO / 'third_party' / 'Matcha-TTS'
for candidate in (COSYVOICE_REPO, MATCHA_PATH):
    candidate_str = str(candidate)
    if candidate.exists() and candidate_str not in sys.path:
        sys.path.insert(0, candidate_str)


def validate_whisper_package() -> None:
    spec = importlib.util.find_spec('whisper')
    if spec is None:
        raise RuntimeError('`openai-whisper` is not installed.')
    origin = str(spec.origin or '')
    if origin.endswith('site-packages\\whisper.py'):
        raise RuntimeError(
            'Wrong `whisper` package is installed. Uninstall `whisper` and install `openai-whisper`. '
            f'Current module path: {origin}'
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-dir', required=True)
    args = parser.parse_args()

    validate_whisper_package()

    import qwen_asr  # noqa: F401
    import whisper  # noqa: F401
    import audio_separator  # noqa: F401
    import hyperpyyaml  # noqa: F401
    import modelscope  # noqa: F401
    import inflect  # noqa: F401
    import onnxruntime  # noqa: F401
    import torchaudio  # noqa: F401
    import diffusers  # noqa: F401
    import omegaconf  # noqa: F401
    import lightning  # noqa: F401
    import wetext  # noqa: F401
    import pyworld  # noqa: F401
    import x_transformers  # noqa: F401
    import gdown  # noqa: F401
    import einops  # noqa: F401
    import scipy  # noqa: F401
    import conformer  # noqa: F401
    import transformers  # noqa: F401
    import librosa  # noqa: F401
    import soundfile  # noqa: F401
    import matplotlib  # noqa: F401
    import wget  # noqa: F401
    import phonemizer  # noqa: F401
    import piper_phonemize  # noqa: F401
    from unidecode import unidecode  # noqa: F401

    from matcha.text import cleaners as _matcha_cleaners  # noqa: F401
    from cosyvoice.flow.flow_matching import ConditionalCFM  # noqa: F401
    from cosyvoice.cli.cosyvoice import AutoModel

    AutoModel(model_dir=args.model_dir)
    print('runtime and CosyVoice model load ok')


if __name__ == '__main__':
    main()
