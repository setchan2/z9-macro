"""숫자를 못 읽었을 때 **무엇을 보고 있었는지** 그림 한 장으로 남긴다.

글자가 안 읽힌다는 말만으로는 무엇이 문제인지 알 수 없다. 테두리가 섞였는지,
글씨가 생각보다 큰지, 글자 색을 거꾸로 봤는지는 눈으로 보면 바로 안다. 그래서
읽기에 실패하면 찍은 자리와 잘라 낸 글자를 그대로 그림으로 남겨 둔다.

    위   : 찍은 자리 그대로 (색 그대로)
    아래 : 잘라 낸 글자들 (검정=글자로 본 칸, 사이 빨간 줄)
"""

from __future__ import annotations

import time
from pathlib import Path

from .png import PngError, write_rgb

DIRNAME = "숫자읽기"
PLATE_DIRNAME = "벌목보기"
ZOOM = 4

_GAP = b"\xd0\xd0\xd0"        # 빈 자리
_INK = b"\x10\x10\x10"        # 글자로 본 칸
_PAPER = b"\xff\xff\xff"      # 그 밖
_EDGE = b"\xc0\x60\x60"       # 글자와 글자 사이


def folder() -> Path:
    from . import storage

    out = storage.DATA_DIR / DIRNAME
    out.mkdir(parents=True, exist_ok=True)
    return out


def save(reading, note: str = "") -> Path | None:
    """읽던 자리를 그림으로. 저장한 경로, 못 남기면 None."""
    frame = getattr(reading, "frame", None)
    if frame is None:
        return None
    try:
        rows = _rows(frame, getattr(reading, "glyphs", []))
        if not rows:
            return None
        width = max(len(row) for row in rows) // 3
        body = b"".join(row.ljust(width * 3, b"\xd0") for row in rows)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        tag = f"-{note}" if note else ""
        path = folder() / f"숫자{tag}-{stamp}.png"
        write_rgb(path, width, len(rows), body)
        return path
    except (PngError, OSError, ValueError):
        return None


def _rows(frame, glyphs) -> list[bytes]:
    rows: list[bytes] = []
    for y in range(frame.h):
        line = bytearray()
        for x in range(frame.w):
            i = (y * frame.w + x) * 4  # BGRA
            line += bytes((frame.buf[i + 2], frame.buf[i + 1], frame.buf[i])) * ZOOM
        rows.extend([bytes(line)] * ZOOM)

    rows.extend([b""] * (ZOOM * 2))  # 사이 띄우기

    if glyphs:
        tall = max(g.h for g in glyphs)
        for y in range(tall):
            line = bytearray()
            for glyph in glyphs:
                for x in range(glyph.w):
                    on = y < glyph.h and glyph.bits[y * glyph.w + x]
                    line += (_INK if on else _PAPER) * ZOOM
                line += _EDGE * ZOOM
            rows.extend([bytes(line)] * ZOOM)
    return rows


def to_rgb(buf, width: int, height: int, step: int = 1) -> tuple[bytes, int, int]:
    """BGRA 캡처를 PNG용 RGB로. step 간격으로 솎아 줄인다. (RGB, 폭, 높이)

    칸마다 파이썬으로 옮기지 않고 줄마다 채널 슬라이스를 끼워 넣는다(C 수준).
    """
    step = max(1, step)
    gw = len(range(0, width, step))
    gh = len(range(0, height, step))
    stride = width * 4
    bstep = 4 * step
    view = memoryview(buf)
    out = bytearray(gw * gh * 3)
    row_len = gw * 3
    for gy, y in enumerate(range(0, height, step)):
        row = view[y * stride:(y + 1) * stride]
        line = bytearray(row_len)
        line[0::3] = bytes(row[2::bstep])[:gw]
        line[1::3] = bytes(row[1::bstep])[:gw]
        line[2::3] = bytes(row[0::bstep])[:gw]
        out[gy * row_len:(gy + 1) * row_len] = line
    return bytes(out), gw, gh


def save_plates(frame, plates, note: str = "벌목", step: int = 2) -> Path | None:
    """찍은 화면에 **찾아낸 이름표마다 네모**를 쳐서 남긴다. 저장한 경로.

    벌목이 엉뚱한 것을 나무로 보고 있는지는 이 그림 한 장이면 바로 안다.
    """
    try:
        rgb, width, height = to_rgb(frame.buf, frame.w, frame.h, step)
        canvas = bytearray(rgb)
        for plate in plates:
            _box(canvas, width, height,
                 plate.x // step, plate.y // step,
                 (plate.x + plate.w) // step, (plate.y + plate.h) // step)
        from . import storage

        out = storage.DATA_DIR / PLATE_DIRNAME
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{note}-{time.strftime('%Y%m%d-%H%M%S')}.png"
        write_rgb(path, width, height, bytes(canvas))
        return path
    except (PngError, OSError, ValueError, AttributeError):
        return None


_MARK = bytes((255, 48, 48))  # 이름표에 두르는 빨간 테두리


def _box(canvas: bytearray, width: int, height: int, x0: int, y0: int,
         x1: int, y1: int, color: bytes = _MARK) -> None:
    """네모 테두리 한 줄."""
    x0, x1 = max(0, x0 - 1), min(width - 1, x1 + 1)
    y0, y1 = max(0, y0 - 1), min(height - 1, y1 + 1)
    if x1 <= x0 or y1 <= y0:
        return
    for x in range(x0, x1 + 1):
        for y in (y0, y1):
            i = (y * width + x) * 3
            canvas[i:i + 3] = color
    for y in range(y0, y1 + 1):
        for x in (x0, x1):
            i = (y * width + x) * 3
            canvas[i:i + 3] = color
