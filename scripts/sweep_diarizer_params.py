# DiariZen clustering 파라미터 sweep — chunk_0006 가 3번째 클러스터로 분리되는 조합 찾기
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "/workspace/project/src")
import torch
from diarizen.pipelines.inference import DiariZenPipeline


def run_one(audio_path: str, model_path: str, embedding_path: str, params: dict) -> dict:
    import toml
    base = toml.load(str(Path(model_path) / "config.toml"))
    inf_args = dict(base["inference"]["args"])
    cl_args = dict(base["clustering"]["args"])
    inf_keys = {"seg_duration", "segmentation_step", "batch_size", "apply_median_filtering"}
    for k, v in params.items():
        if k in inf_keys:
            inf_args[k] = v
        else:
            cl_args[k] = v
    config_parse = {"inference": {"args": inf_args}, "clustering": {"args": cl_args}}

    pipe = DiariZenPipeline(
        diarizen_hub=Path(model_path).absolute(),
        embedding_model=embedding_path,
        config_parse=config_parse,
    )
    pipe.to(torch.device("cuda:0"))
    ann = pipe(audio_path)
    segs = list(ann.itertracks(yield_label=True))
    spk_set = set(str(s) for _, _, s in segs)
    return {"params": params, "n_speakers": len(spk_set), "segments": [(float(t.start), float(t.end), str(s)) for t, _, s in segs]}


def main():
    audio = "/workspace/project/audio/1_original/dialogue.wav"
    model = "/workspace/project/models/diarization/diarizen-wavlm-large-s80-md-v2"
    emb = "/workspace/project/models/embedding/wespeaker-voxceleb-resnet34-LM/speaker-embedding.onnx"

    # chunk_0006 시간: 10.37-12.47s. chunks 1,2,4,7 = Bart. chunks 3,5 = 다른 화자.
    # 목표 — 10.37s 부근 segment 가 chunks 1/2/4/7 와 다른 라벨이어야 함.

    trials = [
        # 짧은 segmentation window
        {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.05, "Fa": 1.0, "Fb": 0.05},
        {"seg_duration": 2, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "Fa": 1.0, "Fb": 0.05},
        {"seg_duration": 1, "segmentation_step": 0.025, "apply_median_filtering": False, "ahc_threshold": 0.0, "Fa": 1.0, "Fb": 0.05},
        {"seg_duration": 8, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "Fa": 0.5, "Fb": 0.1},
        # median filtering on/off
        {"seg_duration": 16, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "Fa": 1.0, "Fb": 0.01},
        {"seg_duration": 16, "segmentation_step": 0.025, "apply_median_filtering": False, "ahc_threshold": 0.0, "Fa": 2.0, "Fb": 0.005},
        # max_iters 매우 크게
        {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "Fa": 1.0, "Fb": 0.001, "max_iters": 200},
        # lda_dim 변경
        {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "lda_dim": 256, "Fa": 1.0, "Fb": 0.05},
        {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "lda_dim": 32, "Fa": 1.0, "Fb": 0.05},
        # forced via min/max speakers
        {"seg_duration": 4, "segmentation_step": 0.05, "apply_median_filtering": False, "ahc_threshold": 0.0, "min_speakers": 3, "max_speakers": 7, "Fa": 1.0, "Fb": 0.05},
    ]
    for i, p in enumerate(trials, 1):
        print(f"\n--- trial {i}/{len(trials)}: {p} ---")
        try:
            res = run_one(audio, model, emb, p)
        except Exception as e:
            print(f"ERR: {e}")
            continue
        n = res["n_speakers"]
        # chunk_0006 라벨 추정 — 10.4 ~ 12.5 사이 segment
        lab_at_chunk6 = None
        for s, e, lab in res["segments"]:
            if 10.4 <= s <= 12.5 or (s < 11.5 < e):
                lab_at_chunk6 = lab
                break
        # chunk_0001 라벨
        lab_at_chunk1 = None
        for s, e, lab in res["segments"]:
            if 0.3 <= s <= 2.6 or (s < 1.5 < e):
                lab_at_chunk1 = lab
                break
        print(f"  -> {n} speakers | chunk_0001 label={lab_at_chunk1} | chunk_0006 label={lab_at_chunk6}")
        if n >= 3 and lab_at_chunk6 != lab_at_chunk1:
            print("  *** SUCCESS *** chunk_0006 differs from chunk_0001")


if __name__ == "__main__":
    main()
