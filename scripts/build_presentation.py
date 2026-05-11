# 중간발표 2 대본을 미니멀 라이트 톤의 .pptx 슬라이드로 빌드
"""scripts/build_presentation.py — 다시 실행하면 docs/presentation-midterm2.pptx 가 새로 생성됨."""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Pt

# ─── design tokens ─────────────────────────────────────────────────────────────
INK = RGBColor(0x0F, 0x17, 0x2A)
BODY = RGBColor(0x33, 0x41, 0x55)
META = RGBColor(0x94, 0xA3, 0xB8)
DIV = RGBColor(0xE2, 0xE8, 0xF0)
BG = RGBColor(0xFF, 0xFF, 0xFF)
ACCENT = RGBColor(0x1D, 0x4E, 0xD8)  # deep navy blue
ACCENT_TINT = RGBColor(0xDB, 0xEA, 0xFE)
SURFACE = RGBColor(0xF8, 0xFA, 0xFC)

FONT_HEAD = "Pretendard"  # fallback to system if absent
FONT_SANS = "Pretendard"
FONT_MONO = "JetBrains Mono"
FONT_KO = "맑은 고딕"

SLIDE_W = Emu(13_333_333)  # 16:9 widescreen, EMU = inches * 914400
SLIDE_H = Emu(7_500_000)


def _set_run(run, *, text: str, size: int, color: RGBColor, bold: bool = False, font: str = FONT_SANS, italic: bool = False) -> None:
    run.text = text
    f = run.font
    f.name = font
    f.size = Pt(size)
    f.color.rgb = color
    f.bold = bold
    f.italic = italic


def _add_text(slide, *, x: float, y: float, w: float, h: float, text: str, size: int, color: RGBColor,
              bold: bool = False, font: str = FONT_SANS, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP) -> None:
    box = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    p = tf.paragraphs[0]
    p.alignment = align
    _set_run(p.add_run(), text=text, size=size, color=color, bold=bold, font=font)


def _add_paragraph_box(slide, *, x: float, y: float, w: float, h: float, paragraphs: list[dict],
                       anchor=MSO_ANCHOR.TOP) -> None:
    """paragraphs: [{ text, size, color, bold?, font?, space_after? }]"""
    box = slide.shapes.add_textbox(Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    for idx, spec in enumerate(paragraphs):
        p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
        p.alignment = spec.get("align", PP_ALIGN.LEFT)
        if spec.get("space_after"):
            p.space_after = Pt(spec["space_after"])
        _set_run(
            p.add_run(),
            text=spec["text"],
            size=spec["size"],
            color=spec["color"],
            bold=spec.get("bold", False),
            font=spec.get("font", FONT_SANS),
            italic=spec.get("italic", False),
        )


def _add_rect(slide, *, x: float, y: float, w: float, h: float, fill: RGBColor, line: RGBColor | None = None) -> None:
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(int(x)), Emu(int(y)), Emu(int(w)), Emu(int(h)))
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
    shape.shadow.inherit = False


def _add_line(slide, *, x: float, y: float, w: float, h: float, color: RGBColor) -> None:
    _add_rect(slide, x=x, y=y, w=w, h=h, fill=color)


# ─── chrome (반복되는 헤더/푸터) ───────────────────────────────────────────────
META_LEFT = Emu(720_000)
META_TOP = Emu(360_000)
FOOT_BASE_Y = Emu(6_750_000)
CONTENT_LEFT = Emu(720_000)
CONTENT_RIGHT_W = Emu(11_900_000)


def _draw_chrome(slide, *, idx: int, total: int, eyebrow: str, hide_pagenum: bool = False) -> None:
    # 좌상단 brand label
    _add_text(slide,
              x=META_LEFT, y=META_TOP, w=Emu(8_000_000), h=Emu(360_000),
              text=eyebrow.upper(), size=10, color=META, font=FONT_MONO)
    # 우상단 카운터
    if not hide_pagenum:
        _add_text(slide,
                  x=Emu(11_400_000), y=META_TOP, w=Emu(1_500_000), h=Emu(360_000),
                  text=f"{idx:02d} / {total:02d}", size=10, color=META, font=FONT_MONO,
                  align=PP_ALIGN.RIGHT)
    # 하단 hairline
    _add_line(slide, x=META_LEFT, y=FOOT_BASE_Y, w=Emu(11_900_000), h=Emu(8_000), color=DIV)
    # 하단 라벨
    _add_text(slide,
              x=META_LEFT, y=Emu(6_900_000), w=Emu(8_000_000), h=Emu(360_000),
              text="MOVIE DUBBING PIPELINE · CAPSTONE MIDTERM II", size=9, color=META, font=FONT_MONO)
    if not hide_pagenum:
        _add_text(slide,
                  x=Emu(11_400_000), y=Emu(6_900_000), w=Emu(1_500_000), h=Emu(360_000),
                  text="2026.05.07", size=9, color=META, font=FONT_MONO, align=PP_ALIGN.RIGHT)


# ─── slide builders ────────────────────────────────────────────────────────────
def slide_cover(prs: Presentation, *, idx: int, total: int) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _draw_chrome(slide, idx=idx, total=total, eyebrow="Capstone · Midterm II", hide_pagenum=True)

    # 좌측 액센트 사각형
    _add_rect(slide, x=Emu(720_000), y=Emu(2_400_000), w=Emu(120_000), h=Emu(2_700_000), fill=ACCENT)

    # 부제목 (eyebrow)
    _add_text(slide,
              x=Emu(1_080_000), y=Emu(2_400_000), w=Emu(10_000_000), h=Emu(360_000),
              text="MOVIE DUBBING AUTOMATION", size=12, color=ACCENT, font=FONT_MONO, bold=True)

    # 메인 타이틀
    _add_paragraph_box(slide,
                       x=Emu(1_080_000), y=Emu(2_900_000), w=Emu(11_000_000), h=Emu(2_400_000),
                       paragraphs=[
                           {"text": "한 번의 업로드로", "size": 54, "color": INK, "bold": True, "font": FONT_KO, "space_after": 8},
                           {"text": "끝나는 영상 더빙.", "size": 54, "color": INK, "bold": True, "font": FONT_KO},
                       ])

    # 메타
    _add_paragraph_box(slide,
                       x=Emu(1_080_000), y=Emu(5_400_000), w=Emu(11_000_000), h=Emu(900_000),
                       paragraphs=[
                           {"text": "한성대학교 캡스톤디자인 · 중간발표 II", "size": 14, "color": BODY, "font": FONT_KO, "space_after": 4},
                           {"text": "2026.05.07", "size": 11, "color": META, "font": FONT_MONO},
                       ])


def slide_toc(prs: Presentation, *, idx: int, total: int, sections: list[tuple[str, str]]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow="Contents")

    # 큰 라벨 (섹션 번호 스타일)
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_200_000), w=Emu(6_000_000), h=Emu(720_000),
              text="00 — Contents", size=11, color=META, font=FONT_MONO)

    _add_text(slide,
              x=Emu(720_000), y=Emu(1_700_000), w=Emu(11_000_000), h=Emu(900_000),
              text="발표 흐름", size=40, color=INK, bold=True, font=FONT_KO)

    # 두 컬럼 TOC (4 + 4)
    col_w = Emu(5_400_000)
    row_h = Emu(680_000)
    start_y = Emu(3_300_000)
    half = (len(sections) + 1) // 2
    for i, (num, title) in enumerate(sections):
        col = i // half
        row = i % half
        x = Emu(720_000 + col * 6_000_000)
        y = Emu(start_y.emu + row * row_h.emu)
        _add_text(slide,
                  x=x, y=y, w=Emu(900_000), h=row_h,
                  text=num, size=14, color=ACCENT, font=FONT_MONO, bold=True)
        _add_text(slide,
                  x=Emu(x.emu + 700_000), y=y, w=Emu(col_w.emu - 700_000), h=row_h,
                  text=title, size=16, color=INK, font=FONT_KO)


def slide_section(prs: Presentation, *, idx: int, total: int, num: str, eyebrow: str, title_lines: list[str], lede: str) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow=eyebrow)

    # 큰 섹션 번호
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_500_000), w=Emu(3_000_000), h=Emu(900_000),
              text=num, size=72, color=ACCENT, bold=True, font=FONT_MONO)
    # 작은 horizontal accent line
    _add_line(slide, x=Emu(720_000), y=Emu(2_700_000), w=Emu(1_200_000), h=Emu(20_000), color=ACCENT)

    # 큰 제목 (multi-line)
    title_specs = []
    for i, line in enumerate(title_lines):
        title_specs.append({"text": line, "size": 44, "color": INK, "bold": True, "font": FONT_KO,
                            "space_after": 6 if i < len(title_lines) - 1 else 0})
    _add_paragraph_box(slide,
                       x=Emu(720_000), y=Emu(3_300_000), w=Emu(11_000_000), h=Emu(1_900_000),
                       paragraphs=title_specs)

    # lede (한 줄 부제)
    _add_text(slide,
              x=Emu(720_000), y=Emu(5_500_000), w=Emu(11_000_000), h=Emu(720_000),
              text=lede, size=16, color=BODY, font=FONT_KO)


def slide_content(prs: Presentation, *, idx: int, total: int, num: str, eyebrow: str, title: str,
                  body_paragraphs: list[str], side_cards: list[tuple[str, str]] | None = None) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow=eyebrow)

    # 좌상단 — 섹션 번호 + 짧은 라인 + 제목
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_080_000), w=Emu(2_000_000), h=Emu(360_000),
              text=num, size=14, color=ACCENT, font=FONT_MONO, bold=True)
    _add_line(slide, x=Emu(720_000), y=Emu(1_400_000), w=Emu(720_000), h=Emu(15_000), color=ACCENT)

    _add_text(slide,
              x=Emu(720_000), y=Emu(1_650_000), w=Emu(11_000_000), h=Emu(900_000),
              text=title, size=32, color=INK, bold=True, font=FONT_KO)

    # 본문 두 컬럼 — side_cards 가 있으면 우측 컬럼 사용
    has_side = bool(side_cards)
    body_w = Emu(7_400_000 if has_side else 11_000_000)
    body_specs = []
    for i, para in enumerate(body_paragraphs):
        body_specs.append({"text": para, "size": 16, "color": BODY, "font": FONT_KO,
                           "space_after": 14 if i < len(body_paragraphs) - 1 else 0})
    _add_paragraph_box(slide,
                       x=Emu(720_000), y=Emu(2_900_000), w=body_w, h=Emu(3_600_000),
                       paragraphs=body_specs)

    if has_side:
        card_x = Emu(8_400_000)
        card_w = Emu(4_200_000)
        gap = Emu(180_000)
        card_h_total = Emu(3_600_000)
        n = max(1, len(side_cards))
        card_h = Emu((card_h_total.emu - gap.emu * (n - 1)) // n)
        for i, (label, value) in enumerate(side_cards):
            y = Emu(2_900_000 + i * (card_h.emu + gap.emu))
            _add_rect(slide, x=card_x, y=y, w=card_w, h=card_h, fill=SURFACE)
            _add_text(slide,
                      x=Emu(card_x.emu + 250_000), y=Emu(y.emu + 200_000),
                      w=Emu(card_w.emu - 500_000), h=Emu(360_000),
                      text=label, size=10, color=META, font=FONT_MONO, bold=True)
            _add_text(slide,
                      x=Emu(card_x.emu + 250_000), y=Emu(y.emu + 600_000),
                      w=Emu(card_w.emu - 500_000), h=Emu(card_h.emu - 700_000),
                      text=value, size=15, color=INK, font=FONT_KO)


def slide_pillars(prs: Presentation, *, idx: int, total: int, num: str, eyebrow: str, title: str,
                  pillars: list[tuple[str, str, str]]) -> None:
    """3-column pillar layout — pillars: [(label, headline, body), ...]"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow=eyebrow)

    _add_text(slide,
              x=Emu(720_000), y=Emu(1_080_000), w=Emu(2_000_000), h=Emu(360_000),
              text=num, size=14, color=ACCENT, font=FONT_MONO, bold=True)
    _add_line(slide, x=Emu(720_000), y=Emu(1_400_000), w=Emu(720_000), h=Emu(15_000), color=ACCENT)
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_650_000), w=Emu(11_000_000), h=Emu(900_000),
              text=title, size=32, color=INK, bold=True, font=FONT_KO)

    n = len(pillars)
    gap = Emu(360_000)
    total_w = Emu(11_900_000)
    col_w = Emu((total_w.emu - gap.emu * (n - 1)) // n)
    start_x = 720_000
    start_y = 2_900_000
    col_h = Emu(3_700_000)
    for i, (label, headline, body) in enumerate(pillars):
        x = Emu(start_x + i * (col_w.emu + gap.emu))
        # 라벨 위 short accent line
        _add_line(slide, x=x, y=Emu(start_y), w=Emu(420_000), h=Emu(20_000), color=ACCENT)
        _add_text(slide,
                  x=x, y=Emu(start_y + 200_000), w=col_w, h=Emu(360_000),
                  text=label, size=11, color=ACCENT, font=FONT_MONO, bold=True)
        _add_text(slide,
                  x=x, y=Emu(start_y + 600_000), w=col_w, h=Emu(900_000),
                  text=headline, size=20, color=INK, bold=True, font=FONT_KO)
        _add_text(slide,
                  x=x, y=Emu(start_y + 1_700_000), w=col_w, h=Emu(col_h.emu - 1_700_000),
                  text=body, size=14, color=BODY, font=FONT_KO)


def slide_pipeline(prs: Presentation, *, idx: int, total: int, num: str, eyebrow: str, title: str) -> None:
    """4 docker services + master timeline diagram."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow=eyebrow)

    _add_text(slide,
              x=Emu(720_000), y=Emu(1_080_000), w=Emu(2_000_000), h=Emu(360_000),
              text=num, size=14, color=ACCENT, font=FONT_MONO, bold=True)
    _add_line(slide, x=Emu(720_000), y=Emu(1_400_000), w=Emu(720_000), h=Emu(15_000), color=ACCENT)
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_650_000), w=Emu(11_000_000), h=Emu(900_000),
              text=title, size=32, color=INK, bold=True, font=FONT_KO)

    # 4 service blocks
    services = [
        ("controller", "오케스트레이션", "ffmpeg · 큐 관리"),
        ("demucs", "보컬 분리", "htdemucs_ft"),
        ("speaker", "화자/감정/ASR", "pyannote · emotion2vec · Qwen3-ASR"),
        ("tts-cosyvoice", "한국어 합성", "Fun-CosyVoice3 · zero-shot"),
    ]
    n = len(services)
    gap = Emu(280_000)
    total_w = Emu(11_900_000)
    col_w = Emu((total_w.emu - gap.emu * (n - 1)) // n)
    block_y = Emu(2_900_000)
    block_h = Emu(2_300_000)

    for i, (service, role, tool) in enumerate(services):
        x = Emu(720_000 + i * (col_w.emu + gap.emu))
        _add_rect(slide, x=x, y=block_y, w=col_w, h=block_h, fill=SURFACE)
        _add_line(slide, x=Emu(x.emu + 250_000), y=Emu(block_y.emu + 250_000),
                  w=Emu(420_000), h=Emu(20_000), color=ACCENT)
        _add_text(slide,
                  x=Emu(x.emu + 250_000), y=Emu(block_y.emu + 400_000), w=Emu(col_w.emu - 500_000), h=Emu(360_000),
                  text=service, size=12, color=ACCENT, font=FONT_MONO, bold=True)
        _add_text(slide,
                  x=Emu(x.emu + 250_000), y=Emu(block_y.emu + 800_000), w=Emu(col_w.emu - 500_000), h=Emu(540_000),
                  text=role, size=18, color=INK, bold=True, font=FONT_KO)
        _add_text(slide,
                  x=Emu(x.emu + 250_000), y=Emu(block_y.emu + 1_500_000), w=Emu(col_w.emu - 500_000), h=Emu(720_000),
                  text=tool, size=11, color=BODY, font=FONT_MONO)

    # master timeline 강조 행
    timeline_y = Emu(5_500_000)
    _add_rect(slide, x=Emu(720_000), y=timeline_y, w=total_w, h=Emu(900_000), fill=ACCENT_TINT)
    _add_text(slide,
              x=Emu(940_000), y=Emu(timeline_y.emu + 200_000), w=Emu(11_400_000), h=Emu(360_000),
              text="MASTER_TIMELINE.JSON", size=11, color=ACCENT, font=FONT_MONO, bold=True)
    _add_text(slide,
              x=Emu(940_000), y=Emu(timeline_y.emu + 540_000), w=Emu(11_400_000), h=Emu(360_000),
              text="네 서비스가 청크별 한 행을 공유 · 어느 단계에서 멈춰도 그 시점 상태가 보존",
              size=14, color=INK, font=FONT_KO)


def slide_lesson(prs: Presentation, *, idx: int, total: int, num: str, eyebrow: str, title: str,
                 problem: str, cause: str, lesson: str) -> None:
    """4-3 학습 분포 일화 같은 "해결 → 교훈" 강조 슬라이드."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow=eyebrow)

    _add_text(slide,
              x=Emu(720_000), y=Emu(1_080_000), w=Emu(2_000_000), h=Emu(360_000),
              text=num, size=14, color=ACCENT, font=FONT_MONO, bold=True)
    _add_line(slide, x=Emu(720_000), y=Emu(1_400_000), w=Emu(720_000), h=Emu(15_000), color=ACCENT)
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_650_000), w=Emu(11_000_000), h=Emu(900_000),
              text=title, size=32, color=INK, bold=True, font=FONT_KO)

    # 3 단계 row — Problem / Cause / Lesson
    rows = [("PROBLEM · 증상", problem, INK), ("CAUSE · 원인", cause, INK), ("LESSON · 교훈", lesson, ACCENT)]
    row_y = 2_900_000
    row_h = 1_080_000
    for i, (label, text, color) in enumerate(rows):
        y = Emu(row_y + i * row_h)
        _add_text(slide,
                  x=Emu(720_000), y=y, w=Emu(2_400_000), h=Emu(360_000),
                  text=label, size=10, color=META, font=FONT_MONO, bold=True)
        _add_text(slide,
                  x=Emu(720_000), y=Emu(y.emu + 380_000), w=Emu(11_900_000), h=Emu(620_000),
                  text=text, size=18 if i < 2 else 22, color=color,
                  bold=(i == 2), font=FONT_KO)
        if i < len(rows) - 1:
            _add_line(slide, x=Emu(720_000), y=Emu(y.emu + row_h - 10_000),
                      w=Emu(11_900_000), h=Emu(8_000), color=DIV)


def slide_panels(prs: Presentation, *, idx: int, total: int, num: str, eyebrow: str, title: str,
                 panels: list[tuple[str, str]]) -> None:
    """2x2 panel layout — for 웹 인터페이스 4 화면."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow=eyebrow)

    _add_text(slide,
              x=Emu(720_000), y=Emu(1_080_000), w=Emu(2_000_000), h=Emu(360_000),
              text=num, size=14, color=ACCENT, font=FONT_MONO, bold=True)
    _add_line(slide, x=Emu(720_000), y=Emu(1_400_000), w=Emu(720_000), h=Emu(15_000), color=ACCENT)
    _add_text(slide,
              x=Emu(720_000), y=Emu(1_650_000), w=Emu(11_000_000), h=Emu(900_000),
              text=title, size=32, color=INK, bold=True, font=FONT_KO)

    cols = 2
    rows = 2
    gap_x = 360_000
    gap_y = 280_000
    grid_x = 720_000
    grid_y = 2_900_000
    grid_w = 11_900_000
    grid_h = 3_700_000
    cell_w = (grid_w - gap_x * (cols - 1)) // cols
    cell_h = (grid_h - gap_y * (rows - 1)) // rows
    for i, (heading, body) in enumerate(panels):
        c = i % cols
        r = i // cols
        x = grid_x + c * (cell_w + gap_x)
        y = grid_y + r * (cell_h + gap_y)
        _add_rect(slide, x=Emu(x), y=Emu(y), w=Emu(cell_w), h=Emu(cell_h), fill=SURFACE)
        _add_line(slide, x=Emu(x + 280_000), y=Emu(y + 280_000), w=Emu(420_000), h=Emu(20_000), color=ACCENT)
        _add_text(slide,
                  x=Emu(x + 280_000), y=Emu(y + 460_000), w=Emu(cell_w - 560_000), h=Emu(540_000),
                  text=heading, size=18, color=INK, bold=True, font=FONT_KO)
        _add_text(slide,
                  x=Emu(x + 280_000), y=Emu(y + 1_080_000), w=Emu(cell_w - 560_000), h=Emu(cell_h - 1_200_000),
                  text=body, size=13, color=BODY, font=FONT_KO)


def slide_closing(prs: Presentation, *, idx: int, total: int) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _draw_chrome(slide, idx=idx, total=total, eyebrow="Thank you", hide_pagenum=True)

    _add_rect(slide, x=Emu(720_000), y=Emu(2_400_000), w=Emu(120_000), h=Emu(2_700_000), fill=ACCENT)
    _add_text(slide,
              x=Emu(1_080_000), y=Emu(2_400_000), w=Emu(10_000_000), h=Emu(360_000),
              text="THANK YOU", size=12, color=ACCENT, font=FONT_MONO, bold=True)

    _add_paragraph_box(slide,
                       x=Emu(1_080_000), y=Emu(2_900_000), w=Emu(11_000_000), h=Emu(2_400_000),
                       paragraphs=[
                           {"text": "한 영상을 업로드하면", "size": 44, "color": INK, "bold": True, "font": FONT_KO, "space_after": 6},
                           {"text": "더빙된 결과까지 한 번에.", "size": 44, "color": INK, "bold": True, "font": FONT_KO},
                       ])
    _add_text(slide,
              x=Emu(1_080_000), y=Emu(5_400_000), w=Emu(11_000_000), h=Emu(540_000),
              text="청크 단위 검수와 부분 재작업까지 — 그게 지금의 도착점.",
              size=16, color=BODY, font=FONT_KO)


# ─── deck wiring ───────────────────────────────────────────────────────────────
def build(out_path: Path) -> None:
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    sections = [
        ("01", "오프닝"),
        ("02", "회고와 변화"),
        ("03", "시스템 구조"),
        ("04", "기술적 도전"),
        ("05", "웹 인터페이스"),
        ("06", "데모 시나리오"),
        ("07", "한계와 다음 단계"),
        ("08", "마무리"),
    ]

    # 슬라이드 카운트 — 표지(1) + TOC(1) + 본문 10 + 닫기(1) = 13
    TOTAL = 13

    slide_cover(prs, idx=1, total=TOTAL)
    slide_toc(prs, idx=2, total=TOTAL, sections=sections)

    slide_section(prs, idx=3, total=TOTAL, num="01",
                  eyebrow="01 · Opening",
                  title_lines=["사람이 하는 일을,", "한 번의 업로드로."],
                  lede="번역 · 녹음 · 컷팅을 자동화하는 영상 더빙 파이프라인.")

    slide_pillars(prs, idx=4, total=TOTAL, num="02",
                  eyebrow="02 · Recap",
                  title="중간발표 1 이후 두 달, 세 가지를 다시 만들었어요.",
                  pillars=[
                      ("01 · MODEL", "감정과 스타일을 모델 입력단에서 다시 설계",
                       "emotion2vec 9-class 분포를 LLM 컨텍스트로 압축. 원본 음색 유지를 1순위 원칙으로."),
                      ("02 · WEB", "검수와 부분 재작업이 가능한 웹 인터페이스",
                       "Dashboard / Projects / Chunks / Compare. 청크 단위 편집과 redub."),
                      ("03 · INFRA", "도커 멀티 서비스로 분리된 파이프라인",
                       "controller / demucs / speaker / tts-cosyvoice. 어느 머신에서도 같은 결과."),
                  ])

    slide_pipeline(prs, idx=5, total=TOTAL, num="03",
                   eyebrow="03 · Architecture",
                   title="네 서비스가 하나의 타임라인을 공유합니다.")

    slide_section(prs, idx=6, total=TOTAL, num="04",
                  eyebrow="04 · Challenges",
                  title_lines=["세 가지 도전,", "세 가지 교훈."],
                  lede="화자 정렬 · 감정 지시문 · 학습 분포 — 각 단계가 우리에게 남긴 것.")

    slide_content(prs, idx=7, total=TOTAL, num="04 · 01",
                  eyebrow="04 · Challenges",
                  title="화자 분리와 시간 정렬",
                  body_paragraphs=[
                      "화자 분리는 발화 구간만, ASR은 단어 타임스탬프만 줍니다. 단순 교집합은 한 문장을 두 화자로 쪼개거나 추임새를 떼어 놓아요.",
                      "화자 분리 구간을 기준선으로 두고, ASR 단어가 그 경계를 넘을 때만 분기하는 병합 규칙으로 해결했습니다.",
                  ],
                  side_cards=[
                      ("INPUT", "pyannote rttm · ASR word ts"),
                      ("RULE", "화자 segment = ground truth"),
                      ("OUTPUT", "speaker_chunks.json"),
                  ])

    slide_content(prs, idx=8, total=TOTAL, num="04 · 02",
                  eyebrow="04 · Challenges",
                  title="감정 인식과 TTS 지시문 생성",
                  body_paragraphs=[
                      "emotion2vec 의 9-class 분포를 그대로 넘기지 않습니다. 상위 3개 감정과 점수, 그리고 앞·현재·뒷 대사를 LLM에 함께 넣어 영어 한 줄 directive 를 만듭니다.",
                      "가장 강조한 원칙 — 원본 화자의 음색과 톤을 최대한 유지하라. 감정은 보조 신호이지 새 캐릭터가 아닙니다.",
                  ],
                  side_cards=[
                      ("INPUT", "Top-3 emotion · ±1 line context"),
                      ("PRINCIPLE", "Preserve original voice"),
                      ("OUTPUT", "English directive · CosyVoice instruct"),
                  ])

    slide_lesson(prs, idx=9, total=TOTAL, num="04 · 03",
                 eyebrow="04 · Challenges",
                 title="학습 분포를 벗어났을 때",
                 problem="instruct 프롬프트의 prefix 를 제거하니 결과 음성에 영어가 섞여 들어왔습니다.",
                 cause="CosyVoice 의 instruct 학습 데이터가 100% 그 prefix 형식 — 빼는 순간 입력이 학습 분포 밖으로 나갑니다.",
                 lesson="모델을 잘 쓴다는 것은 결국 모델이 학습한 분포를 존중하는 일.")

    slide_panels(prs, idx=10, total=TOTAL, num="05",
                 eyebrow="05 · Web UI",
                 title="검수가 가능한 화면 — 결과 위에서 다시 일하기.",
                 panels=[
                     ("Dashboard · 관제실",
                      "진행 중인 더빙, GPU/서비스 헬스, cross-run 활동을 한 화면에 모은 진입점."),
                     ("Projects · 영상 단위 그룹",
                      "input_stem 으로 묶인 프로젝트. 같은 영상의 여러 시도를 카드로 비교."),
                     ("Chunks · 청크 인스펙터",
                      "원본/더빙 A·B 비교, 번역·지시문·감정 편집, 그 청크만 redub."),
                     ("Compare · 결과 영상",
                      "원본 영상과 더빙 결과를 나란히 재생. 입과 음성의 합을 체크."),
                 ])

    slide_content(prs, idx=11, total=TOTAL, num="06",
                  eyebrow="06 · Demo",
                  title="강의 샘플로 본 한 사이클",
                  body_paragraphs=[
                      "약 3분 일본어 강의 영상을 업로드 → 화자 2명 자동 분리 → 청크 약 40개 생성.",
                      "감정이 잘못 잡힌 한 청크를 발견 → Chunks 페이지에서 지시문만 수정 → 그 청크만 다시 더빙.",
                      "전체를 처음부터 돌리지 않고 한 청크만 갱신해서 최종 영상을 다시 합쳤습니다.",
                  ],
                  side_cards=[
                      ("DURATION", "3:14 / 강의샘플"),
                      ("CHUNKS", "약 40개 / 화자 2명"),
                      ("REDUB", "청크 1개만 재합성"),
                  ])

    slide_pillars(prs, idx=12, total=TOTAL, num="07",
                  eyebrow="07 · What's next",
                  title="남은 과제 — 솔직하게.",
                  pillars=[
                      ("01 · LIPSYNC", "립싱크 정렬은 실험 단계",
                       "음성을 입에 맞추는 건 아직 — 청크 길이 보정으로만 부분 대응 중."),
                      ("02 · EMOTION", "감정은 음향만 본다",
                       "대본 문맥에서 벗어난 결과가 나올 때가 있어요. 컨텍스트 보정을 더할 계획."),
                      ("03 · VOICE", "긴 문장에서 음색 흔들림",
                       "Zero-shot 복제는 짧은 문장엔 강하지만 긴 발화에서 일관성이 떨어집니다."),
                  ])

    slide_closing(prs, idx=13, total=TOTAL)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(out_path)
    print(f"Wrote {out_path} ({prs.slide_width.emu}x{prs.slide_height.emu} EMU, {len(prs.slides)} slides)")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    build(project_root / "docs" / "presentation-midterm2.pptx")
