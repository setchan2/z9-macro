"""화면에 적힌 숫자를 읽는다 (비트맵 글꼴 맞추기).

피로도처럼 **숫자 자체가 조건인 것**들이 있다. "피로도: 10502 / 540000"에서
앞의 값이 뒤의 값에 닿으면 더는 얻는 게 없으니 다른 일을 해야 한다. 색이나
그림으로는 이걸 알 수 없다 — 숫자를 실제로 읽어야 한다.

**왜 일반적인 글자 인식이 필요 없나** — 게임 UI의 숫자는 사진이 아니라 비트맵
글꼴이다. 같은 숫자는 언제나 **픽셀 하나까지 똑같이** 그려진다. 그래서 숫자
모양 열 개를 한 번 익혀 두면 그 뒤로는 맞춰 보기만 하면 된다. 흐릿함도 기울기도
없으니 맞으면 완전히 맞고 아니면 확연히 다르다.

읽는 순서는 이렇다.

1. **이진화** — 글자색인지 아닌지만 남긴다 (어두운 글자 / 밝은 글자)
2. **글자 나누기** — 잉크가 있는 세로줄을 이어 붙여 글자 상자로 끊는다
3. **맞추기** — 상자마다 익혀 둔 모양과 대 보고 가장 닮은 것을 고른다

익히기는 사람이 한 번 거든다. 잘라낸 자리에 실제로 뭐라고 적혀 있는지 타이핑해
주면, 글자 상자와 글쇠를 순서대로 짝지어 저장한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import pixel
from .png import PngError, read_rgb, write_rgb

# 글꼴을 두는 폴더 이름 (보관함 폴더 아래). 세트마다 하위 폴더 하나.
FONT_DIRNAME = "숫자글꼴"

# 익힐 수 있는 글쇠. 숫자와 구분자만 있으면 된다.
LEARNABLE = "0123456789/,.:%"

# 파일 이름으로 쓸 수 없는 글쇠는 이름을 바꿔 저장한다.
_FILE_NAMES = {
    "/": "slash",
    ",": "comma",
    ".": "dot",
    ":": "colon",
    "%": "percent",
}
_CHAR_BY_FILE = {v: k for k, v in _FILE_NAMES.items()}

# 맞춤 판정: 어긋난 칸이 이 비율을 넘으면 다른 글자로 본다.
MAX_MISMATCH = 0.14


# 익히지 않고 바로 쓰는 숫자 모양 (5×7 점글씨).
#
# 게임 상태창의 숫자는 옛날 점글씨 그대로다. 실제로 익혀 둔 피로도 글꼴의
# 0 1 2 4 5 6 8 과 '/' 이 아래 모양과 **한 칸도 다르지 않게** 같았다. 그러니
# 사용자가 숫자를 하나하나 익힐 까닭이 없다 — 프로그램이 그냥 알고 있으면 된다.
#
# 3 · 7 · 9 는 익혀 둔 것이 없어 맞춰 볼 수 없었다. 점글씨마다 조금씩 다르게
# 쓰는 글자들이라, 흔한 모양을 함께 넣어 두고 그중 맞는 것을 쓴다.
AUTO_FONT = "자동"

BUILTIN_5X7: dict[str, tuple[str, ...]] = {
    "0": (".###.|#...#|#..##|#.#.#|##..#|#...#|.###.",),
    "1": ("..#..|.##..|..#..|..#..|..#..|..#..|.###.",
          "..#..|.##..|..#..|..#..|..#..|..#..|..#..",),
    "2": (".###.|#...#|....#|...#.|..#..|.#...|#####",),
    "3": ("#####|...#.|..#..|...#.|....#|#...#|.###.",
          ".###.|#...#|....#|..##.|....#|#...#|.###.",
          "####.|....#|....#|.###.|....#|....#|####.",),
    "4": ("...#.|..##.|.#.#.|#..#.|#####|...#.|...#.",
          "....#|...##|..#.#|.#..#|#####|....#|....#",),
    "5": ("#####|#....|####.|....#|....#|#...#|.###.",),
    "6": ("..##.|.#...|#....|####.|#...#|#...#|.###.",
          ".###.|#....|#....|####.|#...#|#...#|.###.",),
    "7": ("#####|....#|...#.|..#..|.#...|.#...|.#...",
          "#####|....#|...#.|..#..|..#..|..#..|..#..",
          "#####|#...#|....#|...#.|..#..|.#...|#....",),
    "8": (".###.|#...#|#...#|.###.|#...#|#...#|.###.",),
    "9": (".###.|#...#|#...#|.####|....#|...#.|.##..",
          ".###.|#...#|#...#|.####|....#|#...#|.###.",
          ".###.|#...#|#...#|.####|....#|....#|.###.",),
    "/": ("....#|....#|...#.|..#..|.#...|#....|#....",),
    ",": (".....|.....|.....|.....|..##.|..#..|.#...",),
    ".": (".....|.....|.....|.....|.....|.##..|.##..",),
    ":": (".....|.##..|.##..|.....|.##..|.##..|.....",),
    "%": ("##..#|##..#|...#.|..#..|.#...|#..##|#..##",),
}


def from_pattern(pattern: str) -> Glyph:
    """'.###.|#...#|…' 을 글자 상자로. 빈 가장자리는 잘라 낸다 — 화면에서
    잘라 온 글자도 바짝 잘려 오므로 그래야 짝이 맞는다."""
    rows = pattern.split("|")
    w = max(len(r) for r in rows)
    ink = bytearray(w * len(rows))
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            if cell != ".":
                ink[y * w + x] = 1
    cols = [x for x in range(w) if any(ink[y * w + x] for y in range(len(rows)))]
    if not cols:
        return Glyph(0, 0, b"")
    return _crop(ink, w, cols[0], cols[-1] + 1)


def resample(glyph: Glyph, w: int, h: int) -> Glyph:
    """글자 상자를 다른 크기로 다시 그린다 (칸을 나눠 절반 넘게 차면 잉크).

    같은 글씨라도 화면 배율이 2배면 상자도 2배로 잘려 온다. 크기를 맞춰 놓고
    견주면 배율이 달라도 같은 글자로 알아본다.
    """
    if w <= 0 or h <= 0 or glyph.w <= 0 or glyph.h <= 0:
        return Glyph(0, 0, b"")
    bits = bytearray(w * h)
    for y in range(h):
        y0, y1 = y * glyph.h // h, max(y * glyph.h // h + 1, (y + 1) * glyph.h // h)
        for x in range(w):
            x0, x1 = x * glyph.w // w, max(x * glyph.w // w + 1, (x + 1) * glyph.w // w)
            ink = total = 0
            for gy in range(y0, y1):
                for gx in range(x0, x1):
                    ink += glyph.bits[gy * glyph.w + gx]
                    total += 1
            if total and ink * 2 >= total:
                bits[y * w + x] = 1
    return Glyph(w, h, bytes(bits))


def font_root(library_root: Path) -> Path:
    return Path(library_root) / FONT_DIRNAME


def font_dir(library_root: Path, name: str) -> Path:
    return font_root(library_root) / (name or "기본")


def list_fonts(library_root: Path) -> list[str]:
    root = font_root(library_root)
    try:
        return sorted(p.name for p in root.iterdir() if p.is_dir())
    except OSError:
        return []


def _file_for(char: str) -> str:
    return _FILE_NAMES.get(char, char) + ".png"


def _char_for(stem: str) -> str:
    return _CHAR_BY_FILE.get(stem, stem)


# --------------------------------------------------------------------------
# 이진화된 글자
# --------------------------------------------------------------------------
class Glyph:
    """글자 하나. 잉크가 있는 칸만 1인 납작한 바이트열."""

    __slots__ = ("w", "h", "bits", "x")

    def __init__(self, w: int, h: int, bits: bytes, x: int = 0) -> None:
        self.w = w
        self.h = h
        self.bits = bits
        # 잘라낸 자리의 왼쪽 끝(읽은 영역 기준). 글자 사이 간격으로 낱말을 나눌 때 쓴다.
        self.x = x

    @property
    def ink(self) -> int:
        return sum(self.bits)

    def at(self, x: int, y: int) -> int:
        if 0 <= x < self.w and 0 <= y < self.h:
            return self.bits[y * self.w + x]
        return 0

    def to_png(self, path: Path) -> None:
        """잉크는 검게, 나머지는 희게 저장한다. 탐색기에서 바로 보인다."""
        rgb = bytearray(self.w * self.h * 3)
        for i, on in enumerate(self.bits):
            value = 0 if on else 255
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = value
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        write_rgb(path, self.w, self.h, bytes(rgb))

    @classmethod
    def from_png(cls, path: Path) -> "Glyph | None":
        try:
            w, h, rgb = read_rgb(path)
        except (PngError, OSError):
            return None
        bits = bytearray(w * h)
        for i in range(w * h):
            bits[i] = 1 if rgb[i * 3] < 128 else 0
        return cls(w, h, bytes(bits))

    def mismatch(self, other: "Glyph") -> float:
        """서로 다른 칸의 비율. 0이면 완전히 같다.

        크기가 다르면 큰 쪽에 맞춰 비교하고, 남는 칸은 빈 칸으로 본다. 같은
        글꼴이라도 잘라낸 자리가 한 칸 어긋날 수 있어 ±1칸까지 밀어 보고 그중
        가장 잘 맞은 값을 쓴다.
        """
        best = 1.0
        w = max(self.w, other.w)
        h = max(self.h, other.h)
        total = w * h
        if total == 0:
            return 1.0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                wrong = 0
                for y in range(h):
                    for x in range(w):
                        if self.at(x, y) != other.at(x - dx, y - dy):
                            wrong += 1
                    if wrong / total >= best:
                        break
                score = wrong / total
                if score < best:
                    best = score
                    if best == 0.0:
                        return 0.0
        return best


# --------------------------------------------------------------------------
# 화면 → 글자 상자
# --------------------------------------------------------------------------
def _is_ink(r: int, g: int, b: int, dark: bool, threshold: int) -> bool:
    """이 픽셀이 글자인가.

    밝기 하나로만 가른다. 게임 UI의 글자는 배경과 밝기가 확실히 갈리게 그려지고,
    색조까지 따지면 안티에일리어싱 가장자리에서 흔들린다.
    """
    level = (r * 299 + g * 587 + b * 114) // 1000
    return level < threshold if dark else level > threshold


def segment(
    frame: pixel.Frame,
    dark: bool = True,
    threshold: int = 128,
    min_width: int = 1,
) -> list[Glyph]:
    """캡처한 조각을 글자 상자들로 끊는다 (왼쪽부터 순서대로).

    글자 사이는 잉크가 하나도 없는 세로줄로 끊긴다. 비트맵 글꼴은 글자끼리
    붙지 않게 최소 한 칸을 띄우므로 이것만으로 충분히 갈린다.
    """
    w, h = frame.w, frame.h
    buf = frame.buf

    ink = bytearray(w * h)
    for y in range(h):
        row = y * w
        for x in range(w):
            i = (row + x) * 4  # BGRA
            if _is_ink(buf[i + 2], buf[i + 1], buf[i], dark, threshold):
                ink[row + x] = 1

    left, right, top, bottom = _trim_frame(ink, w, h)
    if right - left < 1 or bottom - top < 1:
        return []

    _drop_blobs(ink, w, h)
    left, right, top, bottom = _trim_frame(ink, w, h)
    if right - left < 1 or bottom - top < 1:
        return []

    # 잉크가 있는 세로줄 찾기
    filled = [
        any(ink[y * w + x] for y in range(top, bottom)) for x in range(left, right)
    ]

    glyphs: list[Glyph] = []
    start = None
    for index in range(len(filled) + 1):
        has = filled[index] if index < len(filled) else False
        if has and start is None:
            start = index
        elif not has and start is not None:
            if index - start >= min_width:
                glyphs.append(
                    _crop(ink, w, left + start, left + index, top, bottom)
                )
            start = None
    return glyphs


def _lumps(ink: bytearray, w: int, h: int) -> list[tuple[list, list]]:
    """이어 붙은 잉크 덩어리들. 각 덩어리는 ([왼,위,오른,아래,칸수], 줄토막들).

    줄마다 이어진 토막을 만들고, 윗줄 토막과 닿으면 같은 덩어리로 묶는다.
    칸 하나하나를 헤집는 것보다 훨씬 빠르다 — 큰 영역에서도 부담이 없다.
    """
    parent: list[int] = []

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    runs: list[tuple[int, int, int]] = []  # (y, x0, x1)
    prev: list[int] = []
    for y in range(h):
        base = y * w
        line: list[int] = []
        x = 0
        while x < w:
            if not ink[base + x]:
                x += 1
                continue
            start = x
            while x < w and ink[base + x]:
                x += 1
            here = len(runs)
            runs.append((y, start, x))
            parent.append(here)
            line.append(here)
            for other in prev:  # 대각선으로 닿아도 한 덩어리로 본다
                _oy, ox0, ox1 = runs[other]
                if ox0 <= x and start <= ox1:
                    join(here, other)
        prev = line

    lumps: dict[int, tuple[list, list]] = {}
    for index, (y, x0, x1) in enumerate(runs):
        box, mine = lumps.setdefault(find(index), ([x0, y, x1, y + 1, 0], []))
        box[0] = min(box[0], x0)
        box[1] = min(box[1], y)
        box[2] = max(box[2], x1)
        box[3] = max(box[3], y + 1)
        box[4] += x1 - x0
        mine.append(index)
    return [(box, [runs[i] for i in mine]) for box, mine in lumps.values()]


def _drop_blobs(ink: bytearray, w: int, h: int) -> int:
    """글자라고 볼 수 없는 **큰 덩어리**를 지운다. 지운 개수를 돌려준다.

    게임 말풍선에는 까만 테두리나 띠가 함께 찍힌다. 그 띠는 사방을 두르지 않아
    가장자리 벗기기로는 안 없어지고, 세로줄마다 잉크를 만들어 **글자 사이의 빈
    줄을 메워 버린다.** 그래서 한 줄이 통째로 한 글자가 되고, 어떤 밝기 기준을
    써도 안 나뉜다 — 실제로 피로도 말풍선이 그랬다.

    글자들은 키가 고만고만하다. 그 가운뎃값보다 유난히 크거나 긴 덩어리만
    골라 지우면 글자는 그대로 두고 테두리만 없앨 수 있다.
    """
    lumps = _lumps(ink, w, h)
    if len(lumps) < 3:  # 지울 것을 고를 만큼 견줄 것이 없다
        return 0
    tall = sorted(box[3] - box[1] for box, _runs in lumps)
    middle = tall[len(tall) // 2]
    if middle < 3:
        return 0
    gone = 0
    for box, runs in lumps:
        x0, y0, x1, y1, cells = box
        bw, bh = x1 - x0, y1 - y0
        wide = bw > max(6, middle * 5)
        tall = bh > max(3, middle * 2.5)
        if not (wide or tall):
            continue
        if cells < middle * middle:  # 가늘고 긴 획 하나는 글자의 일부일 수 있다
            continue
        # 옆으로 긴 덩어리는 **긴 토막만** 지운다. 밑줄이나 띠가 글자에 닿아
        # 한 덩어리가 됐을 수 있는데, 통째로 지우면 글자까지 사라진다.
        keep = max(6, middle * 3) if wide and not tall else 0
        for y, rx0, rx1 in runs:
            if keep and rx1 - rx0 <= keep:
                continue
            base = y * w
            for x in range(rx0, rx1):
                ink[base + x] = 0
        gone += 1
    return gone


def _trim_frame(ink: bytearray, w: int, h: int) -> tuple[int, int, int, int]:
    """가장자리에 둘린 테두리를 벗겨 낸다. (left, right, top, bottom).

    게임 UI의 글상자에는 검은 테두리가 둘려 있는 경우가 많다. 그 테두리는 사방을
    빙 두르므로 **모든 세로줄에 잉크가 있게** 만들고, 그러면 글자 사이의 빈 줄이
    사라져 전체가 한 글자로 잡힌다. 실제로 그렇게 잘려서 "1개를 잘랐습니다"가 됐다.

    가장자리부터 **꽉 찬 줄**(그 줄 전체가 잉크)을 하나씩 벗긴다. 글자는 위아래로
    빈 곳이 있어서 꽉 차지 않으므로 글자까지 깎일 일은 없다.
    """
    left, right, top, bottom = 0, w, 0, h

    def full_col(x: int) -> bool:
        return all(ink[y * w + x] for y in range(top, bottom))

    def full_row(y: int) -> bool:
        row = y * w
        return all(ink[row + x] for x in range(left, right))

    changed = True
    while changed and right - left > 2 and bottom - top > 2:
        changed = False
        if full_col(left):
            left += 1
            changed = True
        if right - left > 2 and full_col(right - 1):
            right -= 1
            changed = True
        if full_row(top):
            top += 1
            changed = True
        if bottom - top > 2 and full_row(bottom - 1):
            bottom -= 1
            changed = True
    return (left, right, top, bottom)


def _crop(
    ink: bytearray, stride: int, x0: int, x1: int, y0: int = 0, y1: int | None = None
) -> Glyph:
    """글자 상자를 위아래로도 바짝 잘라낸다.

    세로로 바짝 자르지 않으면 같은 '1'이라도 잘라낸 자리에 따라 위쪽 여백이
    달라져 다른 모양이 된다. 위아래를 붙여 두면 그 차이가 사라진다.
    """
    if y1 is None:
        y1 = len(ink) // stride
    top, bottom = y1, -1
    for y in range(y0, y1):
        row = y * stride
        if any(ink[row + x] for x in range(x0, x1)):
            if y < top:
                top = y
            bottom = y
    if bottom < 0:
        return Glyph(0, 0, b"", x0)
    gw = x1 - x0
    gh = bottom - top + 1
    bits = bytearray(gw * gh)
    for y in range(gh):
        src = (top + y) * stride
        dst = y * gw
        for x in range(gw):
            bits[dst + x] = ink[src + x0 + x]
    return Glyph(gw, gh, bytes(bits), x0)


# --------------------------------------------------------------------------
# 자동 맞추기 — 글자 색과 밝기 기준을 대신 찾아 준다
# --------------------------------------------------------------------------
# 훑어볼 밝기 기준. 촘촘히 볼 이유가 없다 — 게임 UI는 글자와 배경의 밝기가
# 확실히 갈리게 그려지므로, 그 사이 어디를 찍어도 결과가 같다.
_THRESHOLDS = (48, 72, 96, 128, 160, 190, 215)


def quality(glyphs: list[Glyph], width: int, height: int) -> float:
    """이 잘림이 '글자 한 줄'처럼 보이는 정도. 클수록 그럴듯하다. 0이면 아니다.

    무엇을 보는가.
      · 두 개 미만이면 글자가 아니다 (배경이 통째로 잡힌 것)
      · 한 글자가 영역의 절반을 넘으면 덩어리다
      · 한 줄에 적힌 글자는 **높이가 고르다**
      · 1~2픽셀짜리는 잡티다
    """
    real = [g for g in glyphs if g.h >= 3 and g.w >= 2]
    if len(real) < 2:
        return 0.0
    if max(g.w for g in real) > width * 0.5:
        return 0.0
    heights = [g.h for g in real]
    spread = max(heights) - min(heights)
    # 높이가 들쭉날쭉하면 글자가 아니라 잡티일 가능성이 크다.
    if spread > height * 0.8:
        return 0.0
    noise = len(glyphs) - len(real)
    return len(real) - spread * 0.5 - noise * 0.5


def autotune(frame: pixel.Frame) -> tuple[bool, int, list[Glyph], float]:
    """글자 색과 밝기 기준을 대신 찾는다. (어두운 글자인가, 기준, 잘린 글자, 점수).

    사람이 고르게 두면 반대로 고르기 쉽고, 그러면 배경이 통째로 한 글자로 잡혀
    "1개를 잘랐습니다"가 된다. 어차피 경우의 수가 열몇 개뿐이니 전부 해 보고
    가장 글자 한 줄처럼 보이는 것을 고르는 편이 낫다.
    """
    best = (True, 128, [], 0.0)
    for dark in (True, False):
        for threshold in _THRESHOLDS:
            glyphs = segment(frame, dark=dark, threshold=threshold)
            score = quality(glyphs, frame.w, frame.h)
            if score > best[3]:
                best = (dark, threshold, glyphs, score)
    return best


# --------------------------------------------------------------------------
# 글꼴 (익혀 둔 글자 모음)
# --------------------------------------------------------------------------
class Font:
    """글쇠 → 모양. 한 번 익혀 두면 계속 쓴다."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self.shapes: dict[str, Glyph] = {}

    def __bool__(self) -> bool:
        return bool(self.shapes)

    @property
    def digits_known(self) -> str:
        return "".join(c for c in "0123456789" if c in self.shapes)

    @property
    def digits_missing(self) -> str:
        return "".join(c for c in "0123456789" if c not in self.shapes)

    def learn(self, char: str, glyph: Glyph) -> None:
        if char in LEARNABLE and glyph.w > 0:
            self.shapes[char] = glyph

    def match(self, glyph: Glyph) -> tuple[str, float]:
        """가장 닮은 글쇠와 어긋난 비율. 못 고르면 ('', 1.0)."""
        best_char, best = "", 1.0
        for char, shape in self.shapes.items():
            score = glyph.mismatch(shape)
            if score < best:
                best_char, best = char, score
                if best == 0.0:
                    break
        if best > MAX_MISMATCH:
            return ("", best)
        return (best_char, best)

    def read(self, glyphs: list[Glyph]) -> tuple[str, list[float]]:
        """글자 상자들을 글로 옮긴다. 못 읽은 자리는 '?'."""
        out = []
        scores = []
        for glyph in glyphs:
            char, score = self.match(glyph)
            out.append(char or "?")
            scores.append(score)
        return ("".join(out), scores)

    # -- 저장 --------------------------------------------------------------
    def save(self, library_root: Path) -> Path:
        folder = font_dir(library_root, self.name)
        folder.mkdir(parents=True, exist_ok=True)
        for char, glyph in self.shapes.items():
            glyph.to_png(folder / _file_for(char))
        return folder

    @classmethod
    def load(cls, library_root: Path, name: str) -> "Font":
        font = cls(name)
        folder = font_dir(library_root, name)
        try:
            files = sorted(folder.glob("*.png"))
        except OSError:
            return font
        for path in files:
            char = _char_for(path.stem)
            if len(char) != 1 or char not in LEARNABLE:
                continue
            glyph = Glyph.from_png(path)
            if glyph is not None:
                font.shapes[char] = glyph
        return font


class BuiltinFont(Font):
    """익히지 않고 바로 쓰는 숫자 글꼴. 모양을 프로그램이 이미 알고 있다.

    익힌 글꼴보다 **깐깐하게** 본다. 익힌 글꼴은 그 게임에서 직접 떠 온 모양이라
    조금 어긋나도 그 글자가 맞지만, 여기 것은 흔한 점글씨를 미리 넣어 둔 것이라
    어설프게 닮았다고 숫자를 지어내면 안 된다. 헷갈리면 '?'로 두고, 그래도 값이
    갈리지 않으면(자릿수로 판가름 나면) 조건은 그대로 선다.
    """

    # 이만큼까지만 같은 글자로 본다. 5×7은 칸이 35개뿐이라 한 칸이 3%다.
    STRICT = 0.09
    # 1등과 2등이 이만큼은 벌어져야 믿는다. 0과 8은 6칸(17%) 차이다.
    MARGIN = 0.06

    # 다른 글자와 이만큼은 달라야 곁들이 모양으로 받아 준다.
    APART = 0.14

    def __init__(self) -> None:
        super().__init__(AUTO_FONT)
        # 맨 앞 모양은 그대로 쓴다 — 게임에서 떠 온 것과 한 칸도 다르지 않았다.
        self.variants: dict[str, list[Glyph]] = {
            char: [from_pattern(patterns[0])]
            for char, patterns in BUILTIN_5X7.items()
        }
        for char, glyphs in self.variants.items():
            self.shapes[char] = glyphs[0]
        # 곁들이 모양(3·7·9처럼 점글씨마다 다르게 쓰는 것)은 **다른 글자와
        # 헷갈릴 만큼 닮았으면 버린다.** 예를 들어 어떤 9는 8과 두 칸밖에 안
        # 달라서, 그것까지 받아 주면 멀쩡한 8을 9로 읽을 수 있다.
        for char, patterns in BUILTIN_5X7.items():
            for pattern in patterns[1:]:
                shape = from_pattern(pattern)
                # 견줄 때는 화면에서 잘라 온 쪽이 기준이라, 가장자리가 한 칸
                # 밀리면 어느 쪽을 기준으로 재느냐에 따라 값이 달라진다. 더
                # 가깝게 나오는 쪽으로 본다 — 헷갈릴 여지를 낮춰 잡아야 한다.
                if all(min(shape.mismatch(other), other.mismatch(shape)) >= self.APART
                       for name, glyphs in self.variants.items() if name != char
                       for other in glyphs):
                    self.variants[char].append(shape)

    def fit(self, glyph: Glyph, shape: Glyph) -> float:
        return glyph.mismatch(shape)

    def scale_of(self, glyphs: list[Glyph]) -> int:
        """이 줄이 몇 배로 그려졌나. 점글씨 한 줄은 7칸이다.

        글자마다 따로 크기를 맞추면 안 된다 — 5×7짜리 '0'을 2×2짜리 '.'에 맞춰
        줄이면 까만 네모가 되어 마침표와 똑같아진다. 줄 전체를 보고 한 번만 정한다.
        """
        tall = sorted(g.h for g in glyphs if g.h >= 5)
        if not tall:
            return 1
        middle = tall[len(tall) // 2]
        return max(1, round(middle / 7))

    def read(self, glyphs: list[Glyph]) -> tuple[str, list[float]]:
        step = self.scale_of(glyphs)
        if step > 1:
            glyphs = [resample(g, max(1, round(g.w / step)), max(1, round(g.h / step)))
                      for g in glyphs]
        return super().read(glyphs)

    def match(self, glyph: Glyph) -> tuple[str, float]:
        best_char, best, second = "", 1.0, 1.0
        for char, shapes in self.variants.items():
            score = min(self.fit(glyph, shape) for shape in shapes)
            if score < best:
                best_char, second, best = char, best, score
            elif score < second:
                second = score
        if best > self.STRICT or second - best < self.MARGIN:
            return ("", best)
        return (best_char, best)


class AutoFont(Font):
    """익히지 않고 읽는 글꼴. 두 가지를 차례로 해 본다.

    1. 내장 점글씨(BUILTIN_5X7) — 옛날 게임 UI에 흔한 5×7 글씨
    2. **윈도 글꼴을 직접 그려 보고** 줄 전체가 가장 잘 맞는 것 (winfont)

    2가 요령이다. 게임 상태창이 굴림·돋움 같은 보통 글꼴로 그려져 있으면 크기가
    게임마다 달라 미리 담아 둘 수 없다. 대신 그 자리에서 그려 보면 된다. 한
    글자씩이 아니라 **줄 전체로** 견주므로, 글꼴과 크기가 맞는 순간 죄다 맞는다.
    """

    def __init__(self, render: bool = False) -> None:
        super().__init__(AUTO_FONT)
        self.shapes = builtin_font().shapes
        self.picked = ""  # 마지막에 고른 글꼴 이름 (로그용)
        # 윈도 글꼴을 그려 보는 일은 처음 한 번이 몇 초 걸린다. 낚시 도중에 그러면
        # 그동안 미니게임을 놓친다. 그래서 **사람이 [지금 읽어 보기]를 누를 때만**
        # 그려 보고, 알아낸 모양은 익혀 두어 그다음부터는 바로 읽는다.
        self.render = render
        self.found: Font | None = None

    def read(self, glyphs: list[Glyph]) -> tuple[str, list[float]]:
        self.picked = ""
        self.found = None
        text, scores = builtin_font().read(glyphs)
        if _enough(text):
            self.picked = "내장 점글씨"
            return (text, scores)
        if not self.render:
            return (text, scores)
        best = (_grade(text, scores), text, scores, "", None)
        for font in _window_fonts(glyphs):
            got, marks = font.read(glyphs)
            grade = _grade(got, marks)
            if grade > best[0]:
                best = (grade, got, marks, font.name, font)
        # **어설프게 닮았다고 숫자를 지어내면 안 된다.** 틀린 숫자로 매크로가 돌면
        # 못 읽은 것보다 나쁘다. 줄 전체가 꽤 잘 맞을 때만 받아들인다.
        digits_read, tight = best[0]
        if best[3] and (digits_read < 4 or tight < -ACCEPT_LINE):
            return (text, scores)
        self.picked = best[3] or "내장 점글씨"
        self.found = best[4]
        return (best[1], best[2])


# 그려 본 글꼴로 읽었다고 인정할 줄 전체의 평균 어긋남.
ACCEPT_LINE = 0.10


def _enough(text: str) -> bool:
    """이 줄을 다 읽었다고 볼 만한가 — '/' 앞뒤로 또렷한 숫자가 있으면 된다."""
    words = [w for w in text.replace(",", "").split("?") if w]
    found = [w for w in words if w and all(c.isdigit() for c in w)]
    return len(found) >= 2


def _grade(text: str, scores: list[float]) -> tuple:
    """읽은 정도. 숫자를 많이, 잘 맞게 읽었을수록 높다."""
    digits_read = sum(1 for c in text if c.isdigit())
    tight = -sum(scores) / len(scores) if scores else -1.0
    return (digits_read, tight)


def _window_fonts(glyphs: list[Glyph]) -> list[Font]:
    """이 줄의 글자 키에 맞는 윈도 글꼴 후보들."""
    tall = sorted(g.h for g in glyphs if g.h >= 4)
    if not tall:
        return []
    try:
        from . import winfont

        return winfont.candidates(tall[len(tall) // 2])
    except Exception:  # 글꼴을 못 그리는 환경이면 내장 모양만 쓴다
        return []


_BUILTIN: BuiltinFont | None = None


def builtin_font() -> BuiltinFont:
    """내장 숫자 글꼴 한 벌 (한 번만 만든다)."""
    global _BUILTIN
    if _BUILTIN is None:
        _BUILTIN = BuiltinFont()
    return _BUILTIN


class FontCache:
    """글꼴을 한 번만 읽어 두고 재사용한다. 파일이 바뀌면 다시 읽는다."""

    def __init__(self) -> None:
        self._cache: dict[tuple, tuple[float, Font]] = {}

    def get(self, library_root: Path, name: str) -> Font:
        folder = font_dir(library_root, name)
        try:
            stamp = max((p.stat().st_mtime for p in folder.glob("*.png")), default=0.0)
        except OSError:
            stamp = 0.0
        key = (str(folder),)
        cached = self._cache.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
        font = Font.load(library_root, name)
        self._cache[key] = (stamp, font)
        return font

    def clear(self) -> None:
        self._cache.clear()


FONTS = FontCache()


# --------------------------------------------------------------------------
# 읽은 글에서 숫자 뽑기
# --------------------------------------------------------------------------
_NUMBER = re.compile(r"\d+")


def numbers_in(text: str) -> list[int]:
    """읽은 글에서 숫자만 차례대로. 자릿점(,)은 미리 지운다."""
    return [int(m) for m in _NUMBER.findall(text.replace(",", ""))]


def split_tokens(glyphs: list[Glyph], text: str) -> list[tuple[str, list[Glyph]]]:
    """글자들을 **사이가 벌어진 곳**에서 낱말로 나눈다. [(글, 글자들)].

    "피로도 : 31057 / 542000"처럼 숫자 앞에 글자가 붙어 있으면, 그 글자는 글꼴에
    없어서 '?'로 읽힌다. 예전에는 '?'가 하나라도 섞이면 숫자 읽기를 통째로 실패로
    봤다 — 정작 숫자는 또렷한데도 그랬다. 낱말 사이는 글자 사이보다 확실히
    넓으므로(보통 두 배 이상), 그 자리에서 잘라 숫자 낱말만 골라 쓸 수 있다.

    '/'도 자르는 자리로 본다. 사이가 좁아 숫자와 붙어 버려도 앞뒤 값이 갈리도록.
    다만 글꼴이 숫자로 읽어 낸 글자는 건드리지 않는다 — '1'이나 '7'을 빗금으로
    잘못 보고 숫자 한가운데를 자르면 값이 달라지기 때문이다.
    """
    if not glyphs:
        return []
    gaps = [glyphs[i + 1].x - (glyphs[i].x + glyphs[i].w) for i in range(len(glyphs) - 1)]
    inside = sorted(g for g in gaps if g >= 0)
    median = inside[len(inside) // 2] if inside else 0
    limit = max(3.0, median * 2.0 + 1.0)
    cuts = {0, len(glyphs)}
    for i, gap in enumerate(gaps):
        if gap > limit:
            cuts.add(i + 1)
    for i, glyph in enumerate(glyphs):
        char = text[i] if i < len(text) else "?"
        if char == "/" or (char == "?" and _slash_like(glyph)):
            cuts.add(i)
            cuts.add(i + 1)
    edges = sorted(cuts)
    return [(text[a:b], glyphs[a:b]) for a, b in zip(edges, edges[1:]) if b > a]


@dataclass
class Number:
    """읽은 숫자 하나. 못 읽은 자리가 있으면 value는 None이고 범위만 안다."""

    text: str
    value: int | None
    low: int  # 못 읽은 자리를 0으로 봤을 때 (가장 작을 때)
    high: int  # 못 읽은 자리를 9로 봤을 때 (가장 클 때)

    @property
    def sure(self) -> bool:
        return self.value is not None


def numbers_from(glyphs: list[Glyph], text: str) -> list[Number]:
    """낱말 중 **숫자로 된 것**만. 못 읽은 자리('?')는 범위로 남긴다.

    자릿수가 그대로 남으므로, 다 못 읽어도 "적어도 이만큼, 많아야 이만큼"은 안다.
    예를 들어 다섯 자리 '?105?'는 아무리 커도 91059다 — 기준이 십만이면 그것만으로
    "아직 안 넘었다"고 답할 수 있다.
    """
    out: list[Number] = []
    for word, _chars in split_tokens(glyphs, text):
        body = word.replace(",", "")
        if not body or any(c not in "0123456789?" for c in body) or not any(
            c.isdigit() for c in body
        ):
            continue
        if "?" in body:
            out.append(Number(word, None, int(body.replace("?", "0")),
                              int(body.replace("?", "9"))))
        else:
            value = int(body)
            out.append(Number(word, value, value, value))
    return out


# --------------------------------------------------------------------------
# 화면에서 한 번 읽기
# --------------------------------------------------------------------------
class Reading:
    """한 번 읽은 결과. 로그와 익히기 화면이 같은 것을 쓴다."""

    __slots__ = ("text", "glyphs", "values", "error", "worst", "elapsed_ms", "frame",
                 "tuned", "reader")

    def __init__(self, text="", glyphs=None, values=None, error="",
                 worst=0.0, elapsed_ms=0.0, frame=None, tuned="", reader=""):
        self.text = text
        self.glyphs = glyphs or []
        self.values = values or []
        self.error = error
        self.worst = worst  # 가장 안 맞은 글자의 어긋난 비율
        self.elapsed_ms = elapsed_ms
        # 찍은 그림. 글꼴로 못 읽었을 때 **모양 비교**로 다시 볼 때 쓴다.
        self.frame = frame
        # 밝기를 스스로 맞춰 읽었으면 어떻게 맞췄는지. 안 맞췄으면 빈 글.
        self.tuned = tuned
        # 어떤 모양으로 읽었는지 (내장 / 익힌 글꼴 이름).
        self.reader = reader

    @property
    def numbers(self) -> list["Number"]:
        """읽은 글에서 고른 숫자 낱말들."""
        return numbers_from(self.glyphs, self.text)

    @property
    def ok(self) -> bool:
        """쓸 만하게 읽혔나 — **숫자 두 개가 또렷한가**로 본다.

        예전에는 '?'가 하나라도 있으면 실패로 봤는데, 그러면 "피로도 :" 같은
        글자(익힐 수도 없고 익힐 까닭도 없다) 때문에 멀쩡한 숫자까지 버려졌다.
        """
        if self.error:
            return False
        found = self.numbers
        return len(found) >= 2 and found[-1].sure and found[-2].sure

    def describe(self) -> str:
        if self.error:
            return self.error
        if not self.glyphs:
            return "글자를 하나도 찾지 못했습니다 (영역·밝기 기준을 확인하세요)"
        found = self.numbers
        if len(found) < 2:
            return (f"'{self.text}' — '/' 앞뒤 숫자 두 개를 못 찾았습니다 "
                    f"(찾은 것 {len(found)}개)")
        blurred = " · ".join(f"'{n.text}'" for n in found[-2:] if not n.sure)
        if blurred:
            return f"'{self.text}' — {blurred}에 못 읽은 자리가 있습니다"
        return f"'{self.text}' → {self.values[-2:]} ({self.elapsed_ms:.0f}ms)"


def grab(watch, library_root, window, ctx=None) -> Reading:
    """숫자 조건 하나를 지금 화면에서 읽는다.

    커서를 올려야 뜨는 것(툴팁)이면 잠깐 올렸다가 **원래 자리로 돌려놓는다.**
    사용자가 쓰던 커서를 낚아채 놓고 안 돌려주면 그것만으로 못 쓸 물건이 된다.
    """
    import time

    from . import sender

    if window is None:
        return Reading(error="게임 창을 찾지 못했습니다")
    area = watch.area(window)
    if area is None:
        return Reading(error="읽을 영역이 지정되지 않았습니다")

    started = time.perf_counter()
    restore = None
    try:
        if watch.hovers:
            restore = sender.cursor_pos()
            hx, hy = window.client_to_screen(watch.hover_x, watch.hover_y)
            sender.mouse_move(hx, hy)
            wait = max(watch.hover_wait_ms, 0) / 1000.0
            if ctx is not None:
                ctx.sleep(wait)
            elif wait:
                time.sleep(wait)

        try:
            frame = pixel.capture_region(*area)
        except pixel.CaptureError as exc:
            return Reading(error=str(exc))
    finally:
        # 읽기에 실패했더라도 커서는 반드시 돌려놓는다.
        if restore is not None:
            try:
                sender.mouse_move(*restore)
            except OSError:
                pass

    font = pick_font(watch, library_root)
    text, glyphs, scores, tuned = _best_read(frame, watch, font)
    elapsed = (time.perf_counter() - started) * 1000.0
    return Reading(
        text=text,
        glyphs=glyphs,
        values=numbers_in(text),
        worst=max(scores) if scores else 0.0,
        elapsed_ms=elapsed,
        frame=frame,
        tuned=tuned,
        reader=font.name,
    )


def pick_font(watch, library_root) -> Font:
    """이 조건을 읽을 글꼴. 익혀 둔 것이 없으면 **내장 숫자 모양**을 쓴다.

    예전에는 글꼴을 안 익혔으면 그냥 실패였다. 게임 상태창 숫자는 늘 같은
    점글씨라 프로그램이 이미 알고 있으니, 사용자가 숫자를 하나하나 익힐 까닭이
    없다. 익혀 둔 글꼴이 있으면 그쪽이 그 게임에서 직접 떠 온 모양이니 먼저 쓴다.
    """
    name = (watch.font or "").strip()
    if not name or name == AUTO_FONT or library_root is None:
        return AutoFont()
    font = find_font(library_root, name)
    if not font or font.digits_missing:
        # 덜 익힌 글꼴이라도 아는 글자는 그쪽이 더 정확하다. 모르는 숫자만
        # 내장 모양으로 메운다.
        return _mixed(font, name)
    return font


def find_font(library_root, name: str) -> Font | None:
    """익혀 둔 글꼴 찾기. 없으면 None.

    라이브러리 폴더를 다른 곳으로 바꾸면 **전에 익혀 둔 숫자 글꼴은 옛 폴더
    (프로그램 옆 library/)에 남는다.** 실제로 피로도 글꼴이 그렇게 떨어져 있어
    조건이 "글꼴을 익히지 않았습니다"로 조용히 안 섰다. 거기서도 찾아본다.
    """
    name = (name or "").strip()
    if not name or name == AUTO_FONT:
        return None
    font = FONTS.get(library_root, name) if library_root is not None else None
    if not font:
        from . import storage

        fallback = storage.DEFAULT_LIBRARY
        if library_root is None or Path(library_root).resolve() != fallback.resolve():
            font = FONTS.get(fallback, name)
    return font or None


def _mixed(font: Font | None, name: str) -> Font:
    """익힌 모양을 앞세우고, 모르는 숫자는 알아서 읽는 글꼴."""
    if font is None or not font:
        return AutoFont()
    base = builtin_font()
    mixed = BuiltinFont()
    mixed.name = f"{name}+내장" if font.shapes else base.name
    for char, glyph in font.shapes.items():
        mixed.shapes[char] = glyph
        mixed.variants[char] = [glyph] + [
            other for other in mixed.variants.get(char, [])
            if other.mismatch(glyph) > 0.0
        ]
    return mixed


def _scored(text: str) -> int:
    """읽어 낸 정도. 알아본 글자가 많을수록 좋다."""
    return sum(1 for c in text if c != "?")


def _best_read(frame, watch, font) -> tuple[str, list[Glyph], list[float], str]:
    """정해 둔 설정으로 읽어 보고, 시원찮으면 **밝기를 스스로 맞춰** 다시 읽는다.

    글자 색(밝은 글자/어두운 글자)을 거꾸로 골라 두면 배경이 통째로 한 글자가
    되어 아무것도 안 읽힌다. 사람이 [자동 맞추기]를 눌러 줄 때까지 기다릴 일이
    아니다 — 경우의 수가 열몇 개뿐이니 그냥 프로그램이 맞춰 본다.
    """
    glyphs = segment(frame, dark=watch.dark_text, threshold=watch.threshold)
    text, scores = font.read(glyphs)
    if len(numbers_from(glyphs, text)) >= 2 and "?" not in text.strip("?"):
        return (text, glyphs, scores, "")
    dark, threshold, tuned_glyphs, quality_score = autotune(frame)
    if quality_score <= 0 or (dark == watch.dark_text and threshold == watch.threshold):
        return (text, glyphs, scores, "")
    text2, scores2 = font.read(tuned_glyphs)
    if _scored(text2) <= _scored(text):
        return (text, glyphs, scores, "")
    how = "어두운 배경에 밝은 글자" if not dark else "밝은 배경에 어두운 글자"
    return (text2, tuned_glyphs, scores2, f"{how} · 밝기 {threshold}")


# 글꼴 없이 "가득 찼나" — '/' 앞뒤 숫자의 모양이 같은가
# --------------------------------------------------------------------------
# '/' 뒤에 최소 이만큼은 글자가 있어야 비교한다. 한 글자끼리 같은 것은 우연이 많다.
SIDE_MIN = 2

# 앞뒤 글자를 **같은 모양**으로 볼 어긋남 한도. 글꼴 읽기(MAX_MISMATCH 14%)보다 훨씬
# 빡빡하다. 같은 화면의 같은 숫자는 픽셀까지 똑같이 그려져 0%가 나오는 반면, 익혀 둔
# 피로도 글자에서 6과 8은 17%밖에 안 달랐다. 아직 안 익힌 9·3은 8과 한두 픽셀만
# 다를 수 있으므로, 툴팁 배경이 비쳐 흔들리는 한 픽셀 정도만 봐준다.
SIDE_MISMATCH = 0.04


def _shape_gap(a: Glyph, b: Glyph) -> float:
    """두 글자가 다른 칸의 비율. **크기가 다르면 다른 글자**이고, 밀어 맞추지 않는다.

    mismatch()는 익힌 글자와 견줄 때 쓰느라 ±1칸 밀어 가장 잘 맞는 값을 고른다.
    같은 화면의 같은 숫자끼리 비교할 때는 그럴 까닭이 없고, 밀면 오히려 서로 다른
    숫자가 더 비슷해 보인다.
    """
    if a.w != b.w or a.h != b.h or not a.bits:
        return 1.0
    return sum(1 for p, q in zip(a.bits, b.bits) if p != q) / len(a.bits)


def _slash_like(glyph: Glyph) -> bool:
    """'/' 처럼 생겼나 — 글꼴을 안 익혀도 모양으로 알아본다.

        · 세로로 길고
        · 줄마다 잉크가 짧게 한 토막이고 (7처럼 가로획이 긴 줄이 드물고)
        · 위로 갈수록 오른쪽으로 옮겨 간다 (줄 가운데와 높이가 거꾸로 따라간다)
    """
    w, h = glyph.w, glyph.h
    if h < 5 or h < w * 1.2:
        return False
    ys, xs = [], []
    wide = 0
    for y in range(h):
        row = [x for x in range(w) if glyph.bits[y * w + x]]
        if not row:
            continue
        if row[-1] - row[0] + 1 > max(2, w * 0.6):
            wide += 1
        ys.append(y)
        xs.append(sum(row) / len(row))
    if len(ys) < 4 or wide > len(ys) * 0.25:
        return False
    my, mx = sum(ys) / len(ys), sum(xs) / len(xs)
    cov = sum((y - my) * (x - mx) for y, x in zip(ys, xs))
    vy = sum((y - my) ** 2 for y in ys)
    vx = sum((x - mx) ** 2 for x in xs)
    if vx <= 0 or vy <= 0:
        return False
    return cov / (vy * vx) ** 0.5 <= -0.8


def sides_match(glyphs: list[Glyph]) -> tuple[bool | None, str]:
    """'/' 뒤의 글자들과 바로 앞 같은 수의 글자들이 **모양이 똑같은가**.

    "피로도 : 548000 / 548000"처럼 가득 차면 앞 값과 뒤 값이 같은 숫자라, 무슨
    숫자인지 몰라도 **그림이 똑같다.** 그래서 글꼴을 하나도 안 익혀도 가득 찼는지는
    알 수 있다. 앞에 "피로도 :" 같은 글자가 붙어 있어도 '/' 바로 앞 같은 개수만 본다.

    (True=같음 · False=다름 · None=판단 못 함, 설명)
    """
    candidates = [i for i, g in enumerate(glyphs) if _slash_like(g)]
    verdict: tuple[bool | None, str] | None = None
    for k in reversed(candidates):  # 가장 오른쪽 '/'부터 — 앞 글자에 비슷한 모양이 있어도
        right = glyphs[k + 1:]
        if len(right) < SIDE_MIN:
            continue
        if k < len(right):
            verdict = verdict or (False, f"'/' 앞 글자({k}자)가 뒤({len(right)}자)보다 적음")
            continue
        left = glyphs[k - len(right):k]
        worst = max(_shape_gap(a, b) for a, b in zip(left, right))
        if worst <= SIDE_MISMATCH:
            return (True, f"'/' 앞뒤 {len(right)}자의 모양이 같음 (어긋남 {worst:.0%})")
        verdict = verdict or (False, f"'/' 앞뒤 {len(right)}자의 모양이 다름 (어긋남 {worst:.0%})")
    if verdict is not None:
        return verdict
    return (None, f"'/'를 못 찾음 (잘린 글자 {len(glyphs)}개)")


def full_by_shape(frame, watch, glyphs: list[Glyph] | None = None) -> tuple[bool | None, str]:
    """글꼴 없이 '앞 값이 뒤 값에 닿았나'를 본다. 지금 밝기 설정으로 안 되면 자동으로."""
    first = glyphs if glyphs is not None else segment(
        frame, dark=watch.dark_text, threshold=watch.threshold)
    hit, detail = sides_match(first)
    if hit is not None or frame is None:
        return (hit, detail)
    # 밝기 기준이 안 맞아 글자가 뭉쳤을 수 있다. 가장 글자 한 줄 같은 설정으로 다시.
    _dark, _threshold, tuned, _score = autotune(frame)
    again, detail2 = sides_match(tuned)
    if again is not None:
        return (again, detail2 + " · 밝기 자동 맞춤")
    return (None, detail)


def _span(watch, current: Number, maximum: Number) -> tuple[float, float] | None:
    """조건이 보는 값의 **범위** (가장 작을 때, 가장 클 때). 낼 수 없으면 None.

    못 읽은 자리를 0으로 채우면 가장 작고, 9로 채우면 가장 크다. 조건이 '앞 값'만
    보면 뒤 값은 못 읽어도 상관없다 — 그런 경우까지 살리려고 범위로 다룬다.
    """
    if watch.target == "current":
        return (float(current.low), float(current.high))
    if watch.target == "max":
        return (float(maximum.low), float(maximum.high))
    if watch.target == "left":  # 뒤 - 앞
        return (float(maximum.low - current.high), float(maximum.high - current.low))
    if watch.target == "percent":
        if maximum.low <= 0:
            return None
        return (current.low * 100.0 / maximum.high, current.high * 100.0 / maximum.low)
    return None


def learn_line(watch, library_root, window, name: str = "자동읽기"):
    """[지금 읽어 보기] 할 때 **이 게임 글씨를 알아내서 익혀 둔다.**

    흔한 윈도 글꼴을 그려 보며 줄 전체가 가장 잘 맞는 것을 고르고, 맞으면 그
    모양을 글꼴로 저장한다. 사람이 숫자 열 개를 적어 줄 일이 없다. 한 번
    알아내고 나면 그다음부터는 그리지 않으니 읽기도 바로 끝난다.

    (익힌 글꼴 이름, 읽은 글) 또는 (None, 까닭).
    """
    reading = grab(watch, library_root, window)
    if reading.error:
        return (None, reading.error)
    if reading.ok:
        return ("", reading.text)  # 이미 읽힌다 — 익힐 것 없음
    auto = AutoFont(render=True)
    text, _scores = auto.read(reading.glyphs)
    if auto.found is None:
        return (None, reading.describe())
    font = Font(name)
    font.shapes.update(auto.found.shapes)
    try:
        font.save(library_root)
    except OSError as exc:
        return (None, f"익힌 모양을 저장하지 못했습니다: {exc}")
    FONTS.clear()
    return (name, text)


def judge_numbers(watch, numbers: list[Number]) -> tuple[bool | None, str]:
    """읽은 숫자 낱말들로 조건을 따진다. 판가름이 안 나면 (None, 까닭).

    마지막 두 낱말을 **앞 값 / 뒤 값**으로 본다 ("피로도 : 31057 / 542000").
    글자가 섞여 있어도 숫자 낱말만 또렷하면 이것으로 답이 난다.

    못 읽은 자리가 있어도 **어떤 숫자가 와도 결론이 같으면** 그대로 답한다. 자릿수는
    남아 있기 때문이다 — 다섯 자리 '?105?'는 아무리 커도 91059라, 기준이 십만이면
    "아직 안 넘었다"가 확실하다. 반대로 기준이 30000이면 첫 자리에 따라 갈리므로
    보류하고, 그 숫자를 익히라고 알려 준다.
    """
    if len(numbers) < 2:
        found = " · ".join(n.text for n in numbers) or "없음"
        return (None, f"'/' 앞뒤 숫자 두 개를 못 찾았습니다 (찾은 것: {found})")
    current, maximum = numbers[-2], numbers[-1]
    if current.sure and maximum.sure:
        return watch.judge(current.value, maximum.value)

    blurred = " · ".join(f"'{n.text}'" for n in (current, maximum) if not n.sure)
    if watch.target == "at_max":
        return (None, f"{blurred}에 못 읽은 자리가 있습니다")
    span = _span(watch, current, maximum)
    if span is None:
        return (None, f"{blurred}에 못 읽은 자리가 있습니다")

    low, high = span
    seen = f"{current.text}/{maximum.text}"
    if watch.compare == "at_least":
        if low >= watch.value:
            return (True, f"{seen} → 아무리 작아도 {low:g} ≥ {watch.value:g}")
        if high < watch.value:
            return (False, f"{seen} → 아무리 커도 {high:g} < {watch.value:g}")
    else:
        if high <= watch.value:
            return (True, f"{seen} → 아무리 커도 {high:g} ≤ {watch.value:g}")
        if low > watch.value:
            return (False, f"{seen} → 아무리 작아도 {low:g} > {watch.value:g}")
    return (None, f"{seen} → {low:g} ~ {high:g} 사이라 {watch.value:g}을(를) "
                  f"넘는지 갈립니다 ({blurred}의 '?' 자리 숫자를 익히면 됩니다)")


def evaluate(watch, library_root, window, ctx=None) -> tuple[bool, str]:
    """숫자 조건 하나의 성립 여부. (성립, 설명).

    못 읽었으면 **성립하지 않은 것으로 본다.** 못 읽은 것과 조건이 맞는 것은
    다르다 — 툴팁이 안 떴다고 매크로를 돌리면 엉뚱한 때에 돈다.

    다만 '앞 값이 뒤 값에 닿으면'은 **글꼴 없이도** 판단한다. 가득 차면 '/' 앞뒤가
    같은 숫자라 그림이 똑같기 때문이다. 글꼴을 안 익혔거나(글꼴 이름만 적어 둔 경우)
    한두 숫자를 덜 익혀 못 읽을 때 이쪽으로 본다.
    """
    reading = grab(watch, library_root, window, ctx)
    # 글자가 섞여 있어도(예: "피로도 :") **숫자 낱말만** 또렷하면 그것으로 판단한다.
    # 못 읽은 자리가 있어도 자릿수로 판가름 나면 답한다.
    if not reading.error:
        hit, detail = judge_numbers(watch, reading.numbers)
        if hit is not None:
            return (hit, detail)
    if watch.target == "at_max" and reading.frame is not None:
        hit, detail = full_by_shape(reading.frame, watch, reading.glyphs)
        if hit is not None:
            return (hit, f"모양 비교: {detail} → {'가득' if hit else '안 참'}")
        return (False, f"모양 비교도 못 함: {detail} · {reading.describe()}")
    return (False, reading.describe())
