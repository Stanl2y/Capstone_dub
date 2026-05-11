# 영상 더빙 자동화 시스템의 프로젝트 구조 (Browser → Host[webapp + 파이프라인 컨테이너 + 호스트 디렉토리] + External LLM) 를 A4 세로 300dpi 로 렌더 — Pillow 만 사용
"""scripts/build_project_structure_diagram.py — docs/booklet-screenshots/diagram-project-structure.{png,jpg} 생성."""
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
LAYER_OUTLINE = (180, 190, 210)
HOST_OUTLINE = (100, 116, 139)
LAYER_BG = (248, 250, 252)

CONTAINER_COLORS = {
    "controller":      (29, 78, 216),
    "separator":       (245, 158, 11),
    "diarizer":        (13, 148, 136),
    "speaker":         (16, 185, 129),
    "tts-cosyvoice":   (139, 92, 246),
    "webapp-backend":  (236, 72, 153),
    "webapp-frontend": (236, 72, 153),
}

DIR_COLORS = {
    "code":  {"fill": (254, 243, 199), "stroke": (217, 119, 6)},
    "model": {"fill": (243, 232, 255), "stroke": (139, 92, 246)},
    "data":  {"fill": (255, 251, 235), "stroke": (156, 163, 175)},
}

PILL_COLORS = {
    "user":     {"fill": (251, 207, 232), "stroke": (190, 24, 93)},
    "external": {"fill": (219, 234, 254), "stroke": (37, 99, 235)},
}

FONTS = {
    "ko": "C:/Windows/Fonts/malgun.ttf",
    "ko_bold": "C:/Windows/Fonts/malgunbd.ttf",
    "mono": "C:/Windows/Fonts/consola.ttf",
    "mono_bold": "C:/Windows/Fonts/consolab.ttf",
}


def load(font_key: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONTS[font_key], size)
    except OSError:
        return ImageFont.load_default()


def _has_korean(s: str) -> bool:
    return any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ" for ch in s)


def _font_for(s: str, *, mono: str = "mono", ko: str = "ko") -> str:
    return ko if _has_korean(s) else mono


def _lighten(color: tuple[int, int, int], factor: float = 0.92) -> tuple[int, int, int]:
    return tuple(int(c + (255 - c) * factor) for c in color)


# ─── primitives ────────────────────────────────────────────────────────────────
def text(draw, xy, s, *, font_key, size, color=INK, anchor="la"):
    draw.text(xy, s, font=load(font_key, size), fill=color, anchor=anchor)


def text_center(draw, x, y, w, s, *, font_key, size, color=INK):
    draw.text((x + w // 2, y), s, font=load(font_key, size), fill=color, anchor="ma")


def rrect(draw, xy, radius, *, fill=None, outline=None, width=0):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def dashed_rect(draw, xy, *, color, width=2, dash=14, gap=10) -> None:
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


def line(draw, p1, p2, *, color=INK, w=3, dashed=False):
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


def arrow_h(draw, x_start, x_end, y, *, color=INK, w=2, head=14):
    if x_end > x_start:
        draw.line([(x_start, y), (x_end - head, y)], fill=color, width=w)
        draw.polygon(
            [(x_end, y), (x_end - head, y - head // 2), (x_end - head, y + head // 2)],
            fill=color,
        )
    else:
        draw.line([(x_start, y), (x_end + head, y)], fill=color, width=w)
        draw.polygon(
            [(x_end, y), (x_end + head, y - head // 2), (x_end + head, y + head // 2)],
            fill=color,
        )


def arrow_v(draw, x, y_start, y_end, *, color=INK, w=3, head=16):
    if y_end > y_start:
        draw.line([(x, y_start), (x, y_end - head)], fill=color, width=w)
        draw.polygon(
            [(x, y_end), (x - head // 2, y_end - head), (x + head // 2, y_end - head)],
            fill=color,
        )
    else:
        draw.line([(x, y_start), (x, y_end + head)], fill=color, width=w)
        draw.polygon(
            [(x, y_end), (x - head // 2, y_end + head), (x + head // 2, y_end + head)],
            fill=color,
        )


def draw_pill(draw, x, y, w, h, *, kind, title, subtitle=""):
    color = PILL_COLORS[kind]
    rrect(draw, (x, y, x + w, y + h), radius=h // 2,
          fill=color["fill"], outline=color["stroke"], width=2)
    text_center(draw, x, y + 14, w, title,
                font_key=_font_for(title, mono="mono_bold", ko="ko_bold"),
                size=22, color=INK)
    if subtitle:
        text_center(draw, x, y + 50, w, subtitle,
                    font_key=_font_for(subtitle), size=15, color=BODY)


def draw_container_box(draw, x, y, w, h, *, container, role, deps=None):
    color = CONTAINER_COLORS[container]
    rrect(draw, (x, y, x + w, y + h), radius=12,
          fill=_lighten(color, 0.93), outline=color, width=2)
    text(draw, (x + 14, y + 12), container,
         font_key="mono_bold", size=18, color=color)
    text(draw, (x + 14, y + 44), role,
         font_key=_font_for(role), size=14, color=INK)
    cy = y + 76
    if deps:
        for dep in deps:
            text(draw, (x + 14, cy), dep,
                 font_key=_font_for(dep), size=13, color=BODY)
            cy += 22


def draw_dir_box(draw, x, y, w, h, *, kind, title, items=None):
    color = DIR_COLORS[kind]
    rrect(draw, (x, y, x + w, y + h), radius=12,
          fill=color["fill"], outline=color["stroke"], width=2)
    # title 띠
    text(draw, (x + 14, y + 12), title,
         font_key="ko_bold" if _has_korean(title) else "mono_bold",
         size=17, color=INK)
    line(draw, (x + 14, y + 42), (x + w - 14, y + 42), color=color["stroke"], w=1)
    cy = y + 54
    if items:
        for item in items:
            text(draw, (x + 14, cy), item,
                 font_key=_font_for(item), size=13, color=BODY)
            cy += 22


# ─── build ─────────────────────────────────────────────────────────────────────
def build(out_dir: Path) -> None:
    img = Image.new("RGB", (A4_W, A4_H), BG)
    draw = ImageDraw.Draw(img)

    M = 80
    INNER_W = A4_W - 2 * M  # 2321
    cx = A4_W // 2

    # ─── 헤더 ─────────────────────────────────────────
    text(draw, (M, 70), "영상 더빙 자동화 시스템 — 프로젝트 구조",
         font_key="ko_bold", size=42, color=INK)
    text(draw, (A4_W - M, 86),
         "Host (Docker Compose · 7 services)  +  External LLM",
         font_key="mono", size=18, color=META, anchor="ra")
    line(draw, (M, 140), (A4_W - M, 140), color=DIV, w=2)

    # ─── 외부 (Browser + External LLM pill 가로 두 개) ────
    pill_w, pill_h = 700, 110
    browser_x = M + 60
    external_x = A4_W - M - 60 - pill_w
    pill_y = 170

    draw_pill(draw, browser_x, pill_y, pill_w, pill_h,
              kind="user", title="USER BROWSER",
              subtitle="React UI · WaveSurfer · /api · /ws · /static")
    draw_pill(draw, external_x, pill_y, pill_w, pill_h,
              kind="external", title="VECTORENGINE GPT (Cloud)",
              subtitle="외부 LLM API · 번역 + TTS instruct")

    # ─── Host 박스 ───────────────────────────────────
    host_x = M
    host_y = pill_y + pill_h + 80
    host_w = INNER_W
    host_h = 2200

    dashed_rect(draw, (host_x, host_y, host_x + host_w, host_y + host_h),
                color=HOST_OUTLINE, width=3, dash=18, gap=12)
    text(draw, (host_x + 16, host_y + 14),
         "HOST  (Windows + Docker Desktop)",
         font_key="mono_bold", size=20, color=HOST_OUTLINE)
    text(draw, (host_x + host_w - 16, host_y + 14),
         "bind mount  ./  ⇆  /workspace/project",
         font_key="mono", size=14, color=META, anchor="ra")

    # ─── Webapp Layer ──────────────────────────────
    layer_pad = 30
    layer_x = host_x + layer_pad
    layer_w = host_w - 2 * layer_pad

    webapp_y = host_y + 60
    webapp_h = 320
    rrect(draw, (layer_x, webapp_y, layer_x + layer_w, webapp_y + webapp_h),
          radius=14, fill=LAYER_BG, outline=LAYER_OUTLINE, width=2)
    text(draw, (layer_x + 14, webapp_y + 12), "WEBAPP LAYER",
         font_key="mono_bold", size=14, color=META)

    box_w = (layer_w - 100 - 60) // 2  # 두 박스, 가운데 spacing 100, 양쪽 padding 30
    box_h = 230
    fe_x = layer_x + 30
    be_x = fe_x + box_w + 100
    box_y = webapp_y + 50

    draw_container_box(draw, fe_x, box_y, box_w, box_h,
                       container="webapp-frontend",
                       role="React 18 · Vite 5173 · TypeScript 5",
                       deps=[
                           "node:20-alpine",
                           "Tailwind · WaveSurfer",
                           "pages: Dashboard · Upload · Progress",
                           "       Chunks · Compare · Activity",
                           "proxy → backend (/api · /ws · /static)",
                       ])
    draw_container_box(draw, be_x, box_y, box_w, box_h,
                       container="webapp-backend",
                       role="FastAPI · uvicorn 8000",
                       deps=[
                           "python:3.12-slim",
                           "docker-ce-cli + compose plugin",
                           "/var/run/docker.sock 마운트",
                           "api: runs · projects · uploads · ws",
                           "services: pipeline_runner · step_router",
                       ])

    # frontend ↔ backend 양방향 화살표
    fb_cy = box_y + box_h // 2
    fe_right = fe_x + box_w
    be_left = be_x
    line(draw, (fe_right, fb_cy), (be_left, fb_cy), color=INK, w=2)
    head = 14
    draw.polygon([(be_left, fb_cy), (be_left - head, fb_cy - head // 2),
                  (be_left - head, fb_cy + head // 2)], fill=INK)
    draw.polygon([(fe_right, fb_cy), (fe_right + head, fb_cy - head // 2),
                  (fe_right + head, fb_cy + head // 2)], fill=INK)
    text_center(draw, (fe_right + be_left) // 2 - 110, fb_cy - 28, 220,
                "HTTP  /api · /ws · /static",
                font_key="mono", size=14, color=META)

    # ─── Pipeline Containers Layer ─────────────────
    pipeline_y = webapp_y + webapp_h + 80
    pipeline_h = 380
    rrect(draw, (layer_x, pipeline_y, layer_x + layer_w, pipeline_y + pipeline_h),
          radius=14, fill=LAYER_BG, outline=LAYER_OUTLINE, width=2)
    text(draw, (layer_x + 14, pipeline_y + 12), "PIPELINE CONTAINERS",
         font_key="mono_bold", size=14, color=META)

    containers = [
        ("controller", "py3.10-slim · CPU torch",
         ["ffmpeg · numpy · soundfile",
          "extract · merge · cut",
          "translate · build_timeline",
          "compose · mux"]),
        ("separator", "cu124 · torch 2.5.1",
         ["audio-separator[gpu] 0.28+",
          "silero-vad 6.2+",
          "BS-RoFormer ep317",
          "MDX23C-8KFFT-InstVoc_HQ"]),
        ("diarizer", "cu121 · torch 2.1.1",
         ["DiariZen (cloned)",
          "pyannote-audio",
          "WeSpeaker embedding",
          "WavLM-Large s80-md-v2"]),
        ("speaker", "cu124 · torch 2.5.1",
         ["qwen-asr 0.0.6+",
          "modelscope 1.20",
          "funasr 1.1.16+",
          "Qwen3-ASR + emotion2vec"]),
        ("tts-cosyvoice", "cu124 + miniforge py3.10",
         ["Fun-CosyVoice3-0.5B",
          "torch 2.3.1+cu121",
          "diffusers · onnxruntime-gpu",
          "conformer · HyperPyYAML"]),
    ]
    pc_box_w = (layer_w - 60 - 4 * 20) // 5
    pc_box_h = 290
    pc_y = pipeline_y + 50
    pc_x = layer_x + 30
    container_centers: list[tuple[int, int, int]] = []
    for name, role, deps in containers:
        draw_container_box(draw, pc_x, pc_y, pc_box_w, pc_box_h,
                           container=name, role=role, deps=deps)
        container_centers.append((pc_x + pc_box_w // 2, pc_y, pc_y + pc_box_h))
        pc_x += pc_box_w + 20

    # webapp-backend → 5 컨테이너 화살표 (T 자형 bus)
    backend_bottom_x = be_x + box_w // 2
    backend_bottom_y = box_y + box_h
    bus_y = pipeline_y - 36
    line(draw, (backend_bottom_x, backend_bottom_y), (backend_bottom_x, bus_y), color=INK, w=2)
    bus_x_start = container_centers[0][0]
    bus_x_end = container_centers[-1][0]
    if backend_bottom_x > bus_x_end:
        line(draw, (bus_x_end, bus_y), (backend_bottom_x, bus_y), color=INK, w=2)
    elif backend_bottom_x < bus_x_start:
        line(draw, (backend_bottom_x, bus_y), (bus_x_start, bus_y), color=INK, w=2)
    line(draw, (bus_x_start, bus_y), (bus_x_end, bus_y), color=INK, w=2)
    for cxc, c_y_top, _ in container_centers:
        arrow_v(draw, cxc, bus_y, c_y_top, color=INK, w=2, head=14)
    text(draw, (backend_bottom_x + 10, bus_y - 22),
         "docker compose exec  (호스트 docker.sock 경유)",
         font_key="mono", size=14, color=META)

    # ─── Host Filesystem Layer ───────────────────
    fs_y = pipeline_y + pipeline_h + 80
    fs_h = 700
    rrect(draw, (layer_x, fs_y, layer_x + layer_w, fs_y + fs_h),
          radius=14, fill=LAYER_BG, outline=LAYER_OUTLINE, width=2)
    text(draw, (layer_x + 14, fs_y + 12),
         "HOST FILESYSTEM  (./  bind mount → /workspace/project)",
         font_key="mono_bold", size=14, color=META)

    sub_w = (layer_w - 60 - 2 * 30) // 3
    sub_h = 600
    sub_y = fs_y + 50
    sub_x = layer_x + 30

    draw_dir_box(draw, sub_x, sub_y, sub_w, sub_h, kind="code",
                 title="코드  (Code)",
                 items=[
                     "src/  파이프라인 모듈 (16 단계)",
                     "  pipeline.py  (단계 dispatch)",
                     "  extract_audio · separate_audio",
                     "  redirect_nonspeech · diarize",
                     "  rttm_to_json · stabilize_diarization",
                     "  merge_speaker_chunks · cut_chunks",
                     "  extract_emotion · run_asr",
                     "  translate_chunks · build_master_timeline",
                     "  generate_tts_instructions",
                     "  run_tts · tts_runtime · reference_policy",
                     "  validate_tts_output · compose_audio",
                     "  audio_features · quality_gate · common",
                     "",
                     "configs/cosyvoice3-docker-draft.json",
                     "",
                     "webapp/backend/app/{api,services,models}",
                     "webapp/frontend/src/{pages,components,api}",
                     "",
                     "scripts/docker/run_pipeline.{ps1,cmd,sh}",
                     "scripts/setup_models.{ps1,sh}",
                     "",
                     "docker/Dockerfile.{cpu,gpu,diarizer,",
                     "                   tts-cosyvoice,webapp-*}",
                     "third_party/CosyVoice  (서브모듈)",
                 ])
    sub_x += sub_w + 30

    draw_dir_box(draw, sub_x, sub_y, sub_w, sub_h, kind="model",
                 title="모델 자산  (Models · .gitignore)",
                 items=[
                     "models/asr/Qwen3-ASR-1.7B",
                     "models/aligner/Qwen3-ForcedAligner-0.6B",
                     "models/emotion/emotion2vec-large",
                     "models/tts/Fun-CosyVoice3-0.5B",
                     "models/diarization/diarizen-wavlm-",
                     "                   large-s80-md-v2",
                     "models/embedding/wespeaker-",
                     "                  voxblink2-samresnet100",
                     "models/separation/",
                     "  BS-RoFormer ep317",
                     "  MDX23C-8KFFT-InstVoc_HQ",
                     "models/vad/silero_vad.jit",
                     "",
                     "── 다운로드 ─────────────────",
                     "scripts/setup_models.ps1",
                     "scripts/setup_models.sh",
                     "download_models.sh",
                     "huggingface_hub[cli]  (gated → hf auth)",
                 ])
    sub_x += sub_w + 30

    draw_dir_box(draw, sub_x, sub_y, sub_w, sub_h, kind="data",
                 title="런타임 산출물  (Runtime)",
                 items=[
                     "── 입력 ────────────────────",
                     "input/{stem}.mp4",
                     "",
                     "── 단계 산출물 ─────────────",
                     "audio/{stem}/",
                     "  raw.wav · dialogue.wav · bgm.wav",
                     "",
                     "meta/{stem}/",
                     "  diarization{,_stabilized}.json",
                     "  speaker_chunks.json",
                     "  asr.json · emotion.json",
                     "  translated.json",
                     "  master_timeline_{engine}.json",
                     "  tts_validation_{engine}.json",
                     "",
                     "chunks/{stem}/<id>.wav",
                     "dub/{stem}_{engine}/<id>_dub.wav",
                     "",
                     "── 최종 출력 ─────────────",
                     "output/{stem}/final_dub_{engine}.wav",
                     "output/{stem}/output_{engine}.mp4",
                     "",
                     "logs/docker-pipeline/<timestamp>/",
                 ])

    # bind mount 점선: 컨테이너 → host fs (5 갈래)
    for cxc, _, c_y_bottom in container_centers:
        line(draw, (cxc, c_y_bottom + 4), (cxc, fs_y - 4),
             color=HOST_OUTLINE, w=2, dashed=True)
    # 양쪽 끝에 작은 화살표 (양방향 의미)
    text(draw, (layer_x + 14, fs_y - 28),
         "bind mount  (read · write)",
         font_key="mono", size=14, color=META)

    # ─── Browser → frontend 화살표 ────────────────
    browser_bottom_cx = browser_x + pill_w // 2
    browser_bottom_y = pill_y + pill_h
    fe_top_cx = fe_x + box_w // 2
    fe_top_y = box_y
    mid_y = browser_bottom_y + 30
    line(draw, (browser_bottom_cx, browser_bottom_y), (browser_bottom_cx, mid_y), w=2)
    if abs(browser_bottom_cx - fe_top_cx) > 5:
        x_min = min(browser_bottom_cx, fe_top_cx)
        x_max = max(browser_bottom_cx, fe_top_cx)
        line(draw, (x_min, mid_y), (x_max, mid_y), w=2)
    line(draw, (fe_top_cx, mid_y), (fe_top_cx, fe_top_y - 14), w=2)
    arrow_v(draw, fe_top_cx, fe_top_y - 14, fe_top_y, color=INK, w=2, head=14)
    text(draw, (browser_bottom_cx + 10, browser_bottom_y + 4), "HTTP 5173",
         font_key="mono", size=14, color=META)

    # ─── External LLM → controller 점선 화살표 ────
    ext_color = PILL_COLORS["external"]["stroke"]
    ext_bottom_cx = external_x + pill_w // 2
    ext_bottom_y = pill_y + pill_h
    controller_cx = container_centers[0][0]
    controller_top_y = container_centers[0][1]
    # path: ext bottom → 수직 mid_y → 가로 controller_cx → 수직 controller_top
    line(draw, (ext_bottom_cx, ext_bottom_y), (ext_bottom_cx, mid_y),
         color=ext_color, w=2, dashed=True)
    x_min = min(ext_bottom_cx, controller_cx)
    x_max = max(ext_bottom_cx, controller_cx)
    line(draw, (x_min, mid_y), (x_max, mid_y),
         color=ext_color, w=2, dashed=True)
    line(draw, (controller_cx, mid_y), (controller_cx, controller_top_y - 14),
         color=ext_color, w=2, dashed=True)
    arrow_v(draw, controller_cx, controller_top_y - 14, controller_top_y,
            color=ext_color, w=2, head=14)
    text(draw, (ext_bottom_cx - 10, ext_bottom_y + 4),
         "HTTPS  (translate · instruct)",
         font_key="mono", size=14, color=META, anchor="ra")

    # ─── Legend + Footer ─────────────────────────
    legend_y = host_y + host_h + 30

    legend_items = [
        ("controller", "controller (CPU)"),
        ("separator", "separator (GPU)"),
        ("diarizer", "diarizer (GPU)"),
        ("speaker", "speaker (GPU)"),
        ("tts-cosyvoice", "tts-cosyvoice (GPU)"),
        ("webapp-backend", "webapp (frontend + backend)"),
    ]
    bw = 28
    bh = 18
    cur_x = M
    for kind, label in legend_items:
        color = CONTAINER_COLORS[kind]
        rrect(draw, (cur_x, legend_y, cur_x + bw, legend_y + bh),
              radius=4, fill=color)
        text(draw, (cur_x + bw + 10, legend_y + 1), label,
             font_key="mono", size=14, color=INK)
        # advance: 박스 폭 + spacing + 라벨 폭 추정 + spacing
        label_w = load("mono", 14).getbbox(label)[2]
        cur_x += bw + 10 + label_w + 26

    # footer
    text(draw, (M, A4_H - 100), "한성대학교 캡스톤디자인 · 2026-1학기",
         font_key="ko", size=14, color=META)
    text(draw, (A4_W - M, A4_H - 100), "2026.05.10",
         font_key="mono", size=14, color=META, anchor="ra")

    # ─── 저장 ─────────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / "diagram-project-structure.png"
    jpg_path = out_dir / "diagram-project-structure.jpg"
    img.save(png_path, dpi=(DPI, DPI), optimize=True)
    img.save(jpg_path, dpi=(DPI, DPI), quality=95, subsampling=0)
    print(f"Wrote {png_path} ({A4_W}x{A4_H} @ {DPI}dpi)")
    print(f"Wrote {jpg_path}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    build(project_root / "docs" / "booklet-screenshots")
