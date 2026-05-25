# 여러 화자 임베딩으로 라벨 일치/재배정을 비교하는 스윕 (정답지 있으면 채점도 함)
from __future__ import annotations

import argparse
import os

import evaluate_diarization as ev  # import 시 src 경로 추가됨
import repair_diarization as rd
from common import load_json


def disagreements(chunks, embs):
    # 초기 centroid 기준, 임베딩이 고른 최고 화자가 DiariZen 라벨과 다른 청크를 찾는다.
    cents = rd._speaker_centroids(chunks, embs)
    out = []
    for c in chunks:
        cid = c["chunk_id"]
        if cid not in embs:
            continue
        sims = {s: rd._dot(embs[cid], v) for s, v in cents.items()}
        best = max(sims, key=sims.get)
        cur = str(c["speaker"])
        if best != cur:
            out.append((cid, cur, best, round(sims[best], 3), round(sims.get(cur, -1.0), 3)))
    return out


def run_one(label, chunks_json, emb_json, margin, expectations, audio):
    chunks = load_json(chunks_json)
    embs = load_json(emb_json)
    dis = disagreements(chunks, embs)
    repaired = rd._embed_reassign(chunks, embeddings_json=emb_json, margin=margin, min_sim=0.5, passes=3)
    n_re = sum(1 for c in repaired if c.get("reassigned_by"))
    line = f"[{label}]  label_mismatch={len(dis)}  reassigned(margin {margin})={n_re}"
    if expectations and os.path.exists(expectations):
        report = ev.evaluate_diarization(
            ev.normalize_records(repaired),
            expectations=ev.load_expectation_spec(expectations),
            audio_duration_sec=ev.read_audio_duration(audio) if audio and os.path.exists(audio) else None,
        )
        tm = report["targeted_expectation_metrics"]
        sim = tm["speaker_identity_metrics"]
        line += f"  identity_error={sim['speaker_identity_error']:.4f}  weighted={tm['weighted_score']:.4f}"
    print(line)
    for cid, cur, best, bs, cs in dis:
        print(f"     {cid}: label {cur} but embedding best {best}({bs}) > {cur}({cs})")


def main():
    parser = argparse.ArgumentParser(description="임베딩별 라벨 일치/재배정 비교 (정답지 있으면 채점).")
    parser.add_argument("--chunks", default="meta/77506256_TEST/speaker_chunks.json")
    parser.add_argument("--expectations", default="references/diarization_expectations/TEST.json")
    parser.add_argument("--audio", default="audio/77506256_TEST/dialogue.wav")
    parser.add_argument("--margin", type=float, default=0.02)
    parser.add_argument("--no-eval", action="store_true", help="정답지 없는 클립용 — 채점 생략")
    parser.add_argument("--emb", nargs="+", required=True, help='"label=경로" 쌍 목록')
    args = parser.parse_args()

    expectations = None if args.no_eval else args.expectations
    print(f"margin={args.margin}\n")
    for spec in args.emb:
        label, _, path = spec.partition("=")
        run_one(label, args.chunks, path, args.margin, expectations, args.audio)
        print()


if __name__ == "__main__":
    main()
