# VibeVoice-ASR 로컬 8비트 추론을 검증하는 독립 실행 스크립트
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import torch
from transformers import AutoProcessor, BitsAndBytesConfig

try:
    from transformers import VibeVoiceAsrForConditionalGeneration
except ImportError as exc:
    raise RuntimeError(
        "VibeVoiceAsrForConditionalGeneration is unavailable. Build the vibevoice-asr image with a Transformers version that supports VibeVoice-ASR."
    ) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local VibeVoice-ASR-HF with 8-bit loading on a short audio sample.")
    parser.add_argument("--model-dir", default="models/asr/VibeVoice-ASR-HF")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--output")
    parser.add_argument("--format", choices=("parsed", "text", "raw"), default="parsed")
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--gpu-memory", default="11GiB")
    parser.add_argument("--cpu-memory", default="32GiB")
    parser.add_argument("--cpu-offload", action="store_true")
    parser.add_argument("--prompt")
    return parser.parse_args()


def move_value_to_cuda(value: Any) -> Any:
    if torch.is_tensor(value):
        if value.is_floating_point():
            return value.to(device="cuda", dtype=torch.float16)
        return value.to(device="cuda")
    if isinstance(value, dict):
        return {key: move_value_to_cuda(item) for key, item in value.items()}
    if isinstance(value, list):
        return [move_value_to_cuda(item) for item in value]
    if isinstance(value, tuple):
        return tuple(move_value_to_cuda(item) for item in value)
    return value


def move_inputs_to_model(inputs: Any, model: Any) -> Any:
    if hasattr(inputs, "to"):
        return inputs.to(model.device, model.dtype)
    if hasattr(inputs, "items"):
        return {key: move_value_to_cuda(value) for key, value in inputs.items()}
    moved = move_value_to_cuda(inputs)
    if not isinstance(moved, dict):
        raise TypeError(f"Expected processor inputs to be mapping-like, got {type(inputs).__name__}")
    return moved


def decode_output(processor: Any, generated_ids: torch.Tensor, output_format: str) -> Any:
    if output_format == "raw":
        decoded = processor.decode(generated_ids)
        return {"raw": decoded[0] if isinstance(decoded, list) else decoded}

    if output_format == "text":
        decoded = processor.decode(generated_ids, return_format="transcription_only")
        return {"text": decoded[0] if isinstance(decoded, list) else decoded}

    try:
        decoded = processor.decode(generated_ids, return_format="parsed")
        return decoded[0] if isinstance(decoded, list) else decoded
    except Exception as exc:  # noqa: BLE001
        decoded = processor.decode(generated_ids)
        return {
            "parse_error": str(exc),
            "raw": decoded[0] if isinstance(decoded, list) else decoded,
        }


def main() -> None:
    args = parse_args()

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the 8-bit VibeVoice-ASR test container.")

    model_dir = Path(args.model_dir).resolve()
    audio_path = Path(args.audio).resolve()
    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory does not exist: {model_dir}")
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

    max_memory: dict[Any, str] = {0: args.gpu_memory}
    if args.cpu_offload:
        max_memory["cpu"] = args.cpu_memory

    quantization_config = BitsAndBytesConfig(
        load_in_8bit=True,
        llm_int8_enable_fp32_cpu_offload=args.cpu_offload,
    )

    processor = AutoProcessor.from_pretrained(
        model_dir,
        local_files_only=True,
        trust_remote_code=True,
    )
    model = VibeVoiceAsrForConditionalGeneration.from_pretrained(
        model_dir,
        quantization_config=quantization_config,
        device_map="auto",
        max_memory=max_memory,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
        local_files_only=True,
        trust_remote_code=True,
    )

    request_kwargs: dict[str, Any] = {"audio": str(audio_path)}
    if args.prompt:
        request_kwargs["prompt"] = args.prompt
    inputs = processor.apply_transcription_request(**request_kwargs)
    inputs = move_inputs_to_model(inputs, model)

    with torch.inference_mode():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=args.max_new_tokens,
        )

    generated_ids = output_ids[:, inputs["input_ids"].shape[1]:]
    result = decode_output(processor, generated_ids, args.format)

    output_text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output_text + "\n", encoding="utf-8")
    else:
        print(output_text)


if __name__ == "__main__":
    main()
