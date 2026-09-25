"""윈도 글꼴을 직접 그려서 **숫자 모양을 떠 오는** 곳.

게임 상태창 글씨가 늘 옛날 점글씨(digits.BUILTIN_5X7)인 것은 아니다. 굴림·돋움
같은 보통 윈도 글꼴로 그려진 곳도 있고, 그러면 크기도 게임마다 다르다. 사람에게
숫자 열 개를 익히게 하는 대신, **프로그램이 흔한 글꼴들을 직접 그려 보고** 화면에서
잘라 온 모양과 가장 잘 맞는 것을 고른다.

한 글자씩 따로 보지 않고 **줄 전체로 견주는** 것이 요령이다. 글꼴과 크기가 맞으면
그 줄의 숫자가 죄다 딱 맞고, 틀리면 죄다 어긋난다. 그래서 고르기가 쉽다.

여기서 그린 모양은 크기(글자 높이)별로 담아 두고 다시 쓴다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import pixel

# 훑어볼 글꼴. 게임 UI에 흔한 것들부터.
FAMILIES = (
    "굴림", "굴림체", "돋움", "돋움체", "바탕", "바탕체", "맑은 고딕",
    "Tahoma", "Arial", "Verdana", "Segoe UI", "MS Sans Serif", "Small Fonts",
    "Consolas", "Courier New",
)

# 떠 올 글쇠. digits.LEARNABLE 과 같은 것들.
CHARS = "0123456789/,.:%"

# 그릴 때 볼 글자 크기(em). 상태창 글씨는 이 언저리다.
EM_RANGE = range(8, 25)

_HANGEUL_CHARSET = 129
_NONANTIALIASED = 3
_ANTIALIASED = 4
_TRANSPARENT = 1
_WHITENESS = 0x00FF0062

_CANVAS_W = 460
_CANVAS_H = 64

try:
    _gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    _user = ctypes.WinDLL("user32", use_last_error=True)
except OSError:  # 윈도가 아니면 이 기능만 조용히 꺼진다
    _gdi = _user = None


class _Header(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _Info(ctypes.Structure):
    _fields_ = [("bmiHeader", _Header), ("bmiColors", wintypes.DWORD * 3)]


def draw(text: str, family: str, em: int, bold: bool = False,
         smooth: bool = False) -> pixel.Frame | None:
    """글자를 흰 바탕에 검게 그려서 그림 한 장으로. 못 그리면 None."""
    if _gdi is None:
        return None
    screen = _user.GetDC(0)
    dc = font = bmp = None
    try:
        dc = _gdi.CreateCompatibleDC(screen)
        if not dc:
            return None
        info = _Info()
        info.bmiHeader.biSize = ctypes.sizeof(_Header)
        info.bmiHeader.biWidth = _CANVAS_W
        info.bmiHeader.biHeight = -_CANVAS_H  # 위에서 아래로
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        bits = ctypes.c_void_p()
        bmp = _gdi.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits),
                                    None, 0)
        if not bmp:
            return None
        _gdi.SelectObject(dc, bmp)
        _gdi.PatBlt(dc, 0, 0, _CANVAS_W, _CANVAS_H, _WHITENESS)
        font = _gdi.CreateFontW(-em, 0, 0, 0, 700 if bold else 400, 0, 0, 0,
                                _HANGEUL_CHARSET, 0, 0,
                                _ANTIALIASED if smooth else _NONANTIALIASED,
                                0, family)
        if not font:
            return None
        _gdi.SelectObject(dc, font)
        _gdi.SetBkMode(dc, _TRANSPARENT)
        _gdi.SetTextColor(dc, 0x000000)
        _gdi.TextOutW(dc, 6, 6, text, len(text))
        buf = ctypes.string_at(bits, _CANVAS_W * _CANVAS_H * 4)
        return pixel.Frame(buf, 0, 0, _CANVAS_W, _CANVAS_H)
    except OSError:
        return None
    finally:
        if font:
            _gdi.DeleteObject(font)
        if bmp:
            _gdi.DeleteObject(bmp)
        if dc:
            _gdi.DeleteDC(dc)
        _user.ReleaseDC(0, screen)


def _shapes(family: str, em: int, bold: bool, smooth: bool):
    """이 글꼴·크기의 글쇠별 모양. 못 뜨면 None.

    글자를 띄어서 그린다 — 붙여 그리면 '/' 가 옆 숫자에 닿아 한 덩어리가 된다.
    """
    from . import digits

    frame = draw("  ".join(CHARS), family, em, bold, smooth)
    if frame is None:
        return None
    glyphs = digits.segment(frame, dark=True, threshold=128)
    if len(glyphs) != len(CHARS):
        return None
    if any(g.w <= 0 or g.h <= 0 for g in glyphs):
        return None
    return dict(zip(CHARS, glyphs))


def _digit_height(shapes) -> int:
    tall = sorted(shapes[c].h for c in "0123456789")
    return tall[len(tall) // 2]


_BOOK: dict[int, list] = {}


def _height_at(family: str, em: int) -> int:
    """이 글꼴·크기로 그리면 숫자 키가 몇 칸인가. 못 그리면 0."""
    from . import digits

    frame = draw("0", family, em)
    if frame is None:
        return 0
    glyphs = digits.segment(frame, dark=True, threshold=128)
    return glyphs[0].h if len(glyphs) == 1 else 0


def _em_for(family: str, height: int) -> int:
    """숫자 키가 height 칸이 되는 글자 크기(em)를 반씩 좁혀 찾는다. 없으면 0.

    크기를 하나씩 다 그려 보면 글꼴마다 열몇 번씩 그려야 한다. 키는 크기를 따라
    커지기만 하므로 반씩 좁히면 네댓 번이면 된다 — 첫 읽기가 눈에 띄게 빨라진다.
    """
    low, high = EM_RANGE.start, EM_RANGE.stop - 1
    while low <= high:
        mid = (low + high) // 2
        got = _height_at(family, mid)
        if got == 0:
            return 0
        if got == height:
            return mid
        if got < height:
            low = mid + 1
        else:
            high = mid - 1
    return 0


def build_for(height: int) -> list:
    """이 키의 숫자를 읽을 글꼴 모양들. 한 번 만들어 두고 다시 쓴다."""
    if height in _BOOK:
        return _BOOK[height]
    from . import digits

    made: list = []
    for family in FAMILIES:
        em = _em_for(family, height)
        if not em:
            continue
        for step in (0, -1, 1):
            for bold in (False, True):
                for smooth in (False, True):
                    shapes = _shapes(family, em + step, bold, smooth)
                    if not shapes or _digit_height(shapes) != height:
                        continue
                    font = digits.Font(
                        f"{family} {em + step}px" + (" 굵게" if bold else "")
                        + (" 부드럽게" if smooth else "")
                    )
                    font.shapes.update(shapes)
                    made.append(font)
    _BOOK[height] = made
    return made


def candidates(height: int) -> list:
    """이 정도 키의 글자를 읽을 만한 글꼴들. 한 칸 차이까지 함께 본다."""
    out = []
    for h in (height, height - 1, height + 1):
        if h > 0:
            out.extend(build_for(h))
    return out
