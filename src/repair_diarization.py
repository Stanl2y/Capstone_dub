# DiariZen 화자분리 결과(speaker_chunks)를 실패유형별 모듈로 교정하는 스테이지
from __future__ import annotations

import argparse
import math
from collections import defaultdict
from typing import Any, Callable

from common import get_logger, load_json, resolve_project_path, save_json

logger = get_logger("repair_diarization")

Chunk = dict[str, Any]
RepairModule = Callable[..., "list[Chunk]"]

def _l2(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _speaker_centroids(chunks: list[Chunk], embs: dict[str, list[float]]) -> dict[str, list[float]]:
    groups: dict[str, list[list[float]]] = defaultdict(list)
    for ch in chunks:
        cid = ch["chunk_id"]
        if cid in embs:
            groups[str(ch["speaker"])].append(embs[cid])
    centroids: dict[str, list[float]] = {}
    for spk, vecs in groups.items():
        dim = len(vecs[0])
        mean = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        centroids[spk] = _l2(mean)
    return centroids


def _embed_reassign(chunks: list[Chunk], *, embeddings_json: str, margin: float = 0.1,
                    min_sim: float = 0.5, passes: int = 3) -> list[Chunk]:
    # 청크 임베딩을 화자 centroid와 비교해 더 가까운 화자로 재배정한다. 자기 화자와의
    # 비교는 leave-one-out(자기 청크 제외)으로 계산 — 작은 클러스터에서 self-bias로
    # 못 옮기는 문제를 막는다. 다중 패스로 centroid를 갱신하며 오염을 제거한다.
    embs = load_json(embeddings_json)
    chunks = [dict(c) for c in chunks]
    for _ in range(int(passes)):
        members: dict[str, list[int]] = defaultdict(list)
        for idx, ch in enumerate(chunks):
            if ch["chunk_id"] in embs:
                members[str(ch["speaker"])].append(idx)
        sums: dict[str, list[float]] = {}
        centroids: dict[str, list[float]] = {}
        for spk, idxs in members.items():
            vecs = [embs[chunks[i]["chunk_id"]] for i in idxs]
            dim = len(vecs[0])
            total = [sum(v[d] for v in vecs) for d in range(dim)]
            sums[spk] = total
            centroids[spk] = _l2(total)
        changed = 0
        for idx, ch in enumerate(chunks):
            cid = ch["chunk_id"]
            if cid not in embs:
                continue
            e = embs[cid]
            cur_spk = str(ch["speaker"])
            if len(members[cur_spk]) >= 2:
                total = sums[cur_spk]
                loo = _l2([total[d] - e[d] for d in range(len(e))])
                cur_sim = _dot(e, loo)
            else:
                cur_sim = 1.0  # 단독 화자는 해체하지 않는다
            best_spk, best_sim = cur_spk, cur_sim
            for spk, cen in centroids.items():
                if spk == cur_spk:
                    continue
                sim = _dot(e, cen)
                if sim > best_sim:
                    best_sim, best_spk = sim, spk
            if best_spk != cur_spk and best_sim > cur_sim + margin and best_sim >= min_sim:
                ch.setdefault("audio_speaker", cur_spk)
                ch["speaker"] = best_spk
                ch["reassigned_by"] = "embed"
                ch["reassign_sim"] = round(best_sim, 3)
                ch["reassign_prev_sim"] = round(cur_sim, 3)
                changed += 1
        logger.info("embed_reassign pass: %s chunks reassigned", changed)
        if changed == 0:
            break
    return chunks


def _kmeans2_cos(vecs: list[list[float]], iters: int = 8) -> tuple[list[int], list[float], list[float]]:
    # 코사인 2-means. seed = 가장 먼(코사인 최소) 두 점. 반환: 라벨(0/1), centroid c0, c1.
    n = len(vecs)
    si, sj, lo = 0, 1, 2.0
    for a in range(n):
        for b in range(a + 1, n):
            d = _dot(vecs[a], vecs[b])
            if d < lo:
                lo, si, sj = d, a, b
    c0, c1 = list(vecs[si]), list(vecs[sj])
    lab = [0] * n
    for _ in range(iters):
        for i, v in enumerate(vecs):
            lab[i] = 0 if _dot(v, c0) >= _dot(v, c1) else 1
        for c, lb in ((c0, 0), (c1, 1)):
            grp = [vecs[i] for i in range(n) if lab[i] == lb]
            if grp:
                dim = len(grp[0])
                nc = _l2([sum(g[d] for g in grp) for d in range(dim)])
                c[:] = nc
    return lab, c0, c1


def _silhouette_cos(vecs: list[list[float]], lab: list[int]) -> float:
    # 코사인 거리(1-cos) 기반 평균 실루엣. 2군집 분리도 측정(높을수록 잘 갈림).
    n = len(vecs)
    if len(set(lab)) < 2:
        return -1.0
    def dist(i, j): return 1.0 - _dot(vecs[i], vecs[j])
    sils = []
    for i in range(n):
        same = [dist(i, j) for j in range(n) if j != i and lab[j] == lab[i]]
        other = [dist(i, j) for j in range(n) if lab[j] != lab[i]]
        if not same or not other:
            continue
        a, b = sum(same) / len(same), sum(other) / len(other)
        sils.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return sum(sils) / len(sils) if sils else -1.0


def _median_f0(audio, sr: int, s: float, e: float) -> float:
    # 구간 [s,e] median F0(Hz). 유성 프레임만. librosa pyin. 실패/무성이면 0.
    import numpy as np
    a, b = int(s * sr), int(e * sr)
    seg = audio[a:b]
    if len(seg) < int(0.1 * sr):
        return 0.0
    try:
        import librosa
        f0, _v, _p = librosa.pyin(seg, fmin=70, fmax=400, sr=sr, frame_length=1024)
        vals = f0[~np.isnan(f0)]
        return float(np.median(vals)) if len(vals) else 0.0
    except Exception:
        return 0.0


def _embed_split(chunks: list[Chunk], *, embeddings_json: str,
                 within_margin: float = 0.08, min_sub: int = 2, sil_min: float = 0.15,
                 min_label_chunks: int = 4,
                 dialogue_audio: str | None = None, f0_split_hz: float = 70.0) -> list[Chunk]:
    # 한 라벨에 '두 화자'가 뭉친 under-cluster 교정. 고정 임계 단일연결(체이닝 취약)을 버리고,
    # 2-means(cosine)로 라벨을 2분할한 뒤 'within_ref(클립 같은-화자 응집도) - margin' 상대임계 +
    # silhouette + 최소부분군집 게이트를 모두 통과할 때만 소수 그룹을 새 라벨로 mint 한다.
    # embed_merge 와 대칭(상대임계)이라 동성·노이즈 클립서 헛분할/미분할을 둘 다 줄이고,
    # split->merge 순서로 두면 헛분할은 뒤따르는 embed_merge 가 되합친다(over-split 안전망).
    embs = load_json(embeddings_json)
    chunks = [dict(c) for c in chunks]
    by_spk: dict[str, list[int]] = defaultdict(list)
    for idx, ch in enumerate(chunks):
        if str(ch["chunk_id"]) in embs:
            by_spk[str(ch["speaker"])].append(idx)
    multi = {s: idxs for s, idxs in by_spk.items() if len(idxs) >= 2}
    if not multi:
        return chunks
    # within_ref: 화자별 (청크↔자기 centroid 코사인 평균) 의 화자 무가중 평균
    per_within = []
    for s, idxs in multi.items():
        vs = [embs[chunks[i]["chunk_id"]] for i in idxs]
        dim = len(vs[0]); cen = _l2([sum(v[d] for v in vs) for d in range(dim)])
        per_within.append(sum(_dot(v, cen) for v in vs) / len(vs))
    within_ref = sum(per_within) / len(per_within)
    thr = within_ref - float(within_margin)

    # F0 게이트용 오디오 로드(있을 때만). 없으면 F0 게이트가 항상 막아 보수적으로 분할 안 함.
    audio = sr = None
    if dialogue_audio:
        try:
            import soundfile as sf
            audio, sr = sf.read(str(resolve_project_path(dialogue_audio)))
            if getattr(audio, "ndim", 1) > 1:
                audio = audio.mean(axis=1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("embed_split: dialogue_audio 로드 실패, F0 게이트 비활성으로 분할 안 함: %s", exc)
            audio = None

    for spk, idxs in list(multi.items()):
        if len(idxs) < max(min_label_chunks, 2 * min_sub):
            continue  # 분할 판단에 충분한 청크가 있어야(소수 라벨 헛분할 방지)
        vecs = [embs[chunks[i]["chunk_id"]] for i in idxs]
        lab, c0, c1 = _kmeans2_cos(vecs)
        g0 = [idxs[i] for i in range(len(idxs)) if lab[i] == 0]
        g1 = [idxs[i] for i in range(len(idxs)) if lab[i] == 1]
        if min(len(g0), len(g1)) < min_sub:
            continue
        inter = _dot(c0, c1)
        sil = _silhouette_cos(vecs, lab)
        if not (inter < thr and sil >= sil_min):
            continue
        # F0 게이트(필수): 두 서브군집의 median F0 가 충분히 달라야 '진짜 다른 화자'로 본다.
        # 단일화자 이중봉(감정/음높이 변동, 검증상 ≤42Hz)은 차단, 교차성역(리사 109Hz 등)만 통과.
        if audio is None:
            continue
        f0_0 = [v for c in g0 for v in [_median_f0(audio, sr, float(chunks[c]["start"]), float(chunks[c]["end"]))] if v > 0]
        f0_1 = [v for c in g1 for v in [_median_f0(audio, sr, float(chunks[c]["start"]), float(chunks[c]["end"]))] if v > 0]
        if not f0_0 or not f0_1:
            continue
        import statistics
        f0d = abs(statistics.median(f0_0) - statistics.median(f0_1))
        if f0d < float(f0_split_hz):
            logger.info("embed_split: '%s' 후보 기각 — F0차 %.0fHz < %.0f (단일화자 이중봉 추정)", spk, f0d, f0_split_hz)
            continue
        # 임베딩 이중봉 + F0 차이 모두 통과 → 소수(청크 적은) 그룹을 새 라벨로
        minor = g0 if len(g0) <= len(g1) else g1
        new_label = f"{spk}_s1"
        for i in minor:
            chunks[i]["split_from"] = spk
            chunks[i]["audio_speaker_pre_split"] = spk
            chunks[i]["speaker"] = new_label
        logger.info("embed_split: '%s' -> '%s'+'%s' (inter=%.3f thr=%.3f sil=%.3f, minor=%s)",
                    spk, spk, new_label, inter, thr, sil, len(minor))
    return chunks


def _embed_merge(chunks: list[Chunk], *, embeddings_json: str, merge_threshold: float | None = None,
                 margin: float = 0.05, min_threshold: float = 0.6, min_members: int = 2) -> list[Chunk]:
    # 한 인물이 여러 라벨로 쪼개진 과분할을 임베딩으로 병합한다(embed_split 의 역).
    # 자기보정: 고정 임계값 대신 그 클립의 '같은 화자' 응집도(within_ref = 화자별 청크↔자기
    # centroid 코사인 평균의, 화자 무가중 평균)를 기준으로, 두 라벨 centroid 코사인이
    # within_ref - margin 이상일 때만 병합 — "두 라벨이 한 화자 내부만큼 닮았을 때만" 합쳐
    # 닮았지만 다른 화자(자매/부모)는 합치지 않는다. 절대 하한 min_threshold 로 저응집(noisy)
    # 클립의 오병합을 막고, 병합은 완전연결(그룹 내 모든 라벨쌍이 thr 이상)만 허용해 전이
    # 과병합(A~B,B~C 인데 A!~C)을 차단한다. merge_threshold 가 주어지면 절대값으로 우선.
    # 각 병합 그룹은 청크 수 최다 라벨을 대표로 유지. 소형 클러스터(min_members 미만) 제외.
    embs = load_json(embeddings_json)
    chunks = [dict(c) for c in chunks]
    members: dict[str, list[int]] = defaultdict(list)
    for idx, ch in enumerate(chunks):
        if ch["chunk_id"] in embs:
            members[str(ch["speaker"])].append(idx)
    spks = [s for s, idxs in members.items() if len(idxs) >= min_members]
    if len(spks) < 2:
        logger.info("embed_merge: 병합 후보 화자 < 2, 변경 없음")
        return chunks
    centroids: dict[str, list[float]] = {}
    per_speaker_within: list[float] = []  # 화자별 평균(청크 수 무가중)
    for spk in spks:
        vecs = [embs[chunks[i]["chunk_id"]] for i in members[spk]]
        dim = len(vecs[0])
        cen = _l2([sum(v[d] for v in vecs) for d in range(dim)])
        centroids[spk] = cen
        per_speaker_within.append(sum(_dot(v, cen) for v in vecs) / len(vecs))

    if merge_threshold is not None:
        thr = float(merge_threshold)
    else:
        within_ref = sum(per_speaker_within) / len(per_speaker_within)
        adaptive = within_ref - float(margin)
        thr = max(adaptive, float(min_threshold))
        if adaptive < float(min_threshold):
            logger.warning("embed_merge: within_ref(%.3f)-margin 이 min_threshold(%.2f) 미만 — "
                           "저응집 클립으로 floor 적용", within_ref, min_threshold)

    # 완전연결 응집: 두 그룹의 모든 교차쌍 코사인의 최솟값이 thr 이상일 때만 병합한다.
    groups: list[list[str]] = [[s] for s in spks]
    while True:
        best: tuple[int, int, float] | None = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                mn = min(_dot(centroids[a], centroids[b]) for a in groups[i] for b in groups[j])
                if mn >= thr and (best is None or mn > best[2]):
                    best = (i, j, mn)
        if best is None:
            break
        i, j, _ = best
        groups[i].extend(groups[j])
        groups.pop(j)

    remap: dict[str, str] = {}
    for grp in groups:
        if len(grp) < 2:
            continue
        rep = max(grp, key=lambda s: len(members[s]))
        for s in grp:
            if s != rep:
                remap[s] = rep
                logger.info("embed_merge: '%s' -> '%s' (cos=%.3f, thr=%.3f)",
                            s, rep, _dot(centroids[s], centroids[rep]), thr)
    for ch in chunks:
        s = str(ch["speaker"])
        if s in remap:
            ch.setdefault("audio_speaker", s)
            ch["speaker"] = remap[s]
            ch["merged_by"] = "embed"
    logger.info("embed_merge: %s labels merged (threshold=%.3f)", len(remap), thr)
    return chunks


def _embed_recluster(chunks: list[Chunk], *, embeddings_json: str, tau: float = 0.45,
                     max_chunks: int = 0) -> list[Chunk]:
    # 청크 임베딩을 평균연결 응집 군집화해 화자 라벨을 처음부터 다시 부여한다(base diarization
    # 라벨을 버림). 짧은 클립(시간축 diarization 이 발화가 적어 불안정)에서 base 보다 임베딩
    # 군집이 정확하다는 실측(1_original 0.25→0.54, sample 0.48→0.70 V-measure)에 근거. 단 긴/정상
    # 클립에서는 base 가 더 우수하므로 max_chunks 게이트(청크 수 ≤ max_chunks 일 때만 적용)로 제한.
    # max_chunks=0 이면 적용 안 함(안전 기본). tau 는 같은 화자로 묶는 평균 코사인 임계값.
    chunks = [dict(c) for c in chunks]
    if max_chunks and len(chunks) > max_chunks:
        logger.info("embed_recluster: 청크 %s > max_chunks %s — base 라벨 유지(skip)", len(chunks), max_chunks)
        return chunks
    embs = load_json(embeddings_json)
    ids = [c["chunk_id"] for c in chunks if c["chunk_id"] in embs]
    if len(ids) < 2:
        return chunks
    groups: list[list[str]] = [[i] for i in ids]

    def gsim(a: list[str], b: list[str]) -> float:
        return sum(_dot(embs[x], embs[y]) for x in a for y in b) / (len(a) * len(b))

    while len(groups) > 1:
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                s = gsim(groups[i], groups[j])
                if best is None or s > best[2]:
                    best = (i, j, s)
        if best is None or best[2] < tau:
            break
        i, j, _ = best
        groups[i].extend(groups[j])
        groups.pop(j)
    label_of: dict[str, str] = {}
    for k, grp in enumerate(groups):
        for cid in grp:
            label_of[cid] = f"R{k}"
    n_changed = 0
    for c in chunks:
        cid = c["chunk_id"]
        if cid in label_of and str(c.get("speaker")) != label_of[cid]:
            c.setdefault("audio_speaker", str(c.get("speaker")))
            c["speaker"] = label_of[cid]
            c["reclustered_by"] = "embed"
            n_changed += 1
    logger.info("embed_recluster: %s chunks -> %s 화자 라벨 (tau=%.2f, %s 청크 라벨 변경)",
                len(ids), len(groups), tau, n_changed)
    return chunks


def _rttm_or_json_segments(path: str) -> list[tuple[float, float, str]]:
    # RTTM(.rttm) 또는 [{start,end,speaker}] JSON 에서 (start,end,speaker) 세그먼트를 읽는다.
    p = resolve_project_path(path)
    if str(p).endswith(".rttm"):
        out = []
        for ln in p.read_text().splitlines():
            f = ln.split()
            if len(f) >= 8 and f[0] == "SPEAKER":
                st = float(f[3]); du = float(f[4]); out.append((st, st + du, f[7]))
        return out
    data = load_json(path)
    return [(float(s["start"]), float(s["end"]), str(s["speaker"])) for s in data]


def _seg_labels_for_chunks(chunks: list[Chunk], segs: list[tuple[float, float, str]]) -> dict[str, str]:
    lab: dict[str, str] = {}
    for c in chunks:
        s, e = float(c["start"]), float(c["end"])
        ov: dict[str, float] = defaultdict(float)
        for a, b, spk in segs:
            o = max(0.0, min(e, b) - max(s, a))
            if o > 0:
                ov[spk] += o
        lab[str(c["chunk_id"])] = max(ov, key=ov.get) if ov else "NONE"
    return lab


def _consensus(chunks: list[Chunk], *, alt_diarizations: list[str] | None = None,
               embeddings_json: str | None = None, recluster_tau: float = 0.45,
               threshold: float = 0.67) -> list[Chunk]:
    # 여러 독립 화자분리(현재 라벨 + 대안 RTTM/JSON + 임베딩 recluster)를 co-association 합의로
    # 결합한다. 두 청크가 voter 중 threshold 비율 이상에서 같은 화자면 같은 군집(연결요소).
    # 모델마다 다른 오류가 상쇄돼 단일 모델보다 정확(검증: input 0.80→0.84, 87a903ab 0.65→0.72).
    chunks = [dict(c) for c in chunks]
    ids = [str(c["chunk_id"]) for c in chunks]
    voters: list[dict[str, str]] = [{str(c["chunk_id"]): str(c.get("speaker")) for c in chunks}]
    for path in (alt_diarizations or []):
        try:
            voters.append(_seg_labels_for_chunks(chunks, _rttm_or_json_segments(path)))
        except Exception as exc:
            logger.warning("consensus: 대안 화자분리 로드 실패 %s (%s)", path, exc)
    if embeddings_json:
        embs = load_json(embeddings_json)
        # recluster voter: 임베딩 응집 군집(_embed_merge 와 동일 평균연결, tau 절대값)
        eids = [i for i in ids if i in embs]
        groups = [[i] for i in eids]
        def gsim(a: list[str], b: list[str]) -> float:
            return sum(_dot(embs[x], embs[y]) for x in a for y in b) / (len(a) * len(b))
        while len(groups) > 1:
            best = None
            for i in range(len(groups)):
                for j in range(i + 1, len(groups)):
                    v = gsim(groups[i], groups[j])
                    if best is None or v > best[2]:
                        best = (i, j, v)
            if best is None or best[2] < recluster_tau:
                break
            i, j, _ = best
            groups[i].extend(groups[j]); groups.pop(j)
        rl = {i: "R%d" % k for k, g in enumerate(groups) for i in g}
        voters.append(rl)
    n = len(voters)
    if n < 2:
        logger.info("consensus: voter < 2, 변경 없음")
        return chunks
    parent = {i: i for i in ids}
    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            i, j = ids[a], ids[b]
            agree = sum(1 for L in voters if L.get(i, "?1") == L.get(j, "?2")) / n
            if agree >= threshold:
                parent[find(i)] = find(j)
    n_changed = 0
    for c in chunks:
        cid = str(c["chunk_id"])
        new = "G%s" % find(cid)
        if str(c.get("speaker")) != new:
            c.setdefault("audio_speaker", str(c.get("speaker")))
            c["speaker"] = new
            c["diarized_by"] = "consensus"
            n_changed += 1
    logger.info("consensus: %s voters, threshold=%.2f, %s 청크 라벨 변경", n, threshold, n_changed)
    return chunks


def _gender_split(chunks: list[Chunk], *, chunks_dir: str | None = None, f_bound: float = 185.0,
                  male_ceil: float = 165.0, min_voiced: float = 0.30, min_gender_chunks: int = 2) -> list[Chunk]:
    # F0/성별 신호(대사 내용 아님, 허용)로 분리: 한 음성 라벨이 명확한 남성·여성 청크를 모두 포함하면
    # (이성이 한 라벨로 잘못 병합) 성별로 분할한다. 청크 wav 에서 librosa.pyin 중앙 F0 측정 →
    # >f_bound 여성, <male_ceil 남성, 사이는 모호(미사용). 모호/무성(voiced<min_voiced)은 보존.
    # 같은 성별 화자(Bart/Ralph, Shaun/Doctor)는 못 가름 — 얼굴이 그 역할.
    try:
        import librosa
        import numpy as np
    except ImportError:
        logger.warning("gender_split: librosa 없음 — skip"); return chunks
    chunks = [dict(c) for c in chunks]

    def chunk_f0(c) -> tuple[float, float]:
        wav = c.get("wav") or (("%s/%s.wav" % (chunks_dir, c["chunk_id"])) if chunks_dir else None)
        if not wav:
            return 0.0, 0.0
        p = resolve_project_path(wav)
        if not p.exists():
            return 0.0, 0.0
        try:
            y, sr = librosa.load(str(p), sr=16000, mono=True)
            f0, vflag, _ = librosa.pyin(y, fmin=70, fmax=450, sr=sr)
            vals = f0[~np.isnan(f0)]
            voiced = float(len(vals)) / max(1, len(f0))
            return (float(np.median(vals)) if len(vals) else 0.0), voiced
        except Exception:
            return 0.0, 0.0

    gender: dict[str, str] = {}
    for c in chunks:
        med, voiced = chunk_f0(c)
        if voiced < min_voiced or med <= 0:
            continue
        if med >= f_bound:
            gender[str(c["chunk_id"])] = "F"
        elif med <= male_ceil:
            gender[str(c["chunk_id"])] = "M"
    by_label: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in gender:
            by_label[str(c["speaker"])][gender[cid]].append(cid)
    remap: dict[str, str] = {}
    for label, g in by_label.items():
        if len(g.get("M", [])) >= min_gender_chunks and len(g.get("F", [])) >= min_gender_chunks:
            # 더 많은 성별이 라벨 유지, 소수 성별을 새 라벨로
            major = "M" if len(g["M"]) >= len(g["F"]) else "F"
            minor = "F" if major == "M" else "M"
            for cid in g[minor]:
                remap[cid] = "%s_g%s" % (label, minor)
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in remap:
            c.setdefault("audio_speaker", str(c["speaker"]))
            c["speaker"] = remap[cid]
            c["split_by"] = "gender_f0"
    logger.info("gender_split: %s 청크 성별분리 (%s 라벨)", len(remap), len(set(remap.values())))
    return chunks


def _face_identity_mint(chunks: list[Chunk], *, asd_tracks_json: str, embeddings_json: str | None = None,
                        face_clus_cos: float = 0.45, split_th: float = 0.35, min_speak_score: float = 0.5,
                        min_face_chunks: int = 2, voice_same: float = 0.60) -> list[Chunk]:
    # S3 이식: 한 음성 라벨(catch-all)의 ASD-발화 얼굴이 서로 distinct 한 face cluster로 갈리면 얼굴로
    # 새 화자를 mint 한다(음성으론 못 가른 동음 화자를 얼굴로 분해). embed_split/face_remap 의 split 과
    # 달리, '음성이 같아 하나로 뭉친' 라벨을 얼굴 신원으로 분해하는 것이 핵심. voice-probe veto:
    # mint 대상 청크의 음성이 다른 기존 라벨 centroid 에 voice_same 이상 더 가까우면 reverse-shot
    # (화면 속 얼굴=청자, 목소리는 타인)으로 보고 mint 대신 그 라벨로 재배정한다.
    asd = load_json(asd_tracks_json)
    tracks = asd.get("tracks", [])
    chunks = [dict(c) for c in chunks]
    if not tracks:
        logger.info("face_identity_mint: 얼굴 트랙 없음 — 변경 없음")
        return chunks
    face_of = _cluster_face_tracks(tracks, face_clus_cos)
    face_members: dict[int, list] = defaultdict(list)
    for t in tracks:
        face_members[face_of[t["track_id"]]].append(t["embedding"])
    face_cent = {fid: _l2([sum(v[d] for v in vs) / len(vs) for d in range(len(vs[0]))])
                 for fid, vs in face_members.items() if vs}
    # 청크별 dominant 발화 얼굴 cluster
    chunk_face: dict[str, int] = {}
    for c in chunks:
        s, e = float(c["start"]), float(c["end"])
        ev: dict[int, float] = defaultdict(float)
        for t in tracks:
            fid = face_of[t["track_id"]]
            for f in t["frames"]:
                if s <= f["t"] < e and f["score"] >= min_speak_score:
                    ev[fid] += f["score"]
        if ev:
            chunk_face[str(c["chunk_id"])] = max(ev, key=ev.get)
    # 음성 라벨 centroid (voice-probe veto 용)
    voice_cent: dict[str, list[float]] = {}
    vembs = load_json(embeddings_json) if embeddings_json else {}
    if vembs:
        lab_vecs: dict[str, list] = defaultdict(list)
        for c in chunks:
            cid = str(c["chunk_id"])
            if cid in vembs:
                lab_vecs[str(c["speaker"])].append(vembs[cid])
        voice_cent = {l: _l2([sum(v[d] for v in vs) / len(vs) for d in range(len(vs[0]))])
                      for l, vs in lab_vecs.items() if vs}
    # 라벨별 dominant-face 분포 → mint
    by_label: dict[str, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in chunk_face:
            by_label[str(c["speaker"])][chunk_face[cid]].append(cid)
    remap: dict[str, str] = {}
    n_mint = 0
    for label, faces in by_label.items():
        strong = {fid: cids for fid, cids in faces.items() if len(cids) >= min_face_chunks}
        if len(strong) < 2:
            continue
        keep = max(strong, key=lambda fid: len(strong[fid]))
        for fid, cids in strong.items():
            if fid == keep or fid not in face_cent or keep not in face_cent:
                continue
            if _dot(face_cent[fid], face_cent[keep]) >= split_th:
                continue  # 얼굴이 충분히 다르지 않음 → mint 안 함
            new_label = "%s_f%d" % (label, fid)
            minted_here = False
            for cid in cids:
                if voice_cent and cid in vembs:
                    e = vembs[cid]
                    best = max(voice_cent, key=lambda l: _dot(e, voice_cent[l]))
                    if best != label and _dot(e, voice_cent[best]) >= voice_same:
                        remap[cid] = best  # reverse-shot veto: 음성이 다른 라벨에 속함
                        continue
                remap[cid] = new_label
                minted_here = True
            if minted_here:
                n_mint += 1
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in remap and remap[cid] != str(c["speaker"]):
            c.setdefault("audio_speaker", str(c["speaker"]))
            c["speaker"] = remap[cid]
            c["minted_by"] = "face_identity"
    logger.info("face_identity_mint: %s face clusters minted (%s chunks relabeled)", n_mint, len(remap))
    return chunks


def _cluster_face_tracks(tracks: list[dict], sim_threshold: float) -> dict[int, int]:
    # 얼굴 트랙 임베딩(이미 단위벡터)을 코사인 그리디 군집화해 시각 인물 ID를 부여.
    centroids: list[list[float]] = []
    members: list[list[list[float]]] = []
    face_of: dict[int, int] = {}
    for t in tracks:
        emb = t["embedding"]
        if centroids:
            sims = [_dot(emb, c) for c in centroids]
            best = max(range(len(sims)), key=lambda i: sims[i])
            best_sim = sims[best]
        else:
            best, best_sim = -1, -1.0
        if best_sim >= sim_threshold:
            members[best].append(emb)
            dim = len(emb)
            mean = [sum(v[d] for v in members[best]) / len(members[best]) for d in range(dim)]
            centroids[best] = _l2(mean)
            face_of[t["track_id"]] = best
        else:
            centroids.append(_l2(emb))
            members.append([emb])
            face_of[t["track_id"]] = len(centroids) - 1
    return face_of


def _visual_reconcile(chunks: list[Chunk], *, asd_tracks_json: str, sim_threshold: float = 0.4,
                      min_evidence: float = 5.0, min_split_chunks: int = 2) -> list[Chunk]:
    # 얼굴 신원으로 오디오 화자 클러스터를 교정. 보수적 '분할 전용' — 한 오디오 화자의
    # 청크가 강한 발화증거로 2개 이상 얼굴에 갈릴 때만 얼굴별로 분리한다. 얼굴 증거 없는
    # 청크는 오디오 라벨 유지(폴백). 라벨 공간 혼합 안 함(예전 per-chunk 덮어쓰기 폐기).
    asd = load_json(asd_tracks_json)
    tracks = asd.get("tracks", [])
    out = [dict(c) for c in chunks]
    if not tracks:
        logger.info("visual_reconcile: 얼굴 트랙 없음 — 변경 없음")
        return out

    face_of = _cluster_face_tracks(tracks, sim_threshold)
    chunk_face: dict[str, int] = {}
    for c in chunks:
        start, end = float(c["start"]), float(c["end"])
        ev: dict[int, float] = defaultdict(float)
        for t in tracks:
            fid = face_of[t["track_id"]]
            for f in t["frames"]:
                if start <= f["t"] < end and f["score"] > 0:
                    ev[fid] += f["score"]
        if ev:
            best = max(ev, key=ev.get)
            if ev[best] >= min_evidence:
                chunk_face[str(c["chunk_id"])] = best

    spk_faces: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in chunk_face:
            spk_faces[str(c["speaker"])][chunk_face[cid]] += 1

    n_split = 0
    for spk, counter in spk_faces.items():
        strong_faces = [fid for fid, n in counter.items() if n >= min_split_chunks]
        if len(strong_faces) >= 2:
            for c in out:
                cid = str(c["chunk_id"])
                if str(c["speaker"]) == spk and chunk_face.get(cid) in strong_faces:
                    c.setdefault("audio_speaker", spk)
                    c["speaker"] = f"{spk}_v{chunk_face[cid]}"
                    c["visual_split"] = True
                    n_split += 1
    logger.info("visual_reconcile: %s개 얼굴 인물 클러스터, %s청크 얼굴분할", len(set(face_of.values())), n_split)
    return out


def _face_remap(chunks: list[Chunk], *, asd_tracks_json: str, sim_threshold: float = 0.4,
                min_speak_score: float = 0.5, min_evidence: float = 5.0,
                dominant_ratio: float = 0.5, min_split_chunks: int = 2,
                do_split: bool = True, do_reassign: bool = False,
                do_intra_split: bool = False, min_intra_sec: float = 0.7) -> list[Chunk]:
    # 팀원 face_clustering 의 dominant-SPK reassign + SPK split + intra-face split 을 우리
    # asd_tracks.json (track별 embedding + frames[{t,score}]) 형식에 맞춰 이식. visual_reconcile
    # 보다 적극적: split + (do_reassign) dominant 얼굴화자 재배정 + (do_intra_split) 청크 내부에서
    # 발화 얼굴이 min_intra_sec 이상 바뀌면 시간 경계로 청크를 쪼갠다.
    # 게이트 — min_evidence(청크 발화증거 합), min_split_chunks(cluster 당 청크 수),
    #         dominant_ratio(reassign 시 cluster 의 dominant SPK 비율). do_reassign 기본 off.
    asd = load_json(asd_tracks_json)
    tracks = asd.get("tracks", [])
    out = [dict(c) for c in chunks]
    if not tracks:
        logger.info("face_remap: 얼굴 트랙 없음 — 변경 없음")
        return out

    face_of = _cluster_face_tracks(tracks, sim_threshold)  # track_id -> face cluster id

    # 청크별 best face cluster: 구간 내 score>=min_speak_score frame 들의 score 합이 최대인 cluster.
    chunk_best: dict[str, int] = {}
    for c in chunks:
        start, end = float(c["start"]), float(c["end"])
        ev: dict[int, float] = defaultdict(float)
        for t in tracks:
            fid = face_of[t["track_id"]]
            for f in t["frames"]:
                if start <= f["t"] < end and f["score"] >= min_speak_score:
                    ev[fid] += f["score"]
        if ev:
            best = max(ev, key=ev.get)
            if ev[best] >= min_evidence:
                chunk_best[str(c["chunk_id"])] = best

    # cluster -> dominant audio SPK (그 cluster 에 매핑된 청크들의 다수 SPK) + 비율
    cluster_spk_count: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in chunk_best:
            cluster_spk_count[chunk_best[cid]][str(c["speaker"])] += 1
    cluster_dom_spk: dict[int, str] = {
        fid: max(cnt, key=cnt.get) for fid, cnt in cluster_spk_count.items()
    }

    # SPK -> face cluster 분포 (split 판단)
    spk_faces: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for c in chunks:
        cid = str(c["chunk_id"])
        if cid in chunk_best:
            spk_faces[str(c["speaker"])][chunk_best[cid]] += 1

    # 한 SPK 청크가 strong cluster 2개 이상에 분산되면 가장 큰 cluster 만 원래 라벨 유지, 나머지 split.
    split_label: dict[str, str] = {}
    if do_split:
        for spk, counter in spk_faces.items():
            strong = sorted((fid for fid, n in counter.items() if n >= min_split_chunks),
                            key=lambda fid: -counter[fid])
            if len(strong) >= 2:
                keep = strong[0]
                for c in chunks:
                    cid = str(c["chunk_id"])
                    if str(c["speaker"]) == spk and chunk_best.get(cid) in strong and chunk_best[cid] != keep:
                        split_label[cid] = f"{spk}_v{chunk_best[cid]}"

    # intra-face split: 한 청크 [start,end] 안에서 dominant 발화 얼굴 cluster 가
    # min_intra_sec 이상 지속되는 run 으로 2개 이상 나뉘면 시간 경계로 분할한다(시간 전체를 타일링).
    def _intra_runs(start: float, end: float) -> list[tuple[int, float, float]]:
        bin_sec = 0.1
        n = max(1, int(math.ceil((end - start) / bin_sec)))
        dom: list[int | None] = [None] * n
        for bi in range(n):
            b0 = start + bi * bin_sec
            b1 = b0 + bin_sec
            sc: dict[int, float] = defaultdict(float)
            for t in tracks:
                fid = face_of[t["track_id"]]
                for f in t["frames"]:
                    if b0 <= f["t"] < b1 and f["score"] >= min_speak_score:
                        sc[fid] += f["score"]
            if sc:
                dom[bi] = max(sc, key=sc.get)
        runs: list[list] = []  # [fid, t0, t1]
        cur_fid: int | None = None
        cur_start = start
        for bi in range(n):
            d = dom[bi]
            if d is None:
                continue
            t0 = start + bi * bin_sec
            if cur_fid is None:
                cur_fid, cur_start = d, t0
            elif d != cur_fid:
                runs.append([cur_fid, cur_start, t0])
                cur_fid, cur_start = d, t0
        if cur_fid is not None:
            runs.append([cur_fid, cur_start, end])
        runs = [r for r in runs if (r[2] - r[1]) >= min_intra_sec]
        if len({r[0] for r in runs}) >= 2:
            return [(int(r[0]), float(r[1]), float(r[2])) for r in runs]
        return []

    n_split = 0
    n_reassign = 0
    n_intra = 0
    expanded: list[Chunk] = []
    for c in out:
        cid = str(c["chunk_id"])
        cur = str(c["speaker"])
        if cid in split_label:  # 1) whole-chunk split 우선
            c.setdefault("audio_speaker", cur)
            c["speaker"] = split_label[cid]
            c["from_face_split"] = True
            n_split += 1
            expanded.append(c)
            continue
        if do_reassign and cid in chunk_best:  # 2) dominant SPK 로 재배정
            fid = chunk_best[cid]
            dom = cluster_dom_spk.get(fid)
            cnt = cluster_spk_count.get(fid, {})
            ratio = cnt.get(dom, 0) / (sum(cnt.values()) or 1)
            if dom and dom != cur and ratio >= dominant_ratio:
                c.setdefault("audio_speaker", cur)
                c["speaker"] = dom
                c["from_face_match"] = True
                n_reassign += 1
        if do_intra_split:  # 3) 청크 내부 발화 얼굴 변화로 시간 분할
            runs = _intra_runs(float(c["start"]), float(c["end"]))
            base_spk = str(c["speaker"])
            # 각 run 을 화자로 매핑 후, 같은 화자 연속 run 은 병합한다.
            merged: list[list] = []  # [spk, t0, t1]
            for fid, t0, t1 in runs:
                spk = cluster_dom_spk.get(fid) or base_spk
                if merged and merged[-1][0] == spk:
                    merged[-1][2] = t1
                else:
                    merged.append([spk, t0, t1])
            # 가드 — 결과 화자가 실제로 2명 이상일 때만 분할(같은 화자 헛분할 방지).
            if len({m[0] for m in merged}) >= 2:
                pts = [float(c["start"])]
                for a, b in zip(merged, merged[1:]):
                    pts.append((a[2] + b[1]) / 2.0)
                pts.append(float(c["end"]))
                for k, (spk, _t0, _t1) in enumerate(merged):
                    seg_start, seg_end = pts[k], pts[k + 1]
                    if seg_end - seg_start < 0.05:
                        continue
                    sub = dict(c)
                    sub["chunk_id"] = f"{cid}_i{k}"
                    sub["start"] = round(seg_start, 3)
                    sub["end"] = round(seg_end, 3)
                    sub.setdefault("audio_speaker", cur)
                    sub["speaker"] = spk
                    sub["from_face_intra_split"] = True
                    expanded.append(sub)
                    n_intra += 1
                continue
        expanded.append(c)
    out = expanded
    logger.info("face_remap: %s face clusters, %s split, %s reassign, %s intra-split",
                len(set(face_of.values())), n_split, n_reassign, n_intra)
    return out


# 실패유형별 교정 모듈 등록부. Phase가 진행되며 채워진다.
#   embed_reassign     — 화자 임베딩으로 짧은/오염 청크를 올바른 화자에 재배정 (기존 화자 간 이동)
#   embed_split        — 한 화자에 두 인물이 병합된 경우 임베딩 부분군집으로 분리 (과병합 교정)
#   embed_merge        — centroid 가 가까운 화자 라벨을 병합 (한 인물이 여러 라벨로 쪼개진 과분할 교정)
#   embed_recluster    — 임베딩 응집 군집으로 라벨 재부여 (짧은 클립 전용, max_chunks 게이트, opt-in)
#   consensus          — 여러 독립 화자분리(대안 RTTM/JSON + 임베딩) co-association 합의 (모델 오류 상쇄)
#   visual_reconcile   — 얼굴 보이는(실사) 클립에서 audio 화자를 얼굴 신원으로 분할 (분할 전용·증거 게이트)
#   face_remap         — 팀원 로직 이식: SPK split + (옵션) dominant 얼굴화자로 reassign
def _singleton_absorb(chunks: list[Chunk], *, embeddings_json: str,
                      dur_low: float = 0.6, dur_high: float = 1.4,
                      min_anchor_members: int = 2, tau_abs: float = 0.50,
                      tau_strong: float = 0.62, margin: float = 0.06,
                      gap_sec: float = 0.5, proximity_floor: float = 0.30) -> list[Chunk]:
    # embed_merge 이후 남은 '진짜 singleton'(1청크 라벨, min_members=2 가 건너뜀)을 흡수한다.
    # 짧은 과분할 조각(예 0.38s '待って')을 기존 화자로 합치되, 진짜 짧은 별도화자(dur>=dur_high)와
    # 근거 약한 경우는 보존한다. 신호 결합: (1)음향(임베딩 vs 앵커 centroid 코사인) 확실하면 그쪽,
    # (2)dur<dur_low 면서 음향 애매하면 좌우 이웃이 같은 앵커(gap<=gap_sec)일 때만 근접 폴백,
    # (3)둘 다 약하면 KEEP. centroid 는 비-singleton 앵커에서만(singleton 끼리 안 합침).
    embs = load_json(embeddings_json)
    chunks = [dict(c) for c in chunks]
    members: dict[str, list[int]] = defaultdict(list)
    for idx, ch in enumerate(chunks):
        members[str(ch["speaker"])].append(idx)
    anchors = [s for s, idxs in members.items() if len(idxs) >= min_anchor_members]
    singletons = [idxs[0] for s, idxs in members.items()
                  if len(idxs) == 1 and chunks[idxs[0]]["chunk_id"] in embs]
    if not anchors or not singletons:
        return chunks
    centroids: dict[str, list[float]] = {}
    for s in anchors:
        vecs = [embs[chunks[i]["chunk_id"]] for i in members[s] if chunks[i]["chunk_id"] in embs]
        if vecs:
            dim = len(vecs[0])
            centroids[s] = _l2([sum(v[d] for v in vecs) for d in range(dim)])
    if not centroids:
        return chunks
    order = sorted(range(len(chunks)), key=lambda i: float(chunks[i]["start"]))
    pos = {idx: r for r, idx in enumerate(order)}
    n_merged = 0
    for i in singletons:
        ch = chunks[i]
        cur = str(ch["speaker"])
        dur = float(ch.get("duration", float(ch["end"]) - float(ch["start"])))
        if dur >= dur_high:
            continue  # KEEP — 진짜 별도화자 가능성(보호)
        e = embs[ch["chunk_id"]]
        sims = sorted(((_dot(e, c), s) for s, c in centroids.items()), reverse=True)
        s1, k1 = sims[0]
        s2 = sims[1][0] if len(sims) > 1 else -1.0
        floor = tau_abs if dur < dur_low else tau_strong
        target, reason = None, ""
        if s1 >= floor and (s1 - s2) >= margin:
            target, reason = k1, "embed"
        elif dur < dur_low:
            r = pos[i]
            nbrs: list[str] = []
            for nb in (order[r - 1] if r - 1 >= 0 else None, order[r + 1] if r + 1 < len(order) else None):
                if nb is None:
                    continue
                gap = (float(ch["start"]) - float(chunks[nb]["end"])) if pos[nb] < r else (float(chunks[nb]["start"]) - float(ch["end"]))
                if gap <= gap_sec and str(chunks[nb]["speaker"]) in centroids:
                    nbrs.append(str(chunks[nb]["speaker"]))
            if nbrs and len(set(nbrs)) == 1 and _dot(e, centroids[nbrs[0]]) >= proximity_floor:
                target, reason = nbrs[0], "proximity"
        if target is None or target == cur:
            continue
        ch.setdefault("audio_speaker", cur)
        ch["speaker"] = target
        ch["absorbed_by"] = "singleton"
        ch["absorb_sim"] = round(s1, 3)
        ch["absorb_reason"] = reason
        n_merged += 1
    logger.info("singleton_absorb: %s/%s singletons 흡수 (anchors=%s)", n_merged, len(singletons), len(anchors))
    return chunks


REPAIR_MODULES: dict[str, RepairModule] = {
    "embed_reassign": _embed_reassign,
    "embed_split": _embed_split,
    "embed_merge": _embed_merge,
    "singleton_absorb": _singleton_absorb,
    "embed_recluster": _embed_recluster,
    "consensus": _consensus,
    "face_identity_mint": _face_identity_mint,
    "gender_split": _gender_split,
    "visual_reconcile": _visual_reconcile,
    "face_remap": _face_remap,
}


def repair_chunks(chunks: list[Chunk], *, modules: list[str], params: dict[str, dict]) -> list[Chunk]:
    # 등록된 모듈을 주어진 순서대로 적용한다. 모듈이 없으면 입력을 그대로 돌려준다.
    for name in modules:
        if name not in REPAIR_MODULES:
            raise ValueError(f"Unknown repair module: {name} (available: {sorted(REPAIR_MODULES)})")
        before = len(chunks)
        chunks = REPAIR_MODULES[name](chunks, **(params.get(name) or {}))
        logger.info("repair module '%s': %s -> %s chunks", name, before, len(chunks))
    return chunks


def repair_diarization_file(
    input_json: str,
    output_json: str,
    *,
    modules: list[str] | None = None,
    params: dict[str, dict] | None = None,
) -> list[Chunk]:
    modules = list(modules or [])
    params = dict(params or {})
    chunks = load_json(input_json)
    if not modules:
        logger.info("repair_diarization: 활성 모듈 없음, %s chunks 그대로 통과", len(chunks))
    repaired = repair_chunks(chunks, modules=modules, params=params)
    save_json(repaired, output_json)
    logger.info("Wrote repaired chunks to %s (%s chunks)", resolve_project_path(output_json), len(repaired))
    return repaired


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="speaker_chunks를 실패유형별 모듈로 교정한다.")
    parser.add_argument("input_json")
    parser.add_argument("output_json")
    parser.add_argument("--modules", nargs="*", default=[], help="적용할 교정 모듈 이름(순서대로)")
    parser.add_argument("--params-json", help="모듈별 파라미터 JSON 파일(선택)")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    params = load_json(args.params_json) if args.params_json else {}
    repair_diarization_file(args.input_json, args.output_json, modules=args.modules, params=params)


if __name__ == "__main__":
    main()
