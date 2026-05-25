# 화자분리 교정 결과를 TEST 기대값으로 채점하고 baseline과 비교하는 측정 루프
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import evaluate_diarization as ev
from common import load_json

DEFAULT_EXPECTATIONS = "references/diarization_expectations/TEST.json"
DEFAULT_AUDIO = "audio/77506256_TEST/dialogue.wav"
DEFAULT_BASELINE_EVAL = "meta/77506256_TEST/eval_baseline.json"


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    tm = report.get("targeted_expectation_metrics") or {}
    sim = tm.get("speaker_identity_metrics") or {}
    return {
        "speaker_identity_error": sim.get("speaker_identity_error"),
        "weighted_score": tm.get("weighted_score"),
        "targeted_error": tm.get("targeted_error"),
        "n_speakers": (report.get("prediction") or {}).get("n_speakers"),
        "by_kind": {k: v.get("score") for k, v in (tm.get("by_kind") or {}).items()},
        "confused_labels": sim.get("confused_labels") or {},
        "unmapped_roles": sim.get("unmapped_roles") or [],
        "fail_ids": [f.get("id") for f in (tm.get("failures") or [])],
    }


def evaluate_chunks(chunks_json: str, expectations_json: str, audio: str | None) -> dict[str, Any]:
    prediction = ev.load_diarization_records(json_path=chunks_json)
    spec = ev.load_expectation_spec(expectations_json)
    audio_dur = ev.read_audio_duration(audio) if audio else None
    return ev.evaluate_diarization(prediction, expectations=spec, audio_duration_sec=audio_dur)


def _fmt(value: Any) -> str:
    return f"{value:.4f}" if isinstance(value, (int, float)) else str(value)


def _arrow(cur: float | None, base: float | None, lower_is_better: bool) -> str:
    # 북극성(speaker_identity_error 등)은 낮을수록 좋음. baseline 대비 개선/악화 표시.
    if cur is None or base is None:
        return ""
    delta = cur - base
    if abs(delta) < 1e-9:
        return "= same"
    better = (delta < 0) if lower_is_better else (delta > 0)
    mark = "BETTER" if better else "WORSE"
    return f"{mark} ({delta:+.4f})"


def main() -> None:
    parser = argparse.ArgumentParser(description="화자분리 교정안을 채점하고 baseline과 비교한다.")
    parser.add_argument("--chunks", required=True, help="평가할 speaker_chunks JSON (교정안)")
    parser.add_argument("--label", default="candidate", help="출력에 표시할 이름")
    parser.add_argument("--expectations", default=DEFAULT_EXPECTATIONS)
    parser.add_argument("--audio", default=DEFAULT_AUDIO)
    parser.add_argument("--baseline-eval", default=DEFAULT_BASELINE_EVAL, help="비교할 baseline eval JSON")
    parser.add_argument("--output-json", help="이번 평가 리포트를 저장할 경로(선택)")
    args = parser.parse_args()

    report = evaluate_chunks(args.chunks, args.expectations, args.audio)
    if args.output_json:
        from common import save_json
        save_json(report, args.output_json)

    cur = summarize(report)
    base = None
    base_path = Path(args.baseline_eval)
    if base_path.exists():
        base = summarize(load_json(args.baseline_eval))

    print(f"=== {args.label} vs baseline ===")
    if base is not None:
        print(f"  speaker_identity_error : {_fmt(cur['speaker_identity_error'])}  (base {_fmt(base['speaker_identity_error'])})  {_arrow(cur['speaker_identity_error'], base['speaker_identity_error'], lower_is_better=True)}  <- NORTH STAR")
        print(f"  weighted_score         : {_fmt(cur['weighted_score'])}  (base {_fmt(base['weighted_score'])})  {_arrow(cur['weighted_score'], base['weighted_score'], lower_is_better=False)}")
        print(f"  targeted_error         : {_fmt(cur['targeted_error'])}  (base {_fmt(base['targeted_error'])})")
    else:
        print(f"  speaker_identity_error : {_fmt(cur['speaker_identity_error'])}  <- NORTH STAR")
        print(f"  weighted_score         : {_fmt(cur['weighted_score'])}")
    print(f"  n_speakers             : {cur['n_speakers']}" + (f"  (base {base['n_speakers']})" if base else ""))
    print(f"  by_kind                : {cur['by_kind']}")
    print(f"  confused_labels        : {cur['confused_labels']}")
    print(f"  unmapped_roles         : {cur['unmapped_roles']}")
    print(f"  fail_ids               : {cur['fail_ids']}")


if __name__ == "__main__":
    main()
