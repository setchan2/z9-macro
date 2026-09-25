"""화면에서 아이콘 이미지를 찾는다 (템플릿 매칭).

인벤토리 속 버프 아이템은 자리가 고정되어 있지 않아서, 좌표를 찍어 두는 방식으로는
잡을 수 없다. 그래서 아이콘 그림을 미리 저장해 두고 화면에서 같은 그림을 찾는다.

순수 파이썬이라 무식하게 전부 비교하면 못 쓴다. 1366x768 화면에서 32x32 아이콘을
찾는다고 하면 위치 100만 곳 × 픽셀 1024개 = 10억 번 비교다.

그래서 세 단계로 줄인다.

1. **축소해서 훑기** — 화면과 아이콘을 같은 배율로 줄여 큰 그림만 비교한다.
   4배로 줄이면 비교량이 256분의 1이 된다.
2. **중간에 포기** — 오차가 이미 기준을 넘었으면 나머지 픽셀은 보지 않는다.
   대부분의 위치는 몇 픽셀 만에 걸러진다.
3. **후보만 원본 해상도로 확인** — 축소본에서 그럴듯했던 몇 곳만 정밀 비교한다.

찾는 영역을 좁혀 주면(인벤토리 창 범위) 훨씬 빨라진다.

**마스크** — 그림 위에 계속 바뀌는 것이 겹쳐 있으면(버프 아이콘의 남은 시간
숫자처럼) 그 칸을 빼고 비교해야 한다. 마스크는 픽셀마다 "볼지 말지"를 적어 둔
바이트열이고, 빠진 칸은 점수 계산에서 통째로 제외된다.

**밝기 보정** — 반투명하게 그려지는 UI는 뒤 배경에 따라 전체가 조금 밝아지거나
어두워진다. 모양은 그대로인데 값만 밀린 것이라, 평균 차이를 먼저 빼고 비교하면
같은 그림으로 알아본다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import pixel

RGB = tuple[int, int, int]


@dataclass
class Template:
    """찾을 아이콘. RGB 바이트를 그대로 들고 있는다.

    mask는 픽셀당 1바이트(1=본다, 0=무시)다. None이면 전부 본다.
    """

    width: int
    height: int
    data: bytes  # RGB, 행 우선
    mask: bytes | None = None  # 픽셀당 1바이트
    # 아래 셋은 처음 쓸 때 채워 두는 계산 캐시다. 비교에 참여하지 않는다.
    _used: list = field(default=None, repr=False, compare=False)
    _probe: tuple = field(default=None, repr=False, compare=False)
    _probe_sums: tuple = field(default=None, repr=False, compare=False)

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def used_count(self) -> int:
        """점수에 실제로 쓰이는 픽셀 수. 0이면 비교할 게 없다는 뜻이다."""
        if self.mask is None:
            return self.pixel_count
        return sum(self.mask)

    def at(self, x: int, y: int) -> RGB:
        i = (y * self.width + x) * 3
        return (self.data[i], self.data[i + 1], self.data[i + 2])

    def uses(self, x: int, y: int) -> bool:
        return self.mask is None or bool(self.mask[y * self.width + x])

    def with_masked_rects(self, rects) -> "Template":
        """사각형 목록을 무시 영역으로 지정한 새 템플릿.

        숫자가 겹쳐 그려지는 칸을 여기서 빼 둔다. 겹쳐 있는 칸을 그냥 두면
        1분마다 그림이 달라지는 셈이라 무슨 짓을 해도 인식률이 오르지 않는다.
        """
        mask = bytearray(self.mask if self.mask is not None else b"" * self.pixel_count)
        for rect in rects:
            rx, ry, rw, rh = rect
            for y in range(max(0, ry), min(self.height, ry + rh)):
                row = y * self.width
                for x in range(max(0, rx), min(self.width, rx + rw)):
                    mask[row + x] = 0
        return Template(self.width, self.height, self.data, bytes(mask))

    def level_probe(self) -> tuple[list[tuple[int, int]], int]:
        """밝기 차이를 잴 때 훑을 픽셀 좌표와 그 개수.

        평균을 내는 데 전체를 다 볼 필요는 없다. 64칸 정도만 고르게 솎아 봐도
        값이 거의 같고, 비교 한 번당 훑는 픽셀이 절반으로 줄어든다.
        """
        if self._probe is None:
            used = self.used_pixels()
            stride = max(1, len(used) // 64)
            picked = used[::stride]
            self._probe = ([(p[0], p[1]) for p in picked], len(picked))
            self._probe_sums = (
                sum(p[2] for p in picked),
                sum(p[3] for p in picked),
                sum(p[4] for p in picked),
            )
        return self._probe

    def probe_sums(self) -> tuple[int, int, int]:
        """level_probe()가 고른 픽셀들의 채널별 합."""
        self.level_probe()
        return self._probe_sums

    def channel_sums(self) -> tuple[int, int, int]:
        """보는 픽셀만 채널별로 더한 값. 밝기 보정에 쓴다."""
        r = g = b = 0
        data = self.data
        mask = self.mask
        for i in range(self.pixel_count):
            if mask is not None and not mask[i]:
                continue
            j = i * 3
            r += data[j]
            g += data[j + 1]
            b += data[j + 2]
        return (r, g, b)

    def used_pixels(self) -> list[tuple[int, int, int, int, int]]:
        """보는 픽셀만 (x, y, r, g, b)로 펼쳐 둔다.

        마스크가 있으면 비교 때마다 "이 칸 보나?"를 되묻는 대신 미리 걸러 둔
        평평한 목록을 훑는 편이 훨씬 빠르다. 템플릿은 한 번 만들면 안 바뀌므로
        처음 한 번만 만들어 두고 계속 쓴다.
        """
        cached = self._used
        if cached is None:
            cached = []
            data = self.data
            mask = self.mask
            for y in range(self.height):
                row = y * self.width
                for x in range(self.width):
                    i = row + x
                    if mask is not None and not mask[i]:
                        continue
                    j = i * 3
                    cached.append((x, y, data[j], data[j + 1], data[j + 2]))
            self._used = cached
        return cached

    def shrink(self, step: int) -> "Template":
        """step×step 블록의 **평균**으로 축소한다.

        픽셀을 하나씩 솎아내면 아이콘이 축소 격자에 1~2픽셀 어긋났을 때 전혀
        다른 위치의 픽셀끼리 비교하게 되어 멀쩡한 아이콘도 놓친다. 블록 평균은
        조금 밀려도 값이 비슷하게 유지된다.

        마스크가 있으면 **보는 픽셀만** 평균 낸다. 그리고 블록의 절반 넘게
        가려져 있으면 그 칸은 통째로 무시한다 — 몇 픽셀 남은 값으로 낸 평균은
        믿을 게 못 된다.
        """
        step = max(1, step)
        if step == 1:
            return self
        gw = (self.width + step - 1) // step
        gh = (self.height + step - 1) // step
        out = bytearray(gw * gh * 3)
        small_mask = bytearray(gw * gh) if self.mask is not None else None
        for gy in range(gh):
            y0 = gy * step
            y1 = min(y0 + step, self.height)
            for gx in range(gw):
                x0 = gx * step
                x1 = min(x0 + step, self.width)
                r = g = b = n = total = 0
                for y in range(y0, y1):
                    base = y * self.width
                    for x in range(x0, x1):
                        total += 1
                        if self.mask is not None and not self.mask[base + x]:
                            continue
                        i = (base + x) * 3
                        r += self.data[i]
                        g += self.data[i + 1]
                        b += self.data[i + 2]
                        n += 1
                o = (gy * gw + gx) * 3
                if n:
                    out[o] = r // n
                    out[o + 1] = g // n
                    out[o + 2] = b // n
                if small_mask is not None:
                    small_mask[gy * gw + gx] = 1 if n * 2 >= total else 0
        return Template(
            gw, gh, bytes(out), bytes(small_mask) if small_mask is not None else None
        )


@dataclass
class Match:
    x: int  # 화면 절대좌표 (아이콘 왼쪽 위)
    y: int
    score: float  # 0.0 = 완전 일치, 클수록 다름 (채널당 평균 차이)

    @property
    def center(self) -> tuple[int, int]:
        return (self.x, self.y)


def template_from_frame(frame: pixel.Frame, x: int, y: int, w: int, h: int) -> Template:
    """캡처한 화면 조각에서 아이콘을 잘라낸다 (x, y는 화면 절대좌표)."""
    out = bytearray()
    for row in range(h):
        for col in range(w):
            color = frame.at(x + col, y + row)
            if color is None:
                raise ValueError("잘라낼 영역이 캡처 범위를 벗어났습니다.")
            out += bytes(color)
    return Template(w, h, bytes(out))


def capture_template(x: int, y: int, w: int, h: int) -> Template:
    """화면에서 바로 아이콘을 떠온다."""
    if w <= 0 or h <= 0:
        raise ValueError("영역 크기가 0 이하입니다.")
    frame = pixel.capture_region(x, y, w, h)
    return template_from_frame(frame, x, y, w, h)


# --------------------------------------------------------------------------
def _region_pixel(buf: bytes, width: int, x: int, y: int) -> tuple[int, int, int]:
    i = (y * width + x) * 4  # BGRA
    return (buf[i + 2], buf[i + 1], buf[i])


def _region_rgb(frame: pixel.Frame) -> bytes:
    """BGRA 캡처 버퍼를 RGB로 옮긴다 (크기 그대로)."""
    buf = frame.buf
    out = bytearray(frame.w * frame.h * 3)
    for i in range(frame.w * frame.h):
        s = i * 4
        d = i * 3
        out[d] = buf[s + 2]
        out[d + 1] = buf[s + 1]
        out[d + 2] = buf[s]
    return bytes(out)


def _shrink_rgb(rgb: bytes, width: int, height: int, step: int) -> tuple[bytes, int, int]:
    """RGB 버퍼를 블록 평균으로 축소한다. 템플릿 쪽과 같은 방식이어야 한다."""
    step = max(1, step)
    if step == 1:
        return (rgb, width, height)
    gw = (width + step - 1) // step
    gh = (height + step - 1) // step
    out = bytearray(gw * gh * 3)
    for gy in range(gh):
        y0 = gy * step
        y1 = min(y0 + step, height)
        for gx in range(gw):
            x0 = gx * step
            x1 = min(x0 + step, width)
            r = g = b = n = 0
            for y in range(y0, y1):
                base = y * width
                for x in range(x0, x1):
                    i = (base + x) * 3
                    r += rgb[i]
                    g += rgb[i + 1]
                    b += rgb[i + 2]
                    n += 1
            o = (gy * gw + gx) * 3
            out[o] = r // n
            out[o + 1] = g // n
            out[o + 2] = b // n
    return (bytes(out), gw, gh)


# 밝기 보정으로 밀어 줄 수 있는 최대치(채널당). 이보다 더 밀어야 맞는다면
# 그건 같은 그림이 아니라 그냥 다른 것이다.
MAX_SHIFT = 48


def _sad(
    region: bytes,
    rw: int,
    template: Template,
    ox: int,
    oy: int,
    limit: float,
) -> float:
    """오차 합. limit을 넘어서면 즉시 포기하고 limit+1을 돌려준다."""
    total = 0
    for tx, ty, tr, tg, tb in template.used_pixels():
        ri = ((oy + ty) * rw + ox + tx) * 3
        total += (
            abs(region[ri] - tr)
            + abs(region[ri + 1] - tg)
            + abs(region[ri + 2] - tb)
        )
        if total > limit:
            return limit + 1
    return total


def _sad_leveled(
    region: bytes,
    rw: int,
    template: Template,
    ox: int,
    oy: int,
    limit: float,
) -> float:
    """평균 밝기 차이를 먼저 빼고 나서 재는 오차 합.

    반투명 UI는 뒤 배경에 따라 통째로 밝아졌다 어두워졌다 한다. 모양은 그대로인데
    값만 밀린 것이라, 그 밀린 양을 먼저 빼고 비교해야 같은 그림으로 알아본다.
    """
    used = template.used_pixels()
    n = len(used)
    if n == 0:
        return limit + 1

    # 밀린 양은 평균이라 몇십 픽셀만 봐도 값이 거의 안 변한다. 전부 더하면
    # 비교 한 번에 훑는 픽셀이 두 배가 되므로, 여기서는 솎아서 본다.
    probe, ratio = template.level_probe()
    sr = sg = sb = 0
    for tx, ty in probe:
        ri = ((oy + ty) * rw + ox + tx) * 3
        sr += region[ri]
        sg += region[ri + 1]
        sb += region[ri + 2]

    tr_s, tg_s, tb_s = template.probe_sums()
    dr = max(-MAX_SHIFT, min(MAX_SHIFT, (sr - tr_s) // ratio))
    dg = max(-MAX_SHIFT, min(MAX_SHIFT, (sg - tg_s) // ratio))
    db = max(-MAX_SHIFT, min(MAX_SHIFT, (sb - tb_s) // ratio))

    total = 0
    for tx, ty, tr, tg, tb in used:
        ri = ((oy + ty) * rw + ox + tx) * 3
        total += (
            abs(region[ri] - tr - dr)
            + abs(region[ri + 1] - tg - dg)
            + abs(region[ri + 2] - tb - db)
        )
        if total > limit:
            return limit + 1
    return total


def suggest_step(template: Template) -> int:
    """축소 배율. 축소본의 짧은 변이 8~12칸쯤 남도록 고른다.

    작은 아이콘을 4배로 줄이면 7x7밖에 안 남아 후보를 못 거르고, 큰 그림을
    2배로만 줄이면 훑을 자리가 너무 많다. 크기에 맞춰 잡는 편이 둘 다 피한다.
    """
    short = min(template.width, template.height)
    return max(1, min(5, round(short / 9)))


def find(
    template: Template,
    region_x: int,
    region_y: int,
    region_w: int,
    region_h: int,
    tolerance: int = 30,
    coarse_step: int = 0,
    max_candidates: int = 8,
    level: bool = True,
) -> Match | None:
    """화면 영역에서 아이콘을 찾는다. 못 찾으면 None.

    tolerance는 채널당 평균 허용 차이다. 게임 화면은 배경이 비쳐 보이거나 살짝
    어두워지는 경우가 있어 완전 일치를 요구하면 놓친다. 30 정도면 사람 눈에
    같은 아이콘으로 보이는 범위를 넉넉히 덮는다.
    """
    if template.width > region_w or template.height > region_h:
        return None

    frame = pixel.capture_region(region_x, region_y, region_w, region_h)
    return find_in_frame(
        template, frame, tolerance=tolerance,
        coarse_step=coarse_step, max_candidates=max_candidates, level=level,
    )


def find_in_frame(
    template: Template,
    frame: pixel.Frame,
    tolerance: int = 30,
    coarse_step: int = 0,
    max_candidates: int = 8,
    level: bool = True,
) -> Match | None:
    """이미 떠 둔 프레임 안에서 찾는다. 여러 아이콘을 같은 화면에서 찾을 때 유용."""
    matches = find_all_in_frame(
        template, frame, tolerance=tolerance, coarse_step=coarse_step,
        max_candidates=max_candidates, level=level, limit=1,
    )
    return matches[0] if matches else None


def find_all_in_frame(
    template: Template,
    frame: pixel.Frame,
    tolerance: int = 30,
    coarse_step: int = 0,
    max_candidates: int = 8,
    level: bool = True,
    limit: int = 1,
    min_gap: int = 0,
) -> list[Match]:
    """점수가 좋은 순으로 최대 limit개를 돌려준다.

    축소본은 블록 평균이라 아이콘이 격자에 어긋나 있어도 값이 비슷하게 남는다.
    그래도 완전히 같지는 않으므로 축소 단계의 허용치는 넉넉히 두고, 최종 판정은
    원본 해상도에서 한다.

    min_gap은 결과끼리 떨어져 있어야 할 최소 거리다. 0이면 템플릿 크기의 절반을
    쓴다 — 같은 아이콘 한 개를 1픽셀 밀린 위치로 여러 번 돌려주지 않기 위해서다.
    """
    used = template.used_count
    if used == 0:
        return []
    if template.width > frame.w or template.height > frame.h:
        return []

    region_rgb = _region_rgb(frame)
    fine_limit = tolerance * used * 3
    compare = _sad_leveled if level else _sad

    step = suggest_step(template) if coarse_step <= 0 else max(1, coarse_step)
    if step == 1:
        candidates = [
            (0.0, x, y)
            for y in range(frame.h - template.height + 1)
            for x in range(frame.w - template.width + 1)
        ]
        offsets = (0,)
    else:
        small_template = template.shrink(step)
        small_used = small_template.used_count
        if small_template.width == 0 or small_template.height == 0 or small_used == 0:
            # 마스크가 심해 축소본에 남는 게 없으면 축소 단계를 건너뛴다.
            return find_all_in_frame(
                template, frame, tolerance=tolerance, coarse_step=1,
                max_candidates=max_candidates, level=level, limit=limit,
                min_gap=min_gap,
            )
        small_region, srw, srh = _shrink_rgb(region_rgb, frame.w, frame.h, step)

        # 어긋남 때문에 생기는 차이를 감안해 넉넉히 잡는다. 여기서 너무 조이면
        # 진짜 아이콘이 후보에도 못 든다.
        coarse_limit = (tolerance + 26) * small_used * 3
        found: list[tuple[float, int, int]] = []
        for sy in range(srh - small_template.height + 1):
            for sx in range(srw - small_template.width + 1):
                score = compare(small_region, srw, small_template, sx, sy, coarse_limit)
                if score <= coarse_limit:
                    found.append((score, sx * step, sy * step))
        if not found:
            return []
        found.sort(key=lambda c: c[0])
        # 후보를 늘려도 정확도는 거의 안 오르고 시간만 는다 (실측: 8 → 40으로
        # 늘리면 40 % 느려지는데 결과는 같았다). 찾을 개수에 맞춰서만 늘린다.
        candidates = found[: max(max_candidates, limit * 6)]
        offsets = range(-step + 1, step)

    gap = min_gap if min_gap > 0 else max(1, min(template.width, template.height) // 2)
    results: list[tuple[float, int, int]] = []
    for _score, cx, cy in candidates:
        best: tuple[float, int, int] | None = None
        for dy in offsets:
            oy = cy + dy
            if not (0 <= oy <= frame.h - template.height):
                continue
            for dx in offsets:
                ox = cx + dx
                if not (0 <= ox <= frame.w - template.width):
                    continue
                exact = compare(region_rgb, frame.w, template, ox, oy, fine_limit)
                if exact <= fine_limit and (best is None or exact < best[0]):
                    best = (exact, ox, oy)
        if best is not None:
            results.append(best)

    if not results:
        return []

    results.sort(key=lambda r: r[0])
    picked: list[Match] = []
    taken: list[tuple[int, int]] = []
    for score, ox, oy in results:
        # 같은 아이콘을 1픽셀씩 밀린 자리로 여러 번 세지 않는다.
        if any(abs(ox - px) < gap and abs(oy - py) < gap for px, py in taken):
            continue
        taken.append((ox, oy))
        picked.append(
            Match(x=frame.x + ox, y=frame.y + oy, score=score / (used * 3))
        )
        if len(picked) >= limit:
            break
    return picked
