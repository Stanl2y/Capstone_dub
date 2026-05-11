# Run 산출물 JSON과 파일 메타데이터를 REST 응답 모델로 변환하는 서비스
from __future__ import annotations

import json
import os
import wave
from pathlib import Path
from typing import Any

from common import deep_get, load_config

from webapp.backend.app.models import (
    PIPELINE_STEPS,
    ChunkRow,
    MetricsResponse,
    PatchChunkPayload,
    RunRecord,
    StepArtifact,
    StepDetailRecord,
    StepName,
)
from webapp.backend.app.services.step_router import STEP_SERVICE, steps_in_range

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", Path(__file__).resolve().parents[4])).resolve()

_PATH_KEYS: dict[StepName, tuple[list[tuple[str, str]], list[tuple[str, str]]]] = {
    "extract_audio": ([('input video', 'input_video')], [('raw audio', 'paths.raw_audio')]),
    "separate_audio": ([('raw audio', 'paths.raw_audio')], [('dialogue audio', 'paths.dialogue_audio'), ('background audio', 'paths.bgm_audio')]),
    "diarize": ([('dialogue audio', 'paths.dialogue_audio')], [('diarization RTTM', 'paths.diarization_rttm')]),
    "rttm_to_json": ([('diarization RTTM', 'paths.diarization_rttm')], [('diarization JSON', 'paths.diarization_json')]),
    "merge_chunks": ([('diarization JSON', 'paths.diarization_json')], [('speaker chunks', 'paths.speaker_chunks_json')]),
    "cut_chunks": ([('speaker chunks', 'paths.speaker_chunks_json'), ('chunk source audio', 'audio.chunk_source')], [('chunk directory', 'paths.chunks_dir')]),
    "extract_emotion": ([('speaker chunks', 'paths.speaker_chunks_json'), ('chunk directory', 'paths.chunks_dir')], [('emotion JSON', 'paths.emotion_json')]),
    "run_asr": ([('speaker chunks', 'paths.speaker_chunks_json'), ('chunk directory', 'paths.chunks_dir')], [('ASR JSON', 'paths.asr_json')]),
    "translate": ([('ASR JSON', 'paths.asr_json')], [('translated JSON', 'paths.translated_json')]),
    "build_timeline": ([('speaker chunks', 'paths.speaker_chunks_json'), ('ASR JSON', 'paths.asr_json'), ('translated JSON', 'paths.translated_json'), ('emotion JSON', 'paths.emotion_json')], [('master timeline', 'paths.master_timeline_json')]),
    "generate_tts_instructions": ([('master timeline', 'paths.master_timeline_json')], [('master timeline', 'paths.master_timeline_json')]),
    "run_tts": ([('master timeline', 'paths.master_timeline_json')], [('dub directory', 'paths.dub_dir'), ('master timeline', 'paths.master_timeline_json')]),
    "validate_tts": ([('master timeline', 'paths.master_timeline_json'), ('dub directory', 'paths.dub_dir')], [('TTS validation JSON', 'paths.tts_validation_json'), ('master timeline', 'paths.master_timeline_json')]),
    "compose_audio": ([('master timeline', 'paths.master_timeline_json'), ('dub directory', 'paths.dub_dir'), ('background audio', 'paths.bgm_audio')], [('final dub audio', 'paths.final_dub_audio')]),
    "mux": ([('input video', 'input_video'), ('final dub audio', 'paths.final_dub_audio')], [('output video', 'paths.output_video')]),
}


def load_run_config(record: RunRecord) -> dict[str, Any]:
    return load_config(record.config_path)


def output_video_path(record: RunRecord) -> str | None:
    config = load_run_config(record)
    value = _config_value(config, "paths.output_video")
    if not value:
        return None
    path = _resolve_project_path(value)
    if not path.exists():
        return None
    return _project_relative(path)


def list_chunks(record: RunRecord) -> list[ChunkRow]:
    config = load_run_config(record)
    master_path = _config_value(config, "paths.master_timeline_json")
    master_rows = _read_json_list(master_path)
    if master_rows:
        return [_chunk_from_timeline(row) for row in master_rows if row.get("chunk_id")]

    chunk_rows = _read_json_list(_config_value(config, "paths.speaker_chunks_json"))
    if not chunk_rows:
        return []
    asr_rows = _by_chunk_id(_read_json_list(_config_value(config, "paths.asr_json")))
    translated_rows = _by_chunk_id(_read_json_list(_config_value(config, "paths.translated_json")))
    emotion_rows = _by_chunk_id(_read_json_list(_config_value(config, "paths.emotion_json")))

    rows: list[ChunkRow] = []
    for chunk in chunk_rows:
        chunk_id = str(chunk.get("chunk_id", ""))
        if not chunk_id:
            continue
        asr = asr_rows.get(chunk_id, {})
        translated = translated_rows.get(chunk_id, {})
        emotion = emotion_rows.get(chunk_id, {})
        source_emotion = emotion.get("source_emotion")
        rows.append(ChunkRow(
            chunk_id=chunk_id,
            speaker=_string_or_none(chunk.get("speaker")),
            start=_float_or_none(chunk.get("start")),
            end=_float_or_none(chunk.get("end")),
            emotion=_emotion_label(source_emotion) or _string_or_none(emotion.get("emotion")),
            source_text=_string_or_none(asr.get("text_src") or translated.get("text_src")),
            translated_text=_string_or_none(translated.get("text_translated")),
            original_audio=_string_or_none(chunk.get("wav")),
            dubbed_audio=None,
            status="queued",
            duration_original=_duration_original(chunk),
            emotion_scores=_emotion_scores(source_emotion),
        ))
    return rows


def get_chunk(record: RunRecord, chunk_id: str) -> ChunkRow | None:
    return next((row for row in list_chunks(record) if row.chunk_id == chunk_id), None)


def get_raw_chunk_row(record: RunRecord, chunk_id: str) -> dict[str, Any] | None:
    """master_timeline 의 raw dict row — preview LLM 호출 등 src/ 함수로 그대로 넘기기 위함."""
    config = load_run_config(record)
    master_path = _config_value(config, "paths.master_timeline_json")
    rows = _read_json_list(master_path)
    for row in rows:
        if str(row.get("chunk_id", "")) == chunk_id:
            return row
    return None


def infer_completed_steps(record: RunRecord) -> list[StepName]:
    config = load_run_config(record)
    output_video = _config_value(config, "paths.output_video")
    if output_video and _path_exists(output_video):
        return list(PIPELINE_STEPS)

    completed: list[StepName] = []
    for step in PIPELINE_STEPS:
        output_specs = _PATH_KEYS[step][1]
        if output_specs and all(_artifact(config, label, ref, "output").exists for label, ref in output_specs):
            completed.append(step)
    return completed


def get_step_detail(record: RunRecord, step: StepName) -> StepDetailRecord:
    config = load_run_config(record)
    step_record = next((entry for entry in record.steps if entry.name == step), None)
    input_specs, output_specs = _PATH_KEYS[step]
    inputs = [_artifact(config, label, ref, "input") for label, ref in input_specs]
    outputs = [_artifact(config, label, ref, "output") for label, ref in output_specs]
    return StepDetailRecord(
        step=step,
        status=step_record.state if step_record else None,
        service=STEP_SERVICE[step],
        inputs=[item.path for item in inputs],
        outputs=[item.path for item in outputs],
        artifacts=inputs + outputs,
        log_excerpt=read_log_lines(record, limit=80),
        error=step_record.error if step_record else None,
    )


def read_log_lines(record: RunRecord, *, limit: int = 500) -> list[str]:
    path = Path(record.log_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max(1, min(limit, 2000)):]


def get_metrics(record: RunRecord) -> MetricsResponse:
    rows = list_chunks(record)
    ratios: list[float] = []
    emotions: dict[str, int] = {}
    ready = stale = errors = validation_failures = 0
    for row in rows:
        if row.status == "done":
            ready += 1
        if row.dub_stale or row.status == "stale":
            stale += 1
        if row.status == "error" or row.error:
            errors += 1
        if row.error and "validation" in row.error.lower():
            validation_failures += 1
        if row.duration_original and row.duration_dub and row.duration_original > 0:
            ratios.append(row.duration_dub / row.duration_original)
        if row.emotion:
            emotions[row.emotion] = emotions.get(row.emotion, 0) + 1
    return MetricsResponse(
        total_chunks=len(rows),
        ready_chunks=ready,
        stale_chunks=stale,
        error_chunks=errors,
        average_duration_ratio=round(sum(ratios) / len(ratios), 3) if ratios else None,
        validation_failures=validation_failures,
        emotion_distribution=emotions,
    )


def patch_chunk(record: RunRecord, chunk_id: str, payload: PatchChunkPayload) -> ChunkRow:
    if payload.speaker is not None or payload.emotion is not None:
        raise ValueError("speaker and emotion(legacy) editing are not supported")

    config = load_run_config(record)
    master_path = _config_value(config, "paths.master_timeline_json")
    master_rows = _read_json_list(master_path)

    nothing_to_do = (
        payload.translated_text is None
        and payload.tts_instruct_text is None
        and payload.emotion_label is None
        and payload.emotion_scores is None
    )
    if nothing_to_do:
        existing = get_chunk(record, chunk_id)
        if existing is None:
            raise KeyError(chunk_id)
        return existing

    changed = False

    # 1) translated_text 변경 — translated.json + master_timeline 양쪽에 반영
    if payload.translated_text is not None:
        translated_path = _config_value(config, "paths.translated_json")
        translated_rows = _read_json_list(translated_path)
        if translated_rows:
            if _patch_translation_rows(translated_rows, chunk_id, payload.translated_text, stale=False):
                _write_json(translated_path, translated_rows)
                changed = True
        if master_rows and _patch_translation_rows(master_rows, chunk_id, payload.translated_text, stale=True):
            changed = True

    # 2) tts_instruct_text / emotion(label, scores) — master_timeline 만 갱신
    if (
        payload.tts_instruct_text is not None
        or payload.emotion_label is not None
        or payload.emotion_scores is not None
    ):
        if not master_rows:
            raise KeyError(chunk_id)
        if _patch_master_for_advanced_fields(
            master_rows,
            chunk_id,
            tts_instruct_text=payload.tts_instruct_text,
            emotion_label=payload.emotion_label,
            emotion_scores=payload.emotion_scores,
        ):
            changed = True

    if changed and master_rows:
        _write_json(master_path, master_rows)

    if not changed:
        raise KeyError(chunk_id)
    updated = get_chunk(record, chunk_id)
    if updated is None:
        raise KeyError(chunk_id)
    return updated


def _patch_master_for_advanced_fields(
    rows: list[dict[str, Any]],
    chunk_id: str,
    *,
    tts_instruct_text: str | None,
    emotion_label: str | None,
    emotion_scores: dict[str, float] | None,
) -> bool:
    for row in rows:
        if str(row.get("chunk_id", "")) != chunk_id:
            continue
        # emotion 편집 — source_emotion dict 갱신, label은 명시값 우선, 없으면 max-score로 자동
        if emotion_label is not None or emotion_scores is not None:
            existing = row.get("source_emotion") if isinstance(row.get("source_emotion"), dict) else {}
            new_emotion: dict[str, Any] = dict(existing)
            if emotion_scores is not None:
                clean_scores: dict[str, float] = {}
                for key, value in emotion_scores.items():
                    try:
                        clean_scores[str(key)] = max(0.0, min(1.0, float(value)))
                    except (TypeError, ValueError):
                        continue
                if clean_scores:
                    new_emotion["scores"] = clean_scores
                    new_emotion["confidence"] = max(clean_scores.values())
                    if emotion_label is None:
                        new_emotion["label"] = max(clean_scores.items(), key=lambda kv: kv[1])[0]
            if emotion_label is not None:
                new_emotion["label"] = str(emotion_label)
            new_emotion["source"] = "manual"
            row["source_emotion"] = new_emotion
            # 감정이 바뀌면 LLM/fallback 프롬프트는 재생성. 사용자가 직접 만든 manual instruction 은 보존.
            instruct_source = row.get("tts_instruct_source")
            if tts_instruct_text is None and instruct_source != "manual":
                row.pop("tts_instruct_text", None)
                row.pop("tts_instruct_source", None)
                row.pop("tts_instruct_emotion_label", None)
                row.pop("tts_instruct_applied", None)
                row.pop("tts_instruct_error", None)
            row["dub_stale"] = True
            row.pop("dub_input_signature", None)

        # tts_instruct_text 편집 — sanitize 로 영어/endofprompt 강제. CJK 만 있던 입력은 빈 결과 → manual 마킹 안 하고 다음 redub 가 LLM 으로 채우게
        if tts_instruct_text is not None:
            from generate_tts_instructions import sanitize_instruction
            cleaned = sanitize_instruction(tts_instruct_text)
            if cleaned:
                row["tts_instruct_text"] = cleaned
                row["tts_instruct_source"] = "manual"
            else:
                row.pop("tts_instruct_text", None)
                row.pop("tts_instruct_source", None)
            row.pop("tts_instruct_error", None)
            row.pop("tts_instruct_applied", None)
            row["dub_stale"] = True
            row.pop("dub_input_signature", None)
        return True
    return False


def mark_chunk_stale(record: RunRecord, chunk_id: str) -> None:
    config = load_run_config(record)
    master_path = _config_value(config, "paths.master_timeline_json")
    rows = _read_json_list(master_path)
    for row in rows:
        if str(row.get("chunk_id", "")) == chunk_id:
            row["dub_stale"] = True
            _write_json(master_path, rows)
            return
    raise KeyError(chunk_id)


def downstream_steps(from_step: StepName) -> list[StepName]:
    return steps_in_range(from_step, "mux")


def _patch_translation_rows(rows: list[dict[str, Any]], chunk_id: str, text: str, *, stale: bool) -> bool:
    for row in rows:
        if str(row.get("chunk_id", "")) != chunk_id:
            continue
        row["text_translated"] = text
        row["text_tts"] = text
        # 사용자가 빈 텍스트 → 번역 본문을 채워 넣은 경우 blocked 마킹 해제 — translate 단계 재실행 없이 다음 단계 진행 가능.
        if text.strip():
            row.pop("translation_blocked", None)
            row.pop("translation_blocked_reason", None)
        if stale:
            row["dub_stale"] = True
            for key in (
                "tts_instruct_text",
                "tts_instruct_source",
                "tts_instruct_emotion_label",
                "tts_instruct_error",
                "tts_instruct_applied",
                "dub_input_signature",
            ):
                row.pop(key, None)
        return True
    return False


def _chunk_from_timeline(row: dict[str, Any]) -> ChunkRow:
    source_emotion = row.get("source_emotion")
    error = _string_or_none(row.get("dub_error") or row.get("tts_validation_error") or row.get("emotion_error"))
    dubbed_audio = _string_or_none(row.get("dub_wav"))
    stale = bool(row.get("dub_stale"))
    blocked = bool(row.get("translation_blocked"))
    status = _chunk_status(error=error, stale=stale, dubbed_audio=dubbed_audio, blocked=blocked)
    return ChunkRow(
        chunk_id=str(row["chunk_id"]),
        speaker=_string_or_none(row.get("speaker")),
        start=_float_or_none(row.get("start")),
        end=_float_or_none(row.get("end")),
        emotion=_emotion_label(source_emotion) or _string_or_none(row.get("emotion")),
        source_text=_string_or_none(row.get("text_src")),
        translated_text=_string_or_none(row.get("text_translated")),
        original_audio=_string_or_none(row.get("wav")),
        dubbed_audio=dubbed_audio,
        status=status,
        dub_stale=stale,
        error=error,
        duration_original=_duration_original(row),
        duration_dub=_duration_dub(row, dubbed_audio),
        emotion_scores=_emotion_scores(source_emotion),
        tts_instruct_text=_string_or_none(row.get("tts_instruct_text")),
        tts_instruct_source=_string_or_none(row.get("tts_instruct_source")),
        translation_blocked=blocked,
        translation_blocked_reason=_string_or_none(row.get("translation_blocked_reason")),
    )


def _chunk_status(*, error: str | None, stale: bool, dubbed_audio: str | None, blocked: bool = False) -> str:
    if blocked:
        return "blocked"
    if error:
        return "error"
    if stale:
        return "stale"
    if dubbed_audio and _path_exists(dubbed_audio):
        return "done"
    return "queued"


def _artifact(config: dict[str, Any], label: str, ref: str, kind: str) -> StepArtifact:
    value = _config_value(config, ref)
    if not value:
        return StepArtifact(label=label, path="", kind=kind)
    path = _resolve_project_path(value)
    exists = path.exists()
    stat = path.stat() if exists else None
    return StepArtifact(
        label=label,
        path=_project_relative(path),
        kind=kind,
        exists=exists,
        size_bytes=stat.st_size if stat and path.is_file() else None,
        mtime=stat.st_mtime if stat else None,
    )


def _config_value(config: dict[str, Any], ref: str) -> str | None:
    if "." not in ref:
        return _string_or_none(config.get(ref))
    value = deep_get(config, tuple(ref.split(".")))
    return _string_or_none(value)


def _read_json_list(path_value: str | None) -> list[dict[str, Any]]:
    if not path_value:
        return []
    path = _resolve_project_path(path_value)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig") as fp:
        data = json.load(fp)
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_json(path_value: str | None, data: Any) -> None:
    if not path_value:
        raise ValueError("missing artifact path")
    path = _resolve_project_path(path_value)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
        fp.write("\n")
    tmp.replace(path)


def _by_chunk_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("chunk_id", "")): row for row in rows if row.get("chunk_id")}


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value)
    resolved = path if path.is_absolute() else PROJECT_ROOT / path
    resolved = resolved.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"artifact path escapes project root: {value}") from exc
    return resolved


def _project_relative(path: str | Path) -> str:
    return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()


def _path_exists(path_value: str) -> bool:
    try:
        return _resolve_project_path(path_value).exists()
    except ValueError:
        return False


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration_original(row: dict[str, Any]) -> float | None:
    direct = _float_or_none(row.get("duration") or row.get("duration_original"))
    if direct is not None:
        return direct
    start = _float_or_none(row.get("start"))
    end = _float_or_none(row.get("end"))
    if start is None or end is None:
        return None
    return round(end - start, 3)


def _duration_dub(row: dict[str, Any], dubbed_audio: str | None) -> float | None:
    for value in (
        row.get("duration_dub"),
        row.get("dub_duration"),
        deep_get(row, ("quality_gates", "tts", "metrics", "actual_duration")),
        deep_get(row, ("quality_gates", "tts_asr", "metrics", "actual_duration")),
    ):
        duration = _float_or_none(value)
        if duration is not None:
            return duration
    if not dubbed_audio:
        return None
    try:
        wav_path = _resolve_project_path(dubbed_audio)
        if not wav_path.exists():
            return None
        with wave.open(str(wav_path), "rb") as handle:
            return round(handle.getnframes() / float(handle.getframerate()), 3)
    except (OSError, wave.Error, ValueError, ZeroDivisionError):
        return None


def _emotion_label(value: Any) -> str | None:
    if isinstance(value, dict):
        return _string_or_none(value.get("label") or value.get("emotion"))
    return _string_or_none(value)


def _emotion_scores(value: Any) -> dict[str, float] | None:
    if not isinstance(value, dict):
        return None
    scores = value.get("scores")
    if not isinstance(scores, dict):
        return None
    out: dict[str, float] = {}
    for key, score in scores.items():
        parsed = _float_or_none(score)
        if parsed is not None:
            out[str(key)] = parsed
    return out or None
