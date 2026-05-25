# 화자분리 산출물의 구조 지표와 기준 정답 대비 지표를 계산하는 스크립트
from __future__ import annotations

import argparse
import json
import math
import sys
import wave
from itertools import permutations
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common import load_json, resolve_project_path, save_json
from rttm_to_json import parse_rttm_line

Record = dict[str, Any]


def normalize_records(records: list[dict[str, Any]]) -> list[Record]:
    normalized: list[Record] = []
    for item in records:
        try:
            speaker = str(item["speaker"])
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            continue
        normalized.append(
            {
                "speaker": speaker,
                "start": round(start, 6),
                "end": round(end, 6),
                "duration": round(end - start, 6),
            }
        )
    normalized.sort(key=lambda item: (float(item["start"]), float(item["end"]), str(item["speaker"])))
    return normalized


def load_diarization_records(*, json_path: str | None = None, rttm_path: str | None = None) -> list[Record]:
    if bool(json_path) == bool(rttm_path):
        raise ValueError("Provide exactly one of JSON or RTTM input.")
    if json_path:
        data = load_json(json_path)
        if not isinstance(data, list):
            raise ValueError(f"Diarization JSON must contain a list: {json_path}")
        return normalize_records(data)

    assert rttm_path is not None
    path = resolve_project_path(rttm_path)
    if not path.exists():
        raise FileNotFoundError(f"RTTM file not found: {path}")
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = parse_rttm_line(line)
        if record is not None:
            records.append(record)
    return normalize_records(records)


def read_audio_duration(audio_path: str | None) -> float | None:
    if not audio_path:
        return None
    path = resolve_project_path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {path}")
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            frames = handle.getnframes()
    except wave.Error:
        return None
    if rate <= 0:
        return None
    return frames / rate


def timeline_end(records: list[Record]) -> float:
    if not records:
        return 0.0
    return max(float(item["end"]) for item in records)


def label_at(records: list[Record], time_sec: float) -> str | None:
    for item in records:
        if float(item["start"]) <= time_sec < float(item["end"]):
            return str(item["speaker"])
    return None


def is_inside_collar(time_sec: float, boundaries: list[float], collar_sec: float) -> bool:
    if collar_sec <= 0:
        return False
    return any(abs(time_sec - boundary) <= collar_sec for boundary in boundaries)


def speaker_durations(records: list[Record]) -> dict[str, float]:
    durations: dict[str, float] = {}
    for item in records:
        speaker = str(item["speaker"])
        durations[speaker] = durations.get(speaker, 0.0) + float(item["duration"])
    return {speaker: round(duration, 6) for speaker, duration in sorted(durations.items())}


def entropy(values: list[float]) -> float:
    total = sum(value for value in values if value > 0)
    if total <= 0:
        return 0.0
    result = 0.0
    for value in values:
        if value <= 0:
            continue
        probability = value / total
        result -= probability * math.log2(probability)
    return result


def evaluate_structure(records: list[Record], *, audio_duration_sec: float | None, short_segment_sec: float) -> dict[str, Any]:
    durations = [float(item["duration"]) for item in records]
    speech_sec = sum(durations)
    duration_sec = audio_duration_sec if audio_duration_sec is not None else timeline_end(records)
    minutes = max(duration_sec / 60.0, 1e-9)
    switches = 0
    for previous, current in zip(records, records[1:]):
        if str(previous["speaker"]) != str(current["speaker"]):
            switches += 1

    per_speaker = speaker_durations(records)
    speaker_entropy = entropy(list(per_speaker.values()))
    max_entropy = math.log2(len(per_speaker)) if len(per_speaker) > 1 else 0.0
    short_count = sum(1 for value in durations if value < short_segment_sec)

    return {
        "n_speakers": len(per_speaker),
        "n_segments": len(records),
        "speech_sec": round(speech_sec, 6),
        "audio_duration_sec": round(duration_sec, 6) if duration_sec is not None else None,
        "coverage_ratio": round(speech_sec / duration_sec, 6) if duration_sec and duration_sec > 0 else None,
        "short_segment_sec": short_segment_sec,
        "short_segment_count": short_count,
        "short_segment_ratio": round(short_count / len(records), 6) if records else 0.0,
        "switch_count": switches,
        "switches_per_min": round(switches / minutes, 6),
        "segments_per_min": round(len(records) / minutes, 6),
        "speaker_durations": per_speaker,
        "max_speaker_share": round(max(per_speaker.values()) / speech_sec, 6) if speech_sec > 0 and per_speaker else 0.0,
        "speaker_entropy": round(speaker_entropy, 6),
        "speaker_entropy_normalized": round(speaker_entropy / max_entropy, 6) if max_entropy > 0 else 0.0,
        "min_segment_sec": round(min(durations), 6) if durations else 0.0,
        "mean_segment_sec": round(speech_sec / len(durations), 6) if durations else 0.0,
        "max_segment_sec": round(max(durations), 6) if durations else 0.0,
    }


def collect_overlap_counts(
    reference: list[Record],
    prediction: list[Record],
    *,
    duration_sec: float,
    frame_step_sec: float,
    collar_sec: float,
) -> tuple[dict[tuple[str, str], float], list[tuple[str | None, str | None]]]:
    boundaries = sorted({float(item["start"]) for item in reference} | {float(item["end"]) for item in reference})
    overlaps: dict[tuple[str, str], float] = {}
    frames: list[tuple[str | None, str | None]] = []
    cursor = 0.0
    while cursor < duration_sec:
        time_sec = cursor + frame_step_sec / 2.0
        cursor += frame_step_sec
        if time_sec >= duration_sec or is_inside_collar(time_sec, boundaries, collar_sec):
            continue
        ref_label = label_at(reference, time_sec)
        pred_label = label_at(prediction, time_sec)
        frames.append((ref_label, pred_label))
        if ref_label is not None and pred_label is not None:
            key = (pred_label, ref_label)
            overlaps[key] = overlaps.get(key, 0.0) + frame_step_sec
    return overlaps, frames


def best_speaker_mapping(overlaps: dict[tuple[str, str], float]) -> dict[str, str]:
    pred_labels = sorted({pred for pred, _ in overlaps})
    ref_labels = sorted({ref for _, ref in overlaps})
    if not pred_labels or not ref_labels:
        return {}

    if max(len(pred_labels), len(ref_labels)) <= 8:
        best_score = -1.0
        best_mapping: dict[str, str] = {}
        if len(pred_labels) <= len(ref_labels):
            for ref_perm in permutations(ref_labels, len(pred_labels)):
                mapping = dict(zip(pred_labels, ref_perm))
                score = sum(overlaps.get((pred, ref), 0.0) for pred, ref in mapping.items())
                if score > best_score:
                    best_score = score
                    best_mapping = mapping
            return best_mapping

        for pred_perm in permutations(pred_labels, len(ref_labels)):
            mapping = {pred: ref for pred, ref in zip(pred_perm, ref_labels)}
            score = sum(overlaps.get((pred, ref), 0.0) for pred, ref in mapping.items())
            if score > best_score:
                best_score = score
                best_mapping = mapping
        return best_mapping

    pairs = sorted(overlaps.items(), key=lambda item: item[1], reverse=True)
    mapping: dict[str, str] = {}
    used_refs: set[str] = set()
    for (pred, ref), _ in pairs:
        if pred in mapping or ref in used_refs:
            continue
        mapping[pred] = ref
        used_refs.add(ref)
    return mapping


def evaluate_against_reference(
    prediction: list[Record],
    reference: list[Record],
    *,
    duration_sec: float,
    frame_step_sec: float,
    collar_sec: float,
) -> dict[str, Any]:
    overlaps, frames = collect_overlap_counts(
        reference,
        prediction,
        duration_sec=duration_sec,
        frame_step_sec=frame_step_sec,
        collar_sec=collar_sec,
    )
    mapping = best_speaker_mapping(overlaps)
    miss_sec = 0.0
    false_alarm_sec = 0.0
    confusion_sec = 0.0
    correct_sec = 0.0
    correct_nonspeech_sec = 0.0
    ref_speech_sec = 0.0

    for ref_label, pred_label in frames:
        if ref_label is not None:
            ref_speech_sec += frame_step_sec
        if ref_label is None and pred_label is None:
            correct_nonspeech_sec += frame_step_sec
        elif ref_label is not None and pred_label is None:
            miss_sec += frame_step_sec
        elif ref_label is None and pred_label is not None:
            false_alarm_sec += frame_step_sec
        elif ref_label is not None and pred_label is not None and mapping.get(pred_label) == ref_label:
            correct_sec += frame_step_sec
        else:
            confusion_sec += frame_step_sec

    der = (miss_sec + false_alarm_sec + confusion_sec) / ref_speech_sec if ref_speech_sec > 0 else None
    scored_sec = len(frames) * frame_step_sec
    return {
        "der": round(der, 6) if der is not None else None,
        "miss_sec": round(miss_sec, 6),
        "false_alarm_sec": round(false_alarm_sec, 6),
        "confusion_sec": round(confusion_sec, 6),
        "correct_speech_sec": round(correct_sec, 6),
        "correct_nonspeech_sec": round(correct_nonspeech_sec, 6),
        "ref_speech_sec": round(ref_speech_sec, 6),
        "scored_sec": round(scored_sec, 6),
        "frame_accuracy": round((correct_sec + correct_nonspeech_sec) / scored_sec, 6) if scored_sec > 0 else None,
        "speaker_count_error": len({str(item["speaker"]) for item in prediction}) - len({str(item["speaker"]) for item in reference}),
        "speaker_mapping": mapping,
    }


def load_expectation_spec(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    spec = load_json(path)
    if not isinstance(spec, dict) or not isinstance(spec.get("expectations"), list):
        raise ValueError(f"Expectation JSON must contain an expectations list: {path}")
    defaults = spec.setdefault("defaults", {})
    defaults.setdefault("min_observed_segment_sec", 0.12)
    defaults.setdefault("min_role_coverage", 0.55)
    defaults.setdefault("max_non_asr_speech_coverage", 0.25)
    defaults.setdefault("sequence_match", "subsequence")
    for index, expectation in enumerate(spec["expectations"], start=1):
        if not isinstance(expectation, dict):
            raise ValueError(f"Expectation #{index} must be an object.")
        for key in ("id", "kind", "start", "end"):
            if key not in expectation:
                raise ValueError(f"Expectation #{index} missing required key: {key}")
        start = float(expectation["start"])
        end = float(expectation["end"])
        if not math.isfinite(start) or not math.isfinite(end) or end <= start:
            raise ValueError(f"Expectation #{index} has invalid time window.")
    return spec


def overlap_segments(records: list[Record], start: float, end: float) -> list[dict[str, Any]]:
    overlaps: list[dict[str, Any]] = []
    for item in records:
        overlap_start = max(start, float(item["start"]))
        overlap_end = min(end, float(item["end"]))
        if overlap_end <= overlap_start:
            continue
        overlaps.append(
            {
                "speaker": str(item["speaker"]),
                "start": overlap_start,
                "end": overlap_end,
                "duration": overlap_end - overlap_start,
            }
        )
    overlaps.sort(key=lambda item: (float(item["start"]), float(item["end"]), str(item["speaker"])))
    return overlaps


def dominant_label(records: list[Record], start: float, end: float) -> tuple[str | None, float, float]:
    totals: dict[str, float] = {}
    for item in overlap_segments(records, start, end):
        speaker = str(item["speaker"])
        totals[speaker] = totals.get(speaker, 0.0) + float(item["duration"])
    if not totals:
        return None, 0.0, 0.0
    label, duration = max(totals.items(), key=lambda item: item[1])
    window = max(end - start, 1e-9)
    return label, duration, duration / window


def collapsed_label_sequence(records: list[Record], start: float, end: float, min_observed_segment_sec: float) -> list[str]:
    sequence: list[str] = []
    for item in overlap_segments(records, start, end):
        if float(item["duration"]) < min_observed_segment_sec:
            continue
        speaker = str(item["speaker"])
        if not sequence or sequence[-1] != speaker:
            sequence.append(speaker)
    return sequence


def contains_role_sequence(label_sequence: list[str], expected_roles: list[str], role_to_label: dict[str, str]) -> bool:
    if not expected_roles:
        return True
    if not label_sequence:
        return False

    if all(role in role_to_label for role in expected_roles):
        expected_labels = [role_to_label[role] for role in expected_roles]
    elif not role_to_label:
        return len(label_sequence) >= len(expected_roles) and len(set(label_sequence[: len(expected_roles)])) >= min(len(expected_roles), 2)
    else:
        expected_labels = [role_to_label.get(role) for role in expected_roles]

    position = 0
    for label in label_sequence:
        target = expected_labels[position]
        if target is None:
            previous_target = expected_labels[position - 1] if position > 0 else None
            next_target = next((item for item in expected_labels[position + 1 :] if item is not None), None)
            if label != previous_target and label != next_target:
                position += 1
        elif label == target:
            position += 1
        if position >= len(expected_labels):
            return True
    return False


def infer_targeted_role_mapping(prediction: list[Record], expectations: list[dict[str, Any]], min_role_coverage: float) -> tuple[dict[str, str], dict[str, str]]:
    overlaps: dict[tuple[str, str], float] = {}
    for expectation in expectations:
        if expectation.get("kind") != "single_role":
            continue
        role = str(expectation.get("role") or "")
        if not role:
            continue
        start = float(expectation["start"])
        end = float(expectation["end"])
        for item in overlap_segments(prediction, start, end):
            coverage = float(item["duration"]) / max(end - start, 1e-9)
            if coverage <= 0:
                continue
            key = (str(item["speaker"]), role)
            overlaps[key] = overlaps.get(key, 0.0) + coverage

    label_to_role = best_speaker_mapping(overlaps)
    role_to_label: dict[str, str] = {}
    for label, role in label_to_role.items():
        role_to_label.setdefault(role, label)

    for expectation in expectations:
        if expectation.get("kind") != "single_role":
            continue
        role = str(expectation.get("role") or "")
        if role in role_to_label:
            continue
        label, _, coverage = dominant_label(prediction, float(expectation["start"]), float(expectation["end"]))
        if label is not None and coverage >= min_role_coverage:
            role_to_label[role] = label
            label_to_role[label] = role
    return role_to_label, label_to_role


def align_ordered_role_sequence(label_sequence: list[str], expected_roles: list[str], role_to_label: dict[str, str]) -> list[str] | None:
    if len(label_sequence) < len(expected_roles):
        return None

    def backtrack(role_index: int, label_index: int) -> list[str] | None:
        if role_index >= len(expected_roles):
            return []
        role = expected_roles[role_index]
        expected_label = role_to_label.get(role)
        for index in range(label_index, len(label_sequence)):
            label = label_sequence[index]
            if expected_label is not None and label != expected_label:
                continue
            rest = backtrack(role_index + 1, index + 1)
            if rest is not None:
                return [label] + rest
        return None

    return backtrack(0, 0)


def evaluate_speaker_identity_metrics(
    prediction: list[Record],
    expectations: list[dict[str, Any]],
    role_to_label: dict[str, str],
    *,
    min_role_coverage: float,
    min_observed_segment_sec: float,
) -> dict[str, Any]:
    role_label_seconds: dict[str, dict[str, float]] = {}
    role_window_seconds: dict[str, float] = {}
    ordered_evidence: dict[str, dict[str, float]] = {}
    expected_roles: set[str] = set()

    for expectation in expectations:
        kind = expectation.get("kind")
        if kind == "single_role":
            role = str(expectation.get("role") or "")
            if not role:
                continue
            expected_roles.add(role)
            start = float(expectation["start"])
            end = float(expectation["end"])
            role_window_seconds[role] = role_window_seconds.get(role, 0.0) + max(end - start, 0.0)
            label_seconds = role_label_seconds.setdefault(role, {})
            for item in overlap_segments(prediction, start, end):
                label = str(item["speaker"])
                label_seconds[label] = label_seconds.get(label, 0.0) + float(item["duration"])
        elif kind == "ordered_roles":
            roles = [str(role) for role in expectation.get("roles") or []]
            expected_roles.update(role for role in roles if role)
            sequence = collapsed_label_sequence(
                prediction,
                float(expectation["start"]),
                float(expectation["end"]),
                min_observed_segment_sec,
            )
            aligned = align_ordered_role_sequence(sequence, roles, role_to_label)
            if aligned is None:
                continue
            for role, label in zip(roles, aligned):
                if not role:
                    continue
                labels = ordered_evidence.setdefault(role, {})
                labels[label] = labels.get(label, 0.0) + 1.0

    per_role: list[dict[str, Any]] = []
    primary_label_by_role: dict[str, str] = {}
    timed_shares: list[float] = []
    timed_coverages: list[float] = []

    for role in sorted(expected_roles):
        label_seconds = role_label_seconds.get(role) or {}
        evidence = ordered_evidence.get(role) or {}
        speech_sec = sum(label_seconds.values())
        window_sec = role_window_seconds.get(role, 0.0)
        if label_seconds:
            primary_label, primary_sec = max(label_seconds.items(), key=lambda item: item[1])
            primary_share = primary_sec / speech_sec if speech_sec > 0 else 0.0
            primary_coverage = primary_sec / window_sec if window_sec > 0 else 0.0
            timed_shares.append(primary_share)
            timed_coverages.append(primary_coverage)
        elif evidence:
            primary_label, primary_sec = max(evidence.items(), key=lambda item: item[1])
            primary_share = None
            primary_coverage = None
        else:
            primary_label = None
            primary_sec = 0.0
            primary_share = None
            primary_coverage = None

        if primary_label is not None:
            primary_label_by_role[role] = primary_label
        per_role.append(
            {
                "role": role,
                "primary_label": primary_label,
                "expected_mapping_label": role_to_label.get(role),
                "speech_sec": round(speech_sec, 6),
                "window_sec": round(window_sec, 6),
                "primary_label_sec": round(primary_sec, 6),
                "primary_label_speech_share": round(primary_share, 6) if primary_share is not None else None,
                "primary_label_window_coverage": round(primary_coverage, 6) if primary_coverage is not None else None,
                "passes_identity_threshold": primary_share is not None and primary_share >= min_role_coverage,
                "label_seconds": {label: round(seconds, 6) for label, seconds in sorted(label_seconds.items())},
                "ordered_label_evidence": {label: round(count, 6) for label, count in sorted(evidence.items())},
            }
        )

    label_to_roles: dict[str, list[str]] = {}
    for role, label in primary_label_by_role.items():
        label_to_roles.setdefault(label, []).append(role)
    label_to_roles = {label: sorted(roles) for label, roles in sorted(label_to_roles.items())}
    mapped_role_count = len(primary_label_by_role)
    distinct_label_count = len(label_to_roles)
    distinctness = distinct_label_count / mapped_role_count if mapped_role_count else 0.0
    mean_share = sum(timed_shares) / len(timed_shares) if timed_shares else None
    mean_coverage = sum(timed_coverages) / len(timed_coverages) if timed_coverages else None
    identity_score = (mean_share if mean_share is not None else distinctness) * distinctness

    return {
        "expected_role_count": len(expected_roles),
        "mapped_role_count": mapped_role_count,
        "distinct_primary_label_count": distinct_label_count,
        "role_label_distinctness": round(distinctness, 6),
        "mean_primary_label_speech_share": round(mean_share, 6) if mean_share is not None else None,
        "mean_primary_label_window_coverage": round(mean_coverage, 6) if mean_coverage is not None else None,
        "speaker_identity_score": round(identity_score, 6),
        "speaker_identity_error": round(1.0 - identity_score, 6),
        "primary_label_by_role": primary_label_by_role,
        "label_to_roles": label_to_roles,
        "confused_labels": {label: roles for label, roles in label_to_roles.items() if len(roles) > 1},
        "unmapped_roles": sorted(role for role in expected_roles if role not in primary_label_by_role),
        "per_role": per_role,
    }


def evaluate_targeted_expectations(prediction: list[Record], spec: dict[str, Any]) -> dict[str, Any]:
    defaults = spec.get("defaults") or {}
    min_observed = float(defaults.get("min_observed_segment_sec", 0.12))
    min_role_coverage = float(defaults.get("min_role_coverage", 0.55))
    max_non_asr_coverage = float(defaults.get("max_non_asr_speech_coverage", 0.25))
    expectations = list(spec.get("expectations") or [])
    role_to_label, label_to_role = infer_targeted_role_mapping(prediction, expectations, min_role_coverage)
    speaker_identity_metrics = evaluate_speaker_identity_metrics(
        prediction,
        expectations,
        role_to_label,
        min_role_coverage=min_role_coverage,
        min_observed_segment_sec=min_observed,
    )

    details: list[dict[str, Any]] = []
    by_kind: dict[str, dict[str, float]] = {}
    passed_weight = 0.0
    total_weight = 0.0
    passed_count = 0
    failed_count = 0

    for expectation in expectations:
        kind = str(expectation["kind"])
        start = float(expectation["start"])
        end = float(expectation["end"])
        weight = float(expectation.get("weight", 1.0))
        total_weight += weight
        kind_stats = by_kind.setdefault(kind, {"passed": 0.0, "total": 0.0, "passed_weight": 0.0, "total_weight": 0.0})
        kind_stats["total"] += 1
        kind_stats["total_weight"] += weight

        label, label_sec, coverage = dominant_label(prediction, start, end)
        sequence = collapsed_label_sequence(prediction, start, end, min_observed)
        mapped_sequence = [label_to_role.get(item, f"unmapped:{item}") for item in sequence]
        passed = False
        observed: dict[str, Any] = {
            "dominant_label": label,
            "dominant_sec": round(label_sec, 6),
            "dominant_coverage": round(coverage, 6),
            "label_sequence": sequence,
            "mapped_sequence": mapped_sequence,
        }

        if kind == "single_role":
            expected_role = str(expectation.get("role") or "")
            mapped_role = label_to_role.get(label or "")
            passed = mapped_role == expected_role and coverage >= min_role_coverage
            observed["expected_role"] = expected_role
            observed["mapped_role"] = mapped_role
        elif kind == "ordered_roles":
            expected_roles = [str(role) for role in expectation.get("roles") or []]
            passed = contains_role_sequence(sequence, expected_roles, role_to_label)
            observed["expected_roles"] = expected_roles
        elif kind == "non_asr":
            speech_sec = sum(float(item["duration"]) for item in overlap_segments(prediction, start, end))
            speech_coverage = speech_sec / max(end - start, 1e-9)
            passed = speech_coverage <= max_non_asr_coverage
            observed["speech_sec"] = round(speech_sec, 6)
            observed["speech_coverage"] = round(speech_coverage, 6)
            observed["max_speech_coverage"] = max_non_asr_coverage
        else:
            observed["error"] = f"Unsupported expectation kind: {kind}"

        if passed:
            passed_count += 1
            passed_weight += weight
            kind_stats["passed"] += 1
            kind_stats["passed_weight"] += weight
        else:
            failed_count += 1

        details.append(
            {
                "id": expectation.get("id"),
                "chunk_id": expectation.get("chunk_id"),
                "kind": kind,
                "passed": passed,
                "weight": weight,
                "start": start,
                "end": end,
                "observed": observed,
            }
        )

    for stats in by_kind.values():
        stats["score"] = round(stats["passed"] / stats["total"], 6) if stats["total"] else 0.0
        stats["weighted_score"] = round(stats["passed_weight"] / stats["total_weight"], 6) if stats["total_weight"] else 0.0

    score = passed_count / len(expectations) if expectations else 0.0
    weighted_score = passed_weight / total_weight if total_weight > 0 else 0.0
    return {
        "score": round(score, 6),
        "weighted_score": round(weighted_score, 6),
        "targeted_error": round(1.0 - weighted_score, 6),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "expectation_count": len(expectations),
        "passed_weight": round(passed_weight, 6),
        "total_weight": round(total_weight, 6),
        "by_kind": by_kind,
        "role_mapping": role_to_label,
        "label_mapping": label_to_role,
        "speaker_identity_metrics": speaker_identity_metrics,
        "failures": [item for item in details if not item["passed"]],
        "details": details,
    }


def evaluate_diarization(
    prediction: list[Record],
    *,
    reference: list[Record] | None = None,
    expectations: dict[str, Any] | None = None,
    audio_duration_sec: float | None = None,
    frame_step_sec: float = 0.05,
    collar_sec: float = 0.25,
    short_segment_sec: float = 0.5,
) -> dict[str, Any]:
    duration_sec = audio_duration_sec or max(timeline_end(prediction), timeline_end(reference or []))
    report: dict[str, Any] = {
        "reference_metrics_available": reference is not None,
        "targeted_expectation_metrics_available": expectations is not None,
        "params": {
            "frame_step_sec": frame_step_sec,
            "collar_sec": collar_sec,
            "short_segment_sec": short_segment_sec,
        },
        "prediction": evaluate_structure(prediction, audio_duration_sec=duration_sec, short_segment_sec=short_segment_sec),
    }
    if reference is not None:
        report["reference"] = evaluate_structure(reference, audio_duration_sec=duration_sec, short_segment_sec=short_segment_sec)
        report["reference_metrics"] = evaluate_against_reference(
            prediction,
            reference,
            duration_sec=duration_sec,
            frame_step_sec=frame_step_sec,
            collar_sec=collar_sec,
        )
    else:
        report["reference_metrics"] = None
    report["targeted_expectation_metrics"] = evaluate_targeted_expectations(prediction, expectations) if expectations is not None else None
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate diarization JSON/RTTM artifacts.")
    prediction = parser.add_mutually_exclusive_group(required=True)
    prediction.add_argument("--prediction-json")
    prediction.add_argument("--prediction-rttm")
    reference = parser.add_mutually_exclusive_group()
    reference.add_argument("--reference-json")
    reference.add_argument("--reference-rttm")
    parser.add_argument("--audio")
    parser.add_argument("--output-json")
    parser.add_argument("--expectations-json")
    parser.add_argument("--frame-step-sec", type=float, default=0.05)
    parser.add_argument("--collar-sec", type=float, default=0.25)
    parser.add_argument("--short-segment-sec", type=float, default=0.5)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    prediction = load_diarization_records(json_path=args.prediction_json, rttm_path=args.prediction_rttm)
    reference = None
    if args.reference_json or args.reference_rttm:
        reference = load_diarization_records(json_path=args.reference_json, rttm_path=args.reference_rttm)
    report = evaluate_diarization(
        prediction,
        reference=reference,
        expectations=load_expectation_spec(args.expectations_json),
        audio_duration_sec=read_audio_duration(args.audio),
        frame_step_sec=args.frame_step_sec,
        collar_sec=args.collar_sec,
        short_segment_sec=args.short_segment_sec,
    )
    if args.output_json:
        save_json(report, args.output_json)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
