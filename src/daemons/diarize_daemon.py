# DiariZen(WavLM-large) 화자분리를 HTTP 로 노출하는 데몬 (fusion 의 1차 backend, 기본 port 8913).
"""DiariZen diarization daemon — 모델 1회 로딩 후 상주 (fusion backend).

client:
    POST /diarize {"vocals_wav": "...", "num_speakers": null}
       → {"segments": [{"start","end","speaker"}...], "n_speakers": ...}

diarizer 이미지(DiariZen 설치됨)에서 기동. cross-container 호출을 위해 0.0.0.0 바인딩.
fastapi/uvicorn 은 diarizer 이미지에 없으므로 docker/Dockerfile.diarizer-daemon 으로 얇게 추가한다.
"""
import argparse
import os
import time
from typing import Optional, List

# Ampere(RTX 3080) + cu121 안정화.
os.environ["TORCH_CUDNN_V8_API_DISABLED"] = "1"
os.environ["CUDNN_FRONTEND_DISABLE_GRAPH"] = "1"
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import torch
torch.backends.cudnn.enabled = False
torch.backends.cudnn.benchmark = False
_orig_load = torch.load
def _safe_load(*args, **kwargs):
    kwargs["weights_only"] = False
    return _orig_load(*args, **kwargs)
torch.load = _safe_load

from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

app = FastAPI()
_pipe = None


class DiarizeRequest(BaseModel):
    vocals_wav: str
    num_speakers: Optional[int] = None
    min_duration: float = 0.3


class DiarizeResponse(BaseModel):
    segments: List[dict]
    n_speakers: int
    success: bool
    error: Optional[str] = None


@app.on_event("startup")
async def load_model():
    global _pipe
    model_id = os.environ.get("DIARIZEN_MODEL", "BUT-FIT/diarizen-wavlm-large-s80-md-v2")
    print(f"[DiarizeDaemon] loading DiariZen ({model_id})...", flush=True)
    t0 = time.time()
    try:
        from diarizen.pipelines.inference import DiariZenPipeline
        _pipe = DiariZenPipeline.from_pretrained(model_id)
        print(f"[DiarizeDaemon] loaded ({time.time()-t0:.1f}s)", flush=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[DiarizeDaemon] load failed: {e}", flush=True)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _pipe is not None}


@app.post("/diarize", response_model=DiarizeResponse)
def diarize(req: DiarizeRequest):
    if _pipe is None:
        return DiarizeResponse(segments=[], n_speakers=0, success=False, error="model not loaded")
    if not os.path.exists(req.vocals_wav):
        return DiarizeResponse(segments=[], n_speakers=0, success=False, error=f"file not found: {req.vocals_wav}")
    try:
        import random as _r, numpy as _np
        _r.seed(42); _np.random.seed(42); torch.manual_seed(42)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(42)
        diar = _pipe(req.vocals_wav)
        segments = []
        for turn, _, speaker in diar.itertracks(yield_label=True):
            spk_str = f"SPEAKER_{int(speaker):02d}" if str(speaker).isdigit() else str(speaker)
            if turn.end - turn.start < req.min_duration:
                continue
            segments.append({"start": round(turn.start, 3), "end": round(turn.end, 3), "speaker": spk_str})
        return DiarizeResponse(segments=segments,
                               n_speakers=len(set(s["speaker"] for s in segments)), success=True)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return DiarizeResponse(segments=[], n_speakers=0, success=False, error=str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8913)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    if not torch.cuda.is_available():
        raise SystemExit("diarize_daemon: CUDA GPU가 필요하다. CPU 실행은 중단한다.")
    print(f"[DiarizeDaemon] starting on {args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
