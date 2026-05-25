# ASR 결과로 비대사 청크(외국어 효과음·빈 텍스트 마이크로 파편)를 걸러 대사 청크만 남기는 스크립트
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from common import load_json, save_json


def filter_chunks(chunks_json: str, asr_json: str, output_json: str, *,
                  target_langs: set[str], dropped_json: str | None = None) -> None:
    chunks = load_json(chunks_json)
    asr = {r["chunk_id"]: r for r in load_json(asr_json)}

    kept, dropped = [], []
    for c in chunks:
        r = asr.get(c["chunk_id"], {})
        text = (r.get("text_src") or "").strip()
        lang = (r.get("language") or "").strip()
        reason = None
        if not text:
            reason = "empty(no-speech)"
        elif lang.lower() not in target_langs:
            reason = f"foreign({lang})"
        if reason:
            item = dict(c)
            item["non_dialogue_reason"] = reason
            dropped.append(item)
        else:
            kept.append(c)

    save_json(kept, output_json)
    if dropped_json:
        save_json(dropped, dropped_json)
    print(f"kept {len(kept)} dialogue chunks, dropped {len(dropped)} non-dialogue:")
    for d in dropped:
        t = (asr.get(d["chunk_id"], {}).get("text_src") or "").strip()
        print(f"  - {d['chunk_id']} {d['start']:.1f}-{d['end']:.1f} ({d['end']-d['start']:.1f}s) [{d['non_dialogue_reason']}] '{t}'")


def main() -> None:
    parser = argparse.ArgumentParser(description="ASR 결과로 비대사 청크를 걸러낸다.")
    parser.add_argument("chunks_json")
    parser.add_argument("asr_json")
    parser.add_argument("output_json")
    parser.add_argument("--target-langs", default="english,en")
    parser.add_argument("--dropped-json")
    args = parser.parse_args()
    langs = {x.strip().lower() for x in args.target_langs.split(",") if x.strip()}
    filter_chunks(args.chunks_json, args.asr_json, args.output_json, target_langs=langs, dropped_json=args.dropped_json)


if __name__ == "__main__":
    main()
