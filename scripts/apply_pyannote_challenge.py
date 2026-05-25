from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

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


def format_chunk_id(index: int) -> str:
    return f"chunk_{index:04d}"


def l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(x) * float(x) for x in vec)) or 1.0
    return [float(x) / norm for x in vec]


def dot(a: list[float], b: list[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def weighted_mean(vectors: list[tuple[list[float], float]]) -> list[float] | None:
    if not vectors:
        return None
    dim = len(vectors[0][0])
    total_weight = sum(max(0.0, weight) for _, weight in vectors)
    if total_weight <= 0:
        total_weight = float(len(vectors))
        vectors = [(vec, 1.0) for vec, _ in vectors]
    mean = [0.0] * dim
    for vec, weight in vectors:
        weight = max(0.0, float(weight))
        for index in range(dim):
            mean[index] += float(vec[index]) * weight
    return l2([value / total_weight for value in mean])


def build_centroids(
    chunks: list[dict[str, Any]],
    embeddings: dict[str, list[float]],
    *,
    exclude_chunk_ids: set[str],
) -> dict[str, list[float]]:
    grouped: dict[str, list[tuple[list[float], float]]] = {}
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        if chunk_id in exclude_chunk_ids:
            continue
        if chunk_id not in embeddings:
            continue
        speaker = str(chunk.get("speaker") or "")
        if not speaker:
            continue
        grouped.setdefault(speaker, []).append((embeddings[chunk_id], float(chunk.get("duration") or 1.0)))
    centroids: dict[str, list[float]] = {}
    for speaker, vectors in grouped.items():
        centroid = weighted_mean(vectors)
        if centroid is not None:
            centroids[speaker] = centroid
    return centroids


def best_speaker(
    embedding: list[float],
    centroids: dict[str, list[float]],
    *,
    fallback: str,
    min_sim: float,
    margin: float,
) -> dict[str, Any]:
    if not centroids:
        return {
            "speaker": fallback,
            "best_speaker": None,
            "best_sim": None,
            "second_speaker": None,
            "second_sim": None,
            "confident": False,
        }
    sims = sorted(
        ((speaker, dot(embedding, centroid)) for speaker, centroid in centroids.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    best_label, best_sim = sims[0]
    second_label, second_sim = sims[1] if len(sims) > 1 else (None, -1.0)
    confident = best_sim >= min_sim and (best_sim - second_sim) >= margin
    return {
        "speaker": best_label if confident else fallback,
        "best_speaker": best_label,
        "best_sim": round(best_sim, 6),
        "second_speaker": second_label,
        "second_sim": round(second_sim, 6) if second_label is not None else None,
        "confident": confident,
    }


def merge_adjacent_segments(segments: list[dict[str, Any]], *, max_gap_sec: float = 0.08) -> list[dict[str, Any]]:
    ordered = sorted(segments, key=lambda item: (float(item["start"]), float(item["end"])))
    merged: list[dict[str, Any]] = []
    for segment in ordered:
        if (
            merged
            and str(merged[-1]["speaker"]) == str(segment["speaker"])
            and float(segment["start"]) - float(merged[-1]["end"]) <= max_gap_sec
        ):
            merged[-1]["end"] = max(float(merged[-1]["end"]), float(segment["end"]))
            merged[-1]["duration"] = round(float(merged[-1]["end"]) - float(merged[-1]["start"]), 6)
            merged[-1].setdefault("source_subchunk_ids", []).extend(segment.get("source_subchunk_ids") or [])
        else:
            merged.append(dict(segment))
    return merged


def should_adopt(
    mapped_segments: list[dict[str, Any]],
    *,
    original_speaker: str,
    min_total_sec: float,
    require_confident_new_speaker: bool,
) -> tuple[bool, dict[str, Any]]:
    totals: dict[str, float] = {}
    confident_totals: dict[str, float] = {}
    for segment in mapped_segments:
        speaker = str(segment["speaker"])
        duration = float(segment["duration"])
        totals[speaker] = totals.get(speaker, 0.0) + duration
        if segment.get("mapping", {}).get("confident"):
            confident_totals[speaker] = confident_totals.get(speaker, 0.0) + duration

    strong = {speaker: total for speaker, total in totals.items() if total >= min_total_sec}
    confident_new = {
        speaker: total
        for speaker, total in confident_totals.items()
        if speaker != original_speaker and total >= min_total_sec
    }
    adopted = len(strong) >= 2 and (bool(confident_new) or not require_confident_new_speaker)
    return adopted, {
        "speaker_totals": {speaker: round(total, 6) for speaker, total in sorted(totals.items())},
        "strong_speaker_totals": {speaker: round(total, 6) for speaker, total in sorted(strong.items())},
        "confident_new_speaker_totals": {
            speaker: round(total, 6) for speaker, total in sorted(confident_new.items())
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply pyannote chunk challenge results when embedding remapping is confident."
    )
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--challenge-report", required=True)
    parser.add_argument("--global-embeddings", required=True)
    parser.add_argument("--subchunk-embeddings", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--decision-output", required=True)
    parser.add_argument("--min-sim", type=float, default=0.42)
    parser.add_argument("--margin", type=float, default=0.035)
    parser.add_argument("--min-adopt-speaker-sec", type=float, default=0.45)
    parser.add_argument("--min-subsegment-sec", type=float, default=0.25)
    parser.add_argument("--merge-gap-sec", type=float, default=0.08)
    parser.add_argument("--require-confident-new-speaker", action=argparse.BooleanOptionalAction, default=True)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    chunks = load_json(args.chunks)
    challenge = load_json(args.challenge_report)
    global_embeddings = load_json(args.global_embeddings)
    subchunk_embeddings = load_json(args.subchunk_embeddings)

    candidate_by_id = {
        str(candidate["chunk_id"]): candidate
        for candidate in challenge.get("candidates", [])
        if candidate.get("split_candidate")
    }
    centroids = build_centroids(
        chunks,
        global_embeddings,
        exclude_chunk_ids=set(candidate_by_id),
    )

    decisions: list[dict[str, Any]] = []
    replacements: dict[str, list[dict[str, Any]]] = {}

    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        candidate = candidate_by_id.get(chunk_id)
        if candidate is None:
            continue

        original_speaker = str(chunk.get("speaker") or "")
        mapped_segments: list[dict[str, Any]] = []
        missing_embeddings: list[str] = []
        for segment in candidate.get("chunk_segments") or []:
            if float(segment.get("duration") or 0.0) < float(args.min_subsegment_sec):
                continue
            subchunk_id = str(segment.get("subchunk_id") or "")
            embedding = subchunk_embeddings.get(subchunk_id)
            if embedding is None:
                missing_embeddings.append(subchunk_id)
                continue
            mapping = best_speaker(
                embedding,
                centroids,
                fallback=original_speaker,
                min_sim=float(args.min_sim),
                margin=float(args.margin),
            )
            mapped_segments.append(
                {
                    "speaker": mapping["speaker"],
                    "start": float(segment["start"]),
                    "end": float(segment["end"]),
                    "duration": round(float(segment["end"]) - float(segment["start"]), 6),
                    "source_chunk_id": chunk_id,
                    "source_subchunk_ids": [subchunk_id],
                    "pyannote_local_speaker": str(segment.get("local_speaker") or ""),
                    "mapping": mapping,
                    "pyannote_challenge": True,
                }
            )

        mapped_segments = merge_adjacent_segments(mapped_segments, max_gap_sec=float(args.merge_gap_sec))
        adopted, stats = should_adopt(
            mapped_segments,
            original_speaker=original_speaker,
            min_total_sec=float(args.min_adopt_speaker_sec),
            require_confident_new_speaker=bool(args.require_confident_new_speaker),
        )
        decision = {
            "chunk_id": chunk_id,
            "original_speaker": original_speaker,
            "adopted": adopted,
            "missing_embeddings": missing_embeddings,
            "mapped_segments": mapped_segments,
            **stats,
        }
        decisions.append(decision)
        if adopted:
            replacements[chunk_id] = mapped_segments

    output_chunks: list[dict[str, Any]] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        replacement = replacements.get(chunk_id)
        if replacement:
            output_chunks.extend(replacement)
        else:
            output_chunks.append(dict(chunk))

    output_chunks.sort(key=lambda item: (float(item["start"]), float(item["end"]), str(item.get("speaker") or "")))
    for index, chunk in enumerate(output_chunks, start=1):
        chunk["chunk_id"] = format_chunk_id(index)
        chunk["duration"] = round(float(chunk["end"]) - float(chunk["start"]), 6)

    decision_report = {
        "schema_version": 1,
        "chunks": project_relative(args.chunks),
        "challenge_report": project_relative(args.challenge_report),
        "global_embeddings": project_relative(args.global_embeddings),
        "subchunk_embeddings": project_relative(args.subchunk_embeddings),
        "output": project_relative(args.output),
        "params": {
            "min_sim": args.min_sim,
            "margin": args.margin,
            "min_adopt_speaker_sec": args.min_adopt_speaker_sec,
            "min_subsegment_sec": args.min_subsegment_sec,
            "merge_gap_sec": args.merge_gap_sec,
            "require_confident_new_speaker": args.require_confident_new_speaker,
        },
        "candidate_count": len(candidate_by_id),
        "adopted_count": len(replacements),
        "decisions": decisions,
    }

    save_json(output_chunks, args.output)
    save_json(decision_report, args.decision_output)
    print(
        json.dumps(
            {
                "output": project_relative(args.output),
                "decision_output": project_relative(args.decision_output),
                "candidate_count": len(candidate_by_id),
                "adopted_count": len(replacements),
                "input_chunks": len(chunks),
                "output_chunks": len(output_chunks),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
