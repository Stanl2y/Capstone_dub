# 청크마다 감정을 정확히 — 오디오 톤힌트 + 대사 + 장면을 LLM 으로 융합해 emotion.json 을 전면 재분류(in-place rewrite)
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from common import get_logger, load_env_file, load_json, save_json
from extract_emotion import EMOTION_HINTS, _normalize_label
from translate_chunks import _strip_json_wrappers, _translate_with_vectorengine_api

logger = get_logger("fuse_emotion_text")

LABELS = ["angry", "disgusted", "fearful", "happy", "neutral", "sad", "surprised", "other", "unknown"]
# LLM 불가 시 폴백 — 부정/긴급 어휘가 보이면 audio-happy 만 보수적으로 강등
_NEG_LEXICON = re.compile(
    r"\b(die|died|dying|dead|death|kill|killed|killing|bleed|bleeding|blood|hurt|pain|"
    r"help|emergency|911|wrong|stop|no\b|don't|can't|never|lose|losing|lost|"
    r"scared|afraid|terrified|panic|hate|angry|fault|sorry|cry|crying|hospital|injured|wound)\b",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _audio_label(row: dict[str, Any]) -> str:
    se = row.get("source_emotion")
    if not isinstance(se, dict):
        return "unknown"
    return str(se.get("label", "") or "").strip().lower() or "unknown"


def _audio_top3(row: dict[str, Any]) -> list[dict[str, Any]]:
    se = row.get("source_emotion") or {}
    scores = se.get("scores") if isinstance(se, dict) else None
    if not isinstance(scores, dict):
        return []
    ranked = sorted(((str(k), float(v)) for k, v in scores.items()), key=lambda x: -x[1])[:3]
    return [{"label": k, "score": round(v, 3)} for k, v in ranked]


def _scene_dialogue(asr_text: dict[str, str], emotion_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in emotion_rows:
        cid = str(r.get("chunk_id", "") or "")
        line = _normalize_text(asr_text.get(cid, ""))
        if line:
            out.append({"chunk_id": cid, "line": line})
    return out


_SYSTEM_PROMPT = (
    "You are an emotion annotator for film dubbing. For EACH line, output the single most accurate emotion of how "
    "that line is spoken in the scene.\n"
    "\n"
    "You are given three signals per line:\n"
    "1. the line text (current_line) and its neighbours — the MEANING.\n"
    "2. scene_dialogue — the whole scene, for situational context (e.g. medical emergency, argument, tender moment, lecture, comedy).\n"
    "3. audio_hint — the top guesses of an ACOUSTIC classifier. It captures vocal tone/energy but is UNRELIABLE on valence: "
    "it frequently labels urgent/loud/animated negative or neutral speech as 'happy', and quiet tension as 'neutral'. "
    "Use it only as a weak cue for vocal tone (e.g. to catch sarcasm or genuine feeling that the words hide); never let it override clear text+scene meaning.\n"
    "\n"
    "How to decide: trust text+scene for WHAT is meant; use audio_hint for HOW it sounds. When they conflict, prefer the "
    "reading that best fits the dramatic situation. A lexically-positive line in a grim/urgent scene ('That's great' during a crisis) is NOT happy.\n"
    "\n"
    "Label space — use EXACTLY one of: angry, disgusted, fearful, happy, neutral, sad, surprised, other, unknown.\n"
    "Pick 'happy' ONLY for genuine cheer/amusement/joy/warmth. Use 'neutral' for plain factual/calm lines. "
    "ALWAYS pick the closest concrete emotion from the seven (angry, disgusted, fearful, happy, neutral, sad, surprised); "
    "a short or urgent line still has an emotion (e.g. a shouted '911!' is fearful/alarmed, a firm order is angry or neutral). "
    "Use 'other'/'unknown' ONLY for non-verbal noise or text with genuinely no discernible emotion — never as an escape from a hard call.\n"
    "\n"
    "Two common traps to avoid:\n"
    "- Short social pleasantries — greetings, self-introductions, small talk ('I'm MJ', 'Hi', 'I'm just a neighbor from across the hall') — are neutral (or happy if warm). Do NOT label them sad just because the audio_hint is low-energy.\n"
    "- Judge each line by its OWN meaning; a fragment that completes the previous line or a quiet aside should NOT automatically inherit the scene's dominant emotion. A light protest ('Come on! It was funny') is happy/amused; a resigned, helpless explanation ('He doesn't know how') is sad, not angry.\n"
    "- Distinguish the TOPIC from the DELIVERY. A calm, factual, or expository line that merely MENTIONS a dangerous/scary/sad subject ('it would be enormously dangerous', 'vulnerable to threats', a lecture about risk or death) is NEUTRAL. Do not assign fearful/sad/angry from emotional keywords — only when the speaker is actually FEELING and expressing that emotion. Single words or brief asides ('Mother', 'Rebirth', 'Nice flowers') take their plain affect in context; do not amplify them.\n"
    "\n"
    "Return ONLY minified JSON: {\"items\":[{\"chunk_id\":\"...\",\"emotion\":\"...\"}]}"
)


def _build_user_prompt(batch: list[dict[str, Any]], scene: list[dict[str, str]]) -> str:
    return json.dumps(
        {
            "task": "For each item return the single best emotion per the system prompt.",
            "scene_dialogue": scene,
            "items": batch,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _parse_llm(raw_text: str) -> dict[str, str]:
    try:
        parsed = json.loads(_strip_json_wrappers(raw_text))
    except json.JSONDecodeError:
        return {}
    items = parsed.get("items") if isinstance(parsed, dict) else None
    if not isinstance(items, list):
        return {}
    out: dict[str, str] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("chunk_id", "") or "").strip()
        emo = _normalize_label(it.get("emotion"))
        if cid and emo in LABELS:
            out[cid] = emo
    return out


def _llm_classify(
    items: list[dict[str, Any]], scene: list[dict[str, str]], *,
    api_key: str, base_url: str, endpoint: str, model_name: str, timeout_sec: int,
) -> dict[str, str]:
    raw = _translate_with_vectorengine_api(
        "", source_language="English", target_language="English",
        target_duration_sec=None, duration_budget=None, register_hint="",
        api_key=api_key, base_url=base_url, endpoint=endpoint, model_name=model_name,
        timeout_sec=min(max(1, timeout_sec), 30),
        response_format_json=True,
        system_prompt_override=_SYSTEM_PROMPT,
        user_prompt_override=_build_user_prompt(items, scene),
    )
    return _parse_llm(raw)


def _blend(audio_scores: dict[str, Any], llm_emotion: str, *, text_weight: float) -> dict[str, float]:
    """텍스트 라벨에 text_weight, 나머지를 오디오 분포로 — 라벨은 텍스트가 결정하되 오디오가 보조 분포(top-3) 형성."""
    base = {k: float(audio_scores.get(k, 0.0)) for k in LABELS}
    total_a = sum(base.values()) or 1.0
    base = {k: v / total_a for k, v in base.items()}
    fused = {k: (text_weight if k == llm_emotion else 0.0) + (1.0 - text_weight) * base[k] for k in LABELS}
    total = sum(fused.values()) or 1.0
    return {k: v / total for k, v in fused.items()}


def fuse_emotion_with_text(
    emotion_json: str | Path,
    asr_json: str | Path,
    *,
    mode: str = "vectorengine_gpt",
    env_file: str | Path = ".env",
    timeout_sec: int = 30,
    batch_size: int = 8,
    text_weight: float = 0.7,
    skip_existing: bool = True,
) -> list[dict[str, Any]]:
    rows = load_json(emotion_json)
    asr_rows = load_json(asr_json)
    asr_text = {str(r.get("chunk_id", "") or ""): _normalize_text(str(r.get("text_src", "") or "")) for r in asr_rows}
    scene = _scene_dialogue(asr_text, rows)

    api_key = base_url = endpoint = model_name = ""
    use_llm = mode == "vectorengine_gpt"
    if use_llm:
        load_env_file(env_file)
        api_key = os.environ.get("VECTORENGINE_API_KEY", "").strip()
        base_url = os.environ.get("VECTORENGINE_BASE_URL", "https://api.vectorengine.ai/").strip()
        model_name = os.environ.get("VECTORENGINE_MODEL", "gpt-5.4").strip()
        endpoint = os.environ.get("VECTORENGINE_ENDPOINT", "/v1/chat/completions").strip()
        if not api_key:
            logger.warning("VECTORENGINE_API_KEY 없음 — lexicon 폴백(happy-only)으로 동작")
            use_llm = False

    # 텍스트 있는 청크는 전부 재분류 대상
    pending = []
    for r in rows:
        cid = str(r.get("chunk_id", "") or "")
        line = asr_text.get(cid, "")
        if not line or not isinstance(r.get("source_emotion"), dict):
            continue
        if skip_existing and _already_fused(r, line):
            continue
        pending.append({"chunk_id": cid, "line": line, "audio_hint": _audio_top3(r)})

    llm_emotion: dict[str, str] = {}
    if use_llm and pending:
        for i in range(0, len(pending), max(1, batch_size)):
            batch = pending[i : i + batch_size]
            try:
                llm_emotion.update(_llm_classify(
                    batch, scene, api_key=api_key, base_url=base_url, endpoint=endpoint,
                    model_name=model_name, timeout_sec=timeout_sec,
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning("fuse LLM 배치 실패(%s건): %s", len(batch), exc)

    pending_ids = {p["chunk_id"] for p in pending}
    changed = kept = 0
    for r in rows:
        cid = str(r.get("chunk_id", "") or "")
        if cid not in pending_ids:
            continue
        se = r["source_emotion"]
        audio_label = str(se.get("label", "") or "").lower()
        line = asr_text.get(cid, "")
        emo = llm_emotion.get(cid)
        source = "llm"
        if emo is None:
            # 폴백 — LLM 결과 없으면 audio-happy 만 보수적으로 neutral 강등, 그 외 유지
            source = "lexicon"
            if audio_label == "happy" and _NEG_LEXICON.search(line):
                emo = "neutral"
            else:
                emo = audio_label  # 변경 없음

        if emo and emo != audio_label:
            fused = _blend(se.get("scores", {}) or {}, emo, text_weight=text_weight)
            new_label = max(fused, key=fused.get)
            se["scores"] = {k: round(v, 6) for k, v in sorted(fused.items())}
            se["label"] = new_label
            se["confidence"] = round(float(fused[new_label]), 6)
            r["tts_emotion_hint"] = EMOTION_HINTS.get(new_label, EMOTION_HINTS["unknown"])
            changed += 1
        else:
            kept += 1
        r["emotion_fusion"] = {
            "audio_label": audio_label,
            "fused_label": se["label"],
            "changed": bool(emo and emo != audio_label),
            "source": source,
            "fused_text_sig": f"{audio_label}|{line}",
        }

    save_json(rows, emotion_json)
    logger.info("Emotion 재분류: 대상 %s / 변경 %s / 유지 %s (mode=%s)", len(pending_ids), changed, kept, "llm" if use_llm else "lexicon")
    return rows


def _already_fused(row: dict[str, Any], line: str) -> bool:
    fz = row.get("emotion_fusion")
    audio_label = str((row.get("source_emotion") or {}).get("label", "") or "").lower()
    # 재분류 후 label 이 바뀌면 audio_label 이 사라지므로 sig 에 원 audio_label 을 보존해 비교
    return isinstance(fz, dict) and fz.get("fused_text_sig", "").endswith(f"|{line}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reclassify per-chunk emotion by fusing audio tone hint + dialogue text + scene.")
    parser.add_argument("emotion_json")
    parser.add_argument("asr_json")
    parser.add_argument("--mode", default="vectorengine_gpt", choices=["vectorengine_gpt", "lexicon"])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--timeout-sec", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--text-weight", type=float, default=0.7)
    parser.add_argument("--no-skip-existing", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    fuse_emotion_with_text(
        args.emotion_json,
        args.asr_json,
        mode=args.mode,
        env_file=args.env_file,
        timeout_sec=args.timeout_sec,
        batch_size=args.batch_size,
        text_weight=args.text_weight,
        skip_existing=not args.no_skip_existing,
    )


if __name__ == "__main__":
    main()
