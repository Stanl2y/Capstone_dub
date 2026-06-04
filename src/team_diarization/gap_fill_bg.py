# 화자분리 gap 에서 놓친 발화를 복구하고, 메인과 안 닮은 목소리는 SPEAKER_BG 로 라벨링.
"""팀원 레포(yujin1103/AI_dubbing_system @ fc39b5d) repair_patches/gap_fill.py 의
gap-recovery + SPEAKER_BG 부분을 우리 Segment 리스트 기반으로 이식한 것이다.

알고리즘은 그대로 보존한다.
  1. 메인 화자별 centroid(가장 긴 segment, ERes2NetV2 임베딩) 추출.
  2. segment 사이/앞뒤의 gap(>= gap_min) 검출.
  3. gap 안에 있는 단어(whisperx 전체 단어 목록에서)를 fresh 발화로 보고,
     단어 ± pad chunk 의 임베딩을 메인 centroid 와 cosine 비교.
       - sim >= sim_main_match → 그 메인 화자로 복구(놓친 발화 회수).
       - 아니면 → 임시 _raw_bg.
  4. _raw_bg 끼리 cosine >= bg_merge 면 union → SPEAKER_BG_xx.
  5. 복구/BG segment 를 기존 segment 리스트에 추가.

팀원 원본과 다른 점은 입력뿐이다. 원본은 gap 마다 ASR 데몬(:8902)을 호출하지만,
우리 어댑터는 이미 whisperx 로 전체 단어 타임스탬프를 갖고 있어 그걸 재사용한다.
임베딩은 어댑터가 로드한 ERes2NetV2 extract 함수를 그대로 쓴다.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np

from common import get_logger

logger = get_logger("team_diarization.gap_fill_bg")


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))


def _cluster_bgs(bgs: list[tuple[str, np.ndarray]], *, bg_merge: float) -> dict[str, str]:
    """bgs: [(id, emb)]. cosine >= bg_merge 면 union. {old_id: SPEAKER_BG_xx} 반환."""
    if not bgs:
        return {}
    labels = list(range(len(bgs)))

    def find(i: int) -> int:
        while labels[i] != i:
            labels[i] = labels[labels[i]]
            i = labels[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            labels[max(ri, rj)] = min(ri, rj)

    for i in range(len(bgs)):
        for j in range(i + 1, len(bgs)):
            if _cosine(bgs[i][1], bgs[j][1]) >= bg_merge:
                union(i, j)

    root_to_label: dict[int, str] = {}
    out: dict[str, str] = {}
    for i, (bid, _) in enumerate(bgs):
        r = find(i)
        if r not in root_to_label:
            root_to_label[r] = f"SPEAKER_BG_{len(root_to_label):02d}"
        out[bid] = root_to_label[r]
    return out


def gap_fill_bg(
    segments: list,
    audio: np.ndarray,
    sample_rate: int,
    extract_emb: Callable,
    words: list[dict[str, Any]],
    *,
    segment_factory: Callable,
    gap_min: float = 1.5,
    pad: float = 0.2,
    sim_main_match: float = 0.50,
    bg_merge: float = 0.40,
    min_seg_sec: float = 0.4,
    overlap_max: float = 0.5,
) -> dict[str, Any]:
    """gap 발화 복구 + SPEAKER_BG 라벨링. segments 를 제자리 확장하고 통계를 반환한다.

    segment_factory(speaker, start, end, text) -> Segment 로 새 segment 를 만든다.
    """
    if not segments or not words:
        return {"recovered": 0, "background": 0, "new_segments": 0}

    total_dur = len(audio) / float(sample_rate)

    def _slice(s: float, e: float) -> np.ndarray:
        i0 = int(max(0, s * sample_rate))
        i1 = int(min(len(audio), e * sample_rate))
        return audio[i0:i1]

    # 1. 메인 centroid — 화자별 가장 긴 segment
    spk_best: dict[str, tuple[float, float, float]] = {}
    for seg in segments:
        dur = seg.end - seg.start
        if seg.speaker not in spk_best or dur > spk_best[seg.speaker][0]:
            spk_best[seg.speaker] = (dur, seg.start, seg.end)
    centroids: dict[str, np.ndarray] = {}
    for spk, (_, s, e) in spk_best.items():
        s2 = max(0.0, s - 0.5)
        e2 = min(total_dur, e + 0.5)
        if e2 - s2 < min_seg_sec:
            continue
        emb = extract_emb(_slice(s2, e2), sample_rate)
        if emb is not None:
            centroids[spk] = np.asarray(emb, dtype=np.float32)
    if not centroids:
        logger.warning("gap_fill_bg: no main centroids (ERes2NetV2 embedding unavailable) — skipping")
        return {"recovered": 0, "background": 0, "new_segments": 0, "centroids": 0}

    # 2. gap 검출
    ordered = sorted(segments, key=lambda x: x.start)
    gaps: list[tuple[float, float]] = []
    if ordered[0].start > gap_min:
        gaps.append((0.0, ordered[0].start))
    for i in range(len(ordered) - 1):
        g0, g1 = ordered[i].end, ordered[i + 1].start
        if g1 - g0 >= gap_min:
            gaps.append((g0, g1))
    if total_dur - ordered[-1].end >= gap_min:
        gaps.append((ordered[-1].end, total_dur))

    # 진단 — gap 개수와 그 안에 떨어지는 단어 수
    gap_word_count = sum(
        1 for (s, e) in gaps for w in words
        if s <= (float(w.get("start", 0.0)) + float(w.get("end", w.get("start", 0.0)))) / 2.0 < e
    )
    logger.info("gap_fill_bg: %d gaps (>= %.1fs), %d whisperx words fall inside them",
                len(gaps), gap_min, gap_word_count)
    if not gaps:
        return {"recovered": 0, "background": 0, "new_segments": 0, "n_gaps": 0, "n_gap_words": 0}

    # 3~4. gap 단어 → 메인 매칭 또는 BG
    new_specs: list[dict[str, Any]] = []  # {start,end,text,speaker(or _raw_bg)}
    raw_bgs: list[tuple[str, np.ndarray]] = []
    bg_counter = 0
    recovered = 0
    skipped_overlap = 0

    for s, e in gaps:
        for w in words:
            ws = float(w.get("start", 0.0))
            we = float(w.get("end", ws))
            mid = (ws + we) / 2.0
            if not (s <= mid < e):
                continue
            c0 = max(0.0, ws - pad)
            c1 = min(total_dur, we + pad)
            if c1 - c0 < min_seg_sec:
                continue
            # 가드 — 복구 후보가 기존 segment 와 많이 겹치면 버린다(중복 청크 방지).
            cand_len = max(1e-6, c1 - c0)
            ov_frac = 0.0
            for seg in ordered:
                ov = min(c1, seg.end) - max(c0, seg.start)
                if ov > 0:
                    ov_frac = max(ov_frac, ov / cand_len)
            if ov_frac >= overlap_max:
                skipped_overlap += 1
                continue
            emb = extract_emb(_slice(c0, c1), sample_rate)
            assigned: str | None = None
            if emb is not None:
                emb = np.asarray(emb, dtype=np.float32)
                best_spk, best_sim = None, -1.0
                for spk, cent in centroids.items():
                    sim = _cosine(emb, cent)
                    if sim > best_sim:
                        best_spk, best_sim = spk, sim
                if best_spk is not None and best_sim >= sim_main_match:
                    assigned = best_spk
                    recovered += 1
            if assigned is None:
                tid = f"_raw_bg_{bg_counter:02d}"
                bg_counter += 1
                if emb is not None:
                    raw_bgs.append((tid, emb))
                assigned = tid
            new_specs.append({"start": c0, "end": c1, "text": str(w.get("word", "")).strip(), "speaker": assigned})

    if not new_specs:
        return {"recovered": 0, "background": 0, "new_segments": 0, "n_gaps": len(gaps), "n_gap_words": gap_word_count, "skipped_overlap": skipped_overlap}

    # 4. BG inter-cluster
    bg_map = _cluster_bgs(raw_bgs, bg_merge=bg_merge)
    for spec in new_specs:
        if spec["speaker"].startswith("_raw_bg_"):
            spec["speaker"] = bg_map.get(spec["speaker"], "SPEAKER_BG_UNK")

    # 5. 기존 리스트에 추가
    for spec in new_specs:
        segments.append(segment_factory(spec["speaker"], round(spec["start"], 3), round(spec["end"], 3), spec["text"]))
    segments.sort(key=lambda x: (x.start, x.end, x.speaker))

    n_bg = len(set(s for s in (sp["speaker"] for sp in new_specs) if s.startswith("SPEAKER_BG")))
    logger.info(
        "gap_fill_bg: %d gaps -> recovered %d to main, %d background segments (%d BG speakers)",
        len(gaps), recovered, len(new_specs) - recovered, n_bg,
    )
    return {"recovered": recovered, "background": len(new_specs) - recovered, "new_segments": len(new_specs), "bg_speakers": n_bg, "n_gaps": len(gaps), "n_gap_words": gap_word_count, "skipped_overlap": skipped_overlap}
