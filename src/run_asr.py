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


def _boost_subchunk_chunks(
    chunk_records: list[dict[str, Any]],
    *,
    volume: float,
    win_sec: float,
    hop_sec: float,
    boost_area: tuple[float, float] | None,
    workdir: Path,
) -> list[dict[str, Any]]:
    # E:\TTS_capstone 의 boost_subchunk_asr.py 검증 로직:
    #   짧은 외침 (Adam! 같은) 을 잡기 위해 volume 3x boost + sub-chunk (4s window,
    #   3s hop, 1s overlap) 로 분할 → 보강 transcripts 생성.
    # test5: 141 → 156 words (+15 fresh, Adam x2 detect).
    #
    # 여기서는 boost된 wav를 새 chunk_records로 추가만 한다 — 메인 transcribe
    # 호출이 그 위에서 그대로 동작. 다운스트림은 chunk_id (suffix _boost)로 구분.
    import subprocess
    if not boost_area:
        return list(chunk_records)
    area_start, area_end = boost_area
    workdir.mkdir(parents=True, exist_ok=True)

    extra: list[dict[str, Any]] = []
    for rec in chunk_records:
        start = float(rec.get("start", 0.0))
        end = float(rec.get("end", 0.0))
        if end <= area_start or start >= area_end:
            continue  # outside boost area
        wav = resolve_project_path(rec["wav"])
        # 4s window, 3s hop sub-chunks
        t = max(start, area_start)
        idx = 0
        while t < min(end, area_end):
            sub_start = t
            sub_end = min(t + win_sec, end, area_end)
            if sub_end - sub_start < 0.5:
                break
            sub_wav = workdir / f"{Path(wav).stem}_boost_{idx:03d}.wav"
            # ffmpeg: cut + boost
            cmd = [
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{sub_start - start:.3f}",
                "-t", f"{sub_end - sub_start:.3f}",
                "-i", str(wav),
                "-filter:a", f"volume={volume}",
                str(sub_wav),
            ]
            rc = subprocess.run(cmd).returncode
            if rc == 0 and sub_wav.exists():
                extra.append({
                    **rec,
                    "chunk_id": f"{rec['chunk_id']}_boost{idx:03d}",
                    "wav": str(sub_wav),
                    "start": sub_start,
                    "end": sub_end,
                    "duration": sub_end - sub_start,
                    "from_boost": True,
                })
            idx += 1
            t += hop_sec
    logger.info("boost_subchunk: produced %s extra sub-chunks (volume=%s, win=%s, hop=%s, area=%s)",
                len(extra), volume, win_sec, hop_sec, boost_area)
    return list(chunk_records) + extra


# 공백 없이 이어쓰는 언어(일본어/중국어 등)는 토큰을 붙이고, 그 외(영어 등)는 공백으로 잇는다.
_NO_SPACE_LANGS = ("japan", "ja", "jp", "chin", "zh", "mandarin", "cantonese", "yue")


def _join_tokens(tokens: list[str], language: str | None) -> str:
    lang = (language or "").strip().lower()
    sep = "" if any(k in lang for k in _NO_SPACE_LANGS) else " "
    return sep.join(t.strip() for t in tokens if t and t.strip()).strip()


def _assign_words_viterbi(
    tokens: list[tuple[str, float, float]],
    chunk_records: list[dict[str, Any]],
    *,
    switch: float = 0.4,
    pause_th: float = 0.8,
) -> dict[str, list[str]]:
    """통짜 전사 단어를 청크에 분배한다 — 화자인지 Viterbi.
    청크 speaker 라벨로 단어별 화자 커버리지를 구하고, switch penalty(실제 pause면 면제)로
    전역 최적 화자경로를 디코딩한 뒤 같은-화자 청크에 재매핑한다. 동시발화 엉킴·경계 cascade를 막는다.
    (검증: 5영상 judge 9.4/10, 하드영상 단독 1위. 단순 스냅/중점은 이웃침범·순서뒤집힘·cascade 발생.)"""
    buckets: dict[str, list[str]] = {str(c["chunk_id"]): [] for c in chunk_records}
    if not tokens or not chunk_records:
        return buckets
    ws = sorted(tokens, key=lambda t: t[1])

    def ov(a0, a1, b0, b1):
        return max(0.0, min(a1, b1) - max(a0, b0))

    def dist(t, c):
        cs, ce = float(c.get("start") or 0.0), float(c.get("end") or 0.0)
        return cs - t if t < cs else (t - ce if t > ce else 0.0)

    def nearest_max_overlap(a0, a1):
        best, bo = None, 0.0
        for c in chunk_records:
            o = ov(a0, a1, float(c.get("start") or 0.0), float(c.get("end") or 0.0))
            if o > bo:
                bo, best = o, c
        return best if best is not None else min(chunk_records, key=lambda c: dist((a0 + a1) / 2.0, c))

    speakers = sorted({str(c.get("speaker")) for c in chunk_records})
    if len(speakers) <= 1:  # 단일 화자 → 겹침최대(+중점 폴백)로 충분
        for text, a0, a1 in ws:
            buckets[str(nearest_max_overlap(a0, a1)["chunk_id"])].append(text)
        return buckets

    cov = []  # 단어별 화자 커버리지
    for text, a0, a1 in ws:
        wd = max(1e-6, a1 - a0)
        s = {sp: 0.0 for sp in speakers}
        for c in chunk_records:
            s[str(c.get("speaker"))] += ov(a0, a1, float(c.get("start") or 0.0), float(c.get("end") or 0.0))
        if max(s.values()) == 0.0:
            nc = min(chunk_records, key=lambda c: dist((a0 + a1) / 2.0, c))
            s[str(nc.get("speaker"))] = wd
        cov.append({sp: s[sp] / wd for sp in speakers})

    N = len(ws); INF = float("inf")
    dp = [{sp: INF for sp in speakers} for _ in range(N)]
    bp: list[dict[str, Any]] = [{sp: None for sp in speakers} for _ in range(N)]
    for sp in speakers:
        dp[0][sp] = -cov[0][sp]
    for i in range(1, N):
        gap = ws[i][1] - ws[i - 1][2]
        trans = 0.0 if gap > pause_th else switch
        for sp in speakers:
            best, bprev = INF, None
            for psp in speakers:
                cost = dp[i - 1][psp] + (0.0 if psp == sp else trans)
                if cost < best or (cost == best and psp == sp):
                    best, bprev = cost, psp
            dp[i][sp] = best - cov[i][sp]
            bp[i][sp] = bprev
    path: list[Any] = [None] * N
    path[N - 1] = min(speakers, key=lambda sp: dp[N - 1][sp])
    for i in range(N - 1, 0, -1):
        path[i - 1] = bp[i][path[i]]
    for (text, a0, a1), sp in zip(ws, path):
        cand = [c for c in chunk_records if str(c.get("speaker")) == sp] or chunk_records
        best_o, best_c = 0.0, None
        for c in cand:
            o = ov(a0, a1, float(c.get("start") or 0.0), float(c.get("end") or 0.0))
            if o > best_o:
                best_o, best_c = o, c
        c = best_c if best_c is not None else min(cand, key=lambda c: dist((a0 + a1) / 2.0, c))
        buckets[str(c["chunk_id"])].append(text)
    return buckets


def _recover_gap_tokens(
    model, audio_path, tokens, language, *,
    gap_min: float = 0.6, pad: float = 0.3, vol: float = 3.0,
    silence_dbfs: float = -55.0, max_word_dur: float = 2.0, min_word_dur: float = 0.06,
) -> list[tuple[str, float, float]]:
    """통짜 ASR이 비운 침묵 gap 을 boost 재전사해 누락 발화를 회수한다(in-process _model 재호출).
    침묵 게이트·span 필터·중복 제거 3중 가드로 환각 삽입을 막는다(팀원 gap_boost 로직 이식)."""
    import numpy as np
    import soundfile as sf
    import tempfile
    import os
    audio, sr = sf.read(str(resolve_project_path(audio_path)))
    if getattr(audio, "ndim", 1) > 1:
        audio = audio.mean(axis=1)
    total = len(audio) / sr
    ts = sorted(tokens, key=lambda t: t[1])
    gaps: list[tuple[float, float]] = []
    prev_end = 0.0
    for _t, s, e in ts:
        if s - prev_end >= gap_min:
            gaps.append((prev_end, s))
        prev_end = max(prev_end, e)
    if total - prev_end >= gap_min:
        gaps.append((prev_end, total))
    fresh: list[tuple[str, float, float]] = []
    for gs, ge in gaps:
        a, b = max(0.0, gs - pad), min(total, ge + pad)
        seg = audio[int(a * sr):int(b * sr)]
        if len(seg) < int(0.1 * sr):
            continue
        boosted = np.clip(seg * vol, -1.0, 1.0).astype("float32")
        rms = float(np.sqrt(np.mean(boosted ** 2))) if len(boosted) else 0.0
        if 20.0 * np.log10(rms + 1e-9) < silence_dbfs:  # 침묵 게이트(환각 방지)
            continue
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tmp = tf.name
        try:
            sf.write(tmp, boosted, sr)
            r = model.transcribe(audio=[tmp], language=[language] if language else None, return_time_stamps=True)
        except Exception:  # noqa: BLE001
            continue
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        for it in (_get_result_attr(r[0], "time_stamps", None) or []):
            st = _get_result_attr(it, "start_time", None)
            en = _get_result_attr(it, "end_time", None)
            if st is None or en is None:
                continue
            gst, gen = a + float(st), a + float(en)
            dur = gen - gst
            if dur > max_word_dur or dur < min_word_dur:  # span 환각 필터
                continue
            mid = (gst + gen) / 2.0
            if not (gs <= mid < ge):  # 메인이 잡은 구간 미접촉(gap 중심 단어만)
                continue
            txt = str(_get_result_attr(it, "text", "") or "")
            if not txt.strip():
                continue
            if any(t[0] == txt and abs(((t[1] + t[2]) / 2.0) - mid) < 0.5 for t in tokens):  # 중복 제거
                continue
            fresh.append((txt, gst, gen))
    if fresh:
        logger.info("gap-recovery: %s gap에서 %s 단어 회수", len(gaps), len(fresh))
    return fresh


def _transcribe_full_audio(
    chunk_records: list[dict[str, Any]],
    output_json: str | Path,
    *,
    model_dir: str | Path,
    device: str,
    dtype: str,
    language: str | None,
    audio_path: str | Path,
    forced_aligner: str | Path,
    max_inference_batch_size: int,
    max_new_tokens: int,
    features_json: str | Path | None = None,
    gap_recovery: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """전체 오디오를 1회 전사(+forced aligner word timestamp)하고 각 청크 [start,end] 에
    화자인지 Viterbi 로 단어를 분배한다. 짧은 청크를 단독 ASR 할 때 생기는 환각을
    통짜 문맥으로 막는다(검증: chunk_16/17 'さて/そうだ' 환각 → 문맥상 실제 단어로 교정)."""
    from qwen_asr import Qwen3ASRModel

    if features_json:
        chunk_features = analyze_chunk_records(chunk_records, output_json=features_json)
    else:
        chunk_features = ensure_chunk_features(chunk_records, reference_path=output_json)
    feature_map = {str(item.get("chunk_id", "")).strip(): item for item in chunk_features if item.get("chunk_id")}

    model = Qwen3ASRModel.from_pretrained(
        str(resolve_project_path(model_dir)),
        forced_aligner=str(resolve_project_path(forced_aligner)),
        dtype=_resolve_torch_dtype(dtype),
        device_map=device,
        max_inference_batch_size=max_inference_batch_size,
        max_new_tokens=max_new_tokens,
    )
    results = model.transcribe(
        audio=[str(resolve_project_path(audio_path))],
        language=[language] if language else None,
        return_time_stamps=True,
    )
    result = results[0]
    items = _get_result_attr(result, "time_stamps", None) or []
    tokens: list[tuple[str, float, float]] = []
    for it in items:
        start = _get_result_attr(it, "start_time", _get_result_attr(it, "start", None))
        end = _get_result_attr(it, "end_time", _get_result_attr(it, "end", None))
        if start is None or end is None:
            continue
        tokens.append((str(_get_result_attr(it, "text", "") or ""), float(start), float(end)))
    logger.info("Full-audio ASR: %s word timestamps over %s chunks", len(tokens), len(chunk_records))

    # 통짜가 놓친 짧은/약한 발화 회수 — 빈 gap 을 boost 재전사(in-process). 침묵·span·중복 가드로 환각 차단.
    if gap_recovery and gap_recovery.get("enabled", False):
        fresh = _recover_gap_tokens(
            model, audio_path, tokens, language,
            gap_min=float(gap_recovery.get("gap_min", 0.6)),
            pad=float(gap_recovery.get("pad", 0.3)),
            vol=float(gap_recovery.get("vol", 3.0)),
            silence_dbfs=float(gap_recovery.get("silence_dbfs", -55.0)),
            max_word_dur=float(gap_recovery.get("max_word_dur", 2.0)),
            min_word_dur=float(gap_recovery.get("min_word_dur", 0.06)),
        )
        tokens = sorted(tokens + fresh, key=lambda t: t[1])

    # 단어를 청크에 분배 — 화자인지 Viterbi(per-chunk 미사용).
    buckets = _assign_words_viterbi(tokens, chunk_records)

    lang_label = _get_result_attr(result, "language", None) or language
    asr_rows: list[dict[str, Any]] = []
    for item in chunk_records:
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
            "language": lang_label,
            "text_src": _join_tokens(buckets.get(chunk_id, []), language),
        }
        if feature:
            row["source_audio_summary"] = compact_feature_summary(feature)
        attach_stage_quality(row, "asr", assess_asr_row(row, chunk_feature=feature))
        asr_rows.append(row)

    save_json(asr_rows, output_json)
    logger.info("Saved full-audio ASR for %s chunks to %s", len(asr_rows), resolve_project_path(output_json))
    return asr_rows


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
    boost_subchunk: dict[str, Any] | None = None,
    full_audio: dict[str, Any] | None = None,
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

    # 통짜 모드 — 전체 오디오 1회 전사 후 청크에 분배(짧은 청크 환각 방지). per-chunk 경로보다 우선.
    # max_new_tokens 는 내부 180초 청크당 생성 한도라 통짜에선 크게(기본 4096) — 256이면 긴 전사가 잘린다(검증).
    if full_audio:
        return _transcribe_full_audio(
            chunk_records,
            output_json,
            model_dir=model_dir,
            device=device,
            dtype=dtype,
            language=language,
            audio_path=full_audio["audio_path"],
            forced_aligner=full_audio["forced_aligner"],
            max_inference_batch_size=max_inference_batch_size,
            max_new_tokens=int(full_audio.get("max_new_tokens", 4096)),
            features_json=features_json,
            gap_recovery=full_audio.get("gap_recovery"),
        )

    if boost_subchunk:
        # boost area=(0,30), volume=3.0, win=4s, hop=3s (1s overlap)
        chunk_records = _boost_subchunk_chunks(
            chunk_records,
            volume=float(boost_subchunk.get("volume", 3.0)),
            win_sec=float(boost_subchunk.get("win_sec", 4.0)),
            hop_sec=float(boost_subchunk.get("hop_sec", 3.0)),
            boost_area=(
                float(boost_subchunk.get("area_start", 0.0)),
                float(boost_subchunk.get("area_end", 30.0)),
            ) if boost_subchunk.get("enabled", True) else None,
            workdir=resolve_project_path(boost_subchunk.get("workdir", "audio/boost_subchunks")),
        )

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
