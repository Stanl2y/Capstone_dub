# 청크별 임베딩 직접 추출 + pairwise cosine distance 출력
import numpy as np
import onnxruntime as ort
import torchaudio
import torch
import sys
from pathlib import Path

def extract_fbank(wav_path, sample_rate=16000, num_mel_bins=80):
    waveform, sr = torchaudio.load(wav_path)
    if sr != sample_rate:
        waveform = torchaudio.functional.resample(waveform, sr, sample_rate)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(0, keepdim=True)
    waveform = waveform * (1 << 15)
    fbank = torchaudio.compliance.kaldi.fbank(
        waveform, num_mel_bins=num_mel_bins, frame_length=25, frame_shift=10,
        dither=0, sample_frequency=sample_rate, window_type="hamming",
        use_energy=False
    )
    fbank = fbank - fbank.mean(0, keepdim=True)
    return fbank.numpy()

def get_embedding(sess, fbank):
    feats = fbank[None, :, :].astype(np.float32)
    emb = sess.run(None, {"feats": feats})[0][0]
    return emb / np.linalg.norm(emb)

def cos_dist(a, b):
    return 1.0 - float(np.dot(a, b))

def main():
    onnx_path = sys.argv[1]
    chunks_dir = "/workspace/project/chunks/1_original"
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    chunk_ids = [f"chunk_{i:04d}" for i in range(1, 8)]
    embs = {}
    for cid in chunk_ids:
        wav = f"{chunks_dir}/{cid}.wav"
        fb = extract_fbank(wav)
        embs[cid] = get_embedding(sess, fb)
    expected = {
        "chunk_0001": "Bart",
        "chunk_0002": "Bart",
        "chunk_0003": "Other",
        "chunk_0004": "Bart",
        "chunk_0005": "Other",
        "chunk_0006": "Ralph",
        "chunk_0007": "Bart",
    }
    print(f"\n=== Pairwise cosine distance ({Path(onnx_path).parent.name}) ===")
    print("       " + " ".join(f"{c[6:]:>6}" for c in chunk_ids))
    for cid in chunk_ids:
        row = " ".join(f"{cos_dist(embs[cid], embs[other]):6.3f}" for other in chunk_ids)
        print(f"{cid[6:]:>6} {row}  ({expected[cid]})")
    print("\n--- 핵심 거리 ---")
    print(f"chunk_0006(Ralph) vs chunk_0001(Bart): {cos_dist(embs['chunk_0006'], embs['chunk_0001']):.3f}")
    print(f"chunk_0006(Ralph) vs chunk_0002(Bart): {cos_dist(embs['chunk_0006'], embs['chunk_0002']):.3f}")
    print(f"chunk_0006(Ralph) vs chunk_0003(Other): {cos_dist(embs['chunk_0006'], embs['chunk_0003']):.3f}")
    print(f"chunk_0001(Bart) vs chunk_0002(Bart): {cos_dist(embs['chunk_0001'], embs['chunk_0002']):.3f}  (같은 화자 기준)")
    print(f"chunk_0003(Other) vs chunk_0005(Other): {cos_dist(embs['chunk_0003'], embs['chunk_0005']):.3f}  (같은 화자 기준)")

if __name__ == "__main__":
    main()
