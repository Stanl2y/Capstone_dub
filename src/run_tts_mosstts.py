# MOSS-TTS-Local 레퍼런스 클로닝으로 한 청크(text+reference wav)를 합성하는 독립 추론 스크립트
"""MOSS-TTS-Local-Transformer 단일 발화 합성 — clis/moss_tts_app.py 의 run_inference 흐름을 CLI 로 옮긴 것.

사용(mosstts 컨테이너 내부):
  python src/run_tts_mosstts.py --text "..." --reference ref.wav --language Korean --output out.wav
"""
from __future__ import annotations

import argparse

import numpy as np
import soundfile as sf
import torch
from transformers import AutoModel, AutoProcessor


def main() -> None:
    ap = argparse.ArgumentParser(description="MOSS-TTS-Local 단일 합성")
    ap.add_argument("--model", default="OpenMOSS-Team/MOSS-TTS-Local-Transformer")
    ap.add_argument("--text", required=True)
    ap.add_argument("--reference", help="레퍼런스 wav(클로닝). 없으면 direct generation")
    ap.add_argument("--language", help="언어 태그 예: Korean / English")
    ap.add_argument("--tokens", type=int, help="duration 제어(1초≈12.5토큰)")
    ap.add_argument("--output", required=True)
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--max-new-tokens", type=int, default=4096)
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--top-p", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=25)
    ap.add_argument("--repetition-penalty", type=float, default=1.0)
    args = ap.parse_args()

    # app.py 와 동일 — 깨진 cuDNN SDPA 백엔드 비활성, 나머지 폴백 유지
    torch.backends.cuda.enable_cudnn_sdp(False)

    device = torch.device(args.device if torch.cuda.is_available() else "cpu")
    dtype = torch.bfloat16 if device.type == "cuda" else torch.float32

    processor = AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    if hasattr(processor, "audio_tokenizer"):
        processor.audio_tokenizer = processor.audio_tokenizer.to(device)

    model = AutoModel.from_pretrained(
        args.model,
        trust_remote_code=True,
        torch_dtype=dtype,
        attn_implementation="sdpa" if device.type == "cuda" else "eager",
    ).to(device).eval()

    sample_rate = int(getattr(processor.model_config, "sampling_rate", 24000))

    user_kwargs: dict = {"text": args.text}
    if args.language:
        user_kwargs["language"] = args.language
    if args.tokens:
        user_kwargs["tokens"] = int(args.tokens)
    if args.reference:
        user_kwargs["reference"] = [args.reference]

    conversations = [[processor.build_user_message(**user_kwargs)]]
    batch = processor(conversations, mode="generation")

    with torch.no_grad():
        outputs = model.generate(
            input_ids=batch["input_ids"].to(device),
            attention_mask=batch["attention_mask"].to(device),
            max_new_tokens=int(args.max_new_tokens),
            audio_temperature=float(args.temperature),
            audio_top_p=float(args.top_p),
            audio_top_k=int(args.top_k),
            audio_repetition_penalty=float(args.repetition_penalty),
        )

    messages = processor.decode(outputs)
    if not messages or messages[0] is None:
        raise RuntimeError("MOSS-TTS 가 디코딩 가능한 오디오를 반환하지 않았다.")

    audio = messages[0].audio_codes_list[0]
    if isinstance(audio, torch.Tensor):
        audio_np = audio.detach().float().cpu().numpy()
    else:
        audio_np = np.asarray(audio, dtype=np.float32)
    audio_np = audio_np.reshape(-1).astype(np.float32, copy=False)

    sf.write(args.output, audio_np, sample_rate)
    print(f"[ok] wrote {args.output} ({len(audio_np) / sample_rate:.2f}s @ {sample_rate}Hz)")


if __name__ == "__main__":
    main()
