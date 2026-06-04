# 청크별 CosyVoice instruct_text 를 LLM 으로 생성한다 — 장면 전체 문맥 + 차등 감정 강도(급박은 강하게) + 노이즈 오디오라벨은 텍스트로 오버라이드
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from common import (
    build_dub_input_signature,
    get_logger,
    load_env_file,
    load_json,
    resolve_project_path,
    save_json,
)
from translate_chunks import _strip_json_wrappers, _translate_with_vectorengine_api

logger = get_logger("generate_tts_instructions")

_END_OF_PROMPT = "<|endofprompt|>"
_DIRECTIVE_OPENER = "Please say it"
_DEFAULT_PREFIX = "You are a helpful assistant."  # CosyVoice 본가 instruct_list 26/26 가 사용하는 학습 분포 trigger — 의미상이 아니라 분포 정합 위해 강제
_CJK_RE = re.compile(r"[㐀-鿿가-힯　-〿＀-￯]")  # 한자+한글+CJK구두점(。、)+전각 — instruct 는 영어 분포에서만 학습됨(언어지시 재부여 시 잔여 구두점 제거)

# 타깃 언어 → instruct 에 넣을 중국어 언어지시(请用<X>说). CosyVoice3 의 언어/방언 제어는 중국어로 학습돼 있어
# (README 예시 请用广东话表达) 영어 "in Korean" 보다 강하게 먹힌다. tts_text(말할 내용)는 그대로 두고 발음·운율만
# 해당 언어로 조건화 → 번역은 한국어인데 말투가 중국어/영어 톤이던 문제 해결. A/B/C 청취로 확정(2026-06-04).
_LANGUAGE_DIRECTIVE_ZH = {
    "korean": "请用韩语说。", "ko": "请用韩语说。",
    "japanese": "请用日语说。", "ja": "请用日语说。", "jp": "请用日语说。",
    "english": "请用英语说。", "en": "请用英语说。",
    "german": "请用德语说。", "de": "请用德语说。",
    "spanish": "请用西班牙语说。", "es": "请用西班牙语说。",
    "french": "请用法语说。", "fr": "请用法语说。",
    "italian": "请用意大利语说。", "it": "请用意大利语说。",
    "russian": "请用俄语说。", "ru": "请用俄语说。",
    # 중국어 타깃은 모델 기본 언어 → 지시 불필요(매핑 없음 = 빈 문자열)
}


def _language_directive(target_language: str) -> str:
    return _LANGUAGE_DIRECTIVE_ZH.get((target_language or "").strip().lower(), "")


def _apply_language_directive(instruction: str, target_language: str) -> str:
    """완성된 영어 instruct_text("You are a helpful assistant. Please say it ...<|endofprompt|>") 의
    prefix 뒤에 중국어 언어지시를 삽입. sanitize 의 CJK strip 이후 단계라 안전하고 멱등하다."""
    directive = _language_directive(target_language)
    if not directive or not instruction or directive in instruction:
        return instruction
    prefix = f"{_DEFAULT_PREFIX} "
    if instruction.startswith(prefix):
        return f"{prefix}{directive}{instruction[len(prefix):]}"
    return f"{directive}{instruction}"


# LLM 실패 시에만 쓰는 폴백 — 라벨만 보는 blunt instrument 라 라벨에 충실한 중간 강도로.
# (장면/텍스트 reconciliation 은 LLM 경로에서만 일어남)
EMOTION_STYLE_FALLBACKS = {
    "angry":     "Please say it very angrily, hard and forceful.",
    "disgusted": "Please say it with strong disgust, cold and sharp.",
    "fearful":   "Please say it very frightened and frantic, breathless and fast.",
    "happy":     "Please say it very happily, bright and lively.",
    "neutral":   "Please say it calmly and evenly, in a natural conversational tone.",
    "other":     "Please say it calmly and evenly, in a natural conversational tone.",
    "sad":       "Please say it very sadly, heavy and sorrowful.",
    "surprised": "Please say it very surprised, with a sharp, startled lift.",
    "unknown":   "Please say it calmly and evenly, in a natural conversational tone.",
}


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _emotion_label(row: dict[str, Any]) -> str:
    emotion = row.get("source_emotion")
    if not isinstance(emotion, dict):
        return "unknown"
    label = str(emotion.get("label", "") or "").strip().lower()
    return label or "unknown"


def _top_emotion_scores(row: dict[str, Any], *, limit: int = 3) -> list[dict[str, Any]]:
    """source_emotion.scores 의 상위 N 개를 score 내림차순으로 반환."""
    emotion = row.get("source_emotion")
    if not isinstance(emotion, dict):
        return []
    scores = emotion.get("scores")
    if not isinstance(scores, dict):
        return []
    ranked: list[tuple[str, float]] = []
    for key, value in scores.items():
        try:
            ranked.append((str(key), float(value)))
        except (TypeError, ValueError):
            continue
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [{"label": key, "score": round(score, 4)} for key, score in ranked[:limit]]


def _adjacent_lines(rows: list[dict[str, Any]], chunk_id: str) -> tuple[str, str]:
    """master_timeline 에서 해당 chunk 의 전·후 대사 (text_src) 를 추출. 없으면 빈 문자열."""
    chunk_id = str(chunk_id or "").strip()
    if not chunk_id:
        return "", ""
    index = -1
    for i, r in enumerate(rows):
        if str(r.get("chunk_id", "")) == chunk_id:
            index = i
            break
    if index < 0:
        return "", ""
    prev_text = ""
    next_text = ""
    if index > 0:
        prev_text = _normalize_text(str(rows[index - 1].get("text_src", "") or ""))
    if index < len(rows) - 1:
        next_text = _normalize_text(str(rows[index + 1].get("text_src", "") or ""))
    return prev_text, next_text


def _scene_dialogue(all_rows: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """클립 전체 대사를 순서대로 (chunk_id, line) 리스트로 — 장면 전체 문맥용."""
    out: list[dict[str, str]] = []
    for r in all_rows or []:
        line = _normalize_text(str(r.get("text_src", "") or ""))
        if line:
            out.append({"chunk_id": str(r.get("chunk_id", "") or ""), "line": line})
    return out


def _fallback_instruction(row: dict[str, Any]) -> str:
    label = _emotion_label(row)
    directive = EMOTION_STYLE_FALLBACKS.get(label, EMOTION_STYLE_FALLBACKS["unknown"])
    return f"{_DEFAULT_PREFIX} {directive}{_END_OF_PROMPT}"


def sanitize_instruction(value: str) -> str:
    """LLM 응답이나 manual 입력을 CosyVoice 호환 형식으로 보정 — 본가 학습 분포 정합용 prefix + "Please say it" + endofprompt 강제."""
    text = _normalize_text(value)
    if not text:
        return ""
    text = text.replace("```", "").strip()
    if _CJK_RE.search(text):
        text = _CJK_RE.sub("", text)
        text = _normalize_text(text)
    if _END_OF_PROMPT in text:
        text = text.split(_END_OF_PROMPT, 1)[0].strip()
    # prefix 가 이미 있으면 떼서 본문만 남김 — 아래에서 일관 형식으로 다시 부여
    if text.lower().startswith(_DEFAULT_PREFIX.lower()):
        text = text[len(_DEFAULT_PREFIX):].strip()
    if not text:
        return ""
    if not text.lower().startswith(_DIRECTIVE_OPENER.lower()):
        text = f"{_DIRECTIVE_OPENER} {text}".strip()
    if not text.endswith(".") and not text.endswith("!"):
        text += "."
    return f"{_DEFAULT_PREFIX} {text}{_END_OF_PROMPT}"


def _parse_instruction_response(raw_text: str) -> str:
    candidate = _strip_json_wrappers(raw_text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return sanitize_instruction(raw_text)
    if not isinstance(parsed, dict):
        return ""
    return sanitize_instruction(str(parsed.get("instruct_text", "") or ""))


_SYSTEM_PROMPT = (
    "You design CosyVoice3 instruct_text directives for film dubbing.\n"
    "\n"
    "GOAL — make each line sound true to the scene's dramatic situation. The dub must carry the real "
    "emotional intensity of the moment: an urgent scene must sound urgent, a panicked line panicked, a "
    "furious line furious, a tender line tender. The reference audio keeps the speaker recognizable; "
    "your directive supplies the emotional delivery, and for high-stakes moments it SHOULD push hard.\n"
    "\n"
    "Return only a minified JSON object: {\"instruct_text\": \"...\"}.\n"
    "\n"
    "REQUIRED OUTPUT FORMAT (single line, English only):\n"
    "  You are a helpful assistant. Please say it <delivery directive>.<|endofprompt|>\n"
    "\n"
    "The exact prefix \"You are a helpful assistant.\" is mandatory — CosyVoice was trained with this "
    "trigger and behaves out-of-distribution without it. The directive must start with \"Please say it\".\n"
    "\n"
    "DIRECTIVE STYLE — the single biggest lever (verified by A/B on real CosyVoice3 output):\n"
    "LEAD with an explicit emotion word + an intensity adverb, THEN add at most ONE short acoustic clause "
    "(pace: slow/measured/rapid/breathless; volume: soft/hushed/loud; pitch & energy: low/flat/sharp). "
    "Form: \"very <emotion>, <one acoustic clause>\". This matches CosyVoice3's training distribution "
    "('say it very angrily / very sadly / very happily') and lands FAR stronger than abstract metaphor. "
    "Abstract-only directives (e.g. 'with heavy sorrowful weight') under-fire; a named emotion + 'very' fires hard.\n"
    "\n"
    "GRADED INTENSITY — calibrate to the moment; do NOT flatten, do NOT overact:\n"
    "  - calm / ordinary: 'calmly and evenly, in a natural conversational tone' (no intensity adverb).\n"
    "  - warm / tender: 'gently and warmly, soft and sincere'.\n"
    "  - high-stakes (fear, fury, grief, desperate plea, urgent command): use 'very' (or 'as ... as possible') and push hard. "
    "Reserve the STRONGEST forms for fear / anger / sadness — they fade most on emotionally neutral target text.\n"
    "\n"
    "Examples (named emotion + intensity + one acoustic clause):\n"
    "  You are a helpful assistant. Please say it very frightened and frantic, breathless and fast.<|endofprompt|>\n"
    "  You are a helpful assistant. Please say it very angrily, hard and forceful, sharp and loud.<|endofprompt|>\n"
    "  You are a helpful assistant. Please say it very sadly, heavy and sorrowful, slow and low.<|endofprompt|>\n"
    "  You are a helpful assistant. Please say it very happily, bright and lively.<|endofprompt|>\n"
    "  You are a helpful assistant. Please say it calmly and evenly, in a natural conversational tone.<|endofprompt|>\n"
    "\n"
    "How to write the directive:\n"
    "1. Read scene_dialogue to grasp the overall situation and stakes of the whole scene (e.g., a medical "
    "emergency, a chase, a heated argument, a tender moment). Let that set the baseline intensity.\n"
    "2. Read previous_line and next_line for conversational flow, and current_line for its intent "
    "(command, warning, plea, confession, reaction, taunt, question, apology).\n"
    "3. Treat emotion2vec.top_3_scores as a NOISY acoustic hint, NOT ground truth. It frequently mislabels "
    "loud or urgent speech as 'happy' or 'neutral'. When the text and scene clearly imply urgency, fear, "
    "anger, panic, or pleading, TRUST THE TEXT AND SCENE and override the acoustic label. Only lean on the "
    "acoustic label when the text is ambiguous.\n"
    "4. Write ONE directive in the DIRECTIVE STYLE above: lead with the emotion word + intensity, then at most one acoustic clause. 6-14 words, single sentence.\n"
    "5. English only. No Korean/Chinese/Japanese characters — CosyVoice3 does NOT understand directives in the output language (Korean/Chinese instruct was A/B-verified to weaken or break the delivery); English is required.\n"
    "6. Direct only HOW it is spoken (mood, energy, pace, force) — not what it means. Do not quote any text, "
    "do not include character names, do not request filler sounds, breaths, or extra wording.\n"
    "7. Output exactly: {\"instruct_text\": \"You are a helpful assistant. Please say it ...<|endofprompt|>\"}"
)


def _build_user_prompt(row: dict[str, Any], all_rows: list[dict[str, Any]] | None = None) -> str:
    chunk_id = str(row.get("chunk_id", "") or "")
    prev_line, next_line = _adjacent_lines(all_rows or [], chunk_id) if all_rows else ("", "")
    emotion = row.get("source_emotion") if isinstance(row.get("source_emotion"), dict) else {}
    payload = {
        "chunk_id": chunk_id,
        "scene_dialogue": _scene_dialogue(all_rows),
        "previous_line": prev_line,
        "current_line": _normalize_text(str(row.get("text_src", "") or "")),
        "next_line": next_line,
        "target_tts_text_language": "Korean",
        "emotion2vec": {
            "label": _emotion_label(row),
            "confidence": emotion.get("confidence") if isinstance(emotion, dict) else None,
            "top_3_scores": _top_emotion_scores(row, limit=3),
        },
        "task": "Produce ONE instruct_text following the format described in the system prompt.",
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _build_batch_user_prompt(
    rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]] | None = None,
    target_language: str = "Korean",
) -> str:
    items: list[dict[str, Any]] = []
    for row in rows:
        chunk_id = str(row.get("chunk_id", "") or "")
        prev_line, next_line = _adjacent_lines(all_rows or [], chunk_id) if all_rows else ("", "")
        emotion = row.get("source_emotion") if isinstance(row.get("source_emotion"), dict) else {}
        items.append(
            {
                "chunk_id": chunk_id,
                "previous_line": prev_line,
                "current_line": _normalize_text(str(row.get("text_src", "") or "")),
                "next_line": next_line,
                "target_tts_text_language": target_language or "Korean",
                "emotion2vec": {
                    "label": _emotion_label(row),
                    "confidence": emotion.get("confidence") if isinstance(emotion, dict) else None,
                    "top_3_scores": _top_emotion_scores(row, limit=3),
                },
            }
        )
    payload = {
        "task": "For each item, produce ONE instruct_text following the format described in the system prompt.",
        "scene_dialogue": _scene_dialogue(all_rows),
        "output_schema": {
            "items": [
                {
                    "chunk_id": "string",
                    "instruct_text": "You are a helpful assistant. Please say it ...<|endofprompt|>",
                }
            ]
        },
        "items": items,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _parse_batch_instruction_response(raw_text: str) -> dict[str, str]:
    candidate = _strip_json_wrappers(raw_text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    items = parsed.get("items")
    if not isinstance(items, list):
        single = _parse_instruction_response(raw_text)
        chunk_id = str(parsed.get("chunk_id", "") or "").strip()
        return {chunk_id: single} if chunk_id and single else {}
    output: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id", "") or "").strip()
        instruction = sanitize_instruction(str(item.get("instruct_text", "") or ""))
        if chunk_id and instruction:
            output[chunk_id] = instruction
    return output


def _generate_instruction_batch_with_llm(
    rows: list[dict[str, Any]],
    *,
    api_key: str,
    base_url: str,
    endpoint: str,
    model_name: str,
    timeout_sec: int,
    all_rows: list[dict[str, Any]] | None = None,
    target_language: str = "Korean",
) -> dict[str, str]:
    raw_response = _translate_with_vectorengine_api(
        "",
        source_language="English",
        target_language="English",
        target_duration_sec=None,
        duration_budget=None,
        register_hint="",
        api_key=api_key,
        base_url=base_url,
        endpoint=endpoint,
        model_name=model_name,
        timeout_sec=min(max(1, timeout_sec), 20),
        response_format_json=True,
        system_prompt_override=_SYSTEM_PROMPT,
        user_prompt_override=_build_batch_user_prompt(rows, all_rows=all_rows, target_language=target_language),
    )
    return _parse_batch_instruction_response(raw_response)


def preview_instruction_for_row(
    row: dict[str, Any],
    *,
    all_rows: list[dict[str, Any]] | None = None,
    env_file: str | Path = ".env",
    timeout_sec: int = 20,
    target_language: str = "Korean",
) -> tuple[str, str]:
    """단일 row 에 대해 LLM 호출 → instruction 텍스트만 받아온다. master_timeline 저장 안 함, 부수효과 없음.
    UI 의 'Preview LLM instruction' 에 호출됨.
    return: (instruction_text_with_endofprompt, source) — source 는 'llm' 또는 'fallback'."""
    load_env_file(env_file)
    api_key = os.environ.get("VECTORENGINE_API_KEY", "").strip()
    if not api_key:
        return _apply_language_directive(_fallback_instruction(row), target_language), "fallback"
    base_url = os.environ.get("VECTORENGINE_BASE_URL", "https://api.vectorengine.ai/").strip()
    model_name = os.environ.get("VECTORENGINE_MODEL", "gpt-5.4").strip()
    endpoint = os.environ.get("VECTORENGINE_ENDPOINT", "/v1/chat/completions").strip()
    try:
        results = _generate_instruction_batch_with_llm(
            [row],
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            model_name=model_name,
            timeout_sec=timeout_sec,
            all_rows=all_rows or [row],
            target_language=target_language,
        )
    except Exception as exc:
        logger.warning("preview_instruction_for_row LLM failed: %s", exc)
        return _apply_language_directive(_fallback_instruction(row), target_language), "fallback"
    chunk_id = str(row.get("chunk_id", "") or "")
    instruction = results.get(chunk_id, "")
    if instruction:
        return _apply_language_directive(instruction, target_language), "llm"
    return _apply_language_directive(_fallback_instruction(row), target_language), "fallback"


def _batched(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), max(1, size))]


def generate_tts_instructions(
    master_timeline_json: str | Path,
    *,
    mode: str = "vectorengine_gpt",
    env_file: str | Path = ".env",
    timeout_sec: int = 60,
    skip_existing: bool = True,
    fallback_on_error: bool = True,
    batch_size: int = 6,
    target_language: str = "Korean",
) -> list[dict[str, Any]]:
    rows = load_json(master_timeline_json)
    api_key = ""
    base_url = ""
    endpoint = ""
    model_name = ""

    if mode == "vectorengine_gpt":
        load_env_file(env_file)
        api_key = os.environ.get("VECTORENGINE_API_KEY", "").strip()
        base_url = os.environ.get("VECTORENGINE_BASE_URL", "https://api.vectorengine.ai/").strip()
        model_name = os.environ.get("VECTORENGINE_MODEL", "gpt-5.4").strip()
        endpoint = os.environ.get("VECTORENGINE_ENDPOINT", "/v1/chat/completions").strip()
        if not api_key and not fallback_on_error:
            raise RuntimeError(f"VECTORENGINE_API_KEY is missing. Put it in {env_file}.")
    elif mode != "fallback":
        raise ValueError(f"Unsupported instruction mode: {mode}")

    pending_rows: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        if not _normalize_text(str(row.get("text_src", "") or "")):
            row.pop("tts_instruct_text", None)
            row.pop("tts_instruct_source", None)
            row.pop("tts_instruct_error", None)
            continue
        if skip_existing and _normalize_text(str(row.get("tts_instruct_text", "") or "")):
            skipped += 1
            continue
        pending_rows.append(row)

    llm_results: dict[str, str] = {}
    batch_errors: dict[str, str] = {}
    if mode == "vectorengine_gpt" and api_key:
        for batch in _batched(pending_rows, batch_size):
            try:
                llm_results.update(
                    _generate_instruction_batch_with_llm(
                        batch,
                        api_key=api_key,
                        base_url=base_url,
                        endpoint=endpoint,
                        model_name=model_name,
                        timeout_sec=timeout_sec,
                        all_rows=rows,
                        target_language=target_language,
                    )
                )
            except Exception as exc:
                if not fallback_on_error:
                    raise
                logger.warning("Instruction LLM batch failed for %s rows: %s", len(batch), exc)
                for row in batch:
                    batch_errors[str(row.get("chunk_id", "") or "")] = str(exc)

    generated = 0
    fallback_count = 0
    for row in pending_rows:
        chunk_id = str(row.get("chunk_id", "") or "")
        instruction = llm_results.get(chunk_id, "")
        source = "llm" if instruction else "fallback"
        error = batch_errors.get(chunk_id, "")
        if mode == "vectorengine_gpt" and api_key:
            pass
        else:
            error = f"Instruction mode {mode} used without API call" if mode == "fallback" else "VECTORENGINE_API_KEY is missing"

        if not instruction:
            instruction = _fallback_instruction(row)
            fallback_count += 1
        else:
            generated += 1

        # 완성된 영어 instruct 에 타깃 언어지시(请用<X>说)를 삽입 — 한국어 등 출력 말투를 해당 언어로 조건화
        instruction = _apply_language_directive(instruction, target_language)
        row["tts_instruct_text"] = instruction
        row["tts_instruct_source"] = source
        row["tts_instruct_emotion_label"] = _emotion_label(row)
        if error:
            row["tts_instruct_error"] = error
        else:
            row.pop("tts_instruct_error", None)

        output_wav = resolve_project_path(row.get("dub_wav", ""))
        existing_signature = str(row.get("dub_input_signature", "") or "")
        current_signature = build_dub_input_signature(row, runtime=row.get("dub_runtime", {}) or {})
        if output_wav.exists() and existing_signature and existing_signature != current_signature:
            row["dub_stale"] = True

    save_json(rows, master_timeline_json)
    logger.info(
        "Prepared TTS instructions at %s | llm=%s | fallback=%s | skipped=%s",
        master_timeline_json,
        generated,
        fallback_count,
        skipped,
    )
    return rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate CosyVoice instruct_text per timeline chunk.")
    parser.add_argument("master_timeline_json")
    parser.add_argument("--mode", default="vectorengine_gpt", choices=["vectorengine_gpt", "fallback"])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout-sec", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--no-skip-existing", action="store_true")
    parser.add_argument("--no-fallback-on-error", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    generate_tts_instructions(
        args.master_timeline_json,
        mode=args.mode,
        env_file=args.env_file,
        timeout_sec=args.timeout_sec,
        skip_existing=not args.no_skip_existing,
        fallback_on_error=not args.no_fallback_on_error,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
