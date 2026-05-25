from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_relative(path: str | Path) -> str:
    resolved = resolve_path(path).resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def load_json(path: str | Path) -> Any:
    with resolve_path(path).open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def save_json(data: Any, path: str | Path) -> None:
    output = resolve_path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def read_audio_crop(audio_path: Path, start_sec: float, end_sec: float) -> tuple[np.ndarray, int]:
    with sf.SoundFile(str(audio_path)) as handle:
        sample_rate = int(handle.samplerate)
        start_frame = max(0, int(round(start_sec * sample_rate)))
        end_frame = max(start_frame, int(round(end_sec * sample_rate)))
        end_frame = min(end_frame, len(handle))
        handle.seek(start_frame)
        data = handle.read(end_frame - start_frame, dtype="float32", always_2d=True)
    if data.size == 0:
        return np.zeros((1, 0), dtype=np.float32), sample_rate
    mono = data.mean(axis=1).astype(np.float32)
    return mono[None, :], sample_rate


def write_audio_crop(audio_path: Path, output_path: Path, start_sec: float, end_sec: float) -> None:
    waveform, sample_rate = read_audio_crop(audio_path, start_sec, end_sec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output_path), waveform[0], sample_rate, subtype="PCM_16")


def get_annotation(result: object, *, exclusive: bool) -> object:
    if hasattr(result, "itertracks"):
        return result
    preferred = []
    if exclusive:
        preferred.append("exclusive_speaker_diarization")
    preferred.extend(["speaker_diarization", "diarization", "prediction", "annotation"])
    for attr in preferred:
        candidate = getattr(result, attr, None)
        if candidate is not None and hasattr(candidate, "itertracks"):
            return candidate
    attrs = [name for name in dir(result) if not name.startswith("_")]
    raise RuntimeError(f"Could not find pyannote Annotation in result. Available attrs: {attrs}")


def iter_annotation_segments(annotation: object, crop_start: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        start = crop_start + float(turn.start)
        end = crop_start + float(turn.end)
        if end <= start:
            continue
        rows.append(
            {
                "local_speaker": str(speaker),
                "start": round(start, 6),
                "end": round(end, 6),
                "duration": round(end - start, 6),
            }
        )
    rows.sort(key=lambda item: (float(item["start"]), float(item["end"]), str(item["local_speaker"])))
    return rows


def clipped_segments(
    segments: list[dict[str, Any]],
    *,
    start: float,
    end: float,
    min_segment_sec: float,
) -> list[dict[str, Any]]:
    clipped: list[dict[str, Any]] = []
    for segment in segments:
        seg_start = max(start, float(segment["start"]))
        seg_end = min(end, float(segment["end"]))
        if seg_end - seg_start < min_segment_sec:
            continue
        clipped.append(
            {
                "local_speaker": str(segment["local_speaker"]),
                "start": round(seg_start, 6),
                "end": round(seg_end, 6),
                "duration": round(seg_end - seg_start, 6),
            }
        )
    return clipped


def candidate_reasons(chunk: dict[str, Any], *, args: argparse.Namespace) -> list[str]:
    duration = float(chunk["end"]) - float(chunk["start"])
    reasons: list[str] = []
    if args.all_chunks:
        reasons.append("all_chunks")
    if duration >= args.long_chunk_sec:
        reasons.append("long_chunk")
    if int(chunk.get("source_segment_count") or 1) > 1:
        reasons.append("merged_source_segments")
    if duration >= args.min_candidate_sec and duration <= args.max_candidate_sec and not reasons:
        reasons.append("eligible_duration")
    return reasons


def speaker_count(segments: list[dict[str, Any]], *, min_total_sec: float) -> tuple[int, dict[str, float]]:
    totals: dict[str, float] = {}
    for segment in segments:
        speaker = str(segment["local_speaker"])
        totals[speaker] = totals.get(speaker, 0.0) + float(segment["duration"])
    totals = {speaker: round(total, 6) for speaker, total in sorted(totals.items()) if total >= min_total_sec}
    return len(totals), totals


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run pyannote on existing diarization chunks and write local split candidates."
    )
    parser.add_argument("--chunks", required=True, help="Input speaker_chunks JSON.")
    parser.add_argument("--audio", required=True, help="Source dialogue wav.")
    parser.add_argument("--output", required=True, help="Challenge report JSON.")
    parser.add_argument("--subchunks-output", required=True, help="Generated subchunk manifest JSON.")
    parser.add_argument("--work-dir", required=True, help="Directory for generated subchunk wav files.")
    parser.add_argument("--model", default="pyannote/speaker-diarization-community-1")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--context-sec", type=float, default=1.25)
    parser.add_argument("--min-candidate-sec", type=float, default=0.8)
    parser.add_argument("--max-candidate-sec", type=float, default=30.0)
    parser.add_argument("--long-chunk-sec", type=float, default=3.0)
    parser.add_argument("--min-local-segment-sec", type=float, default=0.2)
    parser.add_argument("--min-local-speaker-total-sec", type=float, default=0.45)
    parser.add_argument("--min-speakers", type=int, default=1)
    parser.add_argument("--max-speakers", type=int, default=2)
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument("--all-chunks", action="store_true")
    parser.add_argument("--exclusive", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()

    from pyannote.audio import Pipeline

    chunks = load_json(args.chunks)
    audio_path = resolve_path(args.audio)
    output_path = resolve_path(args.output)
    subchunks_output = resolve_path(args.subchunks_output)
    work_dir = resolve_path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN") or "").strip() or None
    pipeline = Pipeline.from_pretrained(args.model, token=token)
    pipeline.to(torch.device(args.device))

    candidates: list[dict[str, Any]] = []
    for chunk in chunks:
        start = float(chunk["start"])
        end = float(chunk["end"])
        duration = end - start
        if duration < args.min_candidate_sec or duration > args.max_candidate_sec:
            continue
        reasons = candidate_reasons(chunk, args=args)
        if not reasons:
            continue
        candidates.append({**chunk, "_challenge_reasons": reasons})

    if args.max_candidates is not None:
        candidates = candidates[: max(0, int(args.max_candidates))]

    report_candidates: list[dict[str, Any]] = []
    subchunks: list[dict[str, Any]] = []

    for candidate_index, chunk in enumerate(candidates, start=1):
        chunk_id = str(chunk["chunk_id"])
        chunk_start = float(chunk["start"])
        chunk_end = float(chunk["end"])
        crop_start = max(0.0, chunk_start - float(args.context_sec))
        crop_end = chunk_end + float(args.context_sec)
        waveform, sample_rate = read_audio_crop(audio_path, crop_start, crop_end)
        if waveform.shape[1] == 0:
            continue

        result = pipeline(
            {"waveform": torch.from_numpy(waveform), "sample_rate": sample_rate},
            min_speakers=int(args.min_speakers),
            max_speakers=int(args.max_speakers),
        )
        annotation = get_annotation(result, exclusive=bool(args.exclusive))
        local_segments = iter_annotation_segments(annotation, crop_start)
        chunk_segments = clipped_segments(
            local_segments,
            start=chunk_start,
            end=chunk_end,
            min_segment_sec=float(args.min_local_segment_sec),
        )
        local_speaker_count, local_speaker_totals = speaker_count(
            chunk_segments,
            min_total_sec=float(args.min_local_speaker_total_sec),
        )
        split_candidate = local_speaker_count >= 2

        for segment_index, segment in enumerate(chunk_segments, start=1):
            subchunk_id = f"{chunk_id}_py{segment_index:02d}"
            wav_path = work_dir / f"{subchunk_id}.wav"
            write_audio_crop(audio_path, wav_path, float(segment["start"]), float(segment["end"]))
            subchunk = {
                "chunk_id": subchunk_id,
                "parent_chunk_id": chunk_id,
                "speaker": str(segment["local_speaker"]),
                "local_speaker": str(segment["local_speaker"]),
                "start": segment["start"],
                "end": segment["end"],
                "duration": segment["duration"],
                "wav": project_relative(wav_path),
            }
            subchunks.append(subchunk)
            segment["subchunk_id"] = subchunk_id
            segment["wav"] = project_relative(wav_path)

        report_candidates.append(
            {
                "chunk_id": chunk_id,
                "speaker": str(chunk["speaker"]),
                "start": round(chunk_start, 6),
                "end": round(chunk_end, 6),
                "duration": round(chunk_end - chunk_start, 6),
                "candidate_index": candidate_index,
                "reasons": list(chunk.get("_challenge_reasons") or []),
                "crop_start": round(crop_start, 6),
                "crop_end": round(crop_end, 6),
                "local_speaker_count": local_speaker_count,
                "local_speaker_totals": local_speaker_totals,
                "split_candidate": split_candidate,
                "local_segments": local_segments,
                "chunk_segments": chunk_segments,
            }
        )

    report = {
        "schema_version": 1,
        "chunks": project_relative(args.chunks),
        "audio": project_relative(args.audio),
        "subchunks_json": project_relative(subchunks_output),
        "params": {
            "model": args.model,
            "device": args.device,
            "context_sec": args.context_sec,
            "min_candidate_sec": args.min_candidate_sec,
            "max_candidate_sec": args.max_candidate_sec,
            "long_chunk_sec": args.long_chunk_sec,
            "min_local_segment_sec": args.min_local_segment_sec,
            "min_local_speaker_total_sec": args.min_local_speaker_total_sec,
            "min_speakers": args.min_speakers,
            "max_speakers": args.max_speakers,
            "max_candidates": args.max_candidates,
            "all_chunks": args.all_chunks,
            "exclusive": args.exclusive,
        },
        "candidate_count": len(report_candidates),
        "split_candidate_count": sum(1 for item in report_candidates if item["split_candidate"]),
        "candidates": report_candidates,
    }
    save_json(subchunks, subchunks_output)
    save_json(report, output_path)
    print(
        json.dumps(
            {
                "output": project_relative(output_path),
                "subchunks_output": project_relative(subchunks_output),
                "candidate_count": report["candidate_count"],
                "split_candidate_count": report["split_candidate_count"],
                "subchunk_count": len(subchunks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
