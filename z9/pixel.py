"""화면 픽셀 샘플링.

GetPixel을 점마다 호출하면 호출당 수백 마이크로초가 들고, 점들 사이에 화면이
갱신되면서 서로 다른 프레임을 섞어 읽는 문제가 생긴다. 그래서 필요한 점들을
감싸는 최소 사각형을 BitBlt로 **한 번에** 떠온 뒤 메모리에서 읽는다.
- 훨씬 빠르다 (점 개수와 무관하게 캡처 1회)
- 모든 점이 같은 프레임에서 나오므로 판정이 흔들리지 않는다
"""

from __future__ import annotations

import ctypes

from . import win32 as w

RGB = tuple[int, int, int]


class Frame:
    """BGRA 바이트 버퍼 + 원점 정보."""

    __slots__ = ("buf", "x", "y", "w", "h")

    def __init__(self, buf: bytes, x: int, y: int, width: int, height: int) -> None:
        self.buf = buf
        self.x = x
        self.y = y
        self.w = width
        self.h = height

    def at(self, sx: int, sy: int) -> RGB | None:
        """화면 절대좌표 (sx, sy)의 색. 프레임 밖이면 None."""
        dx = sx - self.x
        dy = sy - self.y
        if not (0 <= dx < self.w and 0 <= dy < self.h):
            return None
        idx = (dy * self.w + dx) * 4
        b, g, r = self.buf[idx], self.buf[idx + 1], self.buf[idx + 2]
        return (r, g, b)


class CaptureError(RuntimeError):
    pass


def capture_region(x: int, y: int, width: int, height: int) -> Frame:
    """화면의 지정 영역을 캡처한다 (절대좌표)."""
    if width <= 0 or height <= 0:
        raise CaptureError(f"잘못된 캡처 크기: {width}x{height}")

    screen_dc = w.user32.GetDC(None)
    if not screen_dc:
        raise CaptureError("화면 DC를 얻지 못했습니다.")
    mem_dc = None
    bitmap = None
    old = None
    try:
        mem_dc = w.gdi32.CreateCompatibleDC(screen_dc)
        if not mem_dc:
            raise CaptureError("메모리 DC 생성 실패")
        bitmap = w.gdi32.CreateCompatibleBitmap(screen_dc, width, height)
        if not bitmap:
            raise CaptureError("비트맵 생성 실패")
        old = w.gdi32.SelectObject(mem_dc, bitmap)

        if not w.gdi32.BitBlt(
            mem_dc, 0, 0, width, height, screen_dc, x, y, w.SRCCOPY | w.CAPTUREBLT
        ):
            raise CaptureError(
                "BitBlt 실패. 게임이 전체화면(독점) 모드면 창 모드로 바꿔야 합니다."
            )

        info = w.BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(w.BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # 음수 = top-down (첫 행이 맨 위)
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = w.BI_RGB

        buf = ctypes.create_string_buffer(width * height * 4)
        got = w.gdi32.GetDIBits(
            mem_dc, bitmap, 0, height, buf, ctypes.byref(info), w.DIB_RGB_COLORS
        )
        if got == 0:
            raise CaptureError("GetDIBits 실패")
        return Frame(buf.raw, x, y, width, height)
    finally:
        if mem_dc and old:
            w.gdi32.SelectObject(mem_dc, old)
        if bitmap:
            w.gdi32.DeleteObject(bitmap)
        if mem_dc:
            w.gdi32.DeleteDC(mem_dc)
        w.user32.ReleaseDC(None, screen_dc)


def get_pixel(x: int, y: int) -> RGB:
    """단일 픽셀 (절대좌표). 캡처 버튼처럼 1회성 용도에 쓴다."""
    return capture_region(x, y, 1, 1).at(x, y) or (0, 0, 0)


# 화면 읽기 1회의 고정 비용이 픽셀 수보다 훨씬 크다 (측정값: 크기와 무관하게
# 약 6ms, 화면 합성 주기에 동기화되는 것으로 보인다). 그래서 점이 몇 개든 캡처를
# 1회로 묶는 쪽이 거의 항상 빠르다 — 점 3개를 따로 읽으면 18ms, 묶으면 6ms.
# 다만 영역이 아주 커지면 전송량이 비용을 지배하기 시작하므로 그때만 나눠 읽는다.
_AREA_PER_EXTRA_CAPTURE = 400_000


def sample_points(points: list[tuple[int, int]]) -> list[RGB]:
    """여러 화면 좌표의 색을 같은 프레임에서 읽는다."""
    if not points:
        return []
    if len(points) == 1:
        px, py = points[0]
        return [capture_region(px, py, 1, 1).at(px, py) or (0, 0, 0)]

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, y0 = min(xs), min(ys)
    width = max(xs) - x0 + 1
    height = max(ys) - y0 + 1

    if width * height > len(points) * _AREA_PER_EXTRA_CAPTURE:
        # 점들이 화면 양 끝에 흩어진 경우. 프레임 일관성은 포기하고 개별로 읽는다.
        return [get_pixel(px, py) for px, py in points]

    frame = capture_region(x0, y0, width, height)
    return [frame.at(px, py) or (0, 0, 0) for px, py in points]


def color_distance(a: RGB, b: RGB) -> int:
    """채널별 최대 차이. 사람 눈보다 '색이 바뀌었나' 판정에 안정적이다."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def color_matches(actual: RGB, expected: RGB, tolerance: int) -> bool:
    return color_distance(actual, expected) <= tolerance


def to_hex(color: RGB) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def from_hex(text: str) -> RGB | None:
    text = text.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None
