# sample.mp4 청크별 임베딩 pairwise 거리
import numpy as np, onnxruntime as ort, torchaudio, sys
from pathlib import Path

def extract_fbank(wav_path):
    waveform, sr = torchaudio.load(wav_path)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(0, keepdim=True)
    waveform = waveform * (1 << 15)
    fbank = torchaudio.compliance.kaldi.fbank(
        waveform, num_mel_bins=80, frame_length=25, frame_shift=10,
        dither=0, sample_frequency=16000, window_type="hamming", use_energy=False)
    return (fbank - fbank.mean(0, keepdim=True)).numpy()

def main():
    onnx_path = sys.argv[1]
    chunks_dir = "/workspace/project/chunks/sample"
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    chunk_ids = [f"chunk_{i:04d}" for i in range(1, 14)]
    embs = {}
    for cid in chunk_ids:
        wav = f"{chunks_dir}/{cid}.wav"
        if not Path(wav).exists(): continue
        fb = extract_fbank(wav)
        feats = fb[None, :, :].astype(np.float32)
        emb = sess.run(None, {"feats": feats})[0][0]
        embs[cid] = emb / np.linalg.norm(emb)
    valid = list(embs.keys())
    print(f"Computed embeddings for {len(valid)} chunks: {valid}")
    print(f"\n=== chunk_0003 (Hamburgers) vs others ===")
    for cid in valid:
        if cid == "chunk_0003": continue
        d = 1 - np.dot(embs["chunk_0003"], embs[cid])
        print(f"  {cid}: {d:.3f}")
    print(f"\n=== chunk_0005 (Triple) vs others ===")
    if "chunk_0005" in embs:
        for cid in valid:
            if cid == "chunk_0005": continue
            d = 1 - np.dot(embs["chunk_0005"], embs[cid])
            print(f"  {cid}: {d:.3f}")
    print(f"\n=== chunk_0006 (My heart) vs others ===")
    if "chunk_0006" in embs:
        for cid in valid:
            if cid == "chunk_0006": continue
            d = 1 - np.dot(embs["chunk_0006"], embs[cid])
            print(f"  {cid}: {d:.3f}")

if __name__ == "__main__":
    main()
