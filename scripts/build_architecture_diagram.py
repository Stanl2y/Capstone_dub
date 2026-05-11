# 영상 더빙 자동화 시스템의 6 단계 파이프라인을 A4 세로 300dpi 흐름도로 렌더 — Pillow 만 사용
"""scripts/build_architecture_diagram.py — docs/booklet-screenshots/diagram-architecture.{png,jpg} 생성."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ─── canvas (A4 세로 @ 300dpi) ─────────────────────────────────────────────────
DPI = 300
A4_W = int(8.27 * DPI)   # 2481
A4_H = int(11.69 * DPI)  # 3507

# ─── tokens ────────────────────────────────────────────────────────────────────
BG = (255, 255, 255)
INK = (15, 23, 42)
BODY = (51, 65, 85)
META = (148, 163, 184)
DIV = (226, 232, 240)
DASH = (180, 190, 210)

ARROW_INK = (100, 116, 139)
DASHED_ARROW = (148, 163, 184)

STAGE_NUM_FILL = (252, 226, 226)
STAGE_NUM_STROKE = (220, 38, 38)
STAGE_NUM_INK = (185, 28, 28)

PAL: dict[str, dict[str, tuple[int, int, int]]] = {
    "io":     {"fill": (251, 207, 232), "stroke": (190, 24, 93)},
    "model":  {"fill": (220, 252, 231), "stroke": (16, 185, 129)},
    "tool":   {"fill": (254, 243, 199), "stroke": (217, 119, 6)},
    "cloud":  {"fill": (219, 234, 254), "stroke": (37, 99, 235)},
    "tts":    {"fill": (252, 231, 243), "stroke": (236, 72, 153)},
    "data":   {"fill": (255, 251, 235), "stroke": (156, 163, 175)},
}

FONTS = {
    "ko": "C:/Windows/Fonts/malgun.ttf",
    "ko_bold": "C:/Windows/Fonts/malgunbd.ttf",
    "mono": "C:/Windows/Fonts/consola.ttf",
    "mono_bold": "C:/Windows/Fonts/consolab.ttf",
}


def load(font_key, size):
    try:
        return ImageFont.truetype(FONTS[font_key], size)
    except OSError:
        return ImageFont.load_default()


def _has_korean(s):
    return any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ" for ch in s)


def _font_for(s, *, mono="mono", ko="ko"):
    return ko if _has_korean(s) else mono


# ─── primitives ────────────────────────────────────────────────────────────────
def text(draw, xy, s, *, font_key, size, color=INK, anchor="la"):
    draw.text(xy, s, font=load(font_key, size), fill=color, anchor=anchor)


def text_center(draw, x, y, w, s, *, font_key, size, color=INK):
    draw.text((x + w // 2, y), s, font=load(font_key, size), fill=color, anchor="ma")


def rrect(draw, xy, radius, *, fill=None, outline=None, width=0):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def dashed_rect(draw, xy, *, color, width=2, dash=14, gap=10):
    x1, y1, x2, y2 = xy
    for y in (y1, y2):
        x = x1
        while x < x2:
            end = min(x + dash, x2)
            draw.line([(x, y), (end, y)], fill=color, width=width)
            x = end + gap
    for x in (x1, x2):
        y = y1
        while y < y2:
            end = min(y + dash, y2)
            draw.line([(x, y), (x, end)], fill=color, width=width)
            y = end + gap


def line(draw, p1, p2, *, color=ARROW_INK, w=2, dashed=False):
    if not dashed:
        draw.line([p1, p2], fill=color, width=w)
        return
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2:
        ys, ye = sorted([y1, y2])
        y = ys
        while y < ye:
            end = min(y + 12, ye)
            draw.line([(x1, y), (x1, end)], fill=color, width=w)
            y = end + 8
    else:
        xs, xe = sorted([x1, x2])
        x = xs
        while x < xe:
            end = min(x + 12, xe)
            draw.line([(x, y1), (end, y1)], fill=color, width=w)
            x = end + 8


def arrow_h(draw, x_start, x_end, y, *, color=ARROW_INK, w=2, head=12):
    if x_end > x_start:
        draw.line([(x_start, y), (x_end - head, y)], fill=color, width=w)
        draw.polygon([(x_end, y), (x_end - head, y - head // 2), (x_end - head, y + head // 2)], fill=color)
    else:
        draw.line([(x_start, y), (x_end + head, y)], fill=color, width=w)
        draw.polygon([(x_end, y), (x_end + head, y - head // 2), (x_end + head, y + head // 2)], fill=color)


def arrow_v(draw, x, y_start, y_end, *, color=ARROW_INK, w=2, head=12):
    if y_end > y_start:
        draw.line([(x, y_start), (x, y_end - head)], fill=color, width=w)
        draw.polygon([(x, y_end), (x - head // 2, y_end - head), (x + head // 2, y_end - head)], fill=color)
    else:
        draw.line([(x, y_start), (x, y_end + head)], fill=color, width=w)
        draw.polygon([(x, y_end), (x - head // 2, y_end + head), (x + head // 2, y_end + head)], fill=color)


def draw_path(draw, points, *, color=ARROW_INK, w=2, head=12, dashed=False):
    n = len(points)
    for i in range(n - 1):
        p1 = points[i]
        p2 = points[i + 1]
        is_last = i == n - 2
        if not is_last:
            line(draw, p1, p2, color=color, w=w, dashed=dashed)
        else:
            x1, y1 = p1
            x2, y2 = p2
            if x1 == x2:
                if dashed:
                    line(draw, p1, p2, color=color, w=w, dashed=True)
                    if y2 > y1:
                        draw.polygon([(x2, y2), (x2 - head // 2, y2 - head), (x2 + head // 2, y2 - head)], fill=color)
                    else:
                        draw.polygon([(x2, y2), (x2 - head // 2, y2 + head), (x2 + head // 2, y2 + head)], fill=color)
                else:
                    arrow_v(draw, x1, y1, y2, color=color, w=w, head=head)
            elif y1 == y2:
                if dashed:
                    line(draw, p1, p2, color=color, w=w, dashed=True)
                    if x2 > x1:
                        draw.polygon([(x2, y2), (x2 - head, y2 - head // 2), (x2 - head, y2 + head // 2)], fill=color)
                    else:
                        draw.polygon([(x2, y2), (x2 + head, y2 - head // 2), (x2 + head, y2 + head // 2)], fill=color)
                else:
                    arrow_h(draw, x1, x2, y1, color=color, w=w, head=head)
            else:
                line(draw, p1, p2, color=color, w=w, dashed=dashed)


# ─── node / stage label ────────────────────────────────────────────────────────
def draw_node(draw, x, y, w, h, *, kind, title, subtitle="", meta="",
              title_size=16, subtitle_size=13, meta_size=11):
    color = PAL[kind]
    rrect(draw, (x, y, x + w, y + h), radius=10,
          fill=color["fill"], outline=color["stroke"], width=2)
    cy = y + 14
    text_center(draw, x, cy, w, title,
                font_key=_font_for(title, mono="mono_bold", ko="ko_bold"),
                size=title_size, color=INK)
    cy += title_size + 12
    if subtitle:
        for ln in subtitle.split("\n"):
            text_center(draw, x, cy, w, ln, font_key=_font_for(ln), size=subtitle_size, color=BODY)
            cy += subtitle_size + 4
    if meta:
        text_center(draw, x, y + h - meta_size - 12, w, meta,
                    font_key=_font_for(meta), size=meta_size, color=META)


def draw_stage_label(draw, x, y, num, label):
    r = 18
    draw.ellipse((x, y, x + 2 * r, y + 2 * r),
                 fill=STAGE_NUM_FILL, outline=STAGE_NUM_STROKE, width=2)
    text(draw, (x + r, y + r), num, font_key="ko_bold", size=18,
         color=STAGE_NUM_INK, anchor="mm")
    text(draw, (x + 2 * r + 14, y + 6), label,
         font_key="ko_bold", size=22, color=INK)


# ─── layout 상수 ─────────────────────────────────────────────────────────────
M = 60
INNER_W = A4_W - 2 * M
NW = 280
NH = 130
NODE_GAP = 60
ROW_GAP = 60
STAGE_GAP = 80

LINEAR_H = 50 + 30 + NH + 30                       # 240
PARALLEL_H = 50 + 30 + NH + ROW_GAP + NH + 30      # 410
FORK_MERGE_H = 50 + 30 + NH + ROW_GAP + NH + ROW_GAP + NH + 30  # 600


def layout_horizontal(stage_x, stage_w, n):
    total_w = n * NW + (n - 1) * NODE_GAP
    x_start = stage_x + (stage_w - total_w) // 2
    return [x_start + i * (NW + NODE_GAP) for i in range(n)]


# ─── stages 데이터 ───────────────────────────────────────────────────────────
STAGES: list[dict] = [
    {
        "num": "1", "label": "오디오 분리  (extract · separate · redirect)",
        "type": "linear",
        "nodes": [
            {"kind": "tool", "title": "ffmpeg",
             "subtitle": "오디오 추출", "meta": "src/extract_audio.py"},
            {"kind": "model", "title": "BS-RoFormer + MDX23C",
             "subtitle": "보컬 / 배경 음원 분리", "meta": "subtractive ensemble 0.5/0.5"},
            {"kind": "data", "title": "dialogue.wav · bgm.wav",
             "subtitle": "분리된 오디오", "meta": "audio/{stem}/"},
            {"kind": "tool", "title": "Silero-VAD",
             "subtitle": "비발화 → bgm 재배치", "meta": "threshold 0.3 · pad 100ms"},
            {"kind": "data", "title": "dialogue.wav (clean)",
             "subtitle": "발화 영역만 남음", "meta": "audio/{stem}/"},
        ],
    },
    {
        "num": "2", "label": "화자 분리 + 청크화  (diarize · stabilize · merge · cut)",
        "type": "linear",
        "nodes": [
            {"kind": "model", "title": "DiariZen + WeSpeaker",
             "subtitle": "화자 분리 + 임베딩", "meta": "WavLM-Large s80-md-v2"},
            {"kind": "tool", "title": "stabilize_diarization",
             "subtitle": "5-pass 안정화", "meta": "bridge · absorb · tiny"},
            {"kind": "tool", "title": "merge_speaker_chunks",
             "subtitle": "연속 발화 병합", "meta": "gap 1s · 0.5–15s"},
            {"kind": "tool", "title": "cut_chunks (ffmpeg)",
             "subtitle": "청크 wav 분할", "meta": "src/cut_chunks.py"},
            {"kind": "data", "title": "speaker_chunks.json",
             "subtitle": "청크 메타 + chunks/*.wav", "meta": "meta/{stem}/ · chunks/{stem}/"},
        ],
    },
    {
        "num": "3", "label": "음성 분석  (병렬: 감정 + ASR)",
        "type": "parallel",
        "branches": [
            [  # 위 갈래: emotion
                {"kind": "model", "title": "emotion2vec_plus_large",
                 "subtitle": "감정 분석 (FunASR)", "meta": "7-class label"},
                {"kind": "data", "title": "emotion.json",
                 "subtitle": "label · probs · tts_emotion_hint", "meta": "meta/{stem}/"},
            ],
            [  # 아래 갈래: asr
                {"kind": "model", "title": "Qwen3-ASR-1.7B",
                 "subtitle": "음성 인식 (float16)", "meta": "+ audio_features 피처 추출"},
                {"kind": "data", "title": "asr.json",
                 "subtitle": "text_src · features · gates", "meta": "meta/{stem}/"},
            ],
        ],
        # 각 branch 가 다음 단계의 어떤 노드 idx 로 들어가는지
        "branch_targets": [2, 0],  # emotion → build_master_timeline (idx 2), asr → LLM (idx 0)
    },
    {
        "num": "4", "label": "번역 + 타임라인 + TTS 디렉티브",
        "type": "linear",
        "nodes": [
            {"kind": "cloud", "title": "LLM",
             "subtitle": "원문 → 대상 언어 번역", "meta": "context_refine + budget rewrite ×2"},
            {"kind": "data", "title": "translated.json",
             "subtitle": "text_translated · text_tts", "meta": "meta/{stem}/"},
            {"kind": "tool", "title": "build_master_timeline",
             "subtitle": "ASR · 번역 · 감정 통합", "meta": "src/build_master_timeline.py"},
            {"kind": "cloud", "title": "LLM",
             "subtitle": "TTS instruct 생성", "meta": "batch 6 · style instruct"},
            {"kind": "data", "title": "master_timeline_{engine}.json",
             "subtitle": "통합 타임라인", "meta": "meta/{stem}/"},
        ],
    },
    {
        "num": "5", "label": "음성 합성 + 품질 평가  (Voice Cloning)",
        "type": "fork_merge",
        "main": [
            {"kind": "tts", "title": "Fun-CosyVoice3-0.5B",
             "subtitle": "Zero-shot Voice Cloning", "meta": "cross-lingual · tempo 0.8–1.25"},
            {"kind": "data", "title": "dub/{stem}_{engine}/*_dub.wav",
             "subtitle": "청크별 더빙 오디오", "meta": "44.1kHz / 1ch"},
            {"kind": "data", "title": "Reference Bank",
             "subtitle": "화자별 best 청크 누적", "meta": "다음 합성 reference 재활용"},
        ],
        "evaluators": [
            {"kind": "model", "title": "Qwen3-ASR validate",
             "subtitle": "재인식 검증 (옵션)", "meta": "기본 off · mark_stale_on_fail",
             "position": "top"},
            {"kind": "model", "title": "MOS Evaluator",
             "subtitle": "파인튜닝 모델", "meta": "화자별 best 청크 측정",
             "position": "bottom"},
        ],
    },
    {
        "num": "6", "label": "최종 합성 + 영상 출력  (compose · mux)",
        "type": "linear",
        "nodes": [
            {"kind": "tool", "title": "compose_audio",
             "subtitle": "더빙 + 배경 믹싱", "meta": "background 0.8 · peak −1 dBFS"},
            {"kind": "data", "title": "final_dub_{engine}.wav",
             "subtitle": "최종 오디오", "meta": "44.1kHz / 2ch"},
            {"kind": "tool", "title": "ffmpeg mux",
             "subtitle": "영상 + 오디오 결합", "meta": "AAC 192k · video copy"},
        ],
    },
]


# ─── 단계 그리기 ────────────────────────────────────────────────────────────
def draw_stage(draw, x, y, w, stage):
    """단계 박스 + 노드 + 안 화살표 그리기. info 반환."""
    draw_stage_label(draw, x + 6, y, stage["num"], stage["label"])
    box_y_start = y + 50

    if stage["type"] == "linear":
        h = LINEAR_H
        dashed_rect(draw, (x, box_y_start, x + w, y + h), color=DASH, width=2)
        body_y = y + 50 + 30
        nodes = stage["nodes"]
        n = len(nodes)
        positions = layout_horizontal(x, w, n)
        for nx, node in zip(positions, nodes):
            draw_node(draw, nx, body_y, NW, NH, **node)
        for i in range(n - 1):
            arrow_h(draw, positions[i] + NW, positions[i + 1], body_y + NH // 2)
        return {
            "type": "linear",
            "h": h,
            "body_y": body_y,
            "positions": positions,
            "first_top": (positions[0] + NW // 2, body_y),
            "first_left_x": positions[0],
            "first_left_cy": body_y + NH // 2,
            "last_bottom": (positions[-1] + NW // 2, body_y + NH),
            "last_right_x": positions[-1] + NW,
            "last_right_cy": body_y + NH // 2,
        }
    elif stage["type"] == "parallel":
        h = PARALLEL_H
        dashed_rect(draw, (x, box_y_start, x + w, y + h), color=DASH, width=2)
        body_y_top = y + 50 + 30
        body_y_bot = body_y_top + NH + ROW_GAP
        branches = stage["branches"]
        info = {"type": "parallel", "h": h, "branches": []}
        for bi, branch in enumerate(branches):
            n = len(branch)
            positions = layout_horizontal(x, w, n)
            by = body_y_top if bi == 0 else body_y_bot
            for nx, node in zip(positions, branch):
                draw_node(draw, nx, by, NW, NH, **node)
            for i in range(n - 1):
                arrow_h(draw, positions[i] + NW, positions[i + 1], by + NH // 2)
            info["branches"].append({
                "first_left_x": positions[0],
                "first_left_cy": by + NH // 2,
                "first_top_x": positions[0] + NW // 2,
                "first_top_y": by,
                "last_right_x": positions[-1] + NW,
                "last_right_cy": by + NH // 2,
                "last_bottom_x": positions[-1] + NW // 2,
                "last_bottom_y": by + NH,
            })
        info["branch_targets"] = stage.get("branch_targets")
        return info
    else:  # fork_merge — 단계 5
        h = FORK_MERGE_H
        dashed_rect(draw, (x, box_y_start, x + w, y + h), color=DASH, width=2)
        body_y_top = y + 50 + 30
        body_y_mid = body_y_top + NH + ROW_GAP
        body_y_bot = body_y_mid + NH + ROW_GAP

        # 메인 chain 3 노드 — 노드 사이 큰 gap (평가 박스 + 양쪽 30px padding 들어가도록)
        main = stage["main"]
        n = len(main)
        MAIN_GAP = NW + 60  # = 340
        total_w_main = n * NW + (n - 1) * MAIN_GAP
        x_start_main = x + (w - total_w_main) // 2
        main_positions = [x_start_main + i * (NW + MAIN_GAP) for i in range(n)]
        for nx, node in zip(main_positions, main):
            draw_node(draw, nx, body_y_mid, NW, NH, **node)
        # Fun-CosyVoice3 → dub_wav (가로)
        arrow_h(draw, main_positions[0] + NW, main_positions[1], body_y_mid + NH // 2)

        # 평가 박스 위치 — dub_wav 와 Reference Bank 사이 gap (340px) 가운데
        dub_right = main_positions[1] + NW
        ref_left = main_positions[2]
        eval_cx = (dub_right + ref_left) // 2
        eval_x = eval_cx - NW // 2

        evaluators = stage["evaluators"]
        for ev in evaluators:
            ey = body_y_top if ev["position"] == "top" else body_y_bot
            ev_node = {k: v for k, v in ev.items() if k != "position"}
            draw_node(draw, eval_x, ey, NW, NH, **ev_node)

            ev_left = eval_x
            ev_right = eval_x + NW
            ev_cy = ey + NH // 2
            dub_cy = body_y_mid + NH // 2
            ref_cy = body_y_mid + NH // 2

            # dub_wav → eval — gap 가운데 elbow (박스 외부 영역)
            elbow_in = (dub_right + ev_left) // 2  # = 박스 사이 30px gap 가운데
            draw_path(draw, [
                (dub_right, dub_cy),
                (elbow_in, dub_cy),
                (elbow_in, ev_cy),
                (ev_left, ev_cy)
            ])
            # eval → Reference Bank — gap 가운데 elbow (박스 외부)
            elbow_out = (ev_right + ref_left) // 2
            draw_path(draw, [
                (ev_right, ev_cy),
                (elbow_out, ev_cy),
                (elbow_out, ref_cy),
                (ref_left, ref_cy)
            ])

        dub_cx = main_positions[1] + NW // 2
        return {
            "type": "fork_merge",
            "h": h,
            "body_y": body_y_mid,
            "positions": main_positions,
            "first_top": (main_positions[0] + NW // 2, body_y_mid),
            "first_left_x": main_positions[0],
            "first_left_cy": body_y_mid + NH // 2,
            "last_bottom": (dub_cx, body_y_mid + NH),
            "last_right_x": main_positions[1] + NW,
            "last_right_cy": body_y_mid + NH // 2,
            "dub_bottom": (dub_cx, body_y_mid + NH),
        }


def connect_linear_to_linear(draw, prev, nxt, mid_y):
    prev_cx, prev_y = prev["last_bottom"]
    next_cx, next_y = nxt["first_top"]
    draw_path(draw, [
        (prev_cx, prev_y),
        (prev_cx, mid_y),
        (next_cx, mid_y),
        (next_cx, next_y)
    ])


def connect_linear_to_parallel(draw, prev, nxt, mid_y):
    prev_cx, prev_y = prev["last_bottom"]
    first_left_x = nxt["branches"][0]["first_left_x"]
    split_x = first_left_x - 30
    cys = [b["first_left_cy"] for b in nxt["branches"]]
    line(draw, (prev_cx, prev_y), (prev_cx, mid_y))
    line(draw, (prev_cx, mid_y), (split_x, mid_y))
    line(draw, (split_x, mid_y), (split_x, max(cys)))
    for cy in cys:
        arrow_h(draw, split_x, first_left_x, cy)


def connect_parallel_to_linear_split(draw, prev, nxt, mid_y_base):
    """단계 3 → 단계 4: 두 갈래가 단계 4 의 다른 노드로 들어감."""
    targets = prev.get("branch_targets")
    next_positions = nxt["positions"]
    next_body_y = nxt["body_y"]
    branches = prev["branches"]
    gap_mid_y = (prev["end_y"] + nxt["y"]) // 2
    offsets = [-15, 15]
    for bi, (branch, target_idx) in enumerate(zip(branches, targets)):
        src_x = branch["last_bottom_x"]
        src_y = branch["last_bottom_y"]
        target_x = next_positions[target_idx]
        target_cx = target_x + NW // 2
        target_top_y = next_body_y
        my = gap_mid_y + offsets[bi]
        if bi == 0:
            # 위 갈래 (emotion): 그대로 수직 내려가면 아래 갈래의 asr.json 박스 한가운데를 관통
            # → 박스 좌측 외부로 우회 (박스 left - 30 으로 빠진 뒤 아래로)
            elbow_x = src_x - NW // 2 - 30
            draw_path(draw, [
                (src_x, src_y),
                (elbow_x, src_y),
                (elbow_x, my),
                (target_cx, my),
                (target_cx, target_top_y)
            ])
        else:
            draw_path(draw, [
                (src_x, src_y),
                (src_x, my),
                (target_cx, my),
                (target_cx, target_top_y)
            ])


# ─── build ─────────────────────────────────────────────────────────────────────
def build(out_dir: Path) -> None:
    img = Image.new("RGB", (A4_W, A4_H), BG)
    draw = ImageDraw.Draw(img)

    cx = A4_W // 2

    # ─── 헤더 ─────────────────────────────────────────
    text(draw, (M, 50), "영상 더빙 자동화 시스템 — Pipeline",
         font_key="ko_bold", size=42, color=INK)
    text(draw, (A4_W - M, 64),
         "6 단계 · 6 모델 + 외부 LLM",
         font_key="ko", size=16, color=META, anchor="ra")
    line(draw, (M, 110), (A4_W - M, 110), color=DIV, w=2)

    # ─── 입력 영상 박스 (가운데) ──────────────────────
    in_w, in_h = 460, 110
    in_x = cx - in_w // 2
    in_y = 140
    draw_node(draw, in_x, in_y, in_w, in_h, kind="io",
              title="입력 영상  input/{stem}.mp4",
              subtitle="원본 비디오",
              meta="44.1kHz / 2ch · stereo audio",
              title_size=22, subtitle_size=15, meta_size=12)

    # ─── 단계들 그리기 ──────────────────────────────
    y = in_y + in_h + 50
    stage_infos = []
    for stage in STAGES:
        info = draw_stage(draw, M, y, INNER_W, stage)
        info["y"] = y
        info["end_y"] = y + info["h"]
        stage_infos.append(info)
        y = info["end_y"] + STAGE_GAP

    # ─── 입력 → 단계 1 ────────────────────────────
    s1 = stage_infos[0]
    in_bot = (cx, in_y + in_h)
    s1_first_top = s1["first_top"]
    mid_y_in_s1 = (in_y + in_h + s1["y"] + 50) // 2
    draw_path(draw, [
        in_bot,
        (in_bot[0], mid_y_in_s1),
        (s1_first_top[0], mid_y_in_s1),
        s1_first_top
    ])

    # ─── 단계 사이 연결 ────────────────────────────
    for i in range(len(stage_infos) - 1):
        prev = stage_infos[i]
        nxt = stage_infos[i + 1]
        mid_y = (prev["end_y"] + nxt["y"] + 50) // 2

        if prev["type"] == "linear" and nxt["type"] == "linear":
            connect_linear_to_linear(draw, prev, nxt, mid_y)
        elif prev["type"] == "linear" and nxt["type"] == "parallel":
            connect_linear_to_parallel(draw, prev, nxt, mid_y)
        elif prev["type"] == "parallel" and nxt["type"] == "linear":
            connect_parallel_to_linear_split(draw, prev, nxt, mid_y)
        elif prev["type"] == "fork_merge" and nxt["type"] == "linear":
            # 단계 5 → 단계 6: dub_wav 에서 출발
            connect_linear_to_linear(draw, prev, nxt, mid_y)
        elif prev["type"] == "linear" and nxt["type"] == "fork_merge":
            # 단계 4 → 단계 5: 단계 5 의 first_top 으로
            connect_linear_to_linear(draw, prev, nxt, mid_y)

    # ─── 마지막 단계 → 출력 박스 ───────────────────
    s6 = stage_infos[-1]
    s6_bot = s6["last_bottom"]
    out_w, out_h = 600, 110
    out_x = cx - out_w // 2
    out_y = s6["end_y"] + 50
    draw_node(draw, out_x, out_y, out_w, out_h, kind="io",
              title="더빙 영상  output/{stem}/output_{engine}.mp4",
              subtitle="다국어 더빙 영상",
              meta="AAC 192k · 44.1kHz / 2ch",
              title_size=22, subtitle_size=15, meta_size=12)
    out_top = (cx, out_y)
    mid_y_s6_out = (s6["end_y"] + out_y) // 2
    draw_path(draw, [
        s6_bot,
        (s6_bot[0], mid_y_s6_out),
        (out_top[0], mid_y_s6_out),
        out_top
    ])

    # ─── bgm.wav → compose_audio 점선 path (우측 외곽) ──
    s1_info = stage_infos[0]
    s6_info = stage_infos[-1]
    # 단계 1 의 dialogue.wav · bgm.wav 박스 = positions[2]
    bgm_node_x = s1_info["positions"][2]
    bgm_cx = bgm_node_x + NW // 2
    bgm_bottom_y = s1_info["body_y"] + NH  # 박스 아래 (cy 가 아닌 bottom 으로 → 단계 1 의 다른 노드와 같은 cy 안 침범)
    compose_x = s6_info["positions"][0]
    compose_top_y = s6_info["body_y"]
    compose_cx = compose_x + NW // 2
    right_external = A4_W - 30
    # 가로 segment y: 단계 1 점선 박스 끝 직후 (단계 사이 영역) — 박스 내부 통과 안 함
    bgm_horizontal_y = s1_info["end_y"] + 20
    # 단계 6 진입 가로선 y: 단계 6 박스 점선 시작보다 위 (단계 5–6 사이 영역) — 점선 박스와 겹쳐 안 보이는 문제 회피
    bgm_approach_y = s6_info["y"] - 50
    draw_path(draw, [
        (bgm_cx, bgm_bottom_y),
        (bgm_cx, bgm_horizontal_y),
        (right_external, bgm_horizontal_y),
        (right_external, bgm_approach_y),
        (compose_cx, bgm_approach_y),
        (compose_cx, compose_top_y)
    ], color=DASHED_ARROW, w=2, dashed=True)
    text(draw, (right_external - 12, bgm_horizontal_y - 22), "bgm.wav",
         font_key="mono", size=12, color=META, anchor="ra")

    # ─── 입력 비디오 → ffmpeg mux 점선 path (좌측 외곽) ──
    mux_x = s6_info["positions"][2]
    mux_top_y = s6_info["body_y"]
    mux_cx = mux_x + NW // 2
    left_external = 30
    in_left = (in_x, in_y + in_h // 2)
    # 가로 segment y: 단계 6 박스 시작 직전 (단계 ⑤–⑥ 사이 영역) — 라벨/박스 침범 회피
    video_horizontal_y = s6_info["y"] - 30
    draw_path(draw, [
        in_left,
        (left_external, in_left[1]),
        (left_external, video_horizontal_y),
        (mux_cx, video_horizontal_y),
        (mux_cx, mux_top_y)
    ], color=DASHED_ARROW, w=2, dashed=True)
    text(draw, (left_external + 12, in_left[1] - 22), "video stream",
         font_key="mono", size=12, color=META)

    # ─── legend ─────────────────────────────────────
    legend_y = out_y + out_h + 40
    legend_items = [
        ("io",    "입력 / 출력"),
        ("model", "AI 모델"),
        ("tool",  "도구"),
        ("cloud", "Cloud API"),
        ("tts",   "TTS (CosyVoice3)"),
        ("data",  "중간 산출물"),
    ]
    bw, bh = 28, 18
    label_widths = []
    for _, label in legend_items:
        tw = load("ko", 16).getbbox(label)[2]
        label_widths.append(tw + bw + 16 + 24)
    total = sum(label_widths) - 24
    cur_x = M + (INNER_W - total) // 2
    for (kind, label), wlabel in zip(legend_items, label_widths):
        rrect(draw, (cur_x, legend_y, cur_x + bw, legend_y + bh), radius=5,
              fill=PAL[kind]["fill"], outline=PAL[kind]["stroke"], width=2)
        text(draw, (cur_x + bw + 10, legend_y + 1), label,
             font_key="ko", size=16, color=INK)
        cur_x += wlabel

    # 단계 그룹 + 점선 path legend
    note_y = A4_H - 130
    note_x = M
    dashed_rect(draw, (note_x, note_y, note_x + 56, note_y + 22),
                color=DASH, width=2, dash=8, gap=6)
    text(draw, (note_x + 70, note_y + 1), "단계 그룹 (점선 박스)",
         font_key="ko", size=14, color=META)
    text(draw, (note_x + 320, note_y + 1),
         "점선 화살표 — 단계 건너 데이터 직행 (bgm · video)",
         font_key="ko", size=14, color=META)

    # 푸터
    text(draw, (M, A4_H - 80), "한성대학교 캡스톤디자인 · 2026-1학기",
         font_key="ko", size=14, color=META)
    text(draw, (A4_W - M, A4_H - 80), "2026.05.10",
         font_key="mono", size=14, color=META, anchor="ra")

    # ─── 저장 ───────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "diagram-architecture.png"
    jpg_path = out_dir / "diagram-architecture.jpg"
    img.save(png_path, dpi=(DPI, DPI), optimize=True)
    img.save(jpg_path, dpi=(DPI, DPI), quality=95, subsampling=0)
    print(f"Wrote {png_path} ({A4_W}x{A4_H} @ {DPI}dpi)")
    print(f"Wrote {jpg_path}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    build(project_root / "docs" / "booklet-screenshots")
