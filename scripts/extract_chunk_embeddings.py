# 청크 wav에서 wespeaker 화자 임베딩(256d)을 추출해 JSON으로 저장하는 스크립트 (Docker/GPU)
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
import torchaudio
import torchaudio.compliance.kaldi as kaldi

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "models/embedding/wespeaker-voxblink2-samresnet100/speaker-embedding.onnx"


def _fbank_from_waveform(waveform: torch.Tensor, sr: int) -> np.ndarray:
    # wespeaker 표준 전처리. mono → 16k → int16 스케일 → 80-dim fbank(hamming) → utterance CMN.
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    if sr != 16000:
        waveform = torchaudio.functional.resample(waveform, sr, 16000)
    waveform = waveform * (1 << 15)
    feat = kaldi.fbank(
        waveform,
        num_mel_bins=80,
        frame_length=25,
        frame_shift=10,
        dither=0.0,
        sample_frequency=16000,
        window_type="hamming",
        use_energy=False,
    )
    feat = feat - feat.mean(dim=0, keepdim=True)
    return feat.unsqueeze(0).numpy().astype(np.float32)


def compute_fbank(wav_path: str) -> np.ndarray:
    # 청크 wav 파일 한 개에서 fbank 추출.
    waveform, sr = torchaudio.load(wav_path)
    return _fbank_from_waveform(waveform, sr)


def main() -> None:
    parser = argparse.ArgumentParser(description="청크 wav에서 화자 임베딩을 추출한다.")
    parser.add_argument("--chunks", required=True, help="speaker_chunks JSON")
    parser.add_argument("--output", required=True, help="임베딩 JSON 출력 경로 {chunk_id: [256 floats]}")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--chunks-dir", help="speaker_chunks에 wav 필드가 없을 때 청크 wav가 있는 디렉터리")
    parser.add_argument("--audio", help="이 오디오(예: dialogue.wav)에서 각 청크의 [start,end] 구간을 잘라 임베딩 추출 — cut_chunks 전에 사용")
    args = parser.parse_args()

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if args.device == "cuda" else ["CPUExecutionProvider"]
    sess = ort.InferenceSession(str(PROJECT_ROOT / args.model), providers=providers)
    print("providers:", sess.get_providers(), file=sys.stderr)
    input_name = sess.get_inputs()[0].name

    chunks = json.loads(Path(args.chunks).read_text(encoding="utf-8"))

    # --audio 모드: 마스터 오디오를 한 번 로드해 각 청크 [start,end] 구간을 시간슬라이스(cut_chunks 불필요).
    full_wave = None
    full_sr = 0
    if args.audio:
        apath = str(PROJECT_ROOT / args.audio) if not Path(args.audio).is_absolute() else args.audio
        full_wave, full_sr = torchaudio.load(apath)
        print(f"audio slice mode: {apath} sr={full_sr} samples={full_wave.shape[-1]}", file=sys.stderr)

    out: dict[str, list[float]] = {}
    for ch in chunks:
        if full_wave is not None:
            a = max(0, int(float(ch["start"]) * full_sr))
            b = min(full_wave.shape[-1], int(float(ch["end"]) * full_sr))
            if b - a < int(0.05 * full_sr):  # 50ms 미만은 임베딩 불가 → 건너뜀(짧은 토막은 라벨 유지)
                print("too short to embed:", ch["chunk_id"], file=sys.stderr)
                continue
            feats = _fbank_from_waveform(full_wave[:, a:b], full_sr)
        else:
            rel = ch.get("wav") or (f"{args.chunks_dir}/{ch['chunk_id']}.wav" if args.chunks_dir else None)
            if not rel:
                print("no wav path for", ch["chunk_id"], file=sys.stderr)
                continue
            wav = str(PROJECT_ROOT / rel)
            if not Path(wav).exists():
                print("MISSING wav:", wav, file=sys.stderr)
                continue
            feats = compute_fbank(wav)
        emb = sess.run(None, {input_name: feats})[0][0].astype(np.float32)
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        out[ch["chunk_id"]] = emb.round(6).tolist()
        print(f"{ch['chunk_id']} {ch['speaker']} {ch['start']:.1f}-{ch['end']:.1f}  dim={emb.shape[0]}", file=sys.stderr)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {args.output} ({len(out)} embeddings)", file=sys.stderr)


if __name__ == "__main__":
    main()
