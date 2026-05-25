# DiariZen 화자분리 파라미터 조합을 실행하고 평가 리포트를 모으는 스크립트
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from common import deep_get, load_config, load_json, project_relative, require_value, resolve_project_path, sanitize_path_component, save_json
from diarize import diarize_audio
from merge_speaker_chunks import merge_speaker_chunks
from rttm_to_json import convert_rttm_to_json
from stabilize_diarization import stabilize_diarization_file
from evaluate_diarization import evaluate_diarization, load_diarization_records, load_expectation_spec, read_audio_duration

DIARIZE_PARAM_KEYS = {
    "max_speakers",
    "min_speakers",
    "ahc_threshold",
    "ahc_criterion",
    "fa",
    "fb",
    "lda_dim",
    "max_iters",
    "method",
    "min_cluster_size",
    "seg_duration",
    "segmentation_step",
    "batch_size",
    "apply_median_filtering",
}
MODEL_PARAM_KEYS = {"model_dir", "embedding_model_dir"}
ALLOWED_PARAM_KEYS = DIARIZE_PARAM_KEYS | MODEL_PARAM_KEYS
PARAM_ALIASES = {
    "Fa": "fa",
    "Fb": "fb",
    "diarization_model": "model_dir",
    "diarization_embedding": "embedding_model_dir",
    "embedding_model": "embedding_model_dir",
}


def canonicalize_params(params: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in params.items():
        canonical = PARAM_ALIASES.get(key, key)
        if canonical not in ALLOWED_PARAM_KEYS:
            raise ValueError(f"Unknown diarization sweep parameter: {key}")
        result[canonical] = value
    return result


def base_diarization_params(config: dict[str, Any]) -> dict[str, Any]:
    diarization = config.get("diarization", {})
    params = {key: diarization.get(key) for key in DIARIZE_PARAM_KEYS if key in diarization}
    params["model_dir"] = require_value(config, ("models", "diarization"))
    params["embedding_model_dir"] = require_value(config, ("models", "diarization_embedding"))
    return params


def preset_trials(name: str) -> list[dict[str, Any]]:
    presets: dict[str, list[dict[str, Any]]] = {
        "smoke": [
            {"name": "baseline", "params": {}},
            {"name": "seg8_step005", "params": {"seg_duration": 8, "segmentation_step": 0.05}},
            {"name": "seg4_step005", "params": {"seg_duration": 4, "segmentation_step": 0.05}},
        ],
        "balanced": [
            {"name": "baseline", "params": {}},
            {"name": "seg8_step005", "params": {"seg_duration": 8, "segmentation_step": 0.05}},
            {"name": "seg4_step005", "params": {"seg_duration": 4, "segmentation_step": 0.05}},
            {"name": "seg4_no_median", "params": {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False}},
            {"name": "seg8_no_median", "params": {"seg_duration": 8, "segmentation_step": 0.05, "apply_median_filtering": False}},
            {"name": "ahc045", "params": {"ahc_threshold": 0.45}},
            {"name": "ahc055", "params": {"ahc_threshold": 0.55}},
            {"name": "vbx_fa014_fb04", "params": {"fa": 0.14, "fb": 0.4}},
            {"name": "vbx_fa007_fb04", "params": {"fa": 0.07, "fb": 0.4}},
            {"name": "lda64", "params": {"lda_dim": 64}},
            {"name": "lda192", "params": {"lda_dim": 192}},
            {"name": "cluster_min2", "params": {"min_cluster_size": 2}},
        ],
        "wide": [
            {"name": "baseline", "params": {}},
            *[
                {
                    "name": f"seg{seg}_step{str(step).replace('.', '')}_ahc{str(ahc).replace('.', '')}",
                    "params": {"seg_duration": seg, "segmentation_step": step, "ahc_threshold": ahc},
                }
                for seg, step, ahc in product([4, 8, 12, 16], [0.05, 0.1], [0.35, 0.45, 0.55])
            ],
            {"name": "seg4_no_median", "params": {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False}},
            {"name": "seg8_no_median", "params": {"seg_duration": 8, "segmentation_step": 0.05, "apply_median_filtering": False}},
            {"name": "vbx_loose", "params": {"fa": 0.14, "fb": 0.4}},
            {"name": "vbx_tight", "params": {"fa": 0.04, "fb": 0.9}},
        ],
    }
    return presets[name]


def load_trials(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.trials_file:
        data = load_json(args.trials_file)
        if isinstance(data, list):
            trials = data
        elif isinstance(data, dict):
            trials = list(data.get("trials") or [])
            fixed = canonicalize_params(data.get("fixed") or {})
            grid = data.get("grid") or {}
            if grid:
                keys = list(grid.keys())
                canonical_keys = [PARAM_ALIASES.get(key, key) for key in keys]
                for key in canonical_keys:
                    if key not in ALLOWED_PARAM_KEYS:
                        raise ValueError(f"Unknown diarization sweep parameter: {key}")
                values = [grid[key] for key in keys]
                for index, combination in enumerate(product(*values), start=1):
                    params = dict(fixed)
                    params.update({canonical_key: value for canonical_key, value in zip(canonical_keys, combination)})
                    trials.append({"name": f"grid_{index:04d}", "params": params})
        else:
            raise ValueError("Trials file must contain a list or object.")
    else:
        trials = preset_trials(args.preset)

    normalized: list[dict[str, Any]] = []
    for index, trial in enumerate(trials, start=1):
        if not isinstance(trial, dict):
            raise ValueError(f"Trial #{index} must be an object.")
        params = canonicalize_params(trial.get("params") or {})
        normalized.append({"name": str(trial.get("name") or f"trial_{index:04d}"), "params": params})
    if args.limit is not None:
        normalized = normalized[: max(0, int(args.limit))]
    return normalized


def load_manifest_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.manifest:
        data = load_json(args.manifest)
        raw_items = data.get("items") if isinstance(data, dict) else data
        if not isinstance(raw_items, list):
            raise ValueError("Manifest must contain an items list.")
        items = [dict(item) for item in raw_items]
    else:
        items = [
            {
                "id": None,
                "config": args.config,
                "input_video": args.input_video,
                "input_audio": args.input_audio,
                "reference_json": args.reference_json,
                "reference_rttm": args.reference_rttm,
                "expectations_json": args.expectations_json,
            }
        ]

    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        config_path = item.get("config") or args.config
        input_video = item.get("input_video")
        config = load_config(config_path, input_video=input_video)
        input_audio = item.get("input_audio") or deep_get(config, ("paths", "dialogue_audio"))
        if not input_audio:
            raise ValueError(f"Manifest item #{index} has no input_audio and config has no paths.dialogue_audio.")
        item_id = item.get("id") or Path(str(input_audio)).stem or f"item_{index:04d}"
        normalized.append(
            {
                "id": sanitize_path_component(str(item_id), default=f"item_{index:04d}"),
                "config_path": config_path,
                "config": config,
                "input_audio": str(input_audio),
                "reference_json": item.get("reference_json"),
                "reference_rttm": item.get("reference_rttm"),
                "expectations_json": item.get("expectations_json") or args.expectations_json,
            }
        )
    return normalized


def make_sweep_root(args: argparse.Namespace) -> Path:
    if args.output_root:
        root = resolve_project_path(args.output_root)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        root = resolve_project_path("meta/diarization_sweeps") / f"sweep_{stamp}"
    if root.exists() and any(root.iterdir()) and not args.resume and not args.dry_run:
        raise FileExistsError(f"Output root already exists. Use --resume or choose another path: {root}")
    return root


def trial_dir(root: Path, item_id: str, index: int, trial_name: str) -> Path:
    safe_name = sanitize_path_component(trial_name, default=f"trial_{index:04d}")
    return root / item_id / f"trial_{index:04d}_{safe_name}"


def stabilization_enabled(config: dict[str, Any], args: argparse.Namespace) -> bool:
    return not args.no_stabilize and bool(deep_get(config, ("diarization", "stabilization", "enabled"), False))


def merge_enabled(args: argparse.Namespace) -> bool:
    return not args.no_merge_chunks


def run_item_trial(
    *,
    item: dict[str, Any],
    trial: dict[str, Any],
    index: int,
    root: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    config = item["config"]
    merged_params = base_diarization_params(config)
    merged_params.update(trial["params"])
    out_dir = trial_dir(root, item["id"], index, trial["name"])
    output_rttm = out_dir / "diarization.rttm"
    output_json = out_dir / "diarization.json"
    output_stabilized_json = out_dir / "diarization_stabilized.json"
    output_chunks_json = out_dir / "speaker_chunks.json"
    output_eval_json = out_dir / "eval.json"
    output_params_json = out_dir / "params.json"
    started = time.perf_counter()

    if args.skip_existing and output_eval_json.exists():
        report = load_json(output_eval_json)
        return {
            "item_id": item["id"],
            "status": "skipped",
            "runtime_sec": 0.0,
            "output_dir": project_relative(out_dir),
            "eval": report,
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    save_json(merged_params, output_params_json)

    try:
        model_dir = merged_params.get("model_dir")
        embedding_model_dir = merged_params.get("embedding_model_dir")
        diarize_kwargs = {key: merged_params.get(key) for key in DIARIZE_PARAM_KEYS if key in merged_params}
        diarize_audio(
            item["input_audio"],
            output_rttm,
            model_dir=model_dir,
            embedding_model_dir=embedding_model_dir,
            device=args.device or str(deep_get(config, ("runtime", "device"), "cuda:0")),
            **diarize_kwargs,
        )
        convert_rttm_to_json(output_rttm, output_json)

        prediction_json = output_json
        if stabilization_enabled(config, args):
            stabilize_diarization_file(
                output_json,
                output_stabilized_json,
                same_speaker_gap_sec=float(deep_get(config, ("diarization", "stabilization", "same_speaker_gap_sec"), 0.1)),
                bridge_max_sec=float(deep_get(config, ("diarization", "stabilization", "bridge_max_sec"), 0.4)),
                bridge_gap_sec=float(deep_get(config, ("diarization", "stabilization", "bridge_gap_sec"), 0.25)),
                tiny_segment_sec=float(deep_get(config, ("diarization", "stabilization", "tiny_segment_sec"), 0.12)),
                absorb_gap_sec=float(deep_get(config, ("diarization", "stabilization", "absorb_gap_sec"), 0.25)),
                max_passes=int(deep_get(config, ("diarization", "stabilization", "max_passes"), 5)),
            )
            prediction_json = output_stabilized_json

        if merge_enabled(args):
            merge_speaker_chunks(
                prediction_json,
                output_chunks_json,
                gap_threshold=float(deep_get(config, ("chunking", "speaker_merge_gap_sec"), 0.5)),
                min_chunk_sec=float(deep_get(config, ("chunking", "min_chunk_sec"), 0.0)),
                max_chunk_sec=float(deep_get(config, ("chunking", "max_chunk_sec"), 0.0)),
            )

        prediction = load_diarization_records(json_path=str(prediction_json))
        reference = None
        if item.get("reference_json") or item.get("reference_rttm"):
            reference = load_diarization_records(json_path=item.get("reference_json"), rttm_path=item.get("reference_rttm"))
        report = evaluate_diarization(
            prediction,
            reference=reference,
            expectations=load_expectation_spec(item.get("expectations_json")),
            audio_duration_sec=read_audio_duration(item["input_audio"]),
            frame_step_sec=args.frame_step_sec,
            collar_sec=args.collar_sec,
            short_segment_sec=args.short_segment_sec,
        )
        save_json(report, output_eval_json)
        return {
            "item_id": item["id"],
            "status": "done",
            "runtime_sec": round(time.perf_counter() - started, 6),
            "output_dir": project_relative(out_dir),
            "eval": report,
        }
    except Exception as exc:
        return {
            "item_id": item["id"],
            "status": "failed",
            "runtime_sec": round(time.perf_counter() - started, 6),
            "output_dir": project_relative(out_dir),
            "error": str(exc),
        }


def aggregate_trial(item_results: list[dict[str, Any]]) -> dict[str, Any]:
    done = [item for item in item_results if item.get("status") in {"done", "skipped"} and item.get("eval")]
    failed_count = len(item_results) - len(done)
    ders: list[float] = []
    weighted_numerator = 0.0
    weighted_denominator = 0.0
    short_ratios: list[float] = []
    switches: list[float] = []
    targeted_scores: list[float] = []
    targeted_errors: list[float] = []
    speaker_identity_scores: list[float] = []
    speaker_identity_errors: list[float] = []
    targeted_expectation_count = 0
    targeted_failed_expectation_count = 0
    targeted_weighted_numerator = 0.0
    targeted_weighted_denominator = 0.0
    runtimes = [float(item.get("runtime_sec", 0.0) or 0.0) for item in item_results]

    for item in done:
        report = item["eval"]
        prediction = report.get("prediction") or {}
        short_ratios.append(float(prediction.get("short_segment_ratio", 0.0) or 0.0))
        switches.append(float(prediction.get("switches_per_min", 0.0) or 0.0))
        reference_metrics = report.get("reference_metrics") or {}
        der = reference_metrics.get("der")
        if der is not None:
            ders.append(float(der))
            weighted_numerator += float(reference_metrics.get("miss_sec", 0.0) or 0.0)
            weighted_numerator += float(reference_metrics.get("false_alarm_sec", 0.0) or 0.0)
            weighted_numerator += float(reference_metrics.get("confusion_sec", 0.0) or 0.0)
            weighted_denominator += float(reference_metrics.get("ref_speech_sec", 0.0) or 0.0)
        targeted = report.get("targeted_expectation_metrics") or {}
        if targeted:
            score = float(targeted.get("weighted_score", 0.0) or 0.0)
            total_weight = float(targeted.get("total_weight", 0.0) or 0.0)
            targeted_error = targeted.get("targeted_error")
            targeted_scores.append(score)
            targeted_errors.append(float(targeted_error) if targeted_error is not None else 1.0)
            targeted_expectation_count += int(targeted.get("expectation_count", 0) or 0)
            targeted_failed_expectation_count += int(targeted.get("failed_count", 0) or 0)
            targeted_weighted_numerator += score * total_weight
            targeted_weighted_denominator += total_weight
            identity = targeted.get("speaker_identity_metrics") or {}
            if identity:
                speaker_identity_scores.append(float(identity.get("speaker_identity_score", 0.0) or 0.0))
                speaker_identity_error = identity.get("speaker_identity_error")
                speaker_identity_errors.append(float(speaker_identity_error) if speaker_identity_error is not None else 1.0)

    mean_short = sum(short_ratios) / len(short_ratios) if short_ratios else None
    mean_switches = sum(switches) / len(switches) if switches else None
    proxy_score = None
    if mean_short is not None and mean_switches is not None:
        proxy_score = mean_short + min(mean_switches / 120.0, 1.0)
    mean_targeted_error = sum(targeted_errors) / len(targeted_errors) if targeted_errors else None
    mean_speaker_identity_score = sum(speaker_identity_scores) / len(speaker_identity_scores) if speaker_identity_scores else None
    mean_speaker_identity_error = sum(speaker_identity_errors) / len(speaker_identity_errors) if speaker_identity_errors else None
    weighted_targeted_score = targeted_weighted_numerator / targeted_weighted_denominator if targeted_weighted_denominator > 0 else None
    combined_score = None
    if mean_targeted_error is not None and proxy_score is not None:
        combined_score = 0.75 * mean_targeted_error + 0.25 * proxy_score

    return {
        "macro_der": round(sum(ders) / len(ders), 6) if ders else None,
        "weighted_der": round(weighted_numerator / weighted_denominator, 6) if weighted_denominator > 0 else None,
        "worst_der": round(max(ders), 6) if ders else None,
        "mean_short_segment_ratio": round(mean_short, 6) if mean_short is not None else None,
        "mean_switches_per_min": round(mean_switches, 6) if mean_switches is not None else None,
        "proxy_score": round(proxy_score, 6) if proxy_score is not None else None,
        "mean_targeted_score": round(sum(targeted_scores) / len(targeted_scores), 6) if targeted_scores else None,
        "mean_targeted_error": round(mean_targeted_error, 6) if mean_targeted_error is not None else None,
        "weighted_targeted_score": round(weighted_targeted_score, 6) if weighted_targeted_score is not None else None,
        "mean_speaker_identity_score": round(mean_speaker_identity_score, 6) if mean_speaker_identity_score is not None else None,
        "mean_speaker_identity_error": round(mean_speaker_identity_error, 6) if mean_speaker_identity_error is not None else None,
        "combined_proxy_targeted_score": round(combined_score, 6) if combined_score is not None else None,
        "targeted_item_count": len(targeted_scores),
        "targeted_expectation_count": targeted_expectation_count,
        "targeted_failed_expectation_count": targeted_failed_expectation_count,
        "mean_runtime_sec": round(sum(runtimes) / len(runtimes), 6) if runtimes else 0.0,
        "failed_item_count": failed_count,
        "reference_item_count": len(ders),
    }


def trial_status(item_results: list[dict[str, Any]]) -> str:
    if all(item.get("status") == "failed" for item in item_results):
        return "failed"
    if any(item.get("status") == "failed" for item in item_results):
        return "partial"
    return "done"


def result_sort_value(result: dict[str, Any], sort_by: str) -> float:
    aggregate = result.get("aggregate") or {}
    if sort_by == "der":
        key = "macro_der"
    elif sort_by == "runtime_sec":
        key = "mean_runtime_sec"
    elif sort_by == "targeted_error":
        key = "mean_targeted_error"
    elif sort_by == "speaker_identity_error":
        key = "mean_speaker_identity_error"
    else:
        key = sort_by
    value = aggregate.get(key)
    if value is None:
        fallback = aggregate.get("proxy_score")
        return float(fallback) if fallback is not None else float("inf")
    return float(value)


def write_summary_csv(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "trial_id",
        "name",
        "status",
        "macro_der",
        "weighted_der",
        "worst_der",
        "proxy_score",
        "mean_short_segment_ratio",
        "mean_switches_per_min",
        "mean_targeted_score",
        "mean_targeted_error",
        "weighted_targeted_score",
        "mean_speaker_identity_score",
        "mean_speaker_identity_error",
        "combined_proxy_targeted_score",
        "targeted_item_count",
        "targeted_expectation_count",
        "targeted_failed_expectation_count",
        "mean_runtime_sec",
        "failed_item_count",
        "reference_item_count",
        "params_json",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for result in results:
            aggregate = result.get("aggregate") or {}
            writer.writerow(
                {
                    "trial_id": result["trial_id"],
                    "name": result["name"],
                    "status": result["status"],
                    "macro_der": aggregate.get("macro_der"),
                    "weighted_der": aggregate.get("weighted_der"),
                    "worst_der": aggregate.get("worst_der"),
                    "proxy_score": aggregate.get("proxy_score"),
                    "mean_short_segment_ratio": aggregate.get("mean_short_segment_ratio"),
                    "mean_switches_per_min": aggregate.get("mean_switches_per_min"),
                    "mean_targeted_score": aggregate.get("mean_targeted_score"),
                    "mean_targeted_error": aggregate.get("mean_targeted_error"),
                    "weighted_targeted_score": aggregate.get("weighted_targeted_score"),
                    "mean_speaker_identity_score": aggregate.get("mean_speaker_identity_score"),
                    "mean_speaker_identity_error": aggregate.get("mean_speaker_identity_error"),
                    "combined_proxy_targeted_score": aggregate.get("combined_proxy_targeted_score"),
                    "targeted_item_count": aggregate.get("targeted_item_count"),
                    "targeted_expectation_count": aggregate.get("targeted_expectation_count"),
                    "targeted_failed_expectation_count": aggregate.get("targeted_failed_expectation_count"),
                    "mean_runtime_sec": aggregate.get("mean_runtime_sec"),
                    "failed_item_count": aggregate.get("failed_item_count"),
                    "reference_item_count": aggregate.get("reference_item_count"),
                    "params_json": json.dumps(result["params"], ensure_ascii=False, sort_keys=True),
                }
            )


def run_sweep(args: argparse.Namespace) -> dict[str, Any]:
    items = load_manifest_items(args)
    trials = load_trials(args)
    root = make_sweep_root(args)
    plan = {
        "output_root": project_relative(root),
        "items": [
            {
                "id": item["id"],
                "config_path": item["config_path"],
                "input_audio": item["input_audio"],
                "reference_json": item.get("reference_json"),
                "reference_rttm": item.get("reference_rttm"),
                "expectations_json": item.get("expectations_json"),
            }
            for item in items
        ],
        "trials": trials,
    }
    if args.dry_run:
        return {"dry_run": True, "plan": plan}

    root.mkdir(parents=True, exist_ok=True)
    save_json(plan["items"], root / "manifest.json")
    save_json(trials, root / "trials.json")

    results: list[dict[str, Any]] = []
    for index, trial in enumerate(trials, start=1):
        trial_id = f"trial_{index:04d}"
        item_results = [run_item_trial(item=item, trial=trial, index=index, root=root, args=args) for item in items]
        aggregate = aggregate_trial(item_results)
        results.append(
            {
                "trial_id": trial_id,
                "name": trial["name"],
                "params": trial["params"],
                "status": trial_status(item_results),
                "aggregate": aggregate,
                "items": item_results,
            }
        )
        save_json({"results": results}, root / "summary.partial.json")

    ranked = sorted(results, key=lambda result: result_sort_value(result, args.sort_by))
    summary = {
        "output_root": project_relative(root),
        "sort_by": args.sort_by,
        "top_k": ranked[: args.top_k],
        "results": results,
        "ranked_trial_ids": [result["trial_id"] for result in ranked],
    }
    save_json(summary, root / "summary.json")
    write_summary_csv(root / "summary.csv", results)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run DiariZen parameter sweeps and evaluate diarization artifacts.")
    parser.add_argument("--config", default="configs/cosyvoice3-docker-draft.json")
    parser.add_argument("--input-video")
    parser.add_argument("--input-audio")
    parser.add_argument("--reference-json")
    parser.add_argument("--reference-rttm")
    parser.add_argument("--expectations-json")
    parser.add_argument("--manifest")
    parser.add_argument("--trials-file")
    parser.add_argument("--preset", choices=["smoke", "balanced", "wide"], default="smoke")
    parser.add_argument("--output-root")
    parser.add_argument("--device")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    parser.add_argument("--no-stabilize", action="store_true")
    parser.add_argument("--no-merge-chunks", action="store_true")
    parser.add_argument(
        "--sort-by",
        choices=[
            "der",
            "macro_der",
            "worst_der",
            "proxy_score",
            "targeted_error",
            "speaker_identity_error",
            "combined_proxy_targeted_score",
            "runtime_sec",
        ],
        default="macro_der",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--frame-step-sec", type=float, default=0.05)
    parser.add_argument("--collar-sec", type=float, default=0.25)
    parser.add_argument("--short-segment-sec", type=float, default=0.5)
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    summary = run_sweep(args)
    print(json.dumps(summary if args.dry_run else {"output_root": summary["output_root"], "top_k": summary["top_k"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
