# 얼굴 트랙 임베딩으로 시각 신원을 군집화하고, 청크별 발화 트랙으로 화자 라벨을 교정하는 스크립트
# 입력: LightASD 트랙(asd_tracks.json) + 오디오 화자분리(speaker_chunks.json)
# 출력: 시각 신호로 교정된 speaker_chunks. 얼굴이 안 보이거나 발화 증거가 없으면 오디오 라벨 유지(폴백).
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cluster_tracks(tracks: list[dict], sim_threshold: float) -> dict[int, int]:
    # 코사인 그리디 군집화. 임베딩은 이미 단위벡터라 내적 = 코사인 유사도.
    centroids: list[np.ndarray] = []
    members: list[list[int]] = []
    face_of_track: dict[int, int] = {}
    for t in tracks:
        emb = np.asarray(t["embedding"], dtype=np.float32)
        if centroids:
            sims = [float(np.dot(emb, c)) for c in centroids]
            best = int(np.argmax(sims))
            best_sim = sims[best]
        else:
            best, best_sim = -1, -1.0
        if best_sim >= sim_threshold:
            members[best].append(t["track_id"])
            stacked = np.mean([np.asarray(tracks[i_]["embedding"], dtype=np.float32)
                               for i_ in range(len(tracks)) if tracks[i_]["track_id"] in members[best]], axis=0)
            centroids[best] = stacked / (np.linalg.norm(stacked) + 1e-9)
            face_of_track[t["track_id"]] = best
        else:
            centroids.append(emb)
            members.append([t["track_id"]])
            face_of_track[t["track_id"]] = len(centroids) - 1
    return face_of_track


def attribute_chunk(chunk: dict, tracks: list[dict], face_of_track: dict[int, int]) -> tuple[int | None, float]:
    # 청크 구간에서 face_id 별 발화 증거(max(0,score) 합)를 모아 최고를 고른다.
    start, end = float(chunk["start"]), float(chunk["end"])
    evidence: dict[int, float] = {}
    for t in tracks:
        fid = face_of_track[t["track_id"]]
        for f in t["frames"]:
            if start <= f["t"] < end and f["score"] > 0:
                evidence[fid] = evidence.get(fid, 0.0) + f["score"]
    if not evidence:
        return None, 0.0
    best_fid = max(evidence, key=evidence.get)
    return best_fid, evidence[best_fid]


def main() -> None:
    parser = argparse.ArgumentParser(description="시각 신호로 화자분리 라벨을 교정한다.")
    parser.add_argument("--asd-tracks", default="meta/visual/TEST/asd_tracks.json")
    parser.add_argument("--diarization", default="meta/77506256_TEST/speaker_chunks.json")
    parser.add_argument("--output", default="meta/visual/TEST/speaker_chunks_visual.json")
    parser.add_argument("--sim-threshold", type=float, default=0.45, help="얼굴 동일 신원 코사인 유사도 임계값")
    args = parser.parse_args()

    asd = load_json(args.asd_tracks)
    tracks = asd["tracks"]
    chunks = load_json(args.diarization)

    face_of_track = cluster_tracks(tracks, args.sim_threshold)
    n_faces = len(set(face_of_track.values()))

    corrected = []
    attributed = 0
    for chunk in chunks:
        fid, ev = attribute_chunk(chunk, tracks, face_of_track)
        item = dict(chunk)
        item["audio_speaker"] = chunk["speaker"]
        if fid is not None:
            item["speaker"] = "V%d" % fid
            item["visual_attributed"] = True
            attributed += 1
        else:
            item["visual_attributed"] = False
        item["visual_face_id"] = fid
        item["visual_evidence"] = round(ev, 3)
        corrected.append(item)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(corrected, ensure_ascii=False, indent=2), encoding="utf-8")

    print("face clusters: %d (from %d tracks)" % (n_faces, len(tracks)))
    print("chunks: %d | 시각 귀속: %d | 오디오 폴백: %d" % (len(chunks), attributed, len(chunks) - attributed))
    print("wrote", args.output)
    print("--- 청크별 (audio 라벨 -> 시각 라벨, 발화증거) ---")
    for item in corrected:
        cid = item.get("chunk_id", "?")
        print("%s  %.1f~%.1f  %s -> %s  ev=%.2f%s" % (
            cid, item["start"], item["end"], item["audio_speaker"], item["speaker"],
            item["visual_evidence"], "" if item["visual_attributed"] else "  [폴백]"))


if __name__ == "__main__":
    main()
