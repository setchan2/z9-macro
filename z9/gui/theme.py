"""ttk 스타일 — 차분한 중성 팔레트.

원색은 쓰지 않는다. 매크로를 돌리는 동안 옆에 계속 띄워 두는 창이라 눈이
피로하면 안 되고, 강한 색은 정말 중요한 것(비상 정지, 경고)에만 남겨 둬야
구분이 된다.

색은 역할로만 쓴다.
  · 기본 버튼은 무채색   — 대부분의 동작
  · 강조 버튼은 청회색   — 그 화면의 주된 동작 하나
  · 위험 버튼은 벽돌색   — 되돌릴 수 없는 것 (삭제, 비상 정지)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

PALETTE = {
    "bg": "#f4f5f7",  # 창 배경
    "surface": "#ffffff",  # 입력칸 · 목록 배경
    "raised": "#eceef1",  # 버튼 · 탭 기본
    "hover": "#e2e5ea",  # 마우스 올렸을 때
    "pressed": "#d8dce2",
    "border": "#d3d8df",
    "text": "#2b3038",
    "muted": "#6b7280",
    "faint": "#9aa1ab",
    "accent": "#4a6d8c",  # 청회색 — 강조
    "accent_hover": "#3f5e79",
    "accent_soft": "#e7edf3",
    "ok": "#3f7d5a",  # 차분한 초록
    "warn": "#9a7439",  # 차분한 호박색
    "danger": "#a35a55",  # 벽돌색 (원색 빨강 아님)
    "danger_hover": "#8e4a46",
    "stripe": "#f8f9fb",  # 목록 줄무늬
    "select": "#dde6ef",
    "on_accent": "#ffffff",  # 강조 · 위험 버튼 위 글자
    "on_danger": "#ffffff",
    "danger_soft": "#f0e4e3",  # 작은 위험 버튼에 마우스를 올렸을 때
    "danger_soft2": "#e6d5d4",
}

# -- 테마 ---------------------------------------------------------------------
#
# 사람이 직접 고를 수 있는 색은 **여섯 가지뿐**이다. 나머지(마우스 올렸을 때, 테두리,
# 흐린 글자, 줄무늬 …)는 이 여섯에서 섞어 만든다. 스무 가지를 다 고르게 하면 한두
# 개만 바꿔도 서로 안 어울리는 조합이 생기고, 어두운 배경에 어두운 글자처럼 아예 못
# 읽는 화면이 나온다.
COLOR_ROLES = (
    ("bg", "창 배경"),
    ("surface", "입력칸 · 목록"),
    ("raised", "버튼 · 탭"),
    ("text", "글자"),
    ("accent", "강조"),
    ("danger", "위험 · 삭제"),
)
BASE_ROLES = tuple(role for role, _label in COLOR_ROLES)

DEFAULT_THEME = "기본"
DEFAULT_PALETTE = dict(PALETTE)

THEMES: dict[str, dict[str, str]] = {
    # 처음부터 쓰던 차분한 중성 팔레트. 이것만 스무 색을 그대로 들고 있다.
    "기본": DEFAULT_PALETTE,
    "화이트": {"bg": "#ffffff", "surface": "#ffffff", "raised": "#f1f3f5",
             "text": "#1f2328", "accent": "#3a6fb0", "danger": "#b24a44"},
    "다크": {"bg": "#1e1f22", "surface": "#2b2d31", "raised": "#35373c",
           "text": "#e3e5e8", "accent": "#5b8def", "danger": "#d0645e",
           "ok": "#5fb382", "warn": "#d4a656"},
    "모던": {"bg": "#141c26", "surface": "#1d2835", "raised": "#263545",
           "text": "#dde6ee", "accent": "#26b2a1", "danger": "#e0685f",
           "ok": "#4fc28a", "warn": "#e0b25a"},
    "심플": {"bg": "#fafafa", "surface": "#ffffff", "raised": "#ececec",
           "text": "#111111", "accent": "#333333", "danger": "#b3261e"},
    "따뜻한": {"bg": "#f6f1e9", "surface": "#fffdf9", "raised": "#ebe3d6",
            "text": "#3b3129", "accent": "#9c6436", "danger": "#a8463c",
            "ok": "#5d7d3f", "warn": "#a8772e"},
}


def _is_hex(value) -> bool:
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in value[1:]))


def _rgb(value: str) -> tuple[int, int, int]:
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def mix(a: str, b: str, amount: float) -> str:
    """a에서 b 쪽으로 amount(0~1)만큼 옮긴 색."""
    ra, ga, ba = _rgb(a)
    rb, gb, bb = _rgb(b)
    t = max(0.0, min(1.0, amount))
    return "#%02x%02x%02x" % (round(ra + (rb - ra) * t),
                              round(ga + (gb - ga) * t),
                              round(ba + (bb - ba) * t))


def luminance(value: str) -> float:
    """밝기 0(검정)~1(흰색). 사람 눈이 초록을 가장 밝게 느끼는 만큼 무게를 준다."""
    r, g, b = _rgb(value)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255.0


def readable_on(value: str) -> str:
    """그 색 위에 올릴 글자색. 밝은 강조색에 흰 글자를 올리면 안 읽힌다."""
    return "#ffffff" if luminance(value) < 0.6 else "#1b1b1b"


def derive(base: dict[str, str]) -> dict[str, str]:
    """고를 수 있는 여섯 색(+ ok · warn)에서 팔레트 전체를 만든다."""
    bg, surface, raised = base["bg"], base["surface"], base["raised"]
    text, accent, danger = base["text"], base["accent"], base["danger"]
    dark = luminance(bg) < 0.4
    # 어두운 테마에서 "누르면 진해진다"는 곧 밝아진다는 뜻이다.
    toward = "#ffffff" if dark else "#000000"
    return {
        "bg": bg,
        "surface": surface,
        "raised": raised,
        "hover": mix(raised, text, 0.10),
        "pressed": mix(raised, text, 0.18),
        "border": mix(bg, text, 0.22 if dark else 0.15),
        "text": text,
        "muted": mix(text, bg, 0.40),
        "faint": mix(text, bg, 0.58),
        "accent": accent,
        "accent_hover": mix(accent, toward, 0.15),
        "accent_soft": mix(surface, accent, 0.18),
        "ok": base.get("ok") or ("#5fb382" if dark else "#3f7d5a"),
        "warn": base.get("warn") or ("#d4a656" if dark else "#9a7439"),
        "danger": danger,
        "danger_hover": mix(danger, toward, 0.15),
        "stripe": mix(surface, text, 0.035),
        "select": mix(surface, accent, 0.28),
        "on_accent": readable_on(accent),
        "on_danger": readable_on(danger),
        "danger_soft": mix(raised, danger, 0.14),
        "danger_soft2": mix(raised, danger, 0.22),
    }


def build_palette(name: str, overrides: dict | None = None) -> dict[str, str]:
    """테마 이름과 직접 바꾼 색으로 팔레트를 만든다. 모르는 이름이면 기본."""
    preset = THEMES.get(name) or THEMES[DEFAULT_THEME]
    clean = {k: v.lower() for k, v in (overrides or {}).items()
             if k in BASE_ROLES and _is_hex(v)}
    if preset is DEFAULT_PALETTE and not clean:
        return dict(DEFAULT_PALETTE)
    base = {k: preset[k] for k in (*BASE_ROLES, "ok", "warn") if k in preset}
    base.update(clean)
    return _distinct(derive(base))


# 위젯 옵션에 칠해지지 않는 역할(ttk 버튼 글자색에만 쓴다). 색 옮겨 칠하기에서 뺀다.
_STYLE_ONLY = ("on_accent", "on_danger")


def _distinct(palette: dict[str, str]) -> dict[str, str]:
    """역할마다 색 값이 **서로 다르게** 한 칸씩 비킨다 (눈으로는 구별 안 되는 차이).

    recolor()는 색 값으로 역할을 알아낸다. 화이트 테마처럼 창 배경과 목록 배경이
    둘 다 #ffffff 이면 어느 역할인지 모르게 되어, 다음 테마로 바꿀 때 목록 배경이
    창 배경색으로 칠해졌다. 값이 겹치지 않으면 그럴 일이 없다.
    """
    seen: set[str] = set()
    out = {}
    for key, value in palette.items():
        if key in _STYLE_ONLY:
            out[key] = value
            continue
        r, g, b = _rgb(value)
        step = 0
        candidate = value.lower()
        while candidate in seen and step < 40:
            step += 1
            # 밝으면 어둡게, 어두우면 밝게 한 칸씩.
            delta = -step if (r + g + b) > 382 else step
            candidate = "#%02x%02x%02x" % (
                max(0, min(255, r + delta)), max(0, min(255, g + delta)),
                max(0, min(255, b + delta)))
        seen.add(candidate)
        out[key] = candidate
    return out


def use(name: str, overrides: dict | None = None) -> dict[str, str]:
    """팔레트를 갈아 끼운다. **바꾸기 전 팔레트**를 돌려준다 (recolor에 넘긴다).

    PALETTE를 새 dict로 바꾸지 않고 **그 자리에서** 채운다. 다른 모듈이
    theme.PALETTE를 붙들고 있어도 같은 것을 보게 하려는 것이다.
    """
    old = dict(PALETTE)
    new = build_palette(name, overrides)
    PALETTE.clear()
    PALETTE.update(new)
    return old

BASE_FAMILY = "Malgun Gothic"
MONO_FAMILY = "Consolas"

# 배율 1.0일 때의 기준값. 아래 apply(scale=...)가 여기에 배율을 곱한다.
BASE_SIZE = 9
TITLE_SIZE = 13
ROW_HEIGHT = 24

# 배율 범위. 너무 작으면 글씨가 뭉개지고, 너무 크면 창이 화면을 넘긴다.
MIN_SCALE = 0.9
MAX_SCALE = 2.0

SCALE = 1.0
BASE_FONT = (BASE_FAMILY, BASE_SIZE)
BOLD_FONT = (BASE_FAMILY, BASE_SIZE, "bold")
TITLE_FONT = (BASE_FAMILY, TITLE_SIZE, "bold")
MONO_FONT = (MONO_FAMILY, BASE_SIZE)

# style_text()로 색을 입힌 tk.Text / tk.Listbox 들. ttk 위젯은 스타일을 다시
# 걸면 그 자리에서 바뀌지만 이 위젯들은 각자 font 옵션을 들고 있어서,
# 배율이 바뀔 때 여기 모아 둔 것들을 직접 다시 손봐야 한다.
_STYLED: list[tuple[tk.Misc, bool]] = []


def set_family(name: str) -> str:
    """기본 글꼴을 바꾼다. 비우면 맑은 고딕. 다음 apply()부터 쓰인다.

    고정폭 글꼴(로그 · 좌표)은 그대로 둔다 — 줄을 맞춰 읽는 곳이라 글꼴 모양보다
    글자 폭이 같은 것이 중요하다.
    """
    global BASE_FAMILY
    BASE_FAMILY = (name or "").strip() or "Malgun Gothic"
    return BASE_FAMILY


def clamp_scale(value: float) -> float:
    """설정에서 읽은 배율을 쓸 수 있는 범위로 자른다."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return 1.0
    return max(MIN_SCALE, min(MAX_SCALE, scale))


def px(value: float) -> int:
    """기준 배율에서 잰 픽셀값을 지금 배율에 맞춘다."""
    return max(1, int(round(value * SCALE)))


def pad(*values: float) -> tuple[int, ...]:
    """padding 튜플을 통째로 배율에 맞춘다."""
    return tuple(px(v) for v in values)


def font_size(value: float) -> int:
    # 7pt 아래로는 한글이 뭉개져 읽을 수 없다.
    return max(7, int(round(value * SCALE)))


def scale_geometry(size: str, root: tk.Misc | None = None) -> str:
    """"980x680" 같은 창 크기 문자열을 배율에 맞추고 화면 안으로 자른다."""
    try:
        width, height = (int(part) for part in size.lower().split("x"))
    except ValueError:
        return size
    width, height = px(width), px(height)
    if root is not None:
        # 배율을 키운 채 작은 노트북 화면에서 열면 창이 화면 밖으로 나간다.
        width = min(width, int(root.winfo_screenwidth() * 0.95))
        height = min(height, int(root.winfo_screenheight() * 0.92))
    return f"{width}x{height}"


# Tk가 기본으로 들고 있는 글꼴들. 스타일만 고치면 콤보박스 목록·메시지 상자처럼
# 스타일을 안 보는 곳이 예전 크기로 남는다.
_NAMED_FONTS = (
    "TkDefaultFont",
    "TkTextFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkSmallCaptionFont",
    "TkIconFont",
    "TkTooltipFont",
)


def _scale_named_fonts(root: tk.Misc) -> None:
    size = font_size(BASE_SIZE)
    for name in _NAMED_FONTS:
        try:
            tkfont.nametofont(name, root=root).configure(
                family=BASE_FAMILY, size=size
            )
        except (tk.TclError, RuntimeError):
            continue
    try:
        tkfont.nametofont("TkFixedFont", root=root).configure(
            family=MONO_FAMILY, size=size
        )
    except (tk.TclError, RuntimeError):
        pass


def apply(root: tk.Misc, scale: float = 1.0) -> dict[str, str]:
    """루트 창에 스타일을 입히고 팔레트를 돌려준다.

    scale은 글꼴 크기 · 목록 행 높이 · 여백에 한꺼번에 걸리는 배율이다.
    이미 떠 있는 창에 다시 불러도 된다 — ttk 스타일은 인터프리터마다 한 벌뿐이라
    모든 창의 ttk 위젯이 그 자리에서 따라온다. (ttk가 아닌 위젯은
    restyle_widgets()가 맡는다.)
    """
    global SCALE, BASE_FONT, BOLD_FONT, TITLE_FONT, MONO_FONT

    SCALE = clamp_scale(scale)
    BASE_FONT = (BASE_FAMILY, font_size(BASE_SIZE))
    BOLD_FONT = (BASE_FAMILY, font_size(BASE_SIZE), "bold")
    TITLE_FONT = (BASE_FAMILY, font_size(TITLE_SIZE), "bold")
    MONO_FONT = (MONO_FAMILY, font_size(BASE_SIZE))

    _scale_named_fonts(root)

    style = ttk.Style(root)
    # clam은 색 지정이 실제로 먹는 몇 안 되는 기본 테마다. vista/xpnative는
    # 네이티브 그리기를 써서 background 지정이 대부분 무시된다.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    p = PALETTE
    root.configure(background=p["bg"])
    # ttk가 아닌 위젯이 **새로 만들어질 때** 쓸 색. 콤보박스를 펼친 목록, 대화
    # 상자 바탕처럼 스타일을 안 보는 곳이 밝은 기본색으로 튀지 않게 한다.
    for pattern, value in (
        ("*Toplevel.background", p["bg"]),
        ("*TCombobox*Listbox.background", p["surface"]),
        ("*TCombobox*Listbox.foreground", p["text"]),
        ("*TCombobox*Listbox.selectBackground", p["select"]),
        ("*TCombobox*Listbox.selectForeground", p["text"]),
        ("*Listbox.background", p["surface"]),
        ("*Listbox.foreground", p["text"]),
        ("*Text.background", p["surface"]),
        ("*Text.foreground", p["text"]),
        ("*Canvas.background", p["bg"]),
    ):
        root.option_add(pattern, value)

    style.configure(
        ".",
        background=p["bg"],
        foreground=p["text"],
        fieldbackground=p["surface"],
        bordercolor=p["border"],
        lightcolor=p["bg"],
        darkcolor=p["bg"],
        troughcolor=p["raised"],
        font=BASE_FONT,
    )

    # -- 컨테이너 -------------------------------------------------------
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Muted.TLabel", foreground=p["muted"])
    style.configure("Faint.TLabel", foreground=p["faint"])
    style.configure("Ok.TLabel", foreground=p["ok"])
    style.configure("Warn.TLabel", foreground=p["warn"])
    style.configure("Danger.TLabel", foreground=p["danger"])
    style.configure("Accent.TLabel", foreground=p["accent"])
    style.configure("Title.TLabel", font=TITLE_FONT, foreground=p["text"])
    style.configure("Heading.TLabel", font=BOLD_FONT, foreground=p["text"])

    style.configure(
        "TLabelframe",
        background=p["bg"],
        bordercolor=p["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=p["bg"],
        foreground=p["muted"],
        font=BOLD_FONT,
    )

    # -- 버튼 -----------------------------------------------------------
    style.configure(
        "TButton",
        background=p["raised"],
        foreground=p["text"],
        bordercolor=p["border"],
        focuscolor=p["accent_soft"],
        relief="flat",
        borderwidth=1,
        padding=pad(12, 6),
        anchor="center",
    )
    style.map(
        "TButton",
        background=[("pressed", p["pressed"]), ("active", p["hover"]),
                    ("disabled", p["bg"])],
        foreground=[("disabled", p["faint"])],
        bordercolor=[("active", p["accent"])],
    )

    style.configure(
        "Accent.TButton",
        background=p["accent"],
        foreground=p["on_accent"],
        bordercolor=p["accent"],
        padding=pad(14, 7),
    )
    style.map(
        "Accent.TButton",
        background=[("pressed", p["accent_hover"]), ("active", p["accent_hover"]),
                    ("disabled", p["raised"])],
        foreground=[("disabled", p["faint"])],
    )

    style.configure(
        "Danger.TButton",
        background=p["danger"],
        foreground=p["on_danger"],
        bordercolor=p["danger"],
        padding=pad(14, 7),
    )
    style.map(
        "Danger.TButton",
        background=[("pressed", p["danger_hover"]), ("active", p["danger_hover"]),
                    ("disabled", p["raised"])],
        foreground=[("disabled", p["faint"])],
    )

    # 목록 옆 작은 버튼 (+ 추가 / 복제 / 삭제)
    style.configure("Small.TButton", padding=pad(8, 4))
    style.configure(
        "SmallDanger.TButton", padding=pad(8, 4), foreground=p["danger"],
        background=p["raised"],
    )
    style.map(
        "SmallDanger.TButton",
        background=[("active", p["danger_soft"]), ("pressed", p["danger_soft2"])],
        foreground=[("disabled", p["faint"])],
    )

    # -- 입력 -----------------------------------------------------------
    for name in ("TEntry", "TCombobox", "TSpinbox"):
        style.configure(
            name,
            fieldbackground=p["surface"],
            background=p["surface"],
            foreground=p["text"],
            bordercolor=p["border"],
            arrowcolor=p["muted"],
            insertcolor=p["text"],
            padding=pad(6, 4),
            relief="flat",
            font=BASE_FONT,
        )
        style.map(
            name,
            bordercolor=[("focus", p["accent"])],
            fieldbackground=[("readonly", p["surface"]), ("disabled", p["bg"])],
            foreground=[("disabled", p["faint"])],
            arrowcolor=[("disabled", p["faint"])],
        )
    for name in ("TCheckbutton", "TRadiobutton"):
        # 네모 칸 바탕도 테마를 따른다. 안 그러면 어두운 테마에서 흰 칸만 튄다.
        # clam은 체크 표시를 indicatorforeground 로 indicatorbackground 위에 그린다.
        # 둘 다 흰색이면 **체크해도 안 보인다** — 기본 테마에서 실제로 그랬다.
        # 켜진 칸은 강조색으로 채우고 그 위에 강조색에 맞는 글자색으로 표시한다.
        style.configure(name, background=p["bg"], foreground=p["text"],
                        indicatorbackground=p["surface"],
                        indicatorforeground=p["text"])
        style.map(
            name,
            background=[("active", p["bg"])],
            indicatorbackground=[("disabled", p["bg"]),
                                 ("selected", p["accent"]),
                                 ("pressed", p["pressed"])],
            indicatorforeground=[("disabled", p["faint"]),
                                 ("selected", p["on_accent"])],
            foreground=[("disabled", p["faint"])],
        )

    # -- 목록 -----------------------------------------------------------
    style.configure(
        "Treeview",
        background=p["surface"],
        fieldbackground=p["surface"],
        foreground=p["text"],
        bordercolor=p["border"],
        borderwidth=1,
        relief="solid",
        rowheight=px(ROW_HEIGHT),
        font=BASE_FONT,
    )
    style.map(
        "Treeview",
        background=[("selected", p["select"])],
        foreground=[("selected", p["text"])],
    )
    style.configure(
        "Treeview.Heading",
        background=p["raised"],
        foreground=p["muted"],
        font=BOLD_FONT,
        relief="flat",
        padding=pad(6, 5),
        bordercolor=p["border"],
    )
    style.map("Treeview.Heading", background=[("active", p["hover"])])

    # -- 탭 -------------------------------------------------------------
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"],
                    tabmargins=pad(2, 6, 2, 0))
    style.configure(
        "TNotebook.Tab",
        background=p["raised"],
        foreground=p["muted"],
        bordercolor=p["border"],
        padding=pad(16, 8),
        font=BASE_FONT,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p["surface"]), ("active", p["hover"])],
        foreground=[("selected", p["accent"])],
        font=[("selected", BOLD_FONT)],
    )

    # -- 스크롤바 --------------------------------------------------------
    style.configure(
        "TScrollbar",
        background=p["raised"],
        troughcolor=p["bg"],
        bordercolor=p["bg"],
        arrowcolor=p["muted"],
        relief="flat",
    )
    style.map("TScrollbar", background=[("active", p["hover"])])

    style.configure("TSeparator", background=p["border"])

    # -- 분할선 (드래그해서 영역 비율을 바꾸는 손잡이) -----------------------
    # 기본 두께는 눈에도 잘 안 띄고 마우스로 잡기도 어렵다. 배율만큼 두껍게
    # 하고 테두리색을 줘서 "여기를 끌 수 있다"가 보이게 한다.
    # clam의 sash는 제 색을 따로 갖지 않고 판 사이에 난 틈으로 보인다.
    # 그래서 PanedWindow 배경을 테두리색으로 두면 그 틈이 옅은 선으로 드러난다.
    style.configure("TPanedwindow", background=p["border"])
    style.configure(
        "Sash",
        sashthickness=px(7),
        sashpad=0,
        gripcount=0,
        handlesize=px(7),
    )

    return p


def style_text(widget: tk.Misc, mono: bool = False) -> None:
    """tk.Text / tk.Listbox 처럼 ttk가 아닌 위젯의 색을 맞춘다.

    위젯마다 있는 옵션이 다르다 — 예를 들어 Listbox에는 커서 색(insertbackground)이
    없다. 그래서 그 위젯이 실제로 가진 옵션만 골라 적용한다.
    """
    _style_one(widget, mono)
    _STYLED.append((widget, mono))


def _style_one(widget: tk.Misc, mono: bool) -> None:
    p = PALETTE
    wanted = {
        "background": p["surface"],
        "foreground": p["text"],
        "insertbackground": p["text"],
        "selectbackground": p["select"],
        "selectforeground": p["text"],
        "highlightthickness": 1,
        "highlightbackground": p["border"],
        "highlightcolor": p["accent"],
        "borderwidth": 0,
        "relief": "flat",
        "font": MONO_FONT if mono else BASE_FONT,
    }
    try:
        supported = set(widget.keys())
    except tk.TclError:
        supported = set()
    widget.configure(**{k: v for k, v in wanted.items() if k in supported})


def restyle_widgets() -> None:
    """배율이나 테마를 바꾼 뒤, ttk가 아닌 위젯들의 글꼴과 색을 다시 맞춘다.

    ttk 위젯은 스타일 한 벌을 함께 보므로 apply()만으로 따라오지만,
    tk.Text · tk.Listbox 는 각자 font · 색 옵션을 들고 있어 여기서 직접 고친다.
    """
    alive: list[tuple[tk.Misc, bool]] = []
    for widget, mono in _STYLED:
        try:
            if not widget.winfo_exists():
                continue
            _style_one(widget, mono)
        except tk.TclError:
            continue
        alive.append((widget, mono))
    _STYLED[:] = alive
    trees: list[ttk.Treeview] = []
    for tree in _STRIPED:
        try:
            if not tree.winfo_exists():
                continue
            _paint_stripes(tree)
        except tk.TclError:
            continue
        trees.append(tree)
    _STRIPED[:] = trees


# ttk가 아닌 위젯에서 색을 담는 옵션들.
_COLOR_OPTIONS = (
    "background", "foreground", "highlightbackground", "highlightcolor",
    "insertbackground", "selectbackground", "selectforeground",
    "activebackground", "activeforeground", "disabledforeground",
)


def recolor(root: tk.Misc, old: dict[str, str], new: dict[str, str]) -> int:
    """이미 떠 있는 창들에서 **옛 팔레트 색을 새 팔레트 색으로** 바꿔 칠한다.

    ttk 위젯은 apply()로 따라오지만, 여러 화면이 만들 때 theme.PALETTE["bg"]
    같은 값을 **복사해** 넣어 둔다 (캔버스 바탕, 목록 줄 색, 대화 상자 바탕 …).
    그것들을 하나하나 찾아 고치는 대신, 창 전체를 돌며 "옛 팔레트에 있던 색"이면
    같은 역할의 새 색으로 갈아 끼운다. 바꾼 옵션 수를 돌려준다.

    캔버스에 그린 그림(선·사각형)은 건드리지 않는다 — 그런 것은 곧 다시 그려진다.
    """
    mapping: dict[str, str] = {}
    for key, value in old.items():
        if key in _STYLE_ONLY or key not in new:
            continue
        # 바뀌지 않은 역할도 넣는다. 빼 두면 같은 값을 쓰는 다른 역할이 그 자리를
        # 차지해, 그대로여야 할 색이 엉뚱하게 바뀐다.
        mapping.setdefault(value.lower(), new[key])
    mapping = {k: v for k, v in mapping.items() if k != v.lower()}
    if not mapping:
        return 0
    changed = 0
    # 루트 창은 apply()가 이미 새 배경으로 칠했다. 다시 옮기면 새 배경이 우연히
    # 옛 팔레트의 다른 색과 같을 때 한 번 더 바뀐다.
    try:
        stack = list(root.winfo_children())
    except tk.TclError:
        return 0
    while stack:
        widget = stack.pop()
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue
        if isinstance(widget, ttk.Treeview):
            changed += _recolor_tags(widget, mapping, tree=True)
            continue
        if isinstance(widget, ttk.Widget):
            continue
        updates = {}
        for option in _COLOR_OPTIONS:
            try:
                value = str(widget.cget(option)).lower()
            except (tk.TclError, ValueError):
                continue
            if value in mapping:
                updates[option] = mapping[value]
        if updates:
            try:
                widget.configure(**updates)
                changed += len(updates)
            except tk.TclError:
                pass
        if isinstance(widget, tk.Text):
            changed += _recolor_tags(widget, mapping, tree=False)
    return changed


def _recolor_tags(widget, mapping: dict[str, str], tree: bool) -> int:
    """목록(Treeview) 줄 태그와 글상자(Text) 태그의 색을 바꾼다."""
    try:
        if tree:
            names = widget.tk.splitlist(widget.tk.call(widget._w, "tag", "names"))
        else:
            names = widget.tag_names()
    except tk.TclError:
        return 0
    changed = 0
    for tag in names:
        for option in ("background", "foreground"):
            try:
                value = (widget.tag_configure(tag, option) if tree
                         else widget.tag_cget(tag, option))
            except tk.TclError:
                continue
            value = str(value or "").lower()
            if value in mapping:
                try:
                    widget.tag_configure(tag, **{option: mapping[value]})
                    changed += 1
                except tk.TclError:
                    pass
    return changed


# 줄무늬를 입힌 목록들. 테마를 바꾸면 **역할대로** 다시 칠한다 — 색 값만 보고
# 옮기면, 화이트처럼 창 배경과 목록 배경이 같은 흰색인 테마를 거칠 때 목록 줄이
# 창 배경색으로 잘못 옮겨 가 그 뒤로 계속 틀린다.
_STRIPED: list[ttk.Treeview] = []


def stripe(tree: ttk.Treeview) -> None:
    """줄무늬 태그를 등록한다. 채울 때 tag_for(index)를 함께 넘기면 된다."""
    _paint_stripes(tree)
    _STRIPED.append(tree)


def _paint_stripes(tree: ttk.Treeview) -> None:
    tree.tag_configure("odd", background=PALETTE["stripe"])
    tree.tag_configure("even", background=PALETTE["surface"])


def row_tag(index: int) -> str:
    return "odd" if index % 2 else "even"
