from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DPI = 300
W, H = 2480, 3508  # A4 portrait at 300 dpi

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "submission"
JPG_NAME = "2. 02조_이미지_주요 적용 기술 및 구조.jpg"
PNG_NAME = "2. 02조_이미지_주요 적용 기술 및 구조.png"

FONT_REG = "C:/Windows/Fonts/malgun.ttf"
FONT_BOLD = "C:/Windows/Fonts/malgunbd.ttf"
FONT_MONO = "C:/Windows/Fonts/consola.ttf"
FONT_MONO_BOLD = "C:/Windows/Fonts/consolab.ttf"

BG = (250, 251, 253)
PAPER = (255, 255, 255)
INK = (22, 34, 60)
BODY = (58, 72, 96)
MUTE = (122, 137, 158)
GRID = (225, 231, 240)
LINE = (150, 163, 184)

RED = (239, 96, 110)
RED_T = (255, 226, 231)
ORANGE = (245, 158, 11)
ORANGE_T = (255, 244, 214)
GREEN = (69, 171, 93)
GREEN_T = (223, 246, 227)
BLUE = (38, 131, 255)
BLUE_T = (224, 239, 255)
CYAN = (29, 172, 198)
CYAN_T = (218, 248, 252)
PURPLE = (118, 88, 224)
PURPLE_T = (237, 233, 255)
DARK = (38, 50, 75)


def font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    if mono:
        return ImageFont.truetype(FONT_MONO_BOLD if bold else FONT_MONO, size)
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def text_size(draw: ImageDraw.ImageDraw, text: str, size: int, *, bold: bool = False, mono: bool = False) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font(size, bold=bold, mono=mono))
    return box[2] - box[0], box[3] - box[1]


def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    size: int,
    *,
    fill=INK,
    bold: bool = False,
    mono: bool = False,
    anchor: str | None = None,
) -> None:
    draw.text(xy, text, font=font(size, bold=bold, mono=mono), fill=fill, anchor=anchor)


def wrap(draw: ImageDraw.ImageDraw, text: str, max_width: int, size: int, *, bold: bool = False, mono: bool = False) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for token in paragraph.split(" "):
            candidate = token if not current else f"{current} {token}"
            if text_size(draw, candidate, size, bold=bold, mono=mono)[0] <= max_width:
                current = candidate
                continue
            if current:
                lines.append(current)
            if text_size(draw, token, size, bold=bold, mono=mono)[0] <= max_width:
                current = token
                continue
            chunk = ""
            for ch in token:
                candidate = chunk + ch
                if text_size(draw, candidate, size, bold=bold, mono=mono)[0] <= max_width:
                    chunk = candidate
                else:
                    if chunk:
                        lines.append(chunk)
                    chunk = ch
            current = chunk
        if current:
            lines.append(current)
    return lines


def dashed_line(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], *, fill=GRID, width: int = 3, dash: int = 18, gap: int = 14) -> None:
    x1, y1 = start
    x2, y2 = end
    length = math.hypot(x2 - x1, y2 - y1)
    if length == 0:
        return
    dx = (x2 - x1) / length
    dy = (y2 - y1) / length
    pos = 0.0
    while pos < length:
        end_pos = min(pos + dash, length)
        draw.line(
            (
                x1 + dx * pos,
                y1 + dy * pos,
                x1 + dx * end_pos,
                y1 + dy * end_pos,
            ),
            fill=fill,
            width=width,
        )
        pos += dash + gap


def arrow_head(draw: ImageDraw.ImageDraw, a: tuple[int, int], b: tuple[int, int], *, fill=LINE, size: int = 20) -> None:
    ax, ay = a
    bx, by = b
    angle = math.atan2(by - ay, bx - ax)
    p1 = (bx, by)
    p2 = (bx - size * math.cos(angle - math.pi / 6), by - size * math.sin(angle - math.pi / 6))
    p3 = (bx - size * math.cos(angle + math.pi / 6), by - size * math.sin(angle + math.pi / 6))
    draw.polygon([p1, p2, p3], fill=fill)


def connector(draw: ImageDraw.ImageDraw, points: list[tuple[int, int]], *, fill=LINE, width: int = 4, dashed: bool = False) -> None:
    for a, b in zip(points, points[1:]):
        if dashed:
            dashed_line(draw, a, b, fill=fill, width=width, dash=14, gap=10)
        else:
            draw.line((a[0], a[1], b[0], b[1]), fill=fill, width=width)
    if len(points) >= 2:
        arrow_head(draw, points[-2], points[-1], fill=fill, size=18 + width)


def rounded(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, *, fill, outline=None, width: int = 2) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


@dataclass(frozen=True)
class Node:
    x: int
    y: int
    w: int
    h: int

    @property
    def left(self) -> int:
        return self.x - self.w // 2

    @property
    def right(self) -> int:
        return self.x + self.w // 2

    @property
    def top(self) -> int:
        return self.y - self.h // 2

    @property
    def bottom(self) -> int:
        return self.y + self.h // 2

    @property
    def center(self) -> tuple[int, int]:
        return self.x, self.y

    @property
    def mid_left(self) -> tuple[int, int]:
        return self.left, self.y

    @property
    def mid_right(self) -> tuple[int, int]:
        return self.right, self.y

    @property
    def top_mid(self) -> tuple[int, int]:
        return self.x, self.top

    @property
    def bottom_mid(self) -> tuple[int, int]:
        return self.x, self.bottom


def node(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    title: str,
    subtitle: str = "",
    fill,
    outline,
    title_size: int = 24,
    sub_size: int = 17,
    mono_sub: bool = False,
) -> Node:
    # Malgun Gothic is used for every subtitle so Korean never falls back to
    # unsupported monospace glyph boxes in print exports.
    mono_sub = False
    n = Node(x, y, w, h)
    shadow = (0, 0, 0, 18)
    # Tiny offset shadow by using translucent layer is overkill here; use soft gray outline instead.
    rounded(draw, (n.left + 4, n.top + 5, n.right + 4, n.bottom + 5), 18, fill=(235, 239, 246), outline=None, width=0)
    rounded(draw, (n.left, n.top, n.right, n.bottom), 18, fill=fill, outline=outline, width=3)
    title_lines = wrap(draw, title, w - 34, title_size, bold=True)
    title_y = y - (len(title_lines) * (title_size + 4) + (sub_size + 5 if subtitle else 0)) // 2 + 4
    for line in title_lines[:2]:
        draw_text(draw, (x, title_y), line, title_size, fill=INK, bold=True, anchor="ma")
        title_y += title_size + 8
    if subtitle:
        sub_lines = wrap(draw, subtitle, w - 36, sub_size, mono=mono_sub)
        for line in sub_lines[:2]:
            draw_text(draw, (x, title_y + 2), line, sub_size, fill=BODY, mono=mono_sub, anchor="ma")
            title_y += sub_size + 7
    return n


def stage_label(draw: ImageDraw.ImageDraw, number: str, title: str, y: int) -> None:
    draw.ellipse((90, y - 21, 132, y + 21), fill=RED_T, outline=RED, width=3)
    draw_text(draw, (111, y - 1), number, 21, fill=RED, bold=True, anchor="mm")
    draw_text(draw, (150, y - 1), title, 28, fill=DARK, bold=True, anchor="lm")


def legend_item(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, fill, outline) -> int:
    rounded(draw, (x, y - 16, x + 34, y + 16), 7, fill=fill, outline=outline, width=2)
    draw_text(draw, (x + 48, y + 1), label, 21, fill=BODY, anchor="lm")
    return x + 48 + text_size(draw, label, 21)[0] + 42


def build() -> None:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    margin_x = 72
    left = 90
    right = W - 90

    rounded(draw, (32, 32, W - 32, H - 32), 10, fill=PAPER, outline=(185, 197, 216), width=3)

    # Header
    draw_text(draw, (90, 104), "다국어 자동 더빙 시스템 — Pipeline", 40, fill=(26, 52, 109), bold=True)
    draw_text(draw, (W - 90, 106), "16 단계 · 6 서비스 · 청크 단위 재합성", 22, fill=MUTE, anchor="ra")
    draw.line((90, 155, W - 90, 155), fill=(204, 214, 230), width=3)

    input_video = node(
        draw,
        1240,
        285,
        430,
        142,
        title="입력 영상",
        subtitle="input/{stem}.mp4\nSource Movie",
        fill=RED_T,
        outline=RED,
        title_size=28,
        sub_size=18,
        mono_sub=True,
    )

    # Section separators.
    separators = [455, 880, 1305, 1740, 2185, 2645, 3260]
    for y in separators:
        dashed_line(draw, (90, y), (W - 90, y), fill=(211, 220, 234), width=3, dash=20, gap=16)

    # 1. Audio prep
    stage_label(draw, "1", "오디오 분리 및 정제", 505)
    ffmpeg = node(draw, 230, 650, 170, 86, title="ffmpeg", subtitle="audio extract", fill=ORANGE_T, outline=ORANGE, title_size=22, sub_size=16)
    raw = node(draw, 460, 650, 230, 86, title="Raw Audio", subtitle="raw.wav", fill=ORANGE_T, outline=ORANGE, title_size=22, sub_size=16, mono_sub=True)
    sep = node(draw, 790, 650, 310, 124, title="BS-RoFormer\n+ MDX23C", subtitle="vocal / BGM 분리", fill=GREEN_T, outline=GREEN, title_size=23, sub_size=16)
    bgm = node(draw, 1150, 575, 270, 86, title="Background Sound", subtitle="bgm.wav", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=16, mono_sub=True)
    voice = node(draw, 1150, 725, 270, 86, title="Character Voice", subtitle="dialogue.wav", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=16, mono_sub=True)
    vad = node(draw, 1460, 725, 230, 86, title="Silero VAD", subtitle="비발화 보정", fill=GREEN_T, outline=GREEN, title_size=22, sub_size=16)
    clean = node(draw, 1750, 725, 270, 86, title="Clean Dialogue", subtitle="정제된 발화 음성", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=16)
    video_stream = node(draw, 2100, 575, 300, 86, title="Video Stream", subtitle="video copy → mux", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=16, mono_sub=True)

    connector(draw, [input_video.bottom_mid, (1240, 420), (230, 420), ffmpeg.top_mid], fill=LINE, width=4)
    connector(draw, [input_video.mid_right, (2100, input_video.y), (2100, video_stream.top)], fill=LINE, width=4, dashed=True)
    connector(draw, [ffmpeg.mid_right, raw.mid_left], fill=LINE, width=5)
    connector(draw, [raw.mid_right, sep.mid_left], fill=LINE, width=5)
    connector(draw, [sep.mid_right, (980, 575), bgm.mid_left], fill=GREEN, width=5)
    connector(draw, [sep.mid_right, (980, 725), voice.mid_left], fill=GREEN, width=5)
    connector(draw, [voice.mid_right, vad.mid_left], fill=LINE, width=5)
    connector(draw, [vad.mid_right, clean.mid_left], fill=LINE, width=5)

    # 2. Speaker and chunk analysis
    stage_label(draw, "2", "화자·청크 분석 / 대사 추출", 930)
    diar = node(draw, 260, 1065, 310, 112, title="DiariZen + WavLM", subtitle="화자 분리\nspeaker diarization", fill=GREEN_T, outline=GREEN, title_size=21, sub_size=15)
    rttm = node(draw, 610, 1065, 235, 88, title="RTTM → JSON", subtitle="diarization.json", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    merge = node(draw, 900, 1065, 265, 88, title="Merge / Cut", subtitle="speaker chunks", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15)
    chunk = node(draw, 1200, 1065, 250, 88, title="Chunk WAV", subtitle="chunk_0001.wav …", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    qwen = node(draw, 1540, 995, 305, 106, title="Qwen3-ASR-1.7B", subtitle="원문 대사 인식\nasr.json", fill=GREEN_T, outline=GREEN, title_size=20, sub_size=15, mono_sub=True)
    emo = node(draw, 1540, 1135, 305, 106, title="emotion2vec-large", subtitle="9-class 감정 분포\nemotion.json", fill=GREEN_T, outline=GREEN, title_size=20, sub_size=15, mono_sub=True)
    chunks_json = node(draw, 1945, 1250, 290, 88, title="speaker_chunks.json", subtitle="speaker / start / end", fill=ORANGE_T, outline=ORANGE, title_size=18, sub_size=15, mono_sub=True)

    connector(draw, [clean.bottom_mid, (1750, 865), (260, 865), diar.top_mid], fill=LINE, width=4)
    connector(draw, [diar.mid_right, rttm.mid_left], fill=LINE, width=5)
    connector(draw, [rttm.mid_right, merge.mid_left], fill=LINE, width=5)
    connector(draw, [merge.mid_right, chunk.mid_left], fill=LINE, width=5)
    connector(draw, [chunk.mid_right, (1350, 995), qwen.mid_left], fill=LINE, width=4)
    connector(draw, [chunk.mid_right, (1350, 1135), emo.mid_left], fill=LINE, width=4)
    connector(draw, [merge.bottom_mid, (900, 1250), chunks_json.mid_left], fill=LINE, width=3)

    # 3. Translation and master timeline
    stage_label(draw, "3", "번역 및 통합 타임라인 생성", 1355)
    asr_json = node(draw, 270, 1505, 250, 88, title="asr.json", subtitle="청크별 원문", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    translate = node(draw, 610, 1505, 300, 104, title="GPT-5.4 번역", subtitle="EN → KO\n문맥 보정", fill=GREEN_T, outline=GREEN, title_size=21, sub_size=15)
    rewrite = node(draw, 965, 1505, 300, 104, title="Duration-aware", subtitle="발화 길이 맞춤\nrewrite", fill=GREEN_T, outline=GREEN, title_size=20, sub_size=15)
    timeline = node(
        draw,
        1450,
        1505,
        520,
        150,
        title="master_timeline_cosyvoice.json",
        subtitle="text_src · text_translated · emotion\nreference · tts_instruct · dub_wav",
        fill=BLUE_T,
        outline=BLUE,
        title_size=22,
        sub_size=16,
        mono_sub=True,
    )
    emotion_json = node(draw, 270, 1635, 250, 82, title="emotion.json", subtitle="감정 점수", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    chunks_ref = node(draw, 610, 1635, 300, 82, title="speaker_chunks", subtitle="화자 / 시간축", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)

    connector(draw, [qwen.bottom_mid, (1540, 1275), (270, 1275), asr_json.top_mid], fill=LINE, width=4)
    connector(draw, [asr_json.mid_right, translate.mid_left], fill=LINE, width=5)
    connector(draw, [translate.mid_right, rewrite.mid_left], fill=LINE, width=5)
    connector(draw, [rewrite.mid_right, timeline.mid_left], fill=BLUE, width=5)
    connector(draw, [emo.bottom_mid, (1540, 1285), (270, 1285), emotion_json.top_mid], fill=LINE, width=4)
    # Auxiliary inputs join the master timeline through a thin merge bus so the
    # main left-to-right flow stays visually dominant.
    merge_bus = (1138, 1588)
    aux = (178, 190, 206)
    draw.line((emotion_json.top_mid[0], emotion_json.top_mid[1], emotion_json.top_mid[0], merge_bus[1], merge_bus[0], merge_bus[1]), fill=aux, width=3)
    draw.line((chunks_ref.top_mid[0], chunks_ref.top_mid[1], chunks_ref.top_mid[0], merge_bus[1], merge_bus[0], merge_bus[1]), fill=aux, width=3)
    connector(draw, [merge_bus, timeline.mid_left], fill=aux, width=3)

    # 4. Style instruction and reference selection
    stage_label(draw, "4", "감정 기반 TTS 지시문 / 참조 선택", 1790)
    context = node(draw, 270, 1940, 280, 98, title="감정 + 문맥", subtitle="현재/앞/뒤 대사", fill=PURPLE_T, outline=PURPLE, title_size=21, sub_size=15)
    gpt_inst = node(draw, 610, 1940, 295, 98, title="GPT-5.4", subtitle="TTS directive 생성", fill=GREEN_T, outline=GREEN, title_size=22, sub_size=15)
    instruct = node(draw, 945, 1940, 300, 98, title="tts_instruct_text", subtitle="영어 지시문", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    ref_policy = node(draw, 1290, 1940, 290, 98, title="Reference Policy", subtitle="self / speaker bank", fill=PURPLE_T, outline=PURPLE, title_size=20, sub_size=15)
    ref_bank = node(draw, 1630, 1940, 290, 98, title="Reference Bank", subtitle="화자별 우수 샘플", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15)
    timeline_update = node(draw, 1990, 1940, 335, 98, title="Timeline Update", subtitle="instruction / reference 저장", fill=BLUE_T, outline=BLUE, title_size=20, sub_size=15)

    connector(draw, [timeline.bottom_mid, (1450, 1720), (270, 1720), context.top_mid], fill=BLUE, width=4)
    connector(draw, [context.mid_right, gpt_inst.mid_left], fill=LINE, width=5)
    connector(draw, [gpt_inst.mid_right, instruct.mid_left], fill=LINE, width=5)
    connector(draw, [instruct.mid_right, ref_policy.mid_left], fill=LINE, width=5)
    connector(draw, [ref_policy.mid_right, ref_bank.mid_left], fill=LINE, width=5)
    connector(draw, [ref_bank.mid_right, timeline_update.mid_left], fill=BLUE, width=5)

    # 5. Korean TTS and validation
    stage_label(draw, "5", "한국어 음성 합성 · 검증", 2235)
    timeline_in = node(draw, 275, 2415, 280, 94, title="Timeline Row", subtitle="text_tts + instruct", fill=BLUE_T, outline=BLUE, title_size=20, sub_size=15, mono_sub=True)
    ref_wav = node(draw, 610, 2415, 265, 94, title="Reference WAV", subtitle="원본 화자 음색", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15)
    cosy = node(
        draw,
        990,
        2415,
        360,
        142,
        title="CosyVoice3",
        subtitle="instruct2 / cross-lingual\nzero-shot fallback",
        fill=CYAN_T,
        outline=CYAN,
        title_size=25,
        sub_size=16,
    )
    dub = node(draw, 1385, 2415, 300, 94, title="Korean Dub WAV", subtitle="chunk_*_dub.wav", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    valid_asr = node(draw, 1740, 2355, 300, 94, title="Qwen3-ASR 검증", subtitle="재전사 비교", fill=GREEN_T, outline=GREEN, title_size=20, sub_size=15)
    qgate = node(draw, 1740, 2485, 300, 94, title="Quality Gate", subtitle="TTS 품질 상태", fill=GREEN_T, outline=GREEN, title_size=20, sub_size=15)
    validation = node(draw, 2090, 2415, 285, 94, title="Validation JSON", subtitle="검증 결과 저장", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)

    connector(draw, [timeline_update.bottom_mid, (1990, 2160), (275, 2160), timeline_in.top_mid], fill=BLUE, width=4)
    connector(draw, [timeline_in.mid_right, ref_wav.mid_left], fill=LINE, width=5)
    connector(draw, [ref_wav.mid_right, cosy.mid_left], fill=CYAN, width=5)
    connector(draw, [cosy.mid_right, dub.mid_left], fill=CYAN, width=5)
    connector(draw, [dub.mid_right, (1565, 2355), valid_asr.mid_left], fill=LINE, width=4)
    connector(draw, [dub.mid_right, (1565, 2485), qgate.mid_left], fill=LINE, width=4)
    connector(draw, [valid_asr.mid_right, (1900, 2415), validation.mid_left], fill=LINE, width=4)
    connector(draw, [qgate.mid_right, (1900, 2415), validation.mid_left], fill=LINE, width=4)

    # 6. Compose and mux
    stage_label(draw, "6", "최종 음성 합성 · 영상 mux", 2695)
    dub_chunks = node(draw, 275, 2875, 285, 86, title="Dub Chunks", subtitle="한국어 음성", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15)
    bgm_final = node(draw, 275, 3010, 285, 86, title="Background BGM", subtitle="bgm.wav", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15, mono_sub=True)
    video_final = node(draw, 275, 3145, 285, 86, title="Original Video", subtitle="video stream", fill=ORANGE_T, outline=ORANGE, title_size=20, sub_size=15)
    compose = node(draw, 760, 3010, 320, 116, title="ffmpeg compose", subtitle="gain / peak 조정\nfinal_dub.wav", fill=GREEN_T, outline=GREEN, title_size=21, sub_size=15, mono_sub=True)
    mux = node(draw, 1195, 3010, 300, 116, title="ffmpeg mux", subtitle="video copy + audio", fill=GREEN_T, outline=GREEN, title_size=21, sub_size=15)
    output = node(
        draw,
        1705,
        3010,
        480,
        150,
        title="한국어 더빙 영상",
        subtitle="output/{stem}/output_cosyvoice.mp4",
        fill=RED_T,
        outline=RED,
        title_size=27,
        sub_size=17,
        mono_sub=True,
    )

    connector(draw, [dub.bottom_mid, (1385, 2630), (275, 2630), dub_chunks.top_mid], fill=LINE, width=4)
    connector(draw, [dub_chunks.mid_right, (520, 2875), (520, 3010), compose.mid_left], fill=LINE, width=5)
    connector(draw, [bgm_final.mid_right, compose.mid_left], fill=LINE, width=5)
    connector(draw, [video_final.mid_right, (520, 3145), (520, 3010), compose.mid_left], fill=LINE, width=5)
    connector(draw, [compose.mid_right, mux.mid_left], fill=LINE, width=5)
    connector(draw, [mux.mid_right, output.mid_left], fill=RED, width=6)

    # Legend and footer.
    legend_y = 3340
    x = 115
    x = legend_item(draw, x, legend_y, "입력 / 출력", RED_T, RED)
    x = legend_item(draw, x, legend_y, "AI 모델", GREEN_T, GREEN)
    x = legend_item(draw, x, legend_y, "파일 / 중간 산출물", ORANGE_T, ORANGE)
    x = legend_item(draw, x, legend_y, "공유 상태 / 타임라인", BLUE_T, BLUE)
    x = legend_item(draw, x, legend_y, "참조 / 제어 로직", PURPLE_T, PURPLE)
    draw.line((90, 3390, W - 90, 3390), fill=(217, 225, 238), width=2)
    draw_text(draw, (90, 3430), "핵심 구조: master_timeline_cosyvoice.json을 중심으로 각 단계가 청크 단위 상태를 공유하고, 수정된 청크만 다시 합성한다.", 24, fill=BODY)
    draw_text(draw, (W - 90, 3430), "A4 · 300dpi", 22, fill=MUTE, mono=True, anchor="ra")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    jpg_path = OUT_DIR / JPG_NAME
    png_path = OUT_DIR / PNG_NAME
    img.save(jpg_path, "JPEG", quality=97, subsampling=0, dpi=(DPI, DPI))
    img.save(png_path, "PNG", dpi=(DPI, DPI), optimize=True)
    print(jpg_path)
    print(png_path)


if __name__ == "__main__":
    build()
