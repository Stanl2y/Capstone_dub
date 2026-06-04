# ECAPA-TDNN 두 번째 임베딩 관점으로 한 화자 내부를 sub-split 하는 앙상블 리파이너.
"""팀원 레포(yujin1103/AI_dubbing_system @ fc39b5d) Capstone_dub_src/ecapa_recluster.py 의
ensemble 모드를 우리 Segment 리스트 + 인메모리 오디오 기반으로 이식한 것이다.

알고리즘은 그대로 보존한다.
  1. segment 별 ECAPA 임베딩(192-dim) 추출.
  2. cosine 거리 기반 agglomerative cluster.
  3. ensemble — 기존 화자 라벨을 유지하면서, 한 화자 안에서 ECAPA cluster 가 둘 이상
     뚜렷이 갈리면 비-dominant sub-cluster 만 {speaker}_b, _c ... 로 분리.

변경한 것은 입출력뿐이다. 원본의 run_dir/meta/vocals/groups JSON I/O 를 제거하고
Segment 리스트를 제자리 변형한다.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Callable

import numpy as np

from common import get_logger, resolve_project_path

logger = get_logger("team_diarization.ecapa")

MODEL_NAME = "speechbrain/spkrec-ecapa-voxceleb"


def _l2(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / (n + 1e-9)


def load_ecapa(model_path: str, device: str = "cuda") -> Callable:
    """로컬 ECAPA 모델을 로드해 extract(audio, sr) -> L2 정규화 임베딩 클로저를 돌려준다."""
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    source = str(resolve_project_path(model_path))
    model = EncoderClassifier.from_hparams(
        source=source,
        savedir=source,
        run_opts={"device": device},
    )

    def extract(audio: np.ndarray, sr: int = 16000):
        import scipy.signal as sps

        if sr != 16000:
            audio = sps.resample_poly(audio, 16000, sr)
        try:
            t = torch.tensor(np.asarray(audio, dtype=np.float32)).unsqueeze(0)
            with torch.no_grad():
                emb = model.encode_batch(t).squeeze(0).squeeze(0).cpu().numpy()
            return _l2(emb.astype(np.float32))
        except Exception:
            return None

    return extract


def _cluster_embeddings(embs: list, ids: list, threshold: float) -> dict:
    """agglomerative cluster — cosine distance >= (1 - threshold) 면 분리."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    n = len(embs)
    if n == 0:
        return {}
    if n == 1:
        return {ids[0]: 0}

    arr = np.stack(embs)
    sim = arr @ arr.T
    dist = 1 - sim
    np.fill_diagonal(dist, 0)
    dist = np.clip(dist, 0, 2)
    cond = squareform(dist, checks=False)

    Z = linkage(cond, method="average")
    labels = fcluster(Z, t=1 - threshold, criterion="distance")
    return {ids[i]: int(labels[i]) for i in range(n)}


def ecapa_ensemble_split(
    segments: list,
    audio: np.ndarray,
    sample_rate: int,
    extract_emb: Callable,
    *,
    cosine_thr: float = 0.5,
    min_sub: int = 2,
    min_dominant: int = 3,
    min_seg_sec: float = 0.3,
) -> int:
    """기존 화자 라벨을 유지하며 ECAPA 관점으로 sub-split. segments 를 제자리 변형하고
    재배정된 segment 수를 반환한다."""
    embs: list = []
    ids: list = []
    orig_spk: dict = {}
    n_samples = len(audio)
    min_len = int(min_seg_sec * sample_rate)

    for i, seg in enumerate(segments):
        ss = int(max(0, seg.start * sample_rate))
        ee = int(min(n_samples, seg.end * sample_rate))
        if ee - ss < min_len:
            continue
        emb = extract_emb(audio[ss:ee], sample_rate)
        if emb is None:
            continue
        embs.append(np.asarray(emb, dtype=np.float32))
        ids.append(i)
        orig_spk[i] = segments[i].speaker

    if len(embs) < 2:
        return 0

    clusters = _cluster_embeddings(embs, ids, cosine_thr)

    # 기존 화자별 ECAPA cluster 분포
    spk_cluster_pairs: dict = defaultdict(Counter)
    for i, cid in clusters.items():
        spk_cluster_pairs[orig_spk[i]][cid] += 1

    n_split = 0
    for sp, cl_counts in spk_cluster_pairs.items():
        big_cls = [(c, cnt) for c, cnt in cl_counts.most_common() if cnt >= min_sub]
        if len(big_cls) < 2:
            continue
        # dominant cluster 가 충분히 커야만 split (작은 화자 보호)
        if big_cls[0][1] < min_dominant:
            continue
        cid_to_suffix = {c: "abcdefgh"[idx] for idx, (c, _) in enumerate(big_cls)}
        for i, cid in clusters.items():
            if orig_spk[i] != sp:
                continue
            if cid not in cid_to_suffix:
                continue  # singleton noise — 기존 화자 유지
            suffix = cid_to_suffix[cid]
            if suffix == "a":
                continue  # dominant sub — 기존 화자 그대로
            segments[i].speaker = f"{sp}_{suffix}"
            n_split += 1
        logger.info(
            "ECAPA sub-split %s: clusters=%s -> %d segments reassigned",
            sp,
            [c for c, _ in big_cls],
            sum(1 for _, (c, _) in enumerate(big_cls) if cid_to_suffix[c] != "a"),
        )

    return n_split
