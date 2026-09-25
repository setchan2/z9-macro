"""낚시를 실제 화면에 붙인다.

[fishing.py]는 순수하다 — 화면도 입력도 모른다. 그래야 가상 시계로 수백 판을
돌려 보며 명중률을 잴 수 있다. 이 파일이 그 순수한 풀이기를 **진짜 화면과 진짜
마우스**에 잇는다.

한 판은 이렇게 돈다.

    낚시중 ─ 머리 위를 0.1~0.3초마다 두드린다
      │
      └─ 미니게임이 뜨면 ─▶ 두드리기를 멈추고 겹칠 때만 누른다
                              │
                              └─▶ 판이 사라지면 ─▶ 무조건 다시 던진다

**찌를 알아보려 하지 않는다.** 작고 잠깐 떠서 놓치기 일쑤였다. 보이든 안 보이든
그 자리를 계속 두드리는 편이 훨씬 잘 걸리고, 헛클릭은 아무 해가 없다.

**판이 사라지면 그것만으로 다시 던진다.** 낚았든 실패했든 판이 없어졌다는 것은
낚시중이 아니라는 뜻이고, 그러면 [ctrl]을 눌러 다시 낚시중으로 만들어야 한다.
예전에는 빨간 글씨를 본 뒤에야 던졌는데, 그 글씨를 한 번 놓치면 **이미 낚아 놓고도
머리 위만 하염없이 두드렸다.** 낚음을 세는 것과 다시 던지는 것은 별개다 — 세는
쪽은 틀려도 손해가 작지만, 던지는 쪽이 막히면 낚시가 통째로 멈춘다.

**낚았는지는 세 가지로 가린다. 하나만 서도 낚은 것으로 본다.**

    효과음        성공하면 소리가 울린다 — 화면에 기대지 않는 유일한 근거
    빨간 글씨     "○○ 떡밥 1개가 차감됐어요" — 떡밥마다 글자는 달라도 색은 같다
    낚싯대 흔들림 낚았을 때 낚싯대 끝에 물고기가 매달려 쉬지 않고 까딱거린다

**효과음이 가장 든든하다.** 앞의 둘은 결국 화면을 보는 것이라, 창이 가리거나
자리가 밀리거나 움직임이 너무 미세하면 그대로 못 본다. 소리는 그런 것에 안 걸린다.
스피커로 나가는 것을 되받아 듣기 때문에 볼륨을 0으로 두어도 들린다.

소리는 **크기가 아니라 결로** 가린다. 크기만 보면 배경 음악에 그대로 속는다.
어느 높이가 얼마나 섞였는지를 재서 미리 배워 둔 것과 견준다. 자세한 것은
[sound.py]에 있다.

미니게임 화면에서 읽는 것은 네 가지다.

    막대      트랙 띠에서 막대 색의 가운데 x
    물고기    같은 띠에서 물고기 색의 가운데 x
    체력      게이지에서 남은 색이 어디까지 닿았나 (비율)
    남은 시간 숫자를 읽지는 않고, **보이는지**만 본다
"""

from __future__ import annotations

import random
import re
import time

from . import fishing, fishlog, pixel, sender, sound, storage
from .arbiter import ARBITER
from .keys import vk_of
from .model import ColorSpot, FishingSetup, MotionSpot
from .player import Aborted, RunContext

# 미니게임·찌가 떴는지 확인하는 간격(초). 기다리는 동안까지 6ms 캡처를 쉬지
# 않고 돌리면 코어 하나를 통째로 태운다. 여기는 급할 것이 없다.
POLL_S = 0.05

# 판을 시작하기 전에 폭을 재 보는 횟수. 둘 다 재면 바로 그만둔다.
WIDTH_TRIES = 12

# 화면에서 아무것도 못 본 것이 이만큼 이어지면 창이 닫힌 것으로 본다.
# 한 번으로 끊으면 "GO!!" 연출이나 순간적인 가림에도 판이 끝나 버린다.
BLIND_LIMIT = 6

# 미니게임 도중 낚음 근거를 살피는 간격(초). 빨간 알림은 한 번 찍는 데 7ms쯤이라
# 클릭 박자를 해치지 않을 만큼만 본다.
CATCH_LOOK_S = 0.15

# 미니게임에서 클릭이 한 번도 안 나간 채 이만큼 지나면(초) 증거를 남긴다.
DRY_ROUND_S = 3.0
# 그런 증거는 한 번 돌릴 때 이만큼만 남긴다 (디스크를 채우지 않게).
DRY_REPORTS_MAX = 5
# 클릭이 한 번도 안 나간 판이 이만큼 잇따르면 피로도를 곧바로 확인한다.
# 피로도가 거의 차면 게임이 물고기를 안 내준다 — 판은 뜨는데 막대가 안 잡힌다.
DRY_FATIGUE_ROUNDS = 2
_FATIGUE_NOW = re.compile(r"(\d+)\s*/\s*\d+")
# 미니게임 도중 게임 창이 앞에 있는지 살피는 간격(초).
FRONT_LOOK_S = 1.0

# 체력을 정수로 주고받기 위한 눈금. 1000 = 가득.
HEALTH_SCALE = 1000

# 한 물체가 트랙의 이만큼을 넘게 덮으면 **그 물체가 아니다**.
#
# 막대도 물고기도 트랙 안을 오가는 물건이라 트랙보다 한참 좁다. 절반을 넘게
# 덮었다면 배경이나 다른 UI가 그 색에 걸린 것이다. 실제 기록에서 물고기가
# 499px(트랙 518px)로 잡혀 겹침 거리가 207px이 된 적이 있다.
WIDEST = 0.5

# 두 물체 사이가 이만큼 안이면 **붙어 있다**고 본다(px). 막대 테두리와 번짐이
# 보통 1~3px라, 덮인 쪽의 가장자리는 덮은 쪽에서 딱 그만큼 떨어져 잡힌다.
HIDE_PX = 6

# 보이는 폭이 온전한 폭보다 이만큼(또는 4%) 넘게 좁으면 **가려졌을 수 있다**(px).
SHRINK_PX = 2

# 가렸다고 볼 때 덮은 쪽 가장자리가 덮인 쪽 가장자리에서 떨어져도 되는 거리(px).
#
# **고정값으로 두었다가 실제 게임에서 데었다.** 3px로 두었더니 이 게임 막대의
# 주황 테두리가 4px이라, 물고기가 80px에서 44px로 반 가까이 덮였는데도 "4px
# 떨어짐"으로 보고 한 번도 안 메웠다 — 겹침 진단에서 붙은 구간 6번이 전부 0번.
#
# 테두리 굵기는 게임마다 다르므로 **화면에서 배운다.** 누가 봐도 가려진 장면
# (물고기가 크게 줄었는데 막대가 옆에 붙어 있다)에서 둘 사이 거리를 모아 가운뎃값을
# 테두리 굵기로 쓴다. 배우기 전에는 크게 줄었을 때만 BOOT_PX까지 봐준다.
OCCLUDE_PX = 3   # 테두리를 배운 뒤, 거기에 더 봐줄 번짐 몫 / 배우기 전 얕은 가림의 한계
BOOT_PX = 8      # 배우기 전, 크게 줄었을 때 봐줄 거리
DEEP_PX = 8      # 이만큼(또는 상대 폭의 40%) 넘게 줄었으면 "누가 봐도 가려짐"
OUTLINE_MIN = 5  # 테두리 굵기를 믿기 전에 모을 장 수
OUTLINE_KEEP = 41

# 트랙 끝에서 이만큼 안이면 벽에 닿은 것으로 본다(px). 벽에 잘려 좁아진 것을
# 가려진 것으로 알고 메우면 안 된다.
WALL_PX = 2

# 온전한 폭을 뽑으려고 들고 있는 표본 수. 가운뎃값을 쓴다.
CLEAN_KEEP = 31


def _gap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """두 구간 사이 거리(px). 음수면 그만큼 겹쳐 있다."""
    return max(a[0], b[0]) - min(a[1], b[1])


def parse_color(text: str) -> tuple[int, int, int] | None:
    """'#rrggbb' → (r, g, b). 못 읽으면 None."""
    return pixel.from_hex(text) if text else None


def spot_count(spot: ColorSpot, window) -> int:
    """그 사각형에서 그 색이 몇 칸이나 보이는지."""
    rect = spot.rect(window)
    rgb = parse_color(spot.color)
    if rect is None or rgb is None:
        return 0
    try:
        frame = pixel.capture_region(*rect)
    except pixel.CaptureError:
        return 0
    _cx, count = fishing.scan_band(frame.buf, frame.w, rgb, spot.tol,
                                   0, frame.w, 0, frame.h)
    return count


def spot_seen(spot: ColorSpot, window) -> bool:
    """그 색이 문턱만큼 보이는가."""
    return spot.ready and spot_count(spot, window) >= spot.min_px


# --------------------------------------------------------------------------
# 흔들림 보기 — 낚았는지 색이 아니라 **움직임**으로 가린다
# --------------------------------------------------------------------------
_QUANT: dict[int, tuple[bytes, bytes]] = {}

# 0은 0으로, 나머지는 전부 1로. 바이트열을 그대로 0/1 표로 만든다 (C).
_NONZERO = bytes([0] + [1] * 255)


def _quant(tol: int) -> tuple[bytes, bytes]:
    """밝기를 tol 칸으로 뭉개는 변환표 **두 장**. 눈금을 반 칸 엇갈려 둔다.

    한 장만 쓰면 눈금 경계에서 헛걸린다. 허용차 16에 10과 18은 8밖에 안 다른데도
    10//16=0, 18//16=1이라 "바뀌었다"가 된다. 흔들림이 미세한 만큼 이런 헛걸림
    하나하나가 그대로 오탐이 된다.

    그래서 눈금을 반 칸 민 표를 하나 더 두고 **두 장 모두에서 달라진 칸만** 센다.
    10과 18은 민 눈금에서는 둘 다 1이라 걸러진다. 반대로 허용차만큼 제대로
    달라진 값은 어느 눈금에서 보든 달라지므로 그대로 잡힌다.
    """
    step = max(1, min(128, int(tol)))
    got = _QUANT.get(step)
    if got is None:
        half = step // 2
        got = (bytes(v // step for v in range(256)),
               bytes((v + half) // step for v in range(256)))
        _QUANT[step] = got
    return got


def changed_px(before: bytes, after: bytes, tol: int) -> int:
    """두 장 사이에 **몇 칸이 바뀌었나**. BGRA 버퍼 두 개를 받는다.

    칸마다 파이썬으로 견주면 안 된다 — 색 훑기에서 이미 겪었다. 여기서도 반복문을
    전부 C 호출로 민다.

        buf[off::4]      채널 하나만 뽑는다 (C)
        .translate(표)   허용차 안쪽 차이를 뭉갠다 (C)
        정수 XOR         달라진 자리만 남는다 (C)
        .translate       달라졌으면 1, 아니면 0 (C)
        정수 AND         엇갈린 눈금 두 장 모두에서 달라진 칸만 (C)
        .count(0)        그대로인 칸을 센다 (C)

    세 채널(B·G·R)을 OR로 모은다 — 어느 한 채널이라도 달라졌으면 그 칸은 바뀐
    것이다. 알파는 늘 같으므로 본다고 얻을 것이 없다.
    """
    if not before or not after or len(before) != len(after):
        return 0
    n = len(before) // 4
    if n <= 0:
        return 0
    masks = []
    for table in _quant(tol):
        diff = 0
        for off in (0, 1, 2):
            a = before[off::4].translate(table)
            b = after[off::4].translate(table)
            diff |= int.from_bytes(a, "big") ^ int.from_bytes(b, "big")
        if diff == 0:
            return 0  # 한쪽 눈금에서 그대로면 볼 것도 없다
        masks.append(int.from_bytes(
            diff.to_bytes(n, "big").translate(_NONZERO), "big"))
    both = masks[0] & masks[1]
    if both == 0:
        return 0
    return n - both.to_bytes(n, "big").count(0)


class MotionWatch:
    """한 자리가 **되풀이해서** 움직이는지 지켜본다.

    낚았을 때 낚싯대 끝에 매달린 물고기가 쉬지 않고 까딱거린다. 낚시중에는 그
    자리가 거의 그대로다. 색은 물고기 종류마다 다르지만 흔들림은 종류를 안 가리므로,
    색으로 가리는 것보다 든든하다.

    ## 절대 문턱을 사람이 맞히게 했더니 못 맞혔다

    처음에는 "한 장에 몇 칸 넘게 바뀌면 움직임"을 사람이 재서 넣게 했다. 그게
    안 됐다 — 자리마다, 물고기마다, 배경마다 값이 딴판이라 한 번 잘 맞춘 값도
    다음 판에는 안 맞는다. 그러면 아무리 흔들려도 그냥 못 알아본다.

    지금은 **바탕을 스스로 잰다.** 이 자리를 늘 보고 있으므로 조용할 때가 어느
    만큼인지는 저절로 쌓인다.

        바탕    오래 본 점수들 중 아래쪽 (조용할 때가 이만큼)
        문턱    바탕 × rise — 자리를 옮겨도 저절로 따라간다
        되풀이  span_s 안에 문턱을 넘은 장이 repeats개는 나와야 한다

    **바탕은 아주 길게 본 것에서 뽑아야 한다.** 여기서 한 번 데었다. 처음에는
    최근 12초치의 아래쪽 5분의 1을 바탕으로 삼았는데, 물고기가 **쉬지 않고**
    까딱거리면 그 12초가 통째로 "움직이는 중"이라 바탕까지 60칸으로 올라갔다.
    문턱은 그 세 배인 180칸이 되고, 그러면 **아무리 흔들려도 못 알아본다.**
    제 꼬리를 문 셈이다.

    지금은 45초를 들고 아래쪽 10분의 1을 쓴다. 낚시는 기다리는 시간이 길고 낚은
    순간은 짧으므로, 45초 안에는 반드시 조용하던 때가 들어 있다. 그때가 바탕이다.

    같은 까닭으로 **자세가 바뀌어도 바탕은 안 버린다.** 버리면 하필 낚은 그 순간에
    바탕이 없어서, 다시 45초를 채울 때까지 아무것도 못 알아본다.

    ## 되풀이를 세는 것이 핵심이다

    한 번 튀는 것과 계속 까딱거리는 것을 갈라야 한다. 창이 하나 뜨거나 다른
    캐릭터가 지나가면 딱 한 장 튀고 마는데, 매달린 물고기는 보는 내내 튄다.
    그래서 "문턱을 넘은 장이 몇 개인가"를 시간 창 안에서 센다.

    **바로 앞 장하고만 견준다.** 한때 가장 오래된 장과도 견주어 큰 쪽을 썼는데,
    그러면 한 번뿐인 변화가 창에서 밀려날 때까지 몇 장 내리 "많이 바뀜"으로 나와
    되풀이처럼 보였다.
    """

    # 바탕을 잡으려고 들고 있는 시간(초). 낚은 순간보다 훨씬 길어야 한다 —
    # 그래야 한참 흔들려도 그 앞의 조용하던 때가 바탕에 남아 있다.
    BASE_S = 45.0

    # 바탕이 0에 가까울 때 쓸 최소 문턱(칸). 아무것도 안 움직이는 자리에서는
    # 바탕 × 몇 배가 0이라, 잡음 한 칸에도 흔들린다고 하게 된다.
    FLOOR_PX = 5

    def __init__(self, spot: MotionSpot, window) -> None:
        self.spot = spot
        self.window = window
        self.prev: bytes | None = None
        self.scores: list[tuple[float, int]] = []  # 때·점수 (되풀이를 셀 것)
        self.quiet: list[tuple[float, int]] = []  # 때·점수 (바탕을 잡을 것)
        self.last = 0  # 마지막으로 잰 값 (로그에 쓴다)
        self.next_at = 0.0

    def reset(self) -> None:
        """자세가 바뀌었다. 찍어 둔 장과 최근 점수만 버린다.

        **바탕은 안 버린다.** 버리면 하필 낚은 그 순간에 바탕이 없어서, 다시
        채울 때까지 아무것도 못 알아본다. 조용할 때가 어느 만큼인지는 자세가
        바뀐다고 달라지지 않는다.
        """
        self.prev = None
        self.scores.clear()
        self.last = 0

    def due(self, now: float | None = None) -> bool:
        """찍을 때가 됐나. 흔들림 주기보다 촘촘히 찍을 까닭이 없다."""
        return (now or time.perf_counter()) >= self.next_at

    def sample(self, now: float | None = None) -> int | None:
        """한 장 찍어 점수를 낸다. 아직 견줄 것이 없으면 None."""
        spot = self.spot
        if not spot.ready:
            return None
        now = now or time.perf_counter()
        self.next_at = now + spot.gap_s
        rect = spot.rect(self.window)
        if rect is None:
            return None
        try:
            frame = pixel.capture_region(*rect)
        except pixel.CaptureError:
            return None
        buf = frame.buf
        got = None
        if self.prev is not None:
            got = changed_px(self.prev, buf, spot.tol)
            self.last = got
            self.scores.append((now, got))
            self.quiet.append((now, got))
            keep = max(self.spot.span_s * 3.0, 2.0)
            cut = now - keep
            while self.scores and self.scores[0][0] < cut:
                del self.scores[0]
            cut = now - self.BASE_S
            while self.quiet and self.quiet[0][0] < cut:
                del self.quiet[0]
        self.prev = buf
        return got

    # -- 바탕과 문턱 -------------------------------------------------------
    def baseline(self) -> float:
        """조용할 때가 어느 만큼인지. 오래 본 점수들의 아래쪽 10분의 1."""
        if not self.quiet:
            return 0.0
        vals = sorted(v for _t, v in self.quiet)
        return float(vals[len(vals) // 10])

    def threshold(self) -> float:
        """이만큼 넘으면 '움직였다'."""
        spot = self.spot
        if not spot.auto:
            return float(spot.min_px)
        base = self.baseline()
        return max(base * spot.rise, base + self.FLOOR_PX, self.FLOOR_PX)

    def moved(self, span_s: float | None = None) -> int:
        """그 시간 안에 문턱을 넘은 장이 몇이나 되나."""
        if not self.scores:
            return 0
        span = self.spot.span_s if span_s is None else span_s
        edge = self.scores[-1][0] - span
        mark = self.threshold()
        return sum(1 for t, v in self.scores if t >= edge and v >= mark)

    def settled(self) -> bool:
        """바탕을 믿을 만큼은 봤나.

        막 보기 시작했을 때는 바탕이 0이라 무엇이든 문턱을 넘는다. 되풀이를 볼
        만큼 쌓이기 전에는 아무 말도 하지 않는 편이 낫다.
        """
        return (len(self.quiet) >= self.spot.need_frames
                and len(self.scores) >= self.spot.repeats)

    def shaking(self) -> bool:
        """지금 되풀이해서 움직이는 중인가."""
        spot = self.spot
        if not spot.ready or not self.settled():
            return False
        return self.moved() >= spot.repeats

    def describe(self) -> str:
        spot = self.spot
        if not spot.ready:
            return "흔들림 안 정함"
        if not self.settled():
            return f"흔들림 보는 중 ({len(self.quiet)}/{spot.need_frames}장)"
        return (f"흔들림 {self.last}칸 (바탕 {self.baseline():.0f} · 문턱 "
                f"{self.threshold():.0f}) · {spot.span_s:g}초에 "
                f"{self.moved()}장 움직임 (필요 {spot.repeats})")


class Reading:
    """판 한 장에서 읽어 낸 것 전부. 설정 화면과 실행이 같은 것을 본다."""

    __slots__ = ("bar", "bar_px", "bar_w", "fish", "fish_px", "fish_w",
                 "health", "time_px", "gap", "bar_lo", "bar_hi",
                 "fish_lo", "fish_hi", "touch", "raw_touch", "filled", "hint")

    def __init__(self, bar, bar_px, bar_w, fish, fish_px, fish_w, health,
                 time_px, edges=None, raw_edges=None, filled="", hint=""):
        self.bar = bar
        self.bar_px = bar_px
        self.bar_w = bar_w  # 막대의 가로 폭 (px)
        self.fish = fish
        self.fish_px = fish_px
        self.fish_w = fish_w  # 물고기의 가로 폭 — 판마다 다르다
        self.health = health  # 0.0 ~ 1.0
        self.time_px = time_px
        self.gap = (abs(bar - fish) if bar is not None and fish is not None
                    else None)

        # 두 물체의 좌우 끝. **겹쳤는지는 여기서 바로 나온다.**
        got = edges or {}
        self.bar_lo, self.bar_hi = got.get("bar", (None, None))
        self.fish_lo, self.fish_hi = got.get("fish", (None, None))
        self.touch = None
        if None not in (self.bar_lo, self.bar_hi, self.fish_lo, self.fish_hi):
            # 겹친 폭. 음수면 그만큼 떨어져 있다는 뜻이라 그대로 쓸모가 있다 —
            # "얼마나 남았나"를 알려 주므로 다가오는 중인지 가늠할 수 있다.
            self.touch = (min(self.bar_hi, self.fish_hi)
                          - max(self.bar_lo, self.fish_lo))

        # **보이는 그대로의** 겹친 폭. 가려진 부분을 메우기 전 값이다 — 인식
        # 검사가 "메우지 않았으면 못 눌렀을 장면"을 셀 때 쓴다.
        self.filled = filled  # 메웠으면 누가 누구를 가렸는지, 아니면 ""
        self.hint = hint  # 줄어 보이는데 **왜 안 메웠는지** (검사 창이 보여 준다)
        self.raw_touch = self.touch
        raw = raw_edges or {}
        if filled and "bar" in raw and "fish" in raw:
            (blo, bhi), (flo, fhi) = raw["bar"], raw["fish"]
            self.raw_touch = min(bhi, fhi) - max(blo, flo)

    def describe(self, hit_px: float = 10.0) -> str:
        parts = [
            f"막대 {self.bar:.0f}({self.bar_w:.0f}px)" if self.bar is not None
            else f"막대 못 찾음({self.bar_px}칸)",
            f"물고기 {self.fish:.0f}({self.fish_w:.0f}px)"
            if self.fish is not None else f"물고기 못 찾음({self.fish_px}칸)",
        ]
        if self.touch is not None:
            mark = "겹침!" if self.touch >= 0 else ""
            parts.append(
                (f"겹친 폭 {self.touch:.0f}px" if self.touch >= 0
                 else f"{-self.touch:.0f}px 떨어짐") + (" " + mark if mark else ""))
            if self.filled:
                parts.append(f"{self.filled} → 가려진 만큼 메움 "
                             f"(보이는 그대로면 {self.raw_touch:.0f}px)")
        elif self.gap is not None:
            mark = "겹침!" if self.gap <= hit_px else ""
            parts.append(f"거리 {self.gap:.0f}px {mark}".strip())
        parts.append(f"체력 {self.health * 100:.0f}%")
        parts.append(f"시간표시 {self.time_px}칸")
        return " · ".join(parts)


class LiveBoard(fishing.Board):
    """진짜 화면을 읽고 진짜 마우스를 누르는 판.

    [fishing.py]의 순수한 풀이기가 요구하는 것을 화면과 마우스로 채워 준다.
    풀이기는 이 클래스만 보고 돌므로, 시험에서는 가상 시계 판으로 바꿔 끼울 수
    있다.

    **폭을 재는 것이 이 클래스의 숨은 일거리다.** 물고기 크기가 판마다 다르므로
    "겹쳤다고 볼 거리"를 고정값으로 둘 수 없고, 물체의 중심이 튕기는 자리도
    반폭만큼 안쪽이다. 둘 다 화면에서 잰 폭에서 나온다.
    """

    def __init__(self, setup: FishingSetup, ctx: RunContext, rng=None) -> None:
        self.setup = setup
        self.ctx = ctx
        self.rng = rng or random.Random()
        self.rect = setup.board_rect(ctx.window) if ctx.window else None
        self.bar_rgb = parse_color(setup.bar_color)
        self.fish_rgb = parse_color(setup.fish_color)
        self.health_rgb = parse_color(setup.health_color)
        self.time_rgb = parse_color(setup.time_color)
        self.reads = 0
        self.blind = 0
        self._aimed = False
        # 잰 폭. 겹침 거리와 튕기는 자리가 여기서 나온다.
        self._width = {"bar": 0.0, "fish": 0.0}
        # 폭이 트랙을 거의 다 덮어 못 쓴 횟수. 색을 다시 골라야 한다는 뜻이다.
        self._wide: dict[str, int] = {}
        # 실제로 오간 자리. 튕기는 곳을 눈으로 본 뒤에는 어림보다 이쪽이 낫다.
        self._seen = {"bar": [None, None], "fish": [None, None]}
        self._saw_health = False
        # 마지막으로 읽은 **겹친 폭**(px). 음수면 그만큼 떨어져 있다.
        self._touch: float | None = None
        # 상대에게 **안 가려졌을 때** 잰 폭들. 온전한 폭은 여기서 뽑는다.
        self._clean: dict[str, list[float]] = {"bar": [], "fish": []}
        # 가려진 장면에서 잰 둘 사이 거리들 — 덮는 쪽 테두리 굵기를 배운다.
        # 판마다 새 판을 만들므로 Flow가 같은 목록을 넘겨 이어 쓰게 한다.
        self._outline: list[float] = []
        self._fill_note = ""
        # 한 장 읽는 데 드는 시간(초, 이동 평균). 겹칠 때 클릭 속도 배율을 맞출 때 쓴다.
        self.read_cost = 0.007
        # 판을 푸는 도중에도 낚음 근거(빨간 알림·효과음)를 살핀다. Flow가 넣어 준다.
        # 판이 화면에 남아 있어도 낚았으면 거기서 끝내고 곧장 [Ctrl]을 누르게 한다.
        self.catch_check = None
        self.catch_next = 0.0
        self.caught_reason: str | None = None
        # 클릭이 안 나가는 판을 짚는다 — 게임 창이 뒤로 갔으면 앞으로, 3초째면 증거.
        self.born = time.perf_counter()
        self.front_next = 0.0
        self.dry_report = None
        self.dry_done = False

    @classmethod
    def reader(cls, setup: FishingSetup, window=None) -> "LiveBoard":
        """마우스는 안 쓰고 **읽기만** 하는 판.

        설정 화면과 인식 검사 창이 쓴다. 예전에는 그쪽에서 __new__로 필드를 손수
        채웠는데, 이 클래스에 필드가 하나 늘 때마다 그쪽이 조용히 깨졌다.
        """

        class _Idle:
            def __init__(self, win):
                self.window = win
                self.stopped = False

            def check(self):
                pass

            def log(self, msg):
                pass

            def sleep(self, seconds):
                pass

            def point_to(self, client_xy, screen_xy):
                pass

            def button_down(self, button):
                pass

            def button_up(self, button):
                pass

        return cls(setup, _Idle(window))

    # -- 화면에서 읽기 -----------------------------------------------------
    def snapshot(self):
        """판 한 장. 못 찍으면 None.

        **판 자리는 찍을 때마다 지금 창 위치에서 다시 구한다.** 예전에는 낚시를 시작할
        때 한 번 구해 두고 끝까지 썼다. 낚시 도중 게임 창이 조금이라도 움직이면 그
        뒤로는 엉뚱한 곳을 찍어 **미니게임을 한 번도 못 알아봤다** — 머리 위 두드리기처럼
        창 위치를 매번 읽는 것들은 멀쩡해서, 두드리고 다시 던지기만 몇 시간을 되풀이했다
        (9시간 세션 기록: 80분 뒤로 '다시 던짐' 5,540번). 좌표 변환은 호출 한 번이라
        캡처에 비하면 공짜다.
        """
        window = self.ctx.window
        if window is not None:
            fresh = self.setup.board_rect(window)
            if fresh is not None:
                self.rect = fresh
        rect = self.rect
        if rect is None:
            return None
        try:
            return pixel.capture_region(*rect)
        except pixel.CaptureError:
            return None

    def look(self, frame) -> Reading:
        """찍어 둔 한 장에서 네 가지를 읽는다.

        **한 줄이 아니라 띠로 훑는다.** 사람이 줄 하나를 정확히 짚기도 어렵고,
        물고기처럼 속이 빈 그림은 하필 그 줄에 아무것도 안 걸린다.
        """
        setup = self.setup
        width = frame.w
        found = {}
        edges: dict[str, tuple[float, float]] = {}
        spans: dict[str, float] = {}
        for role, rgb, tol, box in (
            ("bar", self.bar_rgb, setup.bar_tol, setup.bar_box()),
            ("fish", self.fish_rgb, setup.fish_tol, setup.fish_box()),
        ):
            if rgb is None:
                found[role] = (None, 0, 0.0)
                continue
            x0, x1, y0, y1 = box
            centre, count, left, right = fishing.scan_span(
                frame.buf, width, rgb, tol, x0, x1, y0, y1)
            if count < setup.track_min_px:
                found[role] = (None, count, 0.0)
                continue
            span = max(0.0, float(right - left + 1))
            # **트랙을 거의 다 덮는 것은 그 물체가 아니다.**
            #
            # 실제 기록에서 물고기 폭이 499px로 잡힌 적이 있다. 트랙이 518px이니
            # 거의 전부다 — 물고기가 아니라 배경이나 다른 UI가 그 색에 걸린 것이다.
            # 그 폭으로 겹침 거리를 뽑으면 207px이 되어 **사실상 늘 겹쳤다고 보고**
            # 누르게 되고, 누르는 족족 빗나가 체력을 도로 채워 준다.
            room = max(1.0, float(setup.track_x1 - setup.track_x0))
            if span > room * WIDEST:
                # **폭만 버리고 자리는 살린다.** 여기서 한 번 크게 데었다.
                #
                # 실제 설정에서 물고기 폭이 499px(트랙 518px)로 잡혔다. 그래서
                # "이건 물고기가 아니다"라고 통째로 물리쳤더니, **미니게임에서
                # 클릭이 한 번도 안 나갔다** — 겹침을 재려면 물고기 자리가
                # 있어야 하는데 그걸 없앤 셈이다.
                #
                # 폭이 오염됐다고 자리까지 틀린 것은 아니다. 가운데는 맞은 칸들의
                # 평균이라 가장자리에 잡티 몇 개가 걸려도 거의 안 흔들리고,
                # 실제로 그 설정에서도 겹침 정확도는 높았다. 틀린 것은 폭 하나뿐이니
                # 폭만 안 쓰면 된다.
                #
                # **가장자리는 버린다.** 폭이 오염됐으면 가장자리도 오염된 것이다 —
                # 그 가장자리로 겹친 폭을 재면 늘 겹쳤다고 나와 헛클릭만 쌓인다.
                # 가장자리가 없으면 풀이기는 가운데 거리로 판단한다.
                self._wide[role] = self._wide.get(role, 0) + 1
                found[role] = (centre, count, 0.0)
                continue
            edges[role] = (float(left), float(right))
            spans[role] = span
            found[role] = (centre, count, span)

        health = 0.0
        if self.health_rgb is not None:
            hx0, hx1, hy0, hy1 = setup.health_box()
            health = fishing.fill_of(frame.buf, width, self.health_rgb,
                                     setup.health_tol, hx0, hx1, hy0, hy1)
        time_px = 0
        if self.time_rgb is not None:
            tx0, tx1, ty0, ty1 = setup.time_box()
            _c, time_px = fishing.scan_band(frame.buf, width, self.time_rgb,
                                            setup.time_tol, tx0, tx1, ty0, ty1)

        bar, bar_px, bar_w = found["bar"]
        fish, fish_px, fish_w = found["fish"]
        self._learn_widths(edges, spans, found)
        raw_edges = dict(edges)
        filled = self._fill_hidden(edges)
        return Reading(bar, bar_px, bar_w, fish, fish_px, fish_w, health,
                       time_px, edges, raw_edges, filled, self._fill_note)

    def _learn_widths(self, edges, spans, found) -> None:
        """온전한 폭을 쌓는다. **상대에게 붙어 있을 때 잰 폭은 안 쓴다.**

        예전에는 읽을 때마다 그 폭을 그대로 썼다. 막대가 물고기를 덮고 있는 동안에는
        물고기가 덮인 만큼 좁게 잡히므로, 겹칠 때마다 폭이 쪼그라들고 거기서 뽑는
        겹침 거리까지 따라 줄었다. 가려진 부분을 메우려면 온전한 폭이 있어야 하는데,
        그 폭마저 가려진 채로 재면 메울 길이 없다.

        그래서 **떨어져 있을 때 잰 것만** 모아 가운뎃값을 쓴다. 가운뎃값이라 잡티
        한두 장에 안 흔들린다.
        """
        for role, other in (("bar", "fish"), ("fish", "bar")):
            span = spans.get(role, 0.0)
            if span <= 0:
                continue
            theirs = edges.get(other)
            # 상대 자리는 있는데 가장자리가 없으면(폭 오염) 붙어 있는지 알 수 없다.
            # 모르는 채로 쌓으면 가려져 좁아진 폭이 온전한 폭으로 섞여 든다.
            unknown = theirs is None and found.get(other, (None,))[0] is not None
            if unknown or (theirs is not None
                           and _gap(edges[role], theirs) <= HIDE_PX):
                if not self._clean[role]:
                    # 아직 온전한 것을 한 번도 못 봤다. 없는 것보다는 낫다.
                    self._width[role] = span
                continue
            kept = self._clean[role]
            kept.append(span)
            if len(kept) > CLEAN_KEEP:
                del kept[0]
            ordered = sorted(kept)
            self._width[role] = ordered[len(ordered) // 2]

    def _fill_hidden(self, edges) -> str:
        """**가려진 부분을 메운다.** 메웠으면 무엇이 무엇을 가렸는지, 아니면 "".

        ## 여기서 클릭이 통째로 사라졌다

        막대가 물고기 위에 그려지면 물고기는 막대에 덮인 만큼 안 보인다. 그러면
        물고기의 가장자리는 **늘 막대 바로 옆으로 물러난다** — 겹친 폭을 재면
        막대가 물고기 한가운데를 지나는 동안에도 0px, 테두리가 있으면 -2px이다.
        "겹친 폭 ≥ 필요한 폭"이 한 번도 안 서므로 **겹치는 내내 한 번도 안 눌렀다.**
        (시늉 판으로 재 봤다: 실제로 20px 겹쳐 있는 동안 잰 값이 내내 -2px.)

        알아보는 법은 둘이다.

            · 보이는 폭이 온전한 폭보다 눈에 띄게 좁다
            · 좁아진 쪽 가장자리에 상대가 딱 붙어 있다 (테두리·번짐만큼 떨어질 수 있다)

        둘 다 서면 가려진 것이다. 줄어든 쪽을 온전한 폭만큼 상대 쪽으로 늘린다.
        반대로 물고기가 막대를 덮는 게임이어도 똑같이 메운다.
        """
        self._fill_note = ""
        if "bar" not in edges or "fish" not in edges:
            return ""
        notes = []
        wall_lo = float(self.setup.track_x0) + WALL_PX
        wall_hi = float(self.setup.track_x1) - WALL_PX
        outline = self.outline_px()
        for role, other, name in (("fish", "bar", "막대가 물고기를 가림"),
                                  ("bar", "fish", "물고기가 막대를 가림")):
            full = self._width.get(role, 0.0)
            lo, hi = edges[role]
            olo, ohi = edges[other]
            shrink = full - (hi - lo)
            # 조금만 좁아져도 본다. 문턱을 10%로 두었더니 겹침 첫 8~9px은 여전히
            # 안 메워져 그 사이 클릭이 안 나갔다. 헛메움은 아래 "붙음"이 막는다.
            if full <= 0 or shrink <= max(SHRINK_PX, full * 0.04):
                continue
            deep = shrink >= max(DEEP_PX, self._width.get(other, 0.0) * 0.4)
            # 얼마나 떨어져도 가린 것으로 볼지. 테두리를 배웠으면 그 굵기 + 번짐,
            # 못 배웠으면 크게 줄었을 때만 넉넉히, 조금 줄었을 때는 빠듯하게.
            #
            # **배운 값이 처음 켰을 때보다 빠듯하게 만들면 안 된다.** 판을 거듭하며
            # 테두리 굵기를 모으는데, 0px짜리가 섞여 가운뎃값이 0으로 쏠리면 한계가
            # 3px로 좁아져 4px 테두리 너머의 가림을 못 메우고 — **겹쳐도 한 번도 안
            # 눌렀다.** 긴급정지 후 다시 켜면 배운 게 지워져 고쳐지던 까닭이 이것이다.
            # 그래서 처음 켰을 때의 한계를 바닥으로 두고, 배운 값은 넓히는 데만 쓴다.
            reach = BOOT_PX if deep else OCCLUDE_PX
            if outline is not None:
                reach = max(reach, outline + OCCLUDE_PX)
            if olo < lo and ohi <= hi:
                from_left = True    # 상대가 왼쪽에서 덮었다
                gap = lo - ohi
                far_at_wall = hi >= wall_hi
            elif ohi > hi and olo >= lo:
                from_left = False   # 상대가 오른쪽에서 덮었다
                gap = olo - hi
                far_at_wall = lo <= wall_lo
            else:
                continue
            if gap > reach:
                if gap <= reach + 12:
                    self._fill_note = (
                        f"{'물고기' if role == 'fish' else '막대'}가 {hi - lo:.0f}px"
                        f"(온전하면 {full:.0f}px)로 줄었고 상대와 {gap:.0f}px — "
                        f"가림으로 보는 한계 {reach:.0f}px"
                        + ("" if outline is not None else " (테두리 아직 못 배움)"))
                continue
            if far_at_wall:
                continue  # 먼 쪽이 벽에 닿아 있다 — 벽에 잘린 것일 수 있다
            if from_left:
                edges[role] = (min(lo, hi - full), hi)
            else:
                edges[role] = (lo, max(hi, lo + full))
            if deep:
                # 누가 봐도 가려진 장면이다. 이때의 거리가 곧 테두리 굵기다.
                kept = self._outline
                kept.append(max(0.0, min(float(BOOT_PX), gap)))
                if len(kept) > OUTLINE_KEEP:
                    del kept[0]
            notes.append(name)
        return " · ".join(notes)

    def outline_px(self) -> float | None:
        """배운 테두리 굵기(px). 아직 덜 모았으면 None."""
        if len(self._outline) < OUTLINE_MIN:
            return None
        ordered = sorted(self._outline)
        return ordered[len(ordered) // 2]

    def peek(self) -> Reading | None:
        """한 장 찍어 읽는다. 못 찍으면 None."""
        frame = self.snapshot()
        return None if frame is None else self.look(frame)

    def signals(self, got: Reading | None) -> list[str]:
        """미니게임이 떠 있다고 볼 **근거들**.

        예전에는 시간 표시 하나만 봤다. 그 문턱이 영역보다 커서 넘을 수 없는 값이
        되어 있었더니, 미니게임이 멀쩡히 떠 있는데도 **한 번도 못 알아봤다.**
        근거를 여럿 두면 하나가 어긋나도 나머지가 받쳐 준다.
        """
        if got is None:
            return []
        setup = self.setup
        out = []
        if self.time_rgb is not None and got.time_px >= setup.time_min_px:
            out.append(f"시간표시 {got.time_px}칸")
        if got.bar is not None:
            out.append(f"막대 {got.bar:.0f}")
        if got.fish is not None:
            out.append(f"물고기 {got.fish:.0f}")
        if got.health > 0:
            out.append(f"체력 {got.health * 100:.0f}%")
        return out

    def enough(self, got: "Reading | None") -> list[str]:
        """미니게임에 **들어가도 될 만큼** 근거가 서는가.

        보여 주기용 signals()보다 까다롭다. 실제 기록에서 46판 중 41판이 여기서
        헛디딘 것이었다 — 물고기 색이 2칸 걸린 것만으로 미니게임이라 보고 들어가,
        0.2초 만에 아무것도 못 하고 나왔다. 그 41판이 고스란히 낭비였다.

        **처음에는 "막대와 물고기를 둘 다 찾아야 한다"로 두었다가 크게 데었다.**
        어떤 설정에서는 물고기 폭이 오염돼 자리를 못 잡는데, 그러면 미니게임에
        아예 못 들어가서 클릭이 한 번도 안 나간다. 하나가 어긋나면 통째로 멈추는
        조건은 여기 두면 안 된다.

        그래서 **근거 둘**이면 들어간다. 헛디딤은 대개 한 가지만 걸리므로(색 몇 칸)
        그것으로 걸러지고, 진짜 판은 막대·물고기·체력·시간표시 중 둘 이상이
        웬만하면 선다. 시간표시는 미니게임에만 있으므로 그것 하나면 충분하다.
        """
        if got is None:
            return []
        marks = self.signals(got)
        if (self.time_rgb is not None
                and got.time_px >= self.setup.time_min_px):
            return marks
        return marks if len(marks) >= 2 else []

    def present(self) -> bool:
        """지금 미니게임이 떠 있나."""
        return bool(self.enough(self.peek()))

    # -- 풀이기가 요구하는 것 ---------------------------------------------
    def read(self):
        """(시각, 막대 x, 물고기 x, 남은 체력). 창이 닫혔으면 None."""
        began = time.perf_counter()
        frame = self.snapshot()
        when = time.perf_counter()
        self.read_cost = self.read_cost * 0.9 + (when - began) * 0.1
        if frame is None:
            self.blind += 1
            return None if self.blind >= BLIND_LIMIT else (when, None, None,
                                                           HEALTH_SCALE)
        got = self.look(frame)
        self._touch = got.touch
        self.reads += 1
        if not self.signals(got):
            # 한 번 안 보인다고 끝내지 않는다 — "GO!!" 연출이나 잠깐의 가림에도
            # 판이 끝나 버린다. 이만큼 이어지면 그때 닫힌 것으로 본다.
            self.blind += 1
            if self.blind >= BLIND_LIMIT:
                return None
        else:
            self.blind = 0

        for role, value in (("bar", got.bar), ("fish", got.fish)):
            if value is None:
                continue
            slot = self._seen[role]
            slot[0] = value if slot[0] is None else min(slot[0], value)
            slot[1] = value if slot[1] is None else max(slot[1], value)

        health = got.health
        if health > 0:
            self._saw_health = True
        elif not self._saw_health:
            # 게이지가 아직 안 그려졌을 뿐이다. 여기서 0을 주면 시작하자마자
            # "다 깎았다"가 되어 판을 깬 것으로 세어 버린다.
            return (when, got.bar, got.fish, HEALTH_SCALE)
        return (when, got.bar, got.fish, int(round(health * HEALTH_SCALE)))

    def touch(self) -> float | None:
        """마지막으로 본 **겹친 폭**(px). 둘 중 하나라도 못 봤으면 None.

        0 이상이면 닿아 있다. 음수면 그만큼 떨어져 있다는 뜻이다.
        """
        return self._touch

    def half(self, which: str) -> float:
        """그 물체의 반폭."""
        return self._width.get(which, 0.0) / 2.0

    def track_range(self, which: str = "bar") -> tuple[float, float]:
        """그 물체의 **중심**이 오가는 좌우 끝.

        눈으로 튕기는 자리를 본 뒤에는 그것을 쓴다. 아직 못 봤으면 트랙 사각형에서
        **반폭만큼 안쪽**으로 잡는다 — 중심은 사각형 끝까지 못 가기 때문이다.
        예전에는 사각형 끝을 그대로 썼는데, 60px짜리 물고기면 양쪽으로 30px씩
        어긋난 자리를 튕김점으로 삼는 셈이라 예측이 통째로 틀렸다.
        """
        lo, hi = self._seen.get(which, [None, None])
        if lo is not None and hi is not None and hi > lo:
            return (float(lo), float(hi))
        half = self.half(which)
        return (float(self.setup.track_x0) + half,
                float(self.setup.track_x1) - half)

    @property
    def hit_px(self) -> float:
        """겹쳤다고 볼 거리.

        **물고기 크기가 판마다 다르다.** 고정값은 어떤 판에선 좁고 어떤 판에선
        넓다. 잰 두 폭의 반씩을 더하면 가장자리가 맞닿는 거리가 되고, 비율 1.0이
        곧 "닿기만 하면 겹친 것" — 게임도 그렇게 판정한다.
        """
        setup = self.setup
        if setup.hit_mode != "auto":
            return setup.hit_px
        bar_w = self._width.get("bar", 0.0)
        fish_w = self._width.get("fish", 0.0)
        if bar_w <= 0 or fish_w <= 0:
            # 폭을 못 쟀다. 사람이 정해 둔 값으로 간다 — 오염된 폭에서 뽑은
            # 터무니없는 거리(실제로 207px이 나온 적이 있다)보다 훨씬 낫다.
            return setup.hit_px
        touching = (bar_w + fish_w) * 0.5
        if setup.learn_hit:
            # **비율을 두 번 곱하면 안 된다.** 배우기를 켜 두면 배수는 성적을
            # 보고 스스로 정하므로, 여기서 사람이 적어 둔 비율까지 곱하면 두 번
            # 좁아진다. 실제로 20.5px짜리 겹침이 0.8 × 0.6 = 9.8px이 되어,
            # 21초 동안 겹침이 세 번밖에 안 잡힌 판이 있었다.
            #
            # 배우기를 켠 동안 [비율] 칸은 잠시 쉰다 — 그 몫을 배수가 대신한다.
            return touching
        return touching * setup.hit_ratio

    # -- 마우스 ------------------------------------------------------------
    def aim(self) -> None:
        """클릭 범위 안 아무 데나 겨눈다. 한 구간에 한 번이면 된다."""
        if self._aimed:
            return
        setup = self.setup
        window = self.ctx.window
        if window is None or setup.click_w <= 0 or setup.click_h <= 0:
            return
        cx = setup.click_x + self.rng.randrange(setup.click_w)
        cy = setup.click_y + self.rng.randrange(setup.click_h)
        self.ctx.point_to((cx, cy), window.client_to_screen(cx, cy))
        self._aimed = True
        self._aim_xy = (cx, cy)

    def rearm(self) -> None:
        """다음 구간을 위해 겨눔을 푼다."""
        self._aimed = False

    def sleep_until(self, when: float) -> None:
        """그때까지 기다린다. **자기 전에 미리 겨눈다** — 어차피 잘 참이다."""
        self.aim()
        left = when - time.perf_counter()
        if left > 0:
            sender.precise_sleep(left)

    def click(self) -> None:
        """겹쳤을 때 누른다. **클릭 속도 배율**이 1이면 예전과 똑같다.

        겹친 동안의 클릭 한 번은 '한 장 읽기 + 누르고 있기'만큼 걸린다(실제 기록:
        읽기 7ms + 누름 33ms ≈ 40ms, 초당 25번). 배율 k면 이 주기를 1/k로 줄인다.
        읽기는 줄일 수 없으니 **누르는 시간을 줄이고**, 그걸로도 모자라면(누름이
        바닥에 닿으면) 한 번 읽을 때 **여러 번** 누른다.
        """
        self.aim()
        hold_s, times = self.click_plan()
        with ARBITER.dispatch():
            for i in range(times):
                if i:
                    sender.precise_sleep(CLICK_GAP_S)
                self.ctx.button_down(self.setup.click_button)
                sender.precise_sleep(hold_s)
                self.ctx.button_up(self.setup.click_button)
        self.clicks_sent = getattr(self, "clicks_sent", 0) + times
        note_input(self.ctx, f"클릭 {getattr(self, '_aim_xy', ('?', '?'))} "
                             f"{hold_s * 1000:.0f}ms" + (f" ×{times}" if times > 1 else ""),
                   f"미니게임 겹침 {self.clicks_sent}번째", log=False)

    def click_plan(self) -> tuple[float, int]:
        """(누르고 있을 시간, 한 번에 누를 횟수). 배율에 맞춰 셈한다."""
        base = max(0.0, self.setup.click_hold_ms) / 1000.0
        speed = float(getattr(self.setup, "overlap_speed", 1.0) or 1.0)
        if speed <= 1.0:
            return (base, 1)           # 1배 이하 — 예전 그대로
        read = max(0.0, self.read_cost)
        target = (read + base) / speed  # 클릭 한 번에 쓸 시간
        hold = target - read
        if hold >= MIN_HOLD_S:
            return (hold, 1)
        # 누름을 바닥까지 줄여도 모자라다 — 한 번 읽을 때 여러 번 누른다.
        per = MIN_HOLD_S + CLICK_GAP_S
        room = target - per
        if room <= 0:
            return (MIN_HOLD_S, MAX_BURST)
        times = int(round(read / room)) + 1
        return (MIN_HOLD_S, max(1, min(MAX_BURST, times)))

    def alive(self) -> bool:
        if self.ctx.stopped:
            return False
        now = time.perf_counter()
        if not getattr(self, "clicks_sent", 0):
            # 아직 한 번도 못 눌렀다. 게임 창이 뒤로 가 있으면 화면이 가려져
            # 막대·물고기를 못 보고, 눌러도 게임이 못 받는다.
            if now >= self.front_next:
                self.front_next = now + FRONT_LOOK_S
                keep_front(self.ctx, "미니게임인데 게임 창이 앞에 없습니다")
            if not self.dry_done and now - self.born >= DRY_ROUND_S:
                self.dry_done = True
                if self.dry_report is not None:
                    self.dry_report(self)
                # 판을 거듭하며 배운 것(테두리 굵기)을 지운다 — 다시 켠 것과 같다.
                # 이 판에서 곧바로 처음처럼 다시 본다.
                del self._outline[:]
        if self.catch_check is not None:
            if now >= self.catch_next:
                self.catch_next = now + CATCH_LOOK_S
                reason = self.catch_check()
                if reason:
                    self.caught_reason = reason  # 낚았다 — 판을 여기서 끝낸다
                    return False
        return True

    def closed_verdict(self, health_before) -> str:
        """창이 사라졌다. 깬 것인가.

        마지막 한 방과 창이 닫히는 사이는 몇 ms뿐이라 **체력 0을 못 보고 지나가는
        일이 흔하다.** 그래서 '거의 다 깎였으면 깬 것'으로 본다. 다만 한 번도 못
        본 판까지 깼다고 하면 안 된다.
        """
        if not self._saw_health or health_before is None:
            return fishing.ABORTED
        ratio = health_before / HEALTH_SCALE
        return (fishing.CLEAR if ratio <= self.setup.clear_ratio
                else fishing.ABORTED)


def note_input(ctx, what: str, why: str = "", log: bool = True,
               style: str = "") -> None:
    """보낸 입력을 **[실행 상태] 창의 '보낸 입력'**에 남긴다. log면 로그에도 적는다.

    낚시는 매크로 재생과 달리 키·클릭을 직접 보내서, 예전에는 상태 창에 "보낸 입력
    0"으로만 나왔다. 무엇이 언제 무엇 때문에 나갔는지 안 보이면 멈췄을 때 짚을 수가
    없다.

    두드리기(초당 몇 번)와 미니게임 클릭(한 판에 수십 번)은 log=False로 부른다 —
    상태 창에는 다 남지만, 로그에 쏟으면 다른 줄이 묻히고 로그를 쓰는 비용이 클릭
    박자를 흔든다.
    """
    text = f"{what} — {why}" if why else what
    board = getattr(ctx, "board", None)
    shown = style
    if board is not None:
        shown = board.sent(text, "낚시", style) or ""
    # **로그에는 드문 입력만** 적는다. 낚을 때마다 똑같이 나가는 "[ctrl] 다시
    # 던지기" 같은 줄은 처음 몇 번만 적고, 그 뒤로는 상태 창에만 남긴다 — 로그가
    # 같은 줄로 도배되면 정작 봐야 할 줄이 묻힌다.
    if log and (shown or board is None):
        logger = getattr(ctx, "log", None)
        if callable(logger):
            logger(f"  ↳ {text}")


def tap_key(name: str, ctx: RunContext, why: str = "", style: str = "") -> bool:
    vk = vk_of(name)
    if vk is None:
        return False
    with ARBITER.dispatch():
        ctx.key_down(vk)
        ctx.sleep(0.04)
        ctx.key_up(vk)
    note_input(ctx, f"키 [{name}]", why, style=style)
    return True


def hold_key(name: str, ctx: RunContext, seconds: float, why: str = "") -> bool:
    """키를 그만큼 **붙잡고 있다가** 뗀다.

    땅을 내리칠 때는 톡 누르는 것으로 안 되고 얼마간 붙잡고 있어야 한다. 붙잡는
    동안 다른 입력이 끼어들면 게임이 헷갈리므로 그 사이는 통째로 잡아 둔다.
    """
    vk = vk_of(name)
    if vk is None:
        return False
    with ARBITER.dispatch():
        ctx.key_down(vk)
        ctx.sleep(max(0.0, seconds))
        ctx.key_up(vk)
    note_input(ctx, f"키 [{name}] {seconds:.2f}초 누름", why)
    return True


def cast(setup: FishingSetup, ctx: RunContext) -> None:
    """낚싯대를 던진다."""
    if not tap_key(setup.cast_key, ctx, "낚싯대 던지기"):
        raise Aborted(f"낚시 키 '{setup.cast_key}'를 모르겠습니다.")


def click_at(ctx: RunContext, screen_xy: tuple[int, int],
             button: str = "left") -> None:
    """그 자리를 한 번 누른다. 찌를 누를 때 쓴다."""
    win = ctx.window
    client = win.screen_to_client(*screen_xy) if win is not None else screen_xy
    ctx.point_to(client, screen_xy)
    with ARBITER.dispatch():
        ctx.button_down(button)
        ctx.sleep(0.04)
        ctx.button_up(button)
    note_input(ctx, f"클릭 {button} {tuple(client)}", "찌 누르기")


def window_at(x: int, y: int) -> str:
    """화면의 그 점을 차지한 창의 제목. 게임 창이 가려졌는지 볼 때 쓴다."""
    import ctypes
    from ctypes import wintypes
    try:
        user32 = ctypes.windll.user32
        user32.WindowFromPoint.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.GetAncestor.restype = wintypes.HWND
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        hwnd = user32.GetAncestor(user32.WindowFromPoint(wintypes.POINT(x, y)), 2)
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        return buf.value or f"(제목 없음 {hwnd})"
    except Exception as exc:  # noqa: BLE001
        return f"(알 수 없음 {exc!r})"


def keep_front(ctx, why: str) -> bool:
    """게임 창이 앞에 없으면 앞으로 올린다. 올렸으면 True."""
    window = getattr(ctx, "window", None)
    if window is None:
        return False
    try:
        if window.is_foreground():
            return False
        window.activate(timeout=0.3)
    except Exception:  # noqa: BLE001 — 창이 사라졌을 수도 있다
        return False
    note_input(ctx, "게임 창을 앞으로", why)
    return True


def wait_for_close(board: "LiveBoard", ctx: RunContext,
                   limit_s: float = 5.0) -> None:
    """미니게임 창이 사라지기를 기다린다. 안 사라져도 그냥 넘어간다."""
    deadline = time.perf_counter() + limit_s
    while time.perf_counter() < deadline:
        ctx.check()
        if not board.present():
            return
        ctx.sleep(POLL_S)


# --------------------------------------------------------------------------
# 흐름 — 상태 기계
# --------------------------------------------------------------------------
# 아무 일도 없을 때 다시 던지기 전에 최소한 이만큼은 기다린다(초).
CAST_GAP_S = 2.0

# 미니게임 없이 '다시 던짐'이 이만큼 이어지면(두드리기 제한 5초 기준 약 30초) 왜 못
# 알아보는지 증거(인식 값 · 창 상태 · 사진)를 한 번 남긴다.
STUCK_NUDGES = 6

# 버프 중첩 알림 — 닫은 뒤 다시 안 누를 시간(초), 낚시중에 살피는 간격(초),
# 알림이 뜬 버프를 다시 걸어 볼 때까지(초).
POPUP_QUIET_S = 1.0
# '다시 던짐'이 이만큼 이어지면 던지기 전에 낚싯대 키부터 누른다.
ROD_AFTER_NUDGES = 2
# 겹칠 때 클릭 속도 배율을 올릴 때: 누르고 있을 최소 시간 · 연달아 누를 때 사이 ·
# 한 번 읽을 때 누를 최대 횟수. 너무 짧게 누르면 게임이 클릭으로 안 칠 수 있다.
MIN_HOLD_S = 0.008
CLICK_GAP_S = 0.004
MAX_BURST = 6
# 되살릴 때 [Esc]를 이 간격으로 잇따라 누른다(초).
ESC_GAP_S = 0.06
# 낚은 뒤 이만큼은 중첩 알림을 안 살핀다(초). 낚음의 빨간 글씨가 중첩 알림처럼
# 보여 [Esc]를 누르면, 막 던진 낚시가 취소된다.
AFTER_CATCH_HOLD_S = 4.0
# 낚고 [Ctrl]을 누른 뒤 이만큼은 미니게임을 새로 안 연다(초). 입질까지는 몇 초가
# 걸리므로 진짜 판일 리 없고, 사라지는 중인 판을 다시 붙잡아 30초를 날리게 된다.
AFTER_CATCH_BOARD_S = 2.5
# 처음 던지기 전, 버프 뒤 늦게 뜨는 중첩 알림을 이만큼 지켜보고 닫는다(초).
FIRST_CAST_WATCH_S = 2.0
POPUP_POLL_S = 0.2
STACK_RETRY_S = 60.0


class Flow:
    """낚시 한 세션의 상태.

        낚시중 ─ 머리 위를 0.1~0.3초마다 두드린다
          │
          └─ 미니게임이 뜨면 ─▶ 두드리기를 멈추고 겹칠 때만 누른다
                                  │
                                  └─▶ 판이 사라짐 ─▶ 무조건 다시 던진다
                                        (그 사이 낚음 근거를 보면 세어 둔다)

    **지금 화면이 어느 상태인지 보고** 거기 맞는 것을 한다. 정해진 순서대로
    밀어붙이면 중간에 한 번 어긋난 뒤로 계속 어긋난다.

    다시 던지는 것과 낚음을 세는 것을 **갈라 놓았다.** 예전에는 빨간 글씨를 봐야만
    다시 던졌는데, 그러면 글씨를 한 번 못 볼 때마다 낚시가 통째로 멈췄다. 지금은
    판이 사라진 것만으로 던지고, 세는 일은 근거가 보이면 덤으로 한다.
    """

    def __init__(self, setup: FishingSetup, ctx: RunContext, find_macro=None,
                 find_rule=None):
        self.setup = setup
        self.ctx = ctx
        self.find_macro = find_macro
        self.find_rule = find_rule
        # 피로도 — 확인한 횟수, 매크로를 돌린 횟수, 마지막으로 무슨 일이 있었나.
        self.fatigue_checks = 0
        self.fatigue_runs = 0
        self.fatigue_shot = False  # 못 읽은 자리를 그림으로 남겼나 (한 판에 한 번)
        self.last_fatigue = ""
        self.fatigue_value: int | None = None  # 지난번에 읽은 피로도
        self.dry_streak = 0  # 클릭이 한 번도 안 나간 판이 몇 번 잇따랐나
        self.board = LiveBoard(setup, ctx)
        self.rng = random.Random()
        self.last_cast = 0.0
        self.next_tap = 0.0
        # 지금 두드리기 판이 언제 시작됐나. 미니게임을 푸는 동안은 안 센다.
        self.tap_since = 0.0
        self.nudges = 0  # 두드리다 지쳐 다시 던진 횟수
        self.revives = 0  # 한참 못 낚아 되살린 횟수
        self.alive_at = 0.0  # 마지막으로 "낚시가 돌고 있다"고 본 때
        # 미니게임 없이 '다시 던짐'만 이어진 횟수. 판을 풀면 0으로 돌아간다.
        self.nudge_streak = 0
        self.shown_at = 0.0  # 실행 상태 창의 '낚시' 줄을 마지막으로 바꾼 때
        # 버프 — 이름마다 언제까지 유지되는지.
        self.buff_until: dict[str, float] = {}
        self.buff_runs = 0
        self.last_buffs = ""
        # 버프 중첩 알림을 닫은 횟수와, 다음에 살필 시각·다시 누르지 않을 시각.
        self.popups = 0
        self.popup_next_at = 0.0
        self.popup_quiet_until = 0.0
        self.popup_hold_until = 0.0  # 낚은 직후 — 중첩 알림을 안 살피는 때까지
        self.board_hold_until = 0.0  # 낚은 직후 — 미니게임을 새로 안 여는 때까지
        # 얼음낚시 — 땅이 다시 얼기 전에 파야 한다.
        self.next_dig = 0.0
        self.digs = 0
        self.last_dig_keys = ""
        self.caught = 0
        self.casts = 0
        self.taps = 0
        # 빨간 알림은 몇 초 떠 있는다. 떠 있는 내내 "낚았다"고 하면 안 되므로
        # **없다가 생긴 순간**만 센다.
        self.notice_on = False
        self.notice_until = 0.0
        self.notice_next_at = 0.0  # 빨간 글씨를 다음에 볼 시각
        # 낚싯대 끝 흔들림 — 색으로 못 가리는 자세를 움직임으로 가린다.
        self.motion = MotionWatch(setup.catch_motion, ctx.window)
        self.motion_until = 0.0
        # 판이 끝난 시각. 0이 아니면 "다시 던져야 하는데 아직 안 던졌다"는 뜻.
        self.round_over_at = 0.0
        self.closed_catch = False  # 이번 판은 창이 사라져 낚음으로 봤나
        self.dry_reports = 0  # 클릭이 안 나간 판의 증거를 남긴 횟수
        self.last_dry: dict | None = None
        self.recasts = 0
        self.last_catch_reason = ""
        # 효과음. 소리는 흘러가므로 **따로 도는 실**이 계속 받아 둔다 — 우리가
        # 미니게임을 푸느라 몇 초씩 딴짓하는 동안에도 놓치지 않으려는 것이다.
        self.ear: sound.Ear | None = None
        self.sound_at = 0.0  # 여기까지는 이미 들어 봤다
        self.sound_until = 0.0
        self.sound_best = 0.0  # 마지막으로 얼마나 닮았었나 (로그에 쓴다)
        # 지난 판에서 들린 클릭 소리. 클릭 소리를 안 배웠으면 None.
        self.last_click_sounds: dict | None = None
        # 배운 테두리 굵기 표본. 판을 넘겨 이어 쓴다 — 판마다 처음부터 배우면
        # 판 첫머리의 얕은 겹침을 번번이 놓친다.
        self.outline: list[float] = []
        self.last_hit_px = 0.0
        self.last_widths = (0.0, 0.0)
        self.state = None  # 마지막으로 알린 상태
        self.said_at = 0.0  # 그때 시각 (같은 상태를 되풀이해 알리지 않으려고)
        self.enter_signals = []  # 미니게임을 무엇으로 알아봤나
        self.last_reads = 0

    # -- 귀 --------------------------------------------------------------
    def open_ear(self) -> str:
        """효과음을 배워 뒀으면 듣기 시작한다. 무슨 일이 있었는지 한 줄로."""
        setup = self.setup
        cue = setup.catch_sound
        clicks = ("클릭 소리 — 맞음 "
                  + ("배움" if setup.hit_sound.ready else "안 배움")
                  + " · 빗나감 "
                  + ("배움" if setup.miss_sound.ready else "안 배움"))
        # **클릭 소리만 배워 둬도 연다.** 클릭 소리는 "게임이 우리 클릭을 받았나"를
        # 알려 주는 유일한 근거라, 성공 효과음이 없다고 귀를 닫으면 그것까지 잃는다.
        if not (cue.ready or setup.hit_sound.ready or setup.miss_sound.ready):
            return "성공 효과음 — 안 배움 · " + clicks
        # **게임 소리만** 듣는다. 스피커로 나가는 소리를 되받으면 윈도 음량을
        # 0으로 두거나 음소거했을 때 같이 조용해져 효과음을 못 알아봤다.
        ear = sound.Ear(sound.game_pid(self.ctx.window))
        try:
            ear.open()
        except sound.SoundError as exc:
            # 소리를 못 들어도 낚시는 돌아야 한다. 근거가 하나 주는 것뿐이다.
            return f"⚠ 소리를 못 듣습니다 — {exc}"
        self.ear = ear
        self.sound_at = time.perf_counter()
        head = (f"성공 효과음 {cue.describe()} · 닮은 정도 {cue.near:.2f} 이상인 "
                f"조각 {cue.hits}개" if cue.ready else "성공 효과음 안 배움")
        return (f"{head} · {ear.fmt.describe()}\n                 {clicks}"
                f"\n                 듣는 것: {ear.source}")

    def close_ear(self) -> None:
        if self.ear is not None:
            self.ear.close()
            self.ear = None

    def click_sounds(self, since: float, until: float) -> dict | None:
        """그 사이 들린 클릭 소리 횟수. {"hit": 맞음, "miss": 빗나감}.

        클릭 소리를 하나도 안 배웠거나 소리를 못 들으면 None — "0번 들렸다"와
        "안 들어 봤다"는 전혀 다른 말이므로 섞으면 안 된다.
        """
        setup = self.setup
        cues = {name: (c.shape, c.near, c.floor, c.hits)
                for name, c in (("hit", setup.hit_sound),
                                ("miss", setup.miss_sound)) if c.ready}
        if self.ear is None or not cues:
            return None
        # 소리는 클릭보다 늦게 들어온다. 그 여유가 지나기 전에 세면 끝 무렵 소리를 놓친다.
        left = until - time.perf_counter()
        if left > 0:
            time.sleep(left)
        frames = [f for f in self.ear.recent(since) if f[0] <= until]
        # 안 배운 쪽은 0이 아니라 None이다 — "안 들렸다"와 "안 들어 봤다"는 다르다.
        out = {name: (0 if name in cues else None) for name in ("hit", "miss")}
        for _when, label, _score in sound.events(frames, cues):
            out[label] += 1
        return out

    def sound_heard(self, now: float) -> bool:
        """배운 효과음이 그새 울렸나."""
        cue = self.setup.catch_sound
        if self.ear is None or not cue.ready:
            return False
        frames = self.ear.recent(self.sound_at)
        if not frames:
            return False
        self.sound_at = frames[-1][0]
        hit, best = sound.match(frames, sound.SoundPrint(cue.shape),
                                cue.near, cue.floor, cue.hits)
        self.sound_best = best
        return hit and now >= self.sound_until

    # -- 낚았는가 ----------------------------------------------------------
    def catch_reason(self, motion: bool = True) -> str | None:
        """낚았다고 볼 근거. 없으면 None.

        근거가 셋이고 **하나만 서도 낚은 것으로 본다.** 빨간 글씨는 다른 것에
        가리거나 뜨는 자리가 밀리면 그대로 못 보고, 흔들림은 물고기가 하필 멈춘
        순간에 못 본다. 효과음은 그 둘과 달리 화면을 안 보므로 창이 가려도 들린다.
        서로 다른 이유로 놓치므로 셋을 함께 두면 훨씬 덜 놓친다.

        한쪽이 서면 다른 쪽도 잠시 잠재운다. 같은 한 마리를 두 번 세지 않으려는
        것이다.
        """
        setup = self.setup
        now = time.perf_counter()

        # 효과음 — 먼저 본다. 화면에 기대지 않으므로 가장 덜 틀린다.
        if self.sound_heard(now):
            self.hush(now)
            return "성공 효과음"

        # 빨간 글씨 — 몇 초 떠 있으므로 **없다가 생긴 순간**만 센다.
        if setup.notice.ready and now >= self.notice_next_at:
            # 두드리는 동안 step()은 초당 백 번 돈다. 그때마다 찍으면 캡처
            # 하나에 6.9ms니 코어를 통째로 태운다. 여기는 급할 것이 없다.
            self.notice_next_at = now + POLL_S
            seen = spot_seen(setup.notice, self.ctx.window)
            rising = seen and not self.notice_on
            self.notice_on = seen
            if rising and now >= self.notice_until:
                self.hush(now)
                return "빨간 알림"

        # 낚싯대에 매달린 물고기가 흔들리는가.
        spot = setup.catch_motion
        if motion and spot.ready and self.motion.due(now):
            self.motion.sample(now)
            if self.motion.shaking() and now >= self.motion_until:
                self.hush(now)
                self.motion.reset()
                return "낚싯대 흔들림"
        return None

    def hush(self, now: float) -> None:
        """한 마리를 셌다. 세 근거 모두 잠시 잠재운다."""
        self.notice_until = now + self.setup.notice_cooldown_s
        self.motion_until = now + self.setup.catch_motion.cooldown_s
        self.sound_until = now + self.setup.catch_sound.cooldown_s

    # -- 손짓 --------------------------------------------------------------
    def cast(self) -> None:
        cast(self.setup, self.ctx)
        self.last_cast = time.perf_counter()
        self.tap_since = self.last_cast
        self.casts += 1
        # 던지는 자세를 흔들림으로 세면 [Ctrl]이 한 번 더 나간다.
        self.motion.reset()

    def revive(self) -> str:
        """한참 한 마리도 못 낚았다 — **낚시중이 아니게 된 것**으로 보고 되살린다.

        손에 낚싯대가 아닌 것을 들었거나, 초대·거래 같은 신청 창이 떠서 키가 통째로
        안 먹는 때다. 화면으로는 둘을 가려내기 어렵지만, 되살리는 방법은 같다.

            [Esc] 몇 번 빠르게  →  창을 닫는다 (안 떠 있어도 해가 없다)
            [낚싯대 키] 한 번   →  손에 낚싯대를 든다
            [던지기] 한 번      →  다시 낚시중으로  (그 뒤는 여느 때처럼 두드린다)
        """
        setup, ctx = self.setup, self.ctx
        self.revives += 1
        note_input(ctx, f"낚시 되살리기 ({self.revives}번째)",
                   f"{setup.dry_s:g}초 동안 한 마리도 못 낚았습니다")
        for i in range(max(0, setup.dry_esc_times)):
            tap_key("Esc", ctx, "신청 창 닫기" if i == 0 else "")
            ctx.sleep(ESC_GAP_S)
        if setup.dry_rod_key:
            ctx.sleep(0.15)
            tap_key(setup.dry_rod_key, ctx, "낚싯대 들기")
            ctx.sleep(0.25)
        self.resume()
        now = time.perf_counter()
        self.alive_at = now
        self.hush(now)
        return "revive"

    def resume(self, why: str = "다시 던지기 (낚시중으로)", style: str = "") -> None:
        """다시 던져서 낚시중으로 돌아간다.

        낚았을 때도, 판만 사라졌을 때도 같은 키를 누른다 — 둘 다 "지금 낚시중이
        아니다"라는 점에서 같다.
        """
        tap_key(self.setup.back_key, self.ctx, why, style=style)
        self.last_cast = time.perf_counter()
        self.tap_since = self.last_cast
        self.next_tap = self.last_cast + self.setup.rest_s
        # 살피는 간격은 여기서 한 번 풀어 준다. 던진 직후가 가장 중요한 때다.
        self.notice_next_at = 0.0
        # 자세가 바뀐다. 낚시중 화면과 낚음 화면을 견주면 흔들리지도 않았는데
        # 흔들린 것으로 보인다.
        self.motion.reset()

    # -- 버프 --------------------------------------------------------------
    def close_popup(self) -> bool:
        """버프 중첩 알림이 떠 있으면 닫는 키를 **한 번** 누른다. 눌렀으면 True.

        누르고 나서 잠깐은 다시 안 누른다. 창이 사라지는 데 한두 장 걸리는데, 그
        사이 또 보인다고 한 번 더 누르면 닫힌 뒤의 [Esc]가 게임 메뉴를 연다.
        """
        spot = self.setup.stack_popup
        now = time.perf_counter()
        if not spot.ready or now < self.popup_quiet_until:
            return False
        if not spot_seen(spot, self.ctx.window):
            return False
        tap_key(self.setup.stack_close_key or "Esc", self.ctx, "버프 중첩 알림 닫기")
        self.popups += 1
        self.popup_quiet_until = time.perf_counter() + POPUP_QUIET_S
        self.ctx.sleep(0.15)  # 창이 닫힐 틈
        return True

    def wait_watching(self, seconds: float) -> bool:
        """그만큼 쉬되, 그 사이 중첩 알림이 뜨면 닫는다. 닫았으면 True."""
        if not self.setup.stack_popup.ready:
            self.ctx.sleep(seconds)
            return False
        closed = False
        deadline = time.perf_counter() + max(0.0, seconds)
        while True:
            self.ctx.check()
            closed = self.close_popup() or closed
            left = deadline - time.perf_counter()
            if left <= 0:
                return closed
            self.ctx.sleep(min(POLL_S, left))

    def after_buff_key(self, name: str, gap: float) -> bool:
        """버프 키 하나를 누른 뒤. 알림이 뜨는지 지켜보고, 떴으면 닫는다.

        알림이 떴다는 것은 **그 버프가 아직 켜져 있다**는 뜻이다. 우리 시계로는
        만료였지만 게임에서는 남아 있던 것이다. 닫고 나면 버프는 예전 남은 시간
        그대로이므로, 우리 시계를 꽉 채워 두면 그만큼 버프가 끊긴 채로 돈다. 그래서
        조금 뒤(STACK_RETRY_S)에 다시 걸어 보게 해 둔다.
        """
        wait = gap
        if self.setup.stack_popup.ready:
            wait = max(gap, self.setup.stack_wait_s)
        if not self.wait_watching(wait):
            return False
        self.buff_until[name] = time.perf_counter() + STACK_RETRY_S
        return True

    def zeros(self, count: int) -> None:
        """0키를 그만큼 또박또박 누른다."""
        setup = self.setup
        for _ in range(max(0, count)):
            tap_key(setup.buff_zero_key, self.ctx, "버프 0키")
            self.ctx.sleep(setup.buff_zero_gap_s)

    def click_center(self) -> bool:
        """게임 창 한복판을 한 번 누른다.

        시작하기 전에 창이 입력을 받게 해 두려는 것이다. 창 크기를 못 알아내면
        조용히 넘어간다 — 이것 때문에 낚시가 멈추면 안 된다.
        """
        window = self.ctx.window
        if window is None:
            return False
        try:
            width, height = window.client_size()
        except Exception:  # noqa: BLE001 — 창이 막 사라졌을 수 있다
            return False
        if width <= 0 or height <= 0:
            return False
        cx, cy = width // 2, height // 2
        self.ctx.point_to((cx, cy), window.client_to_screen(cx, cy))
        with ARBITER.dispatch():
            self.ctx.button_down(self.setup.click_button)
            sender.precise_sleep(0.03)
            self.ctx.button_up(self.setup.click_button)
        note_input(self.ctx, f"클릭 창 한복판 ({cx}, {cy})", "버프 걸기 전 창 활성화")
        return True

    def open_buffs(self) -> str:
        """낚시를 시작하며 버프를 처음 건다.

            [1] → [7] →(1초)→ [8] → [0]×23 → [6]

        0키를 두 몫(4 + 19) 한 번에 누르는 것이라 처음만 23번이다.
        """
        setup = self.setup
        got = setup.buffs()
        if not got:
            return "버프 없음"
        head = ""
        if setup.buff_center_click and self.click_center():
            # 창이 입력을 받게 해 둔다. 안 그러면 첫 키들이 흘러간다.
            head = "창 한복판 클릭 → "
            self.ctx.sleep(setup.buff_zero_gap_s)
        tap_key(setup.buff_pre_key, self.ctx, "버프 준비")
        self.ctx.sleep(setup.buff_zero_gap_s)
        now = time.perf_counter()
        stacked = []
        for i, (name, key, span, _z) in enumerate(got):
            tap_key(key, self.ctx, f"버프 {name} 쓰기 (처음)")
            self.buff_until[name] = now + span
            gap = (setup.buff_open_gap_s if i < len(got) - 1
                   else setup.buff_zero_gap_s)
            if self.after_buff_key(name, gap):
                stacked.append(f"[{key}]")
        self.zeros(setup.buff_open_zeros)
        self.close_popup()  # 0키 뒤에 늦게 뜬 것까지
        # 낚싯대를 다시 든다. 이걸 빼면 던져도 아무 일이 없다.
        if setup.buff_rod_key:
            tap_key(setup.buff_rod_key, self.ctx, "낚싯대 다시 들기")
        self.buff_runs += 1
        tail = ""
        if stacked:
            tail = (f"  (이미 켜진 {', '.join(stacked)} 중첩 알림 → "
                    f"[{setup.stack_close_key}]로 닫음 · {STACK_RETRY_S:g}초 뒤 다시)")
        return head + setup.buff_story() + tail

    def buff_status(self, now: float | None = None) -> str:
        """버프마다 얼마나 남았는지. 로그에 그대로 쓴다.

        **언제 다시 걸지가 가장 궁금한 값이다.** 남은 시간을 안 보여 주면
        버프가 끊긴 채로 돌고 있는지 알 길이 없다.
        """
        setup = self.setup
        if not setup.buff_ready:
            return "버프 안 씀"
        now = now or time.perf_counter()
        parts = []
        for name, key, span, _z in setup.buffs():
            left = self.buff_until.get(name, 0.0) - now
            if left <= 0:
                parts.append(f"[{key}] 만료 — 다음 낚음 때 다시")
            else:
                parts.append(f"[{key}] {int(left) // 60}:{int(left) % 60:02d} 남음")
        return " · ".join(parts)

    def buffs_due(self, now: float) -> list[tuple[str, str, float, int]]:
        """유지 시간이 다 된 버프들."""
        if not self.setup.buff_ready:
            return []
        return [b for b in self.setup.buffs()
                if now >= self.buff_until.get(b[0], 0.0)]

    def redo_buffs(self, due) -> str:
        """만료된 버프를 다시 건다.

            [1] → [만료된 버프키] → [0]×N → (다 걸고 나서) [6]

        마지막 [ctrl]은 부르는 쪽의 resume()이 누른다 — 버프를 걸든 안 걸든
        낚음 뒤에는 어차피 다시 던져야 하기 때문이다.
        """
        setup = self.setup
        now = time.perf_counter()
        names = []
        # **버프를 걸 때는 언제나 창 한복판을 먼저 누른다.** 처음 걸 때만
        # 그랬더니, 낚는 중에 다시 걸 때 창이 입력을 안 받고 있으면 키가
        # 그냥 흘러가 버프가 안 걸린 채로 낚시가 돌았다.
        if setup.buff_center_click and self.click_center():
            self.ctx.sleep(setup.buff_zero_gap_s)
            names.append("창 한복판")
        for i, (name, key, span, count) in enumerate(due):
            if i:
                # 버프와 버프 사이 쉰다 — [7] 쓰고 바로 [8]을 누르면 뒤엣것이 씹힌다.
                self.ctx.sleep(setup.buff_open_gap_s)
            tap_key(setup.buff_pre_key, self.ctx, "버프 준비")
            self.ctx.sleep(setup.buff_zero_gap_s)
            tap_key(key, self.ctx, f"버프 {name} 다시 쓰기 (만료)")
            self.buff_until[name] = now + span
            stacked = self.after_buff_key(name, setup.buff_zero_gap_s)
            self.zeros(count)
            names.append(f"[{key}]+{count}"
                         + (f" (중첩 알림 → [{setup.stack_close_key}])"
                            if stacked else ""))
        self.close_popup()  # 0키 뒤에 늦게 뜬 것까지
        if setup.buff_rod_key:
            tap_key(setup.buff_rod_key, self.ctx, "낚싯대 다시 들기")
        self.buff_runs += 1
        # 버프를 거는 동안 자세도 화면도 바뀐다.
        self.motion.reset()
        return " · ".join(names)

    def did_catch(self, reason: str) -> None:
        """한 마리 낚았다. 만료된 버프가 있으면 **이 틈에** 다시 건다.

        낚시 도중에 끼어들면 그 판이 날아가므로, 만료되자마자 걸지 않고 여기까지
        기다린다.
        """
        self.caught += 1
        self.last_catch_reason = reason
        self.alive_at = time.perf_counter()
        self.nudge_streak = 0  # 낚였다 = 멈춰 있지 않다
        # 피로도를 버프보다 먼저 본다. 가득 차서 매크로가 무엇을 하든(아이템을 쓰든
        # 자리를 옮기든), 버프를 먼저 걸어 두면 그 사이 헛되이 쓸 수 있다.
        self.last_fatigue = self.check_fatigue() if self.fatigue_due() else ""
        due = self.buffs_due(time.perf_counter())
        self.last_buffs = self.redo_buffs(due) if due else ""
        # **무엇을 보고 낚았다고 했는지** 실행 상태 창에 빨간 글씨로 남긴다.
        board = getattr(self.ctx, "board", None)
        if board is not None:
            board.set(낚음=f"{self.caught}마리째 — {reason}")
        # 이때 누르는 [Ctrl]은 '보낸 입력'에서도 빨갛게 — 무엇 때문에 눌렀는지 함께.
        self.resume(f"낚음 알아봄 ({reason}) → 다시 던지기", style="catch")
        self.popup_hold_until = time.perf_counter() + AFTER_CATCH_HOLD_S
        self.board_hold_until = time.perf_counter() + AFTER_CATCH_BOARD_S

    # -- 피로도 ------------------------------------------------------------
    def fatigue_due(self) -> bool:
        """이번 낚음이 피로도를 확인할 차례인가 (N마리째마다)."""
        setup = self.setup
        if not setup.fatigue_mode:
            return False
        # 클릭 0번인 판이 잇따른다 — 피로도가 차서 못 낚는 것일 수 있다. 바로 본다.
        if getattr(self, "dry_streak", 0) >= DRY_FATIGUE_ROUNDS:
            return True
        return (setup.fatigue_every > 0
                and self.caught > 0 and self.caught % setup.fatigue_every == 0)

    def fatigue_goal(self) -> tuple[str, float]:
        """무엇을 기다리는지. ("가득"|"31057 이상", 기준값).

        기준값이 0보다 크면 **가득 차기를 기다리지 않고** 그 값을 넘는 순간 돈다.
        게임에서 피로도를 일부러 꽉 채워 보기는 어려우니, 눈에 보이는 숫자로
        시험해 볼 수 있어야 한다.
        """
        over = float(self.setup.fatigue_over or 0.0)
        return (f"{over:g} 이상" if over > 0 else "가득", over)

    def fatigue_rule(self, rule):
        """기준값이 있으면 조건의 숫자 보기를 '앞 값이 ○○ 이상'으로 바꿔 본다.

        조건에 적어 둔 **읽을 자리·글꼴·밝기는 그대로** 쓰고, 견주는 방법만 갈아
        끼운다. [조건] 탭에 같은 자리를 보는 조건을 하나 더 만들지 않아도 되도록.
        """
        over = float(self.setup.fatigue_over or 0.0)
        if over <= 0 or not rule.numbers:
            return rule
        from dataclasses import replace

        numbers = [replace(w, target="current", compare="at_least", value=over)
                   for w in rule.numbers]
        return replace(rule, numbers=numbers)

    def fatigue_probe(self, rule, detail: str) -> str:
        """숫자를 못 읽었으면 **본 자리를 그림으로 한 번** 남긴다.

        조건이 안 선 것과 숫자를 못 읽은 것은 다르다. 못 읽었을 때만, 그것도
        한 판에 한 번만 남긴다 — 낚시 도중에 그림을 자꾸 쓰면 그것대로 짐이다.
        """
        if getattr(self, "fatigue_shot", False) or "못 찾았습니다" not in detail:
            return ""
        self.fatigue_shot = True
        try:
            from . import digits, numprobe

            watch = next((w for w in rule.numbers), None)
            if watch is None:
                return ""
            reading = digits.grab(watch, self.ctx.library_root, self.ctx.window)
            shot = numprobe.save(reading, "낚시피로도")
        except Exception:
            return ""
        if shot is None:
            return ""
        return f"  (본 자리를 그림으로 남겼습니다: {shot})"

    def check_fatigue(self) -> str:
        """피로도가 다 찼는지(또는 정한 값을 넘겼는지) 보고, 그러면 정해 둔
        매크로를 **한 번** 돌린다.

        무슨 일이 있었는지 한 줄로 돌려준다. 조건이나 매크로를 못 찾아도 낚시는
        멈추지 않는다 — 경고만 남기고 넘어간다. 피로도 하나 때문에 낚시가 통째로
        서면 그게 더 큰 손해다.

        매크로가 끝나면 부르는 쪽(did_catch)이 resume()으로 다시 던진다.
        """
        setup = self.setup
        self.fatigue_checks += 1
        nth = f"{self.caught}마리째"
        if self.find_rule is None:
            return f"⚠ 피로도 확인 ({nth}) — 이 실행 경로는 조건을 찾을 수 없습니다"
        rule = self.find_rule(setup.fatigue_rule) if setup.fatigue_rule else None
        if rule is None:
            return (f"⚠ 피로도 확인 ({nth}) — 조건 '{setup.fatigue_rule or '안 정함'}'"
                    f"을(를) 찾지 못해 건너뜁니다")
        from .tasks import evaluate_rule  # 순환 참조를 피해 여기서 가져온다

        goal, _over = self.fatigue_goal()
        note_input(self.ctx, f"피로도 확인 ({nth})",
                   f"조건 '{rule.name}' · {goal}이면 매크로 — 커서를 올려 상태창 읽기")
        full, detail = evaluate_rule(self.fatigue_rule(rule), self.ctx)
        self.dry_streak = 0
        # **피로도가 더 안 오르면 가득 찬 것으로 본다.** 거의 다 차면 게임이 물고기를
        # 안 내주는데(판은 떠도 못 낚음), 그러면 끝까지 안 차서 매크로가 영영 안
        # 돌았다. 실제로 522201/546000에서 15판을 내리 놓쳤다.
        found = _FATIGUE_NOW.search(detail or "")
        value = int(found.group(1)) if found else None
        before = getattr(self, "fatigue_value", None)
        self.fatigue_value = value
        if (not full and value is not None and before is not None
                and value <= before):
            full = True
            detail += f" · 지난번({before})보다 안 올라 가득으로 봄"
        if not full:
            return (f"피로도 확인 ({nth}) — 아직 {goal} 아님 [{detail}]"
                    + self.fatigue_probe(rule, detail))
        macro = setup.fatigue_macro
        if not macro or self.find_macro is None or self.find_macro(macro) is None:
            return (f"⚠ 피로도 {goal} ({nth}) [{detail}] — 돌릴 매크로 "
                    f"'{macro or '안 정함'}'을(를) 찾지 못했습니다")

        from .player import _run_macro_step

        self.ctx.log(f"[피로도 {goal}] {nth} 확인 [{detail}] → 매크로 '{macro}' "
                     f"한 번 실행 후 낚시를 이어 갑니다")
        if not _run_macro_step(macro, self.ctx, self.find_macro, "  피로도 매크로"):
            raise Aborted()
        self.fatigue_runs += 1
        self.fatigue_value = None  # 피로도를 뺐다 — 다음 확인부터 새로 잰다
        # 매크로가 무슨 소리·화면을 냈든 그것을 낚음으로 세면 안 된다. 자세도 바뀌었다.
        now = time.perf_counter()
        self.hush(now)
        self.motion.reset()
        self.ctx.sleep(max(0.3, setup.rest_s))
        return (f"피로도 {goal} ({nth}) [{detail}] → 매크로 '{macro}' 실행함 "
                f"({self.fatigue_runs}번째) → 다시 던집니다")

    def dig(self) -> str:
        """언 땅을 판다.

            [5] 삽을 든다
            [ctrl] 내리친다 × 몇 번   ← 한 번으로는 안 뚫린다
            [6] 낚싯대로 바꾼다
            [ctrl] 던진다             ← 여기서부터 다시 낚시

        **처음 뚫는 자리는 한 번 더 내리쳐야 한다.** 이미 뚫었던 자리는 얼어붙은
        것만 깨면 되므로 덜 친다. 그래서 이 세션의 첫 번째만 더 친다.

        내리치는 키는 톡 누르는 것으로 안 되고 얼마간 붙잡고 있어야 하며, 내리침
        사이에도 뜸을 들여야 한다. 둘 다 정한 범위 안에서 무작위로 고른다 — 늘
        똑같은 박자로 치면 사람이 아닌 티가 난다.
        """
        setup = self.setup
        first = self.digs == 0
        count = setup.ice_hit_count(first)

        tap_key(setup.ice_dig_key, self.ctx, "삽 들기")      # 삽을 든다
        self.ctx.sleep(setup.ice_gap_s)
        for i in range(count):                     # 내리친다
            hold_key(setup.ice_hit_key, self.ctx, setup.ice_hold(self.rng),
                     f"언 땅 내리치기 {i + 1}/{count}")
            if i < count - 1:
                self.ctx.sleep(setup.ice_press_gap(self.rng))
        self.ctx.sleep(setup.ice_gap_s)
        tap_key(setup.ice_back_key, self.ctx, "낚싯대로 바꾸기")  # 낚싯대로 바꾼다
        self.ctx.sleep(setup.ice_gap_s)
        tap_key(setup.back_key, self.ctx, "던지기 (땅 판 뒤)")    # 던진다 — 다시 낚시
        now = time.perf_counter()
        self.next_dig = now + max(1.0, setup.ice_every_s)
        # 파는 동안 자세도 화면도 바뀐다. 던진 것으로 치고 처음부터 다시 센다.
        self.last_cast = now
        self.tap_since = now
        self.next_tap = now + setup.rest_s
        self.motion.reset()
        self.digs += 1
        return setup.ice_story(first) + (" (처음 뚫는 자리)" if first else "")

    def tap(self) -> None:
        """머리 위를 한 번 누른다."""
        got = self.setup.tap_point(self.ctx.window, self.rng)
        if got is None:
            return
        client, screen = got
        self.ctx.point_to(client, screen)
        with ARBITER.dispatch():
            self.ctx.button_down(self.setup.click_button)
            sender.precise_sleep(0.012)
            self.ctx.button_up(self.setup.click_button)
        self.taps += 1
        note_input(self.ctx, f"클릭 {tuple(client)}",
                   f"머리 위 두드리기 {self.taps}번째", log=False)
        self.next_tap = time.perf_counter() + self.setup.tap_gap(self.rng)

    # -- 지금 무엇이 보이나 -------------------------------------------------
    def look_around(self) -> str:
        """지금 화면에서 알아본 것들을 한 줄로. 로그에 그대로 쓴다."""
        setup = self.setup
        parts = []
        got = self.board.peek()
        if got is None:
            parts.append("판을 못 찍음")
        else:
            signals = self.board.signals(got)
            parts.append("미니게임 " + ("있음 [" + " · ".join(signals) + "]"
                                     if signals else "없음"))
            bits = []
            bits.append(f"막대 {got.bar:.0f}" if got.bar is not None
                        else f"막대 못 찾음({got.bar_px}칸)")
            bits.append(f"물고기 {got.fish:.0f}" if got.fish is not None
                        else f"물고기 못 찾음({got.fish_px}칸)")
            bits.append(f"체력 {got.health * 100:.0f}%")
            if setup.time_color:
                bits.append(f"시간표시 {got.time_px}/{setup.time_min_px}칸")
            parts.append(" · ".join(bits))
        if setup.notice.ready:
            count = spot_count(setup.notice, self.ctx.window)
            parts.append(f"성공알림 {count}/{setup.notice.min_px}칸"
                         + (" ●떴음" if count >= setup.notice.min_px else ""))
        if setup.stack_popup.ready:
            count = spot_count(setup.stack_popup, self.ctx.window)
            parts.append(f"중첩알림 {count}/{setup.stack_popup.min_px}칸"
                         + (" ●떴음" if count >= setup.stack_popup.min_px else ""))
        if setup.catch_motion.ready:
            self.motion.sample()
            parts.append(self.motion.describe()
                         + (" ●흔들림" if self.motion.shaking() else ""))
        if setup.catch_sound.ready:
            if self.ear is None:
                parts.append("효과음 안 듣는 중")
            else:
                got = self.ear.latest()
                level = got[1] if got else 0.0
                parts.append(f"소리 {level:.3f} · 닮은 정도 "
                             f"{self.sound_best:.2f}/{setup.catch_sound.near:.2f}")
        return "  |  ".join(parts)

    def say(self, what: str, detail: str = "", force: bool = False,
            log: bool = True) -> None:
        """상태가 바뀌었을 때만 알린다. 같은 상태면 가끔만.

        매 바퀴 찍으면 초당 백 줄이 쏟아져 로그가 쓸모없어지고, 그 줄을 만드는
        비용이 그대로 클릭 수를 깎는다. 그렇다고 아무 말도 안 하면 지금 무엇을
        하는 중인지 알 길이 없다.
        """
        now = time.perf_counter()
        changed = what != self.state
        # 지금 상태는 **실행 상태 창**에 늘 띄운다 (가볍다 — 글 한 줄 바꾸기).
        board = getattr(self.ctx, "board", None)
        if board is not None and (changed or force or now - self.shown_at >= 0.5):
            self.shown_at = now
            first = detail.split("\n")[0] if detail else ""
            board.set(낚시=f"{what}" + (f" — {first}" if first else ""))
        # 로그에는 **바뀌었을 때만** 적는다. 예전에는 같은 상태여도 5초마다 한 번씩
        # 적었는데, 낚시를 오래 돌리면 로그가 그 줄로 도배됐다.
        if not (changed or force) or not log:
            self.state = what
            return
        self.state = what
        self.said_at = now
        self.ctx.log(f"[{what}] {detail}" if detail else f"[{what}]")

    # -- 한 걸음 ----------------------------------------------------------
    def step(self) -> str:
        """지금 화면을 보고 한 가지를 한다."""
        setup, ctx = self.setup, self.ctx
        now = time.perf_counter()

        # 1) 미니게임이 떠 있으면 그것부터. 다른 무엇보다 급하다.
        #    미니게임 인식은 잘 되므로 이것을 첫 관문으로 삼는다.
        got = self.board.peek()
        signals = self.board.enough(got) if got else []
        if signals and now >= getattr(self, "board_hold_until", 0.0):
            self.enter_signals = signals
            # 판이 떴다 = 낚시가 돌고 있다. 되살리기 시계를 되돌린다 — 판을 푸는
            # 동안 시계가 차서, 판이 끝나자마자 엉뚱하게 되살리면 안 된다.
            self.alive_at = now
            # 판을 푸는 동안은 두드린 시간을 안 센다. 30초짜리 판을 풀고 나왔다고
            # 해서 "두드리기만 30초 했다"가 되면 안 된다.
            self.tap_since = 0.0
            return "minigame"

        # 1-1) 버프 중첩 알림이 떠 있으면 닫는다. 떠 있는 동안은 어떤 키도 안 먹으므로
        #      던지기·두드리기보다 먼저다. 버프를 걸 때 말고도 뜰 수 있어 늘 살핀다.
        if (setup.stack_popup.ready and now >= self.popup_next_at
                and now >= self.popup_hold_until):
            self.popup_next_at = now + POPUP_POLL_S
            if self.close_popup():
                # [Esc]는 던져 둔 낚시도 취소한다. 낚시중이었다면 다시 던진다.
                if self.casts > 0:
                    self.resume("알림 닫은 뒤 다시 던지기")
                return "popup"

        # 1-2) 한참 한 마리도 못 낚았다 — 손에 든 것이 바뀌었거나 신청 창이
        #      떠서 키가 안 먹는 것이다. 여기서만 본다: 미니게임이 떠 있으면 위에서
        #      이미 돌아갔으므로, 판을 푸는 도중에 [Esc]를 눌러 판을 날릴 일이 없다.
        if setup.dry_s > 0:
            if self.alive_at <= 0.0:
                self.alive_at = now
            elif (now - self.alive_at) >= setup.dry_s and self.casts > 0:
                return self.revive()

        # 2) 판이 방금 사라졌다 — 낚았든 실패했든 **낚시중이 아니다.**
        #
        #    잠깐은 낚음 근거를 살핀다. 빨간 글씨는 판이 닫히고 조금 뒤에 뜨고,
        #    흔들림도 몇 장은 봐야 알 수 있기 때문이다. 그러나 **못 봐도 던진다.**
        #    근거를 기다리다 못 보면 낚시가 통째로 멈추는데, 그게 지금까지 가장
        #    자주 겪은 고장이었다.
        if self.round_over_at:
            reason = self.catch_reason()
            if reason is not None:
                self.round_over_at = 0.0
                self.did_catch(reason)
                return "caught"
            if (now - self.round_over_at) >= max(0.3, setup.rest_s):
                self.round_over_at = 0.0
                self.last_catch_reason = ""
                self.recasts += 1
                self.resume()
                return "recast"
            return "waiting"

        # 3) 낚음 근거가 보이면 낚은 것이다. 다시 던진다.
        #
        #    미니게임 없이 곧장 낚이는 판도 있다 — 던지자마자 걸리면 찌가 뜨기도
        #    전에 낚인다. 그래서 판이 끝난 뒤만이 아니라 **낚시중에도 늘 살핀다.**
        #    아직 안 던졌으면 볼 것도 없다 — 버프 뒤 화면을 낚음으로 보면
        #    [Ctrl]이 두 번 나간다.
        reason = self.catch_reason() if self.casts > 0 else None
        if reason is not None:
            self.did_catch(reason)
            return "caught"

        # 4) 아직 한 번도 안 던졌으면 먼저 던진다. [낚시 시작]을 누른 순간
        #    캐릭터는 아직 낚시를 하고 있지 않다.
        if self.casts == 0:
            # 버프 뒤 늦게 뜨는 중첩 알림을 먼저 닫는다. 던진 뒤에 닫으면
            # [Esc]가 낚시를 취소해 [Ctrl]을 또 눌러야 한다.
            if self.buff_runs and setup.stack_popup.ready:
                self.wait_watching(FIRST_CAST_WATCH_S)
            self.cast()
            return "cast"

        # 낚시중이다. 가끔 지금 무엇이 보이는지 알려 둔다.
        if got is not None:
            tail = ""
            if setup.buff_ready:
                tail = "\n    버프 — " + self.buff_status(now)
            if setup.ice_ready:
                left = max(0.0, self.next_dig - now)
                tail += f"\n    땅 파기까지 {int(left) // 60}:{int(left) % 60:02d}"
            self.say("낚시중 · 두드리는 중",
                     f"두드림 {self.taps}회 · " + self.look_around() + tail)

        # 5) 얼음낚시 — 땅이 얼기 전에 다시 판다.
        #
        #    미니게임이 떠 있을 때는 여기까지 오지 않는다(1번에서 돌아간다).
        #    판을 푸는 도중에 키를 누르면 그 판을 통째로 날린다.
        if setup.ice_ready and now >= self.next_dig:
            self.last_dig_keys = self.dig()
            return "dig"

        # 6) 두드리기만 너무 오래 이어졌다 — 이미 낚아 놓고 못 알아본 것이다.
        #
        #    이 상태는 아무 일도 안 일어나므로 스스로 빠져나올 길이 없다.
        #    그냥 한 번 던져 보는 편이 기다리는 것보다 언제나 낫다.
        if self.tap_since <= 0.0:
            self.tap_since = now
        limit = setup.tap_limit_s
        if limit > 0 and (now - self.tap_since) >= limit:
            self.nudges += 1
            self.nudge_streak += 1
            # **두 번째부터는 낚싯대를 먼저 든다.** 한 번 다시 던져도 안 풀리면
            # 손에 낚싯대가 아닌 것을 들고 있을 때가 많다 — 그러면 던지기 키를
            # 몇 번 눌러도 소용없다.
            if self.nudge_streak >= ROD_AFTER_NUDGES and setup.dry_rod_key:
                tap_key(setup.dry_rod_key, ctx,
                        f"낚싯대 들기 (다시 던짐 {self.nudge_streak}번째)")
                ctx.sleep(0.25)
            self.resume()
            return "nudge"

        # 7) 낚시중이다. 머리 위를 두드린다.
        #    찌가 보이는지 따지지 않는다 — 헛클릭은 해가 없고, 찌를 알아보려다
        #    놓치는 것보다 계속 두드리는 편이 훨씬 잘 걸린다.
        if setup.tap_w > 0 and now >= self.next_tap:
            self.tap()
            return "tap"

        # 8) 한참 아무 일도 없으면 다시 던진다. 줄이 끊긴 것이다.
        if now - self.last_cast >= max(CAST_GAP_S, setup.bite_wait_s):
            self.cast()
            return "cast"
        return "waiting"

    def stuck_report(self) -> dict:
        """미니게임을 한참 못 알아볼 때 **왜 그런지 짚을 증거**를 모은다.

        창이 밀렸는지(창 위치 · 판 자리), 창이 뒤로 갔거나 최소화됐는지, 판은 떴는데
        색이 안 맞는지(막대 · 물고기 · 체력 인식 값)를 적고, 판 자리와 창 전체를 사진으로
        남긴다. 사진이 있으면 "그때 화면이 어땠나"를 추측하지 않아도 된다.
        """
        from datetime import datetime

        from . import png
        from .numprobe import to_rgb

        info: dict = {}
        window = self.ctx.window
        try:
            info["window_origin"] = list(window.client_origin())
            info["client_size"] = list(window.client_size())
            info["foreground"] = bool(window.is_foreground())
            info["minimized"] = bool(getattr(window, "minimized", False))
        except Exception as exc:  # noqa: BLE001 — 창이 사라졌을 수도 있다
            info["window_error"] = repr(exc)
        got = self.board.peek()
        info["board_rect"] = list(self.board.rect) if self.board.rect else None
        if got is not None:
            info.update(bar=got.bar, bar_px=got.bar_px, fish=got.fish, fish_px=got.fish_px,
                        health=round(got.health, 3), time_px=got.time_px,
                        signals=self.board.signals(got))
        folder = storage.DATA_DIR / "fishlog"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shots = []
        try:
            folder.mkdir(parents=True, exist_ok=True)
            frame = self.board.snapshot()
            if frame is not None:
                rgb, w, h = to_rgb(frame.buf, frame.w, frame.h, 1)
                png.write_rgb(folder / f"stuck-{stamp}-board.png", w, h, rgb)
                shots.append(f"stuck-{stamp}-board.png")
            if window is not None:
                ox, oy = window.client_origin()
                cw, ch = window.client_size()
                if cw > 0 and ch > 0:
                    whole = pixel.capture_region(ox, oy, cw, ch)
                    rgb, w, h = to_rgb(whole.buf, whole.w, whole.h, 2)
                    png.write_rgb(folder / f"stuck-{stamp}-window.png", w, h, rgb)
                    shots.append(f"stuck-{stamp}-window.png")
        except Exception as exc:  # noqa: BLE001 — 증거를 못 남겨도 낚시는 이어 간다
            info["shot_error"] = repr(exc)
        info["shots"] = shots
        return info

    def dry_round_report(self, board: "LiveBoard") -> None:
        """미니게임이 3초째인데 클릭이 한 번도 안 나갔다 — **왜 그런지 증거를 남긴다.**

        판 사진 · 창 전체 사진 · 그때 읽은 값(막대 · 물고기 · 겹친 폭) · 게임 창이
        앞에 있었는지 · 판 자리와 클릭 자리를 **어느 창이 차지하고 있었는지**를
        적는다. 다른 창이 가리고 있었다면 거기서 바로 드러난다.
        """
        self.dry_reports += 1
        info: dict = {"nth": self.dry_reports}
        setup, window = self.setup, self.ctx.window
        try:
            ox, oy = window.client_origin()
            info["foreground"] = bool(window.is_foreground())
            info["board_center_window"] = window_at(
                ox + setup.board_x + setup.board_w // 2,
                oy + setup.board_y + setup.board_h // 2)
            info["click_window"] = window_at(ox + setup.click_x + setup.click_w // 2,
                                             oy + setup.click_y + setup.click_h // 2)
        except Exception as exc:  # noqa: BLE001
            info["window_error"] = repr(exc)
        try:
            got = board.peek()
            if got is not None:
                info.update(bar=got.bar, bar_px=got.bar_px, fish=got.fish,
                            fish_px=got.fish_px, health=round(got.health, 3),
                            time_px=got.time_px, touch=board.touch(),
                            outline=board.outline_px(),
                            widths=dict(board._width), fill=board._fill_note)
        except Exception as exc:  # noqa: BLE001
            info["read_error"] = repr(exc)
        try:
            report = self.stuck_report()  # 사진 두 장(판 · 창 전체)
            info["shots"] = report.get("shots", [])
        except Exception as exc:  # noqa: BLE001
            info["shot_error"] = repr(exc)
        self.last_dry = info
        self.ctx.log(
            f"⚠ 미니게임 {DRY_ROUND_S:g}초째 클릭 0번 — 앞에 있음 {info.get('foreground')}"
            f" · 판 자리 창 '{info.get('board_center_window')}'"
            f" · 클릭 자리 창 '{info.get('click_window')}'"
            f" · 막대 {info.get('bar')} · 물고기 {info.get('fish')} · 겹친 폭 {info.get('touch')}"
            f" · 배운 테두리 {info.get('outline')} → 지우고 처음처럼 다시 봄"
            f"\n    사진: data/fishlog/{', '.join(info.get('shots', []))}")

    def solve(self, lead, ratio=None):
        """떠 있는 미니게임을 한 판 푼다.

        겹침 거리는 **그 판에서 잰 폭**으로 정한다. 물고기 크기가 판마다 다르기
        때문이다. 판을 새로 만들어 폭도 새로 재게 한다.
        """
        self.nudge_streak = 0
        fresh = LiveBoard(self.setup, self.ctx)
        fresh._outline = self.outline  # 같은 목록 — 이 판에서 배운 것도 남는다
        # 판 도중 빨간 알림·효과음이 오면 낚은 것이다. (흔들림은 판에 가려 못 믿는다.)
        fresh.catch_check = lambda: self.catch_reason(motion=False)
        if getattr(self, "dry_reports", DRY_REPORTS_MAX) < DRY_REPORTS_MAX:
            fresh.dry_report = self.dry_round_report
        # 폭을 먼저 재 둔다. 첫 겹침을 어림잡을 근거가 필요하다.
        #
        # **둘 다 잴 때까지 본다.** 예전에는 네 번만 보고 말았는데, 판이 막 뜨는
        # 동안에는 막대나 물고기가 아직 안 그려져 있어 그 네 번이 헛돌 수 있다.
        # 그러면 창이 기본값에 굳은 채로 판이 돌아간다.
        #
        # 한 장을 두 번 찍던 것도 고쳤다 — snapshot()은 매번 새로 찍으므로
        # (한 번에 6.9ms) 그냥 낭비였고, 하필 두 번째가 None이면 터졌다.
        for _ in range(WIDTH_TRIES):
            frame = fresh.snapshot()
            if frame is None:
                break
            fresh.look(frame)
            if fresh._width["bar"] > 0 and fresh._width["fish"] > 0:
                break
        began = time.perf_counter()
        result = fishing.play(fresh, lead, self.setup.limit_s,
                              fresh.hit_px, ratio)
        self.dry_streak = 0 if result.clicks else getattr(self, "dry_streak", 0) + 1
        ended = time.perf_counter()
        self.last_hit_px = fresh.hit_px
        self.last_widths = (fresh._width["bar"], fresh._width["fish"])
        self.last_reads = fresh.reads
        if fresh.caught_reason:
            result.outcome = fishing.CLEAR  # 낚았다 — 판이 남아 있어도 기다리지 않는다
        else:
            wait_for_close(fresh, self.ctx)
        # 클릭 소리는 **판이 끝난 뒤에** 센다. 판을 푸는 반복문에서 들여다보면 그만큼
        # 클릭이 늦어진다. 소리는 클릭보다 조금 늦게 나므로 끝에 여유를 둔다.
        self.last_click_sounds = self.click_sounds(began, ended + 0.3)
        # 귀는 이제 60초치를 들고 있다. 성공 효과음을 판 도중 소리까지 되짚어 찾으면
        # 닮은 클릭 소리에 속을 기회만 는다. 판이 끝날 무렵부터만 본다.
        self.sound_at = max(self.sound_at, ended - 0.5)
        # 판이 사라졌다 = 낚았거나 실패했다 = **어느 쪽이든 다시 던져야 한다.**
        # 여기에 시각을 남겨 두면 step()이 알아서 처리한다.
        now = time.perf_counter()
        self.round_over_at = now
        self.next_tap = now + self.setup.rest_s
        self.notice_next_at = 0.0
        # 판이 떠 있는 동안 캐릭터 자리는 가려져 있었다. 그때 장과 지금 장을
        # 견주면 흔들림이 아니라 판이 사라진 것을 보게 된다.
        self.motion.reset()
        # **판이 사라졌다 = 낚았다.** 근거(빨간 글씨·효과음)를 기다리지 않고
        # 바로 [Ctrl]로 다시 던진다. 시간이 다 돼 판이 남아 있을 때만 예전처럼
        # step()이 근거를 살피고 던진다.
        if fresh.caught_reason:
            # 판 도중 빨간 알림·효과음 — 이미 hush()로 잠재웠다.
            self.closed_catch = True
            self.round_over_at = 0.0
            self.did_catch(fresh.caught_reason)
        else:
            self.closed_catch = not fresh.present()
            if self.closed_catch:
                self.round_over_at = 0.0
                self.hush(now)  # 곧 뜰 빨간 글씨·효과음으로 한 번 더 세지 않게
                self.did_catch("미니게임 창 사라짐")
        return result


def run_fishing(setup: FishingSetup, ctx: RunContext, rounds: int = 0,
                seconds: float = 0.0, find_macro=None, on_round=None,
                find_rule=None) -> dict:
    """낚시를 되풀이한다.

    rounds가 0이고 seconds도 0이면 [정지]를 누를 때까지 계속한다.
    rounds는 **푼 미니게임 판 수**를 센다.

    **배운 값(lead)은 판을 넘겨 이어 간다.** 판마다 처음부터 배우면 그 판은
    탐색만 하다 끝난다. 낚시는 하루에도 수백 번이라, 이어 두면 금방 수렴한다.
    """
    problems = setup.problems()
    if problems:
        ctx.log("낚시 설정이 덜 됐습니다 — " + ", ".join(problems))
        return {"rounds": 0, "clears": 0}

    lead = fishing.Lead().load(setup.lead_stats, setup.lead_ms)
    ratio = fishing.Ratio(learn=setup.learn_hit)
    if setup.learn_hit:
        ratio.load(setup.ratio_stats)
    flow = Flow(setup, ctx, find_macro, find_rule)
    started = time.perf_counter()
    done = clears = 0

    # -- 무엇이 준비됐는지 먼저 낱낱이 적는다 ------------------------------
    #
    # 낚시가 안 돌 때 왜 안 도는지 알 길이 없는 것이 가장 답답하다. 시작할 때
    # 무엇을 어디서 보기로 했는지 다 적어 두면, 로그만 보고도 어디가 어긋났는지
    # 짚을 수 있다.
    def head(title):
        ctx.log("")
        ctx.log(f"── {title} " + "─" * max(0, 46 - len(title)))

    ctx.log("═" * 12 + " 낚시 시작 " + "═" * 12)
    ctx.log("이 매크로는 이렇게 돕니다:")
    ctx.log("  ① 던진다 → ② 머리 위를 두드린다 → ③ 미니게임이 뜨면 풀고")
    ctx.log("  → ④ 낚음을 알아보면 세고 다시 던진다 (①로)")

    head("1. 어디를 보나")
    ctx.log(f"  판 영역      창 기준 ({setup.board_x}, {setup.board_y}) "
            f"{setup.board_w}×{setup.board_h}")
    ctx.log(f"  움직이는 범위 x {setup.track_x0}~{setup.track_x1} · "
            f"y {setup.track_y0}~{setup.track_y1}")
    ctx.log(f"  막대         {setup.bar_color} 세로 "
            f"{setup.bar_box()[2]}~{setup.bar_box()[3]} "
            f"(최소 {setup.track_min_px}칸)")
    ctx.log(f"  물고기       {setup.fish_color} 세로 "
            f"{setup.fish_box()[2]}~{setup.fish_box()[3]}")
    ctx.log(f"  체력         {setup.health_color} "
            f"x {setup.health_x0}~{setup.health_x1}")
    ctx.log("  시간표시     "
            + (f"{setup.time_color} {setup.time_min_px}칸 이상"
               if setup.time_color else "안 정함"))

    head("2. 겹치면 어떻게 누르나")
    ctx.log("  겹침 거리    "
            + ("판마다 두 물체의 폭을 재서 정함"
               if setup.hit_mode == "auto" else f"{setup.hit_px:g}px 고정"))
    ctx.log("  겹침 배수    "
            + (f"배우는 중 (지금 {ratio.best:.1f}배) — 성적을 보고 스스로 조절"
               if setup.learn_hit
               else f"{setup.hit_ratio:g}배 고정 (안 배움)"))
    ctx.log(f"  한 번 누름   {setup.click_hold_ms:g}ms 붙잡음")
    ctx.log(f"  누르는 자리  ({setup.click_x}, {setup.click_y}) "
            f"{setup.click_w}×{setup.click_h} 안에서 무작위")
    ctx.log(f"  한 판 제한   {setup.limit_s:g}초 · 배운 lead "
            f"{lead.best:+.0f}ms")

    head("3. 낚음을 무엇으로 아나 (하나만 서도 낚은 것)")
    ctx.log("  ⓪ 효과음     " + flow.open_ear())
    ctx.log("  ① 빨간 글씨  "
            + (f"{setup.notice.color} {setup.notice.min_px}칸 이상 "
               f"({setup.notice.w}×{setup.notice.h} 자리)"
               if setup.notice.ready else "안 정함"))
    spot = setup.catch_motion
    ctx.log("  ② 흔들림     "
            + (f"({spot.x}, {spot.y}) {spot.w}×{spot.h} · {spot.gap_s:g}초마다 "
               f"보고 {spot.span_s:g}초에 {spot.repeats}번 움직이면 흔들림"
               if spot.ready else "안 정함"))
    if not setup.can_tell_caught:
        ctx.log("  ⚠ 셋 다 안 정했습니다 — 낚은 수를 못 셉니다 "
                "(그래도 판이 끝나면 다시 던지므로 낚시는 돕니다)")

    head("4. 언제 다시 던지나")
    ctx.log(f"  판이 사라지면 늦어도 {max(0.3, setup.rest_s):g}초 안에 "
            f"[{setup.back_key}] (근거를 못 봐도)")
    ctx.log("  두드리기만   "
            + (f"{setup.tap_limit_s:g}초 이어지면 [{setup.back_key}]"
               if setup.tap_limit_s > 0 else "안 끊음"))
    ctx.log(f"  아무 일 없으면 {max(CAST_GAP_S, setup.bite_wait_s):g}초 뒤 "
            f"[{setup.cast_key}]")
    ctx.log("  두드릴 자리  "
            + (f"({setup.tap_x}, {setup.tap_y}) {setup.tap_w}×{setup.tap_h} · "
               f"{setup.tap_min_s:g}~{setup.tap_max_s:g}초 간격"
               if setup.tap_w > 0 else "⚠ 안 정함 — 안 두드립니다"))

    if setup.dry_s > 0:
        ctx.log(f"  되살리기  {setup.dry_s:g}초 동안 한 마리도 못 낚으면 "
                f"[Esc]×{setup.dry_esc_times} → [{setup.dry_rod_key or '안 누름'}]"
                f"(낚싯대) → [{setup.back_key}]로 다시 던짐")
    if setup.buff_ready or setup.ice_ready or setup.fatigue_mode:
        head("5. 곁들이 (버프 · 얼음낚시 · 피로도)")
    if setup.fatigue_mode:
        goal = (f"{setup.fatigue_over:g} 이상" if setup.fatigue_over > 0 else "가득")
        ctx.log(f"  피로도 확인  낚음 {setup.fatigue_every}마리마다 조건 "
                f"'{setup.fatigue_rule or '안 정함'}' → {goal}이면 매크로 "
                f"'{setup.fatigue_macro or '안 정함'}' 한 번 → 다시 던짐")
        if (find_rule is None or not setup.fatigue_rule
                or find_rule(setup.fatigue_rule) is None):
            ctx.log("  ⚠ 피로도 조건을 찾지 못했습니다 — [조건] 탭의 이름과 같은지 "
                    "보세요 (확인은 건너뛰고 낚시는 돕니다)")
        if (find_macro is None or not setup.fatigue_macro
                or find_macro(setup.fatigue_macro) is None):
            ctx.log("  ⚠ 피로도 매크로를 찾지 못했습니다 — 가득 차도 아무것도 안 "
                    "돌립니다")
    if setup.buff_ready:
        ctx.log("  중첩 알림    "
                + (f"{setup.stack_popup.color} {setup.stack_popup.min_px}칸 이상 "
                   f"보이면 [{setup.stack_close_key}] 한 번"
                   if setup.stack_popup.ready
                   else "⚠ 안 정함 — 켜져 있는 버프를 또 쓰면 뜨는 창을 못 닫아 "
                        "입력이 막힐 수 있습니다"))
        ctx.log("  버프 순서    " + flow.open_buffs())
        ctx.log("  버프 남음    " + flow.buff_status())
        ctx.log("  ※ 만료돼도 바로 안 겁니다 — 다음에 한 마리 낚을 때 그 틈에 "
                "겁니다 (낚는 도중에 끼어들면 그 판이 날아갑니다)")
    elif setup.buff_mode:
        ctx.log("  ⚠ 버프를 켜 두었지만 키가 비어 있습니다")
    if setup.ice_ready:
        flow.next_dig = 0.0
        ctx.log(f"  얼음낚시     {setup.ice_every_s:g}초마다 "
                + " → ".join(f"[{k}]" for k in setup.ice_key_list())
                + " (시작할 때 한 번 팝니다)")

    head("6. 지금 보이는 것")
    ctx.log("  " + flow.look_around())

    # -- 기록 -------------------------------------------------------------
    book = None
    if setup.keep_log:
        book = fishlog.FishLog(storage.DATA_DIR / "fishlog")
        if book.path is not None:
            ctx.log(f"  기록은 data/fishlog/{book.path.name} 에 남깁니다")
        book.write(
            "start",
            setup={
                "board": [setup.board_w, setup.board_h],
                "hit_mode": setup.hit_mode,
                "hit_ratio": setup.hit_ratio,
                "hit_px": setup.hit_px,
                "click_hold_ms": setup.click_hold_ms,
                "limit_s": setup.limit_s,
                "tap_gap": [setup.tap_min_s, setup.tap_max_s],
                "tap_limit_s": setup.tap_limit_s,
                "rest_s": setup.rest_s,
                "bite_wait_s": setup.bite_wait_s,
                "learn_hit": setup.learn_hit,
                "ice": setup.ice_mode,
                "ice_every_s": setup.ice_every_s,
                "tell": {
                    "notice": setup.notice.ready,
                    "motion": setup.catch_motion.ready,
                    "sound": setup.catch_sound.ready,
                },
            },
            buff=setup.buff_story() if setup.buff_ready else None,
            learned={"lead_ms": lead.best, "ratio": ratio.best,
                     "rounds": setup.rounds, "clears": setup.clears},
        )
    ctx.log("═" * 34)

    def report_catch() -> None:
        setup.caught += 1
        cycle = book.caught(flow.last_catch_reason) if book else None
        # 낚을 때마다 **한 줄만.** 늘 같은 말("[ctrl]로 다시 던집니다",
        # 버프 남은 시간)은 빼고 실행 상태 창에서 보이게 했다.
        lines = [f"{flow.caught}마리째 — {flow.last_catch_reason}"
                 + (f" · 직전 낚음에서 {cycle:.1f}초" if cycle else "")]
        if flow.last_fatigue:
            lines.append(flow.last_fatigue)
            if book:
                book.write("fatigue", nth=flow.fatigue_checks,
                           runs=flow.fatigue_runs,
                           detail=flow.last_fatigue)
        if flow.last_buffs:
            lines.append(f"만료된 버프를 다시 걸었습니다 "
                         f"({flow.last_buffs})")
        if setup.buff_ready:
            board = getattr(ctx, "board", None)
            if board is not None:
                board.set(판="버프 — " + flow.buff_status())
        flow.say("낚음", "\n    ".join(lines), force=True)
        if book and flow.last_buffs:
            book.write("buff", keys=flow.last_buffs,
                       nth=flow.buff_runs)

    try:
        while True:
            ctx.check()
            if rounds and done >= rounds:
                break
            if seconds and (time.perf_counter() - started) >= seconds:
                break

            what = flow.step()
            if what == "caught":
                report_catch()
                ctx.sleep(setup.rest_s)
                continue
            if what == "dig" and book:
                book.write("dig", nth=flow.digs)
            if what == "dig":
                flow.say("땅 파기",
                         f"{flow.digs}번째 — 언 땅을 다시 팝니다"
                         f"\n    누른 키: {flow.last_dig_keys}"
                         f"\n    다음은 {setup.ice_every_s:g}초 뒤입니다",
                         force=True)
                ctx.sleep(POLL_S)
                continue
            if what == "popup":
                if book:
                    book.write("popup", nth=flow.popups)
                flow.say("중첩 알림 닫음",
                         f"버프 중첩 알림이 떠 있어 [{setup.stack_close_key}]를 한 번 "
                         f"눌렀습니다 ({flow.popups}번째)", force=True)
                ctx.sleep(POLL_S)
                continue
            if what == "nudge" and book:
                book.write("nudge", nth=flow.nudges)
            if what == "nudge" and flow.nudge_streak == STUCK_NUDGES:
                # 미니게임을 한참 못 알아본다. 이어지는 동안 한 번만 증거를 남긴다.
                report = flow.stuck_report()
                if book:
                    book.write("stuck", streak=flow.nudge_streak, **report)
                flow.say("미니게임을 한참 못 알아봄",
                         f"'다시 던짐'이 {flow.nudge_streak}번 이어졌습니다 — 판 자리 "
                         f"{report.get('board_rect')} · 창 {report.get('window_origin')} "
                         f"{report.get('client_size')} · 앞에 있음 {report.get('foreground')}"
                         f" · 최소화 {report.get('minimized')}"
                         f"\n    인식: 막대 {report.get('bar')} · 물고기 {report.get('fish')} · "
                         f"체력 {report.get('health')} · 시간표시 {report.get('time_px')}칸"
                         f"\n    사진: {', '.join(report.get('shots') or []) or '못 찍음'} "
                         f"(data/fishlog)", force=True)
            if what == "nudge":
                streak = flow.nudge_streak
                rod = (streak >= ROD_AFTER_NUDGES and setup.dry_rod_key)
                how = (f"[{setup.dry_rod_key}] 낚싯대 들고 → [{setup.back_key}]"
                       if rod else f"[{setup.back_key}]")
                # 이어지는 '다시 던짐'은 처음 · 낚싯대를 들기 시작할 때만 로그에
                # 적는다. 사이사이는 실행 상태 창에만 — 같은 줄이 쌓이지 않게.
                flow.say("다시 던짐",
                         f"두드리기만 {setup.tap_limit_s:g}초가 이어졌습니다 "
                         f"({streak}번째 연속) → {how}",
                         force=True,
                         log=streak in (1, ROD_AFTER_NUDGES))
                ctx.sleep(POLL_S)
                continue
            if what == "revive":
                if book:
                    book.write("revive", nth=flow.revives)
                flow.say("낚시 되살림",
                         f"{setup.dry_s:g}초 동안 한 마리도 못 낚았습니다 "
                         f"({flow.revives}번째)"
                         f"\n    → [Esc]×{setup.dry_esc_times} (신청 창 닫기) → "
                         f"[{setup.dry_rod_key or '안 누름'}] (낚싯대) → "
                         f"[{setup.back_key}] (다시 던지기)", force=True)
                ctx.sleep(POLL_S)
                continue
            if what == "recast" and book:
                book.write("recast", nth=flow.recasts)
            if what == "recast":
                # 판은 끝났는데 낚음 근거를 못 봤다. 그래도 던진다 — 안 던지면
                # 낚시가 여기서 멈춘다.
                flow.say("다시 던짐",
                         f"판이 끝났는데 낚음 근거(효과음·빨간 글씨·흔들림)를 "
                         f"하나도 못 봤습니다 ({flow.recasts}번째)"
                         f"\n    → [{setup.back_key}]로 낚시중으로 되돌립니다"
                         f"\n    " + flow.look_around(), force=True)
                ctx.sleep(POLL_S)
                continue
            if what == "cast" and book:
                book.write("cast", nth=flow.casts)
            if what == "cast":
                # 던질 때마다 같은 줄이라 로그에는 처음 한 번만.
                flow.say("던짐", f"{flow.casts}번째 — "
                                f"[{setup.cast_key}] · " + flow.look_around(),
                         force=True, log=flow.casts <= 1)
                ctx.sleep(POLL_S)
                continue
            if what != "minigame":
                # 두드리는 중이거나 기다리는 중이다. 두드림 자체가 간격을
                # 들고 있으므로 여기서는 짧게만 쉰다.
                ctx.sleep(0.01 if what == "tap" else POLL_S)
                continue

            # 판마다 같은 말이라 로그에는 안 적는다 — 판이 끝나면 한 줄로 요약한다.
            flow.say("미니게임 인식",
                     "본 것: " + " · ".join(flow.enter_signals)
                     + " → 겹칠 때만 누릅니다", force=True, log=False)
            result = flow.solve(lead, ratio)
            done += 1
            setup.rounds += 1
            if result.outcome == fishing.CLEAR:
                clears += 1
                setup.clears += 1
            # 배운 것을 바로 설정에 옮겨 둔다. 중간에 멈춰도 남는다.
            setup.lead_stats = lead.save()
            setup.lead_ms = lead.best
            if setup.learn_hit:
                setup.ratio_stats = ratio.save()
            widths = ""
            if flow.last_widths[1] > 0:
                widths = (f"\n    잰 폭 — 막대 {flow.last_widths[0]:.0f}px · "
                          f"물고기 {flow.last_widths[1]:.0f}px → 겹쳤다고 볼 "
                          f"거리 {flow.last_hit_px:.0f}px")
            rate = (flow.last_reads / result.seconds) if result.seconds else 0
            learned = ""
            if setup.learn_hit:
                learned = (f"\n    배운 겹침 배수 {ratio.best:.1f} "
                           f"(→ {flow.last_hit_px * ratio.best:.0f}px) · "
                           f"{ratio.table()}")
            # **안 눌렀는지, 눌렀는데 게임이 안 받았는지를 가른다.** 둘은 화면으로는
            # 똑같이 보인다(체력이 안 준다). 소리를 배워 뒀으면 소리가 가른다.
            heard = flow.last_click_sounds
            alarm = ""
            if heard is not None:
                def said(value):
                    return "안 배움" if value is None else f"{value}번"
                alarm = (f"\n    클릭 소리 — 맞음 {said(heard['hit'])} · 빗나감 "
                         f"{said(heard['miss'])} (보낸 클릭 {result.clicks}번 · "
                         f"촘촘한 연타는 하나로 셉니다)")
                # **둘 다 배웠을 때만** 경고한다. 맞음 소리만 배웠는데 그 판을 전부
                # 빗나갔다면 소리가 안 나는 게 당연하다.
                both = heard["hit"] is not None and heard["miss"] is not None
                if both and result.clicks and not (heard["hit"] or heard["miss"]):
                    alarm += ("\n    ⚠ 클릭을 보냈는데 클릭 소리가 한 번도 안 났습니다 "
                              "— 게임이 클릭을 못 받고 있을 수 있습니다 (관리자 "
                              "권한으로 실행했는지 · 클릭 범위 · 게임 창이 맨 앞인지)")
            if not result.clicks and result.seconds >= 1.0:
                alarm += ("\n    ⚠ 이 판에서 한 번도 안 눌렀습니다 — [인식 검사] → "
                          "[겹침 진단]으로 왜 안 누르는지 보세요")
            # 판마다 **한 줄.** 잰 폭 · 배운 배수 · 읽은 장 수는 판마다 비슷해서
            # 실행 상태 창과 기록 파일(data/fishlog)에만 남긴다. 경고는 그대로 적는다.
            short = (f"[{done}판째] {result.describe()}"
                     + (f" · 겹침 {result.shots}번 · 클릭 {result.clicks}번 "
                        f"(맞음 {result.hits} · 빗나감 {result.misses})"
                        if result.shots else ""))
            board = getattr(ctx, "board", None)
            if board is not None:
                board.set(판=(short + widths + learned
                             + f"\n화면 초당 {rate:.0f}장").replace("\n    ", "\n"))
            ctx.log(short + alarm)
            if book:
                book.round_done(
                    result, reads=flow.last_reads, read_rate=round(rate, 1),
                    bar_w=round(flow.last_widths[0], 1),
                    fish_w=round(flow.last_widths[1], 1),
                    base_hit_px=round(flow.last_hit_px, 1),
                    hit_sounds=heard["hit"] if heard else None,
                    miss_sounds=heard["miss"] if heard else None)
            flow.state = None  # 다음 상태는 반드시 알린다
            if flow.last_dry is not None:
                if book:
                    book.write("dry_round", **flow.last_dry)
                flow.last_dry = None
            if flow.closed_catch:
                report_catch()  # [Ctrl]은 판이 사라지자마자 이미 눌렀다
            if on_round is not None:
                on_round(result, None)
            if result.outcome == fishing.ABORTED and ctx.stopped:
                break
    except Aborted:
        pass
    finally:
        # 소리 듣는 실은 반드시 거둔다. 안 그러면 [정지]를 눌러도 계속 돌면서
        # 소리 장치를 붙잡고 있는다.
        flow.close_ear()

    rate = clears / done * 100 if done else 0.0
    line = f"낚시 끝 — {done}판 중 {clears}판 클리어 ({rate:.0f}%)"
    if setup.can_tell_caught:
        line += f" · 낚음 {flow.caught}마리"
    if flow.recasts:
        line += f" · 근거 없이 다시 던짐 {flow.recasts}회"
    if flow.nudges:
        line += f" · 두드리다 다시 던짐 {flow.nudges}회"
    if flow.digs:
        line += f" · 땅 파기 {flow.digs}회"
    if flow.buff_runs:
        line += f" · 버프 {flow.buff_runs}회"
    if flow.popups:
        line += f" · 중첩 알림 닫음 {flow.popups}회"
    if flow.revives:
        line += f" · 되살림 {flow.revives}회"
    if flow.fatigue_checks:
        line += (f" · 피로도 확인 {flow.fatigue_checks}회 "
                 f"(매크로 {flow.fatigue_runs}회)")
    line += (f" · 던짐 {flow.casts}회 · 두드림 {flow.taps}회 · "
             f"lead {lead.best:+.0f}ms · 명중률 {lead.rate * 100:.0f}% · "
             f"{lead.table()}")
    if setup.learn_hit and ratio.shots:
        line += f"\n    겹침 배수 {ratio.best:.1f} · {ratio.table()}"
    ctx.log(line)
    if book:
        book.write("end", rounds=done, clears=clears, caught=flow.caught,
                   casts=flow.casts, taps=flow.taps, nudges=flow.nudges,
                   recasts=flow.recasts, digs=flow.digs,
                   lead_ms=lead.best, ratio=ratio.best,
                   lead_table=lead.table(), ratio_table=ratio.table())
    return {"rounds": done, "clears": clears, "caught": flow.caught,
            "casts": flow.casts, "taps": flow.taps, "recasts": flow.recasts,
            "nudges": flow.nudges, "digs": flow.digs,
            "buffs": flow.buff_runs,
            "lead_ms": lead.best, "rate": lead.rate}
