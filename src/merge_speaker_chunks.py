# 인접 동일-라벨 diarization 세그먼트를 청크로 병합 — 단 실제 음높이(F0)가 다르면(다른 화자) 병합 금지(섞임 방지)
from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
from typing import Any

from common import format_chunk_id, get_logger, load_json, resolve_project_path, save_json

logger = get_logger("merge_speaker_chunks")


def _load_f0_helper(dialogue_audio: str | Path | None):
    """dialogue 오디오로 [start,end] 구간 median F0(Hz) 를 주는 함수 반환. 불가하면 None(게이트 비활성)."""
    if not dialogue_audio:
        return None
    try:
        import librosa
        import numpy as np
    except Exception as exc:  # librosa 없는 런타임 → 게이트 비활성, 라벨만으로 병합
        logger.warning("F0 merge-gate disabled (librosa unavailable: %s)", exc)
        return None
    path = resolve_project_path(dialogue_audio)
    if not path.exists():
        logger.warning("F0 merge-gate disabled (dialogue audio not found: %s)", path)
        return None
    sr = 16000
    y, _ = librosa.load(str(path), sr=sr, mono=True)

    @lru_cache(maxsize=4096)
    def median_f0(start: float, end: float) -> float:
        a = max(0, int(start * sr)); b = min(len(y), int(end * sr))
        seg = y[a:b]
        if len(seg) < 400:
            return 0.0
        try:
            f0, _, _ = librosa.pyin(seg, fmin=70, fmax=400, sr=sr)
            f0 = f0[~np.isnan(f0)]
        except Exception:
            return 0.0
        return float(np.median(f0)) if f0.size else 0.0

    return median_f0


def merge_speaker_chunks(
    input_json: str | Path,
    output_json: str | Path,
    *,
    gap_threshold: float = 0.5,
    min_chunk_sec: float = 0.0,
    max_chunk_sec: float = 0.0,
    dialogue_audio: str | Path | None = None,
    f0_gate_hz: float = 50.0,
    short_absorb_sec: float = 0.0,
) -> list[dict[str, Any]]:
    segments = load_json(input_json)
    ordered = sorted(segments, key=lambda item: float(item["start"]))

    f0_of = _load_f0_helper(dialogue_audio)

    def voices_differ(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
        """병합 금지 여부 — '다른 화자라는 명확한 증거'가 있을 때만 금지(연속 발화 연결 우선).
        F0 비교 가능(librosa+오디오): 두 구간 median F0 가 둘 다 유효(유성·충분길이)하고 차이 > gate 일 때만
        다른 화자로 보고 병합 금지(True). 한쪽이라도 F0 무효(무성/짧음)면 다른 화자 증거가 없으므로 라벨을
        신뢰해 병합 허용(False) — 짧은 토막을 화자가 바뀐 것으로 오인해 과분할하는 것을 막는다.
        F0 비교 불가(librosa 없음 등)면 라벨에 맡김(False)."""
        if f0_of is None or f0_gate_hz <= 0:
            return False  # F0 사용 불가 → 라벨만으로 병합(폴백)
        fa = f0_of(round(a_start, 3), round(a_end, 3))
        fb = f0_of(round(b_start, 3), round(b_end, 3))
        if fa <= 0 or fb <= 0:
            return False  # 음높이로 다른 화자 확인 불가(짧음/무성) → 라벨 신뢰(병합 허용)
        return abs(fa - fb) > f0_gate_hz

    # 짧은 토막 흡수 — 라벨/F0/임베딩이 신뢰 불가한 sub-threshold 세그먼트를, '다른 화자 증거'가 없는
    # 인접 이웃(더 긴 쪽=라벨 신뢰도 높음)의 라벨로 재지정해 연속 발화에 합류시킨다. 과분할(예: 0.26초
    # "You're not." 토막)로 끊긴 더빙을 연결한다. 원본 라벨 스냅샷 기준으로 판정(연쇄 재지정 방지).
    if short_absorb_sec and short_absorb_sec > 0:
        orig_speaker = [str(s["speaker"]) for s in ordered]
        absorbed = 0
        for i, seg in enumerate(ordered):
            if float(seg["end"]) - float(seg["start"]) >= short_absorb_sec:
                continue
            best: tuple[float, str] | None = None  # (neighbor_dur, neighbor_speaker)
            for j in (i - 1, i + 1):
                if not (0 <= j < len(ordered)):
                    continue
                nb = ordered[j]
                gap = (float(seg["start"]) - float(nb["end"])) if j < i else (float(nb["start"]) - float(seg["end"]))
                if gap > gap_threshold:
                    continue
                if voices_differ(float(seg["start"]), float(seg["end"]), float(nb["start"]), float(nb["end"])):
                    continue
                ndur = float(nb["end"]) - float(nb["start"])
                if best is None or ndur > best[0]:
                    best = (ndur, orig_speaker[j])
            if best is not None and str(seg["speaker"]) != best[1]:
                seg.setdefault("audio_speaker", str(seg["speaker"]))
                seg["speaker"] = best[1]
                seg["short_absorbed"] = True
                absorbed += 1
        if absorbed:
            logger.info("short-absorb: %s 짧은 토막(<%.2fs)을 인접 화자로 흡수", absorbed, short_absorb_sec)

    merged: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    source_count = 0
    f0_blocks = 0
    max_chunk_sec = max(0.0, float(max_chunk_sec or 0.0))

    def finalize(item: dict[str, Any], count: int) -> None:
        duration = float(item["end"]) - float(item["start"])
        if duration < min_chunk_sec:
            logger.warning("Dropping short chunk for %s (%.3fs < %.3fs)", item["speaker"], duration, min_chunk_sec)
            return
        item["duration"] = round(duration, 3)
        item["source_segment_count"] = count
        merged.append(item)

    def split_segment(segment: dict[str, Any]) -> list[dict[str, Any]]:
        speaker = str(segment["speaker"])
        start = float(segment["start"])
        end = float(segment["end"])
        if max_chunk_sec <= 0 or end - start <= max_chunk_sec:
            return [{"speaker": speaker, "start": start, "end": end}]
        pieces: list[dict[str, Any]] = []
        cursor = start
        while cursor < end:
            piece_end = min(end, cursor + max_chunk_sec)
            pieces.append({"speaker": speaker, "start": cursor, "end": piece_end, "chunking_split_reason": "max_chunk_sec"})
            cursor = piece_end
        return pieces

    for segment in ordered:
        for piece in split_segment(segment):
            speaker = str(piece["speaker"])
            start = float(piece["start"])
            end = float(piece["end"])
            if current is None:
                current = dict(piece)
                source_count = 1
                continue

            gap = start - float(current["end"])
            merged_duration = max(float(current["end"]), end) - float(current["start"])
            can_merge_duration = max_chunk_sec <= 0 or merged_duration <= max_chunk_sec
            same_label_close = speaker == current["speaker"] and gap <= gap_threshold and can_merge_duration
            if same_label_close and voices_differ(float(current["start"]), float(current["end"]), start, end):
                f0_blocks += 1
                same_label_close = False  # 라벨은 같지만 음높이가 달라 다른 화자 → 병합 금지
            if same_label_close:
                current["end"] = max(float(current["end"]), end)
                source_count += 1
                continue

            finalize(current, source_count)
            current = dict(piece)
            source_count = 1

    if current is not None:
        finalize(current, source_count)

    for index, item in enumerate(merged, start=1):
        item["chunk_id"] = format_chunk_id(index)

    save_json(merged, output_json)
    logger.info("Merged %s diarization rows into %s chunks (F0-gate blocked %s same-label merges)", len(ordered), len(merged), f0_blocks)
    return merged


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge nearby same-speaker diarization segments into chunk spans (F0-gated).")
    parser.add_argument("input_json")
    parser.add_argument("output_json")
    parser.add_argument("--gap-threshold", type=float, default=0.5)
    parser.add_argument("--min-chunk-sec", type=float, default=0.0)
    parser.add_argument("--max-chunk-sec", type=float, default=0.0)
    parser.add_argument("--dialogue-audio", default=None)
    parser.add_argument("--f0-gate-hz", type=float, default=50.0)
    parser.add_argument("--short-absorb-sec", type=float, default=0.0)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    merge_speaker_chunks(
        args.input_json,
        args.output_json,
        gap_threshold=args.gap_threshold,
        min_chunk_sec=args.min_chunk_sec,
        max_chunk_sec=args.max_chunk_sec,
        dialogue_audio=args.dialogue_audio,
        f0_gate_hz=args.f0_gate_hz,
        short_absorb_sec=args.short_absorb_sec,
    )


if __name__ == "__main__":
    main()
