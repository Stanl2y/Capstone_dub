from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from audio_features import analyze_chunk_records, compact_feature_summary, ensure_chunk_features
from common import get_logger, load_json, resolve_project_path, save_json
from quality_gate import assess_asr_row, attach_stage_quality

logger = get_logger("run_asr")


def _prepare_qwen_asr_imports() -> None:
    repo_path = resolve_project_path("third_party/Qwen3-ASR")
    if repo_path.exists():
        repo_str = str(repo_path)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)


def _resolve_torch_dtype(name: str) -> object:
    import torch

    mapping = {
        "float16": torch.float16,
        "float32": torch.float32,
        "bfloat16": torch.bfloat16,
    }
    if name not in mapping:
        raise ValueError(f"Unsupported torch dtype: {name}")
    return mapping[name]


def _get_result_attr(result: object, attr: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(attr, default)
    return getattr(result, attr, default)


def transcribe_chunks(
    chunk_json: str | Path,
    output_json: str | Path,
    *,
    model_dir: str | Path,
    device: str = "cuda:0",
    dtype: str = "float16",
    max_inference_batch_size: int = 8,
    max_new_tokens: int = 256,
    language: str | None = None,
    features_json: str | Path | None = None,
) -> list[dict[str, Any]]:
    _prepare_qwen_asr_imports()

    try:
        from qwen_asr import Qwen3ASRModel
    except ImportError as exc:
        raise RuntimeError(
            "qwen-asr is not installed. Install it with `pip install -U qwen-asr` or clone the repo into `third_party/Qwen3-ASR`."
        ) from exc

    chunk_records = load_json(chunk_json)
    if not chunk_records:
        save_json([], output_json)
        return []

    if features_json:
        chunk_features = analyze_chunk_records(chunk_records, output_json=features_json)
    else:
        chunk_features = ensure_chunk_features(chunk_records, reference_path=output_json)
    feature_map = {str(item.get("chunk_id", "")).strip(): item for item in chunk_features if item.get("chunk_id")}

    audio_paths = [str(resolve_project_path(item["wav"])) for item in chunk_records]
    language_arg: list[str | None] | None
    if language is None:
        language_arg = None
    else:
        language_arg = [language] * len(audio_paths)

    model = Qwen3ASRModel.from_pretrained(
        str(resolve_project_path(model_dir)),
        dtype=_resolve_torch_dtype(dtype),
        device_map=device,
        max_inference_batch_size=max_inference_batch_size,
        max_new_tokens=max_new_tokens,
    )
    results = model.transcribe(audio=audio_paths, language=language_arg)

    asr_rows: list[dict[str, Any]] = []
    for item, result in zip(chunk_records, results):
        duration = item.get("duration")
        if duration is None and item.get("start") is not None and item.get("end") is not None:
            duration = max(0.0, float(item["end"]) - float(item["start"]))

        chunk_id = str(item["chunk_id"])
        feature = feature_map.get(chunk_id)
        row = {
            "chunk_id": item["chunk_id"],
            "speaker": item["speaker"],
            "wav": item.get("wav"),
            "start": item.get("start"),
            "end": item.get("end"),
            "duration": duration,
            "language": _get_result_attr(result, "language"),
            "text_src": (_get_result_attr(result, "text", "") or "").strip(),
        }
        if feature:
            row["source_audio_summary"] = compact_feature_summary(feature)
        attach_stage_quality(row, "asr", assess_asr_row(row, chunk_feature=feature))
        asr_rows.append(row)

    save_json(asr_rows, output_json)
    logger.info("Saved ASR for %s chunks to %s", len(asr_rows), resolve_project_path(output_json))
    return asr_rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Qwen3-ASR over chunk wav files.")
    parser.add_argument("chunk_json")
    parser.add_argument("output_json")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", default="float16")
    parser.add_argument("--max-inference-batch-size", type=int, default=8)
    parser.add_argument("--max-new-tokens", type=int, default=256)
    parser.add_argument("--language")
    parser.add_argument("--features-json")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    transcribe_chunks(
        args.chunk_json,
        args.output_json,
        model_dir=args.model_dir,
        device=args.device,
        dtype=args.dtype,
        max_inference_batch_size=args.max_inference_batch_size,
        max_new_tokens=args.max_new_tokens,
        language=args.language,
        features_json=args.features_json,
    )


if __name__ == "__main__":
    main()
