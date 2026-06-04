# UI overrides 6개 knob 을 base config 에 화이트리스트 머지 → configs/runs/{run_id}.json 으로 저장
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from webapp.backend.app.models import RunOverrides

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/workspace/project"))
RUN_CONFIG_DIR = PROJECT_ROOT / "configs" / "runs"


def _load_base(base_config: str) -> dict:
    path = PROJECT_ROOT / base_config
    if not path.exists():
        raise FileNotFoundError(f"Base config not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def _set_nested(target: dict, dotted: str, value) -> None:
    """'tts.style_priority' → target['tts']['style_priority']=value (없으면 dict 생성)."""
    parts = dotted.split(".")
    cur = target
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value


def _scope_paths_to_run(paths: dict, run_id: str) -> dict:
    """런별 격리: per-run 산출물(meta/chunks/dub/output) 경로에 run_id 를 끼워 넣어
    같은 영상의 여러 런이 서로 덮어쓰지 않게 한다. audio(분리본)는 결정적·재계산 비싸 영상 단위 공유 유지.
    {input_stem}/{tts_engine} 플레이스홀더는 그대로 두고(나중에 expand) run_id 만 리터럴로 삽입."""
    # asd_tracks(얼굴+LightASD 발화점수)는 소스 영상만의 함수라 분리오디오와 동일하게 영상 단위 공유.
    # 격리하면 run 마다 LightASD 를 재실행하고 사전생성본도 못 쓰므로 meta/ 격리에서 제외한다.
    shared_video_level = {"asd_tracks_json"}
    scoped: dict = {}
    for key, val in paths.items():
        if not isinstance(val, str) or key in shared_video_level:
            scoped[key] = val
            continue
        if val.startswith("meta/{input_stem}/"):
            val = "meta/{input_stem}/" + run_id + "/" + val[len("meta/{input_stem}/"):]
        elif val.startswith("output/{input_stem}/"):
            val = "output/{input_stem}/" + run_id + "/" + val[len("output/{input_stem}/"):]
        elif val.startswith("chunks/{input_stem}"):
            val = "chunks/{input_stem}/" + run_id + val[len("chunks/{input_stem}"):]
        elif val.startswith("dub/{input_stem}"):
            val = "dub/{input_stem}/" + run_id + val[len("dub/{input_stem}"):]
        # audio/... 및 그 외는 공유(미변경)
        scoped[key] = val
    return scoped


# UI knob 만 허용 — 그 외 base config 필드는 절대 덮어쓰지 않는다
_OVERRIDE_MAP: dict[str, str] = {
    "target_language": "translation.target_language",
    "fit_to_duration": "tts.fit_to_duration",
    "duration_fit_max_tempo": "tts.duration_fit_max_tempo",
    "use_separator": "pipeline.use_separator",
    "skip_existing": "tts.skip_existing",
}


def build_run_config(
    *,
    run_id: str,
    base_config: str,
    overrides: RunOverrides,
    input_video: str,
) -> Path:
    """base config 사본 → overrides 적용 → input_video 셋 → configs/runs/{run_id}.json 으로 저장."""
    config = copy.deepcopy(_load_base(base_config))
    config["input_video"] = input_video
    config["run_id"] = run_id
    # 런별 격리 — per-run 산출물 경로에 run_id 삽입(같은 영상 여러 런이 서로 덮어쓰던 문제 해결)
    config["paths"] = _scope_paths_to_run(config.get("paths", {}), run_id)

    for field, value in overrides.model_dump(exclude_none=True).items():
        if field not in _OVERRIDE_MAP:
            continue
        _set_nested(config, _OVERRIDE_MAP[field], value)

    RUN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RUN_CONFIG_DIR / f"{run_id}.json"
    with out_path.open("w", encoding="utf-8") as fp:
        json.dump(config, fp, ensure_ascii=False, indent=2)
    return out_path
