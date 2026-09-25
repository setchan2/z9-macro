"""낚시 — 미니게임을 푼다.

미니게임은 이렇게 생겼다. 위에 물고기 체력 막대가 있고, 아래 트랙에서 **노란 막대**와
**물고기**가 서로 다른 속도로 좌우를 왕복한다. 둘이 겹칠 때 클릭하면 체력이 줄고,
체력을 다 깎으면 클리어다. 정해진 시간 안에 못 깎으면 경험치가 없다.

**빗나가면 벌칙이 있다** — 얻는 경험치가 줄고 물고기 체력이 회복된다. 되돌리는 양이
깎는 양보다 크므로, 헛클릭은 그냥 헛일이 아니라 손해다. 반대로 **겹쳐 있는 동안에는
몇 번을 눌러도 이득이다.** 이 두 가지가 아래 설계 전부를 결정한다.

## 규칙은 하나다 — 보이면 누른다

    읽는다 → 겹쳐 있으면 누른다 → 또 읽는다 → 또 누른다 → …

한때는 겹칠 시각을 미리 계산해 그 자리로 자러 갔다가, 깨어나서 겹쳐 있으면 눌렀다.
계산이 맞을 때는 잘 돌았지만 **틀리면 한 번도 못 눌렀다** — 도착해 보니 안 겹쳐 있으면
그대로 지나가 버렸기 때문이다. 겹침은 그동안에도 계속 일어나고 있는데 말이다.
**예측을 클릭의 조건으로 둔 것이 잘못이었다.**

이 컴퓨터에서 잰 값이다.

    화면 한 조각 읽기      6.06ms  (판만 한 크기 616x148 — 초당 165장)
    색 훑기 (620x39 띠)    0.07ms
    입력 내보내기          0.016ms
    짧은 대기의 오차       +0.4ms

초당 165장이면 한 번 겹쳐 있는 동안에도 열 장 넘게 본다. 그러니 어렵게 갈 이유가 없다.

**그 6ms는 우리 몫이 아니라 화면 합성 주기다.** 1000/165 = 6.06ms로 모니터 주사율과
딱 맞는다. 정말 그런지 확인하려고 도구(DC·비트맵·버퍼)를 매번 새로 만들지 않고 한 번
만들어 다시 쓰게 해 봤고, 느리다고 알려진 CAPTUREBLT 깃발도 빼 봤다. **셋 다 초당
165장으로 똑같았다.** 캡처 경로에는 남은 여유가 없다.

    지금 (매번 새로 만듦)          초당 165장 · 6.03ms
    도구 다시 쓰기                초당 165장 · 6.02ms
    도구 다시 쓰기 + CAPTUREBLT 뺌  초당 165장 · 6.04ms

다만 **크기와 무관하지는 않다.** 판만 한 크기에서는 고정 비용에 묻혀 안 보이지만,
1200x400을 찍으면 초당 64장(17ms)으로 떨어진다. 판을 좁게 잡으라는 말은 그래서다.

## 계산은 버리지 않았다 — 세 군데에 쓴다

    가려서 안 보일 때   둘이 겹치면 하나가 다른 하나를 가려 하필 가장 중요한 때
                        못 읽는다. 그때만 직전 모델로 메운다
    게임이 늦게 처리     지금 눈에 겹쳐 보여도 판정할 때는 벌어져 있을 수 있다.
                        배운 보정(lead)만큼 앞을 내다본다

셋 다 **모델이 최근 표본과 잘 맞을 때만** 쓴다. 어긋난 모델에 거부권이나 발언권을
주면 진짜 겹침까지 걷어내거나 헛클릭을 부른다.

## 두 가지를 스스로 배운다

    lead    겹치기 몇 ms 전에 눌러야 맞는지 (Lead)
    배수    잰 그림 폭의 몇 배까지를 겹친 것으로 볼지 (Ratio)

배수가 특히 중요하다. 그림 폭대로 잡으면 게임이 맞다고 치는 자리보다 훨씬 넓을 수
있고, 넓은 만큼이 고스란히 헛클릭이 되어 깎아 둔 체력을 도로 채워 준다. **명중률이
아니라 초당 깎은 체력으로** 고른다 — 명중률로 고르면 아주 좁게 잡아 백발백중이 되지만
클릭이 줄어 판을 못 끝낸다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# 표본을 몇 개까지 들고 모델을 세울지. 6ms 간격이므로 48개면 약 0.3초 치다.
#
# 처음에는 12개(70ms)만 봤다. 그 정도로는 속도 중앙값이 흔들리고, 무엇보다
# **한 프레임만 놓쳐도 표본이 통째로 날아가** 모델을 처음부터 다시 세워야 했다.
# 길게 들고 있으면 중간에 몇 장 못 읽어도 모델이 살아 있다.
TRACK_SAMPLES = 48

# 위상을 맞출 때 되짚어 볼 표본 수와, 얼마나 촘촘히 밀어 볼지.
PHASE_LOOK = 24
PHASE_STEPS = 21

# 앞으로 몇 ms까지 내다볼지. 멀리 볼수록 모델 오차가 커진다.
HORIZON_MS = 2500

# 가장 가까웠던 거리에서 이만큼 벌어지면 그 구간은 접는다(px).
PARTING_PX = 4.0

# 모델이 최근 표본과 이보다 더 어긋나 있으면 **믿지 않는다**(px).
#
# 눈으로 본 겹침을 모델이 거부하는 길이 딱 하나 있다 — 게임이 늦게 판정하는 만큼
# 앞을 내다보는 검사다. 모델이 엉터리면 그 검사가 진짜 겹침을 전부 걷어내고, 그러면
# 예전처럼 **한 번도 못 누르게 된다.** 잘 맞을 때만 거부권을 준다.
TRUST_PX = 6.0

# 둘이 겹쳐 하나가 다른 하나를 가렸을 때, "직전까지 붙어 오고 있었다"고 볼
# 시간(초). 이보다 오래된 관측으로는 안 보이는 동안을 겹침으로 치지 않는다.
BLIND_MEMORY_S = 0.12

# **닿은 것을 본 뒤, 안 보이는 동안에도 계속 누를 시간(초).**
#
# 막대가 물고기를 덮으면 물고기 색이 안 보인다. 그런데 그때가 가장 깊이 겹친
# 순간이다. 이 시간이 없으면 첫 접촉에 한 번 누르고 곧바로 손을 떼게 된다 —
# 실제 기록에서 겹침 하나에 클릭이 딱 한 번씩만 나갔다.
#
# 겹쳐 있는 시간 자체가 보통 0.1~0.3초라 그 언저리로 잡는다. 너무 길면 이미
# 갈라선 뒤에도 누르게 되고, 너무 짧으면 가려진 동안을 못 메운다.
HIDDEN_S = 0.18

# 화면에서 물체를 못 본 채로 이만큼 지나면 모델을 버린다(초).
# 그 전까지는 **직전 모델로 계속 쏜다** — 왕복 운동은 화면을 못 읽는 동안에도
# 그대로 이어지므로, 몇 장 놓쳤다고 예측이 틀려지지 않는다.
BLIND_GRACE_S = 1.2

# 클릭한 뒤 결과를 이만큼까지 기다린다(초). 체력이 줄면 그 즉시 맞은 것이고,
# 여기까지 안 줄면 빗나간 것이다. 게임이 클릭을 늦게 처리하는 만큼보다 넉넉해야
# 한다 — 짧으면 맞은 것을 빗나갔다고 세고, 그 성적으로 보정을 배운다.
VERDICT_WAIT = 0.25

# 체력이 이만큼 내리 0으로 읽혀야 깬 것으로 보고 손을 뗀다(초). 진짜로 깨면 판이
# 곧 사라져서 이보다 먼저 끝난다 — 이것은 판이 안 사라질 때를 위한 마지막 한도다.
ZERO_HOLD_S = 1.5


# --------------------------------------------------------------------------
# 색 훑기 — 미니게임 도중에 쓰는 유일한 화면 읽기
# --------------------------------------------------------------------------
def find_center(buf, width, row, target, tol, x0=0, x1=None):
    """그 **한 줄**에서 target 색인 칸들의 가운데 x. 없으면 None.

    가운데를 쓰는 이유는 가장자리가 안티에일리어싱으로 흐려지기 때문이다. 첫
    칸만 보면 흐린 정도에 따라 한두 칸씩 흔들린다.
    """
    got, _count = scan_band(buf, width, target, tol, x0, x1, row, row + 1)
    return got


def count_color(buf, width, row, target, tol, x0=0, x1=None):
    """그 한 줄에서 target 색인 칸 수."""
    _got, count = scan_band(buf, width, target, tol, x0, x1, row, row + 1)
    return count


# 한 띠에서 몇 줄만 훑을지. 물체는 띠 높이를 가로지르므로 몇 줄만 봐도 가로
# 위치는 똑같이 나온다. 39줄을 다 보면 그만큼 느려질 뿐이다.
SCAN_ROWS = 6

# 채널 값이 허용 범위 안이면 1, 아니면 0으로 바꾸는 표. 색마다 한 번만 만든다.
_TABLES: dict = {}


def _table(value: int, tol: int) -> bytes:
    key = (value, tol)
    got = _TABLES.get(key)
    if got is None:
        lo, hi = value - tol, value + tol
        got = bytes(1 if lo <= i <= hi else 0 for i in range(256))
        if len(_TABLES) > 64:
            _TABLES.clear()
        _TABLES[key] = got
    return got


# 맞은 칸들이 이만큼 안쪽으로 떨어져 있으면 **한 덩어리**로 본다(px).
#
# 물고기 그림은 속이 비거나 지느러미가 떨어져 보일 수 있어서, 조금 벌어진 것은
# 이어 붙여야 한 마리로 읽힌다. 반대로 저 멀리 트랙 끝에 걸린 잡티는 이만큼으로는
# 절대 안 이어지므로 따로 남는다.
MERGE_PX = 24


def _clusters(found: bytes, x0: int):
    """맞은 칸들을 **덩어리로 묶는다.** (칸 수, 왼쪽, 오른쪽)들을 돌려준다.

    이걸 안 하면 저 멀리 걸린 잡티 한두 칸이 폭을 통째로 망친다. 실제 설정에서
    물고기 폭이 499px(트랙 518px)로 잡힌 적이 있는데, 진짜 물고기는 60px이고
    나머지는 트랙 양 끝에 걸린 2px짜리 잡티였다. 그 폭으로 겹침 거리를 뽑으면
    207px이 되어 사실상 늘 겹쳤다고 보고 누르게 된다.
    """
    out = []
    pos = found.find(1)
    if pos < 0:
        return out
    left = right = pos
    count = 1
    pos = found.find(1, pos + 1)
    while pos >= 0:
        if pos - right <= MERGE_PX:
            right = pos
            count += 1
        else:
            out.append((count, left, right))
            left = right = pos
            count = 1
        pos = found.find(1, pos + 1)
    out.append((count, left, right))
    return [(c, x0 + lo, x0 + hi) for c, lo, hi in out]


def scan_span(buf, width, target, tol, x0, x1, y0, y1, rows: int = 0):
    """띠 안에서 target 색을 찾는다. (가운데 x, 칸 수, 왼쪽 끝, 오른쪽 끝).

    **한 줄이 아니라 띠로 보는 이유.** 한 줄만 훑으면 사람이 그 줄을 정확히
    짚어야 하고, 물고기처럼 속이 빈 그림은 하필 그 줄에 아무것도 안 걸리는 일이
    생긴다. 몇 줄을 함께 보면 훨씬 잘 잡힌다.

    **가장 큰 덩어리만 쓴다.** 처음에는 맞은 칸 전체의 왼쪽 끝~오른쪽 끝을 폭으로
    삼았는데, 저 멀리 걸린 잡티 한두 칸에 폭이 통째로 망가졌다(60px짜리 물고기가
    499px로 잡혔다). 겹쳤다고 볼 거리는 이 폭에서 나오므로, 그러면 트랙의 40%가
    창이 되어 늘 누르게 된다. 지금은 떨어진 것들을 덩어리로 묶고 **가장 큰 덩어리**의
    자리와 폭을 쓴다.

    가운데는 그 덩어리 안에서 맞은 칸들의 x 평균이다. 좌우 끝의 중점을 쓰면 한쪽에
    치우친 그림에서 가운데가 밀린다.

    ## 왜 이렇게 꼬아 놓았나

    처음에는 칸마다 파이썬으로 세 채널을 견줬다. 620x39 띠 하나에 2.8ms가 들었고,
    막대·물고기 둘이면 5.6ms다. 화면 캡처가 6.9ms(모니터 주사율에 묶인 하한)이니
    **읽는 속도가 절반으로 깎인 셈**이었다.

    그래서 파이썬 반복문을 걷어내고 전부 C 쪽 호출로 옮겼다.

        row[0::4]        채널 하나만 뽑아낸다 (C)
        .translate(표)   허용 범위 안이면 1, 밖이면 0 (C)
        정수 AND         세 채널이 모두 맞는 자리만 남긴다 (C)
        정수 OR          여러 줄을 한 줄로 겹친다 (C)
        .count(1)        맞은 칸 수 (C)
        .find(1, i)      맞은 자리로 곧장 건너뛴다 (C)

    남는 파이썬 반복은 **덩어리를 묶는 한 바퀴**뿐이다.
    """
    if x1 is None:
        x1 = width
    n = x1 - x0
    if n <= 0 or y1 <= y0:
        return (None, 0, 0.0, 0.0)

    tr, tg, tb = target
    t_b, t_g, t_r = _table(tb, tol), _table(tg, tol), _table(tr, tol)

    ys = range(y0, y1)
    cap = rows or SCAN_ROWS
    if cap and (y1 - y0) > cap:
        step = (y1 - y0) / cap
        ys = [y0 + int(i * step) for i in range(cap)]
    # 몇 줄만 봤으면 칸 수도 그만큼 적게 나온다. **띠 전체를 본 셈으로 되돌려
    # 준다** — 안 그러면 "몇 칸 이상이면 찾은 것" 기준이 전부 뜻을 잃는다.
    scale = (y1 - y0) / len(ys)

    total = 0
    combined = 0  # 줄들을 한 줄로 겹친 것 — 가운데를 셀 때 쓴다
    spans = []  # 줄마다 (폭, 가운데, 왼쪽, 오른쪽)
    for y in ys:
        base = (y * width + x0) * 4
        row = buf[base:base + n * 4]
        mask = (int.from_bytes(row[0::4].translate(t_b), "big")
                & int.from_bytes(row[1::4].translate(t_g), "big")
                & int.from_bytes(row[2::4].translate(t_r), "big"))
        if not mask:
            continue
        found = mask.to_bytes(n, "big")
        total += found.count(1)
        combined |= mask
        groups = _clusters(found, x0)
        if not groups:
            continue
        _big, left, right = max(groups)
        # 가운데는 그 덩어리 안에서만 센다.
        weighted = 0
        seen = 0
        pos = found.find(1, left - x0)
        while 0 <= pos <= right - x0:
            weighted += pos
            seen += 1
            pos = found.find(1, pos + 1)
        if seen:
            spans.append((right - left + 1, x0 + weighted / seen,
                          float(left), float(right + 1)))
    if total == 0 or not spans:
        return (None, 0, 0.0, 0.0)

    # **가운뎃값을 기준으로 삼고, 거기 닿는 줄들을 이어 붙인다.**
    #
    # 가운뎃값만 쓰면 한 줄짜리 줄무늬는 잘 막히지만, 줄마다 두께가 다른 그림이
    # 잘린다 — 머리만 두꺼운 물고기에서 60px짜리가 18px(머리)로 잡혔다.
    # 겹침을 그 폭으로 보면 몸통에 닿아 있는데도 떨어진 줄 안다.
    #
    # 기준에 닿는 것만 이어 붙이면 둘 다 된다. 멀리 있는 줄무늬는 기준과 안
    # 닿으므로 빠지고, 같은 그림의 머리와 몸통은 서로 닿으므로 하나가 된다.
    spans.sort()
    _w, _c, left, right = spans[len(spans) // 2]
    grew = True
    while grew:
        grew = False
        for _sw, _sc, lo, hi in spans:
            if lo > right + MERGE_PX or hi < left - MERGE_PX:
                continue  # 기준과 동떨어진 줄 — 남의 것이다
            if lo < left or hi > right:
                left, right = min(left, lo), max(right, hi)
                grew = True

    # 가운데는 이어 붙인 자리 안에서만 센다.
    found = combined.to_bytes(n, "big")
    weighted = 0
    seen = 0
    pos = found.find(1, max(0, int(left) - x0))
    stop = min(n - 1, int(right) - x0)
    while 0 <= pos <= stop:
        weighted += pos
        seen += 1
        pos = found.find(1, pos + 1)
    centre = x0 + weighted / seen if seen else spans[len(spans) // 2][1]
    return (centre, int(round(total * scale)), left, right)


def scan_band(buf, width, target, tol, x0, x1, y0, y1):
    """scan_span에서 (가운데 x, 칸 수)만. 폭이 필요 없을 때 쓴다."""
    got = scan_span(buf, width, target, tol, x0, x1, y0, y1)
    return (got[0], got[1])


def fill_of(buf, width, target, tol, x0, x1, y0, y1):
    """게이지가 얼마나 차 있나. 0.0~1.0. 아무것도 안 보이면 0.

    **칸 수를 세지 않고 가장 오른쪽 칸까지의 길이를 쓴다.** 게이지에는 눈금
    선이 그어져 있어서(이 게임도 그렇다) 칸을 세면 눈금만큼 모자라게 나온다.
    남아 있는 부분은 왼쪽에서 이어지므로, 마지막으로 보인 자리까지가 곧 길이다.
    """
    tr, tg, tb = target
    right = -1
    seen = 0
    for y in range(y0, y1):
        base = y * width * 4
        for x in range(x1 - 1, x0 - 1, -1):
            i = base + x * 4
            if (
                abs(buf[i + 2] - tr) <= tol
                and abs(buf[i + 1] - tg) <= tol
                and abs(buf[i] - tb) <= tol
            ):
                seen += 1
                if x > right:
                    right = x
                break  # 이 줄에서 가장 오른쪽을 찾았으니 더 볼 것 없다
    if right < x0 or seen == 0:
        return 0.0
    span = max(1, x1 - x0)
    return min(1.0, (right - x0 + 1) / span)


# --------------------------------------------------------------------------
# 움직임 모델 — 등속 왕복(삼각파)
# --------------------------------------------------------------------------
@dataclass
class Motion:
    """한 물체의 지금 상태와 속도. 좌우 끝에서 튕긴다."""

    at: float  # 기준 시각 (perf_counter)
    x: float
    speed: float  # px/ms, 항상 양수
    direction: int  # +1 오른쪽, -1 왼쪽
    left: float
    right: float
    residual: float = 0.0  # 최근 표본이 모델과 얼마나 어긋났나 (px)
    cycle_ms: float = 0.0  # 한 바퀴(왼쪽 끝 → 오른쪽 끝 → 왼쪽 끝)에 걸리는 시간

    def phase(self) -> float:
        """기준 시각의 위상. 왕복 한 바퀴를 [0, 2*span)으로 편 좌표다.

        앞 절반(0~span)은 오른쪽으로 가는 중, 뒷 절반은 왼쪽으로 가는 중이다.
        **왼쪽으로 가는 중이면 뒷 절반에 놓아야 한다.** 이걸 빠뜨리면 왼쪽으로
        가던 물체가 오른쪽으로 가는 것으로 계산되어 예측이 통째로 틀어진다.
        """
        span = self.right - self.left
        offset = self.x - self.left
        return offset if self.direction >= 0 else (2.0 * span - offset)

    def where(self, when: float) -> float:
        """when(초) 시각의 위치. 끝에서 튕기는 것을 접어서 계산한다."""
        span = self.right - self.left
        if span <= 0:
            return self.x
        cycle = span * 2.0
        folded = (self.phase() + self.speed * (when - self.at) * 1000.0) % cycle
        if folded < 0:
            folded += cycle
        return self.left + (folded if folded <= span else cycle - folded)


def _miss(motion: "Motion", samples) -> float:
    """이 모델이 표본들과 평균 몇 px 어긋나는가."""
    total = 0.0
    for when, x in samples:
        total += abs(motion.where(when) - x)
    return total / len(samples)


def fit_motion(samples: list[tuple[float, float]], left: float, right: float):
    """(시각, 위치) 표본들에서 움직임을 뽑아낸다. 못 뽑으면 None.

    속도는 이웃한 표본의 차이에서 얻되 **중앙값**을 쓴다. 튕기는 순간의 한 걸음과
    가끔 튀는 표본을 평균으로 섞으면 속도가 통째로 틀어지기 때문이다.

    위상은 **마지막 표본에 걸지 않는다.** 마지막 한 장이 1px만 흔들려도 모델
    전체가 그만큼 밀리고, 그 밀림이 1초 뒤 예측에서는 몇십 px이 된다. 대신 모델을
    시간축으로 조금씩 밀어 보며 최근 표본 전체와 가장 잘 맞는 자리를 고른다.
    """
    if len(samples) < 4:
        return None
    span = right - left
    if span <= 0:
        return None

    speeds = []
    for i in range(len(samples) - 1):
        dt = (samples[i + 1][0] - samples[i][0]) * 1000.0
        if dt <= 0:
            continue
        speeds.append(abs(samples[i + 1][1] - samples[i][1]) / dt)
    if len(speeds) < 3:
        return None
    speeds.sort()
    speed = speeds[len(speeds) // 2]
    if speed <= 0.0001:
        return None

    # 방향은 마지막 몇 걸음의 합으로 본다. 한 걸음만 보면 튕기는 순간에 뒤집힌다.
    tail = samples[-4:]
    drift = tail[-1][1] - tail[0][1]
    direction = 1 if drift >= 0 else -1

    motion = Motion(
        at=samples[-1][0], x=samples[-1][1], speed=speed,
        direction=direction, left=left, right=right,
    )

    # 위상 맞추기 — 모델을 앞뒤로 조금씩 밀어 보고 가장 잘 맞는 자리를 쓴다.
    recent = samples[-PHASE_LOOK:]
    cycle_ms = 2.0 * span / speed
    reach = min(cycle_ms * 0.25, 60.0)  # 이보다 크게 밀 일은 없다
    best_shift, best_miss = 0.0, _miss(motion, recent)
    for step in range(1, PHASE_STEPS // 2 + 1):
        for sign in (-1.0, 1.0):
            shift = sign * reach * step / (PHASE_STEPS // 2)
            motion.at = samples[-1][0] + shift / 1000.0
            got = _miss(motion, recent)
            if got < best_miss:
                best_shift, best_miss = shift, got
    motion.at = samples[-1][0] + best_shift / 1000.0

    # 이 모델로 최근 표본을 되짚어 얼마나 어긋나는지 잰다. 이것이 곧 신뢰도다.
    worst = 0.0
    for when, x in recent[-8:]:
        worst = max(worst, abs(motion.where(when) - x))
    motion.residual = worst
    motion.cycle_ms = cycle_ms
    return motion


# --------------------------------------------------------------------------
# 겹칠 시각 예측
# --------------------------------------------------------------------------
@dataclass
class Shot:
    """노려 볼 만한 한 번의 겹침.

    한 순간이 아니라 **구간**이다. 겹쳐 있는 동안에는 몇 번을 눌러도 되므로,
    시작과 끝을 알면 그 사이를 두드릴 수 있다. 한 번만 정확히 누르려 하면
    모델이 몇 ms만 어긋나도 통째로 빗나간다.
    """

    when: float  # 가운데가 겹치는 시각 (perf_counter)
    start: float  # 겹치기 시작하는 시각
    end: float  # 겹침이 끝나는 시각
    gap_speed: float  # 겹치는 순간의 상대 속도 (px/ms)
    window_ms: float  # 맞을 수 있는 시간 폭
    horizon_ms: float  # 지금부터 얼마나 뒤인가
    residual: float  # 두 모델 중 나쁜 쪽의 어긋남


def state_at(m: Motion, when: float) -> tuple[float, float, float]:
    """그 시각의 (위치, 부호 있는 속도 px/ms, 다음 튕김까지 남은 ms)."""
    span = m.right - m.left
    if span <= 0:
        return (m.x, 0.0, 1e9)
    cycle = span * 2.0
    folded = (m.phase() + m.speed * (when - m.at) * 1000.0) % cycle
    if folded < 0:
        folded += cycle
    if folded <= span:
        return (m.left + folded, m.speed, (span - folded) / m.speed)
    return (m.left + (cycle - folded), -m.speed, (cycle - folded) / m.speed)


def next_crossing(bar: Motion, fish: Motion, now: float, hit_px: float,
                  horizon_ms: float = HORIZON_MS) -> Shot | None:
    """다음에 겹치는 시각. 없으면 None.

    1ms씩 굴려 보는 대신 **식으로 푼다.** 두 물체 다 튕기기 전까지는 등속이므로,
    그 사이에서 위치 차는 직선이고 0이 되는 시각이 한 번에 나온다. 튕기는 시각으로
    구간을 끊어 가며 앞으로 나아가면 되는데, 2.5초 안에 그런 구간은 몇 개뿐이다.

    (굴려 보는 방식은 2500걸음이라 표본마다 하면 너무 무거웠다. 식으로 풀면
    보통 두세 번의 계산으로 끝난다.)
    """
    at = now
    for _ in range(40):
        used_ms = (at - now) * 1000.0
        if used_ms >= horizon_ms:
            return None
        pb, vb, rb = state_at(bar, at)
        pf, vf, rf = state_at(fish, at)
        segment = min(rb, rf, horizon_ms - used_ms)
        if segment <= 0:
            return None

        gap = pb - pf
        closing = vb - vf
        if abs(closing) < 1e-9:
            # 나란히 간다. 이미 겹쳐 있으면 이 구간 내내 기회다.
            if abs(gap) <= hit_px:
                return Shot(
                    when=at, start=at, end=at + segment / 1000.0,
                    gap_speed=0.0, window_ms=segment, horizon_ms=used_ms,
                    residual=max(bar.residual, fish.residual),
                )
            at += segment / 1000.0
            continue

        root_ms = -gap / closing
        if 0.0 <= root_ms <= segment:
            cross = at + root_ms / 1000.0
            # 겹쳐 있는 **구간**을 구한다. 가운데 거리가 hit_px 안에 드는 동안이
            # 곧 그 구간이고, 등속이므로 앞뒤로 같은 시간만큼 벌어진다.
            half_ms = hit_px / abs(closing)
            return Shot(
                when=cross,
                start=cross - half_ms / 1000.0,
                end=cross + half_ms / 1000.0,
                gap_speed=abs(closing),
                window_ms=2.0 * half_ms,
                horizon_ms=(cross - now) * 1000.0,
                residual=max(bar.residual, fish.residual),
            )
        # 이 구간에는 없다. 튕기는 지점 바로 뒤로 넘어간다.
        at += segment / 1000.0 + 1e-9


# --------------------------------------------------------------------------
# 자가 보정 — 내 지연을 스스로 배운다
# --------------------------------------------------------------------------
class Lead:
    """겹치기 몇 ms 전에 눌러야 맞는지. 써 보고 가장 잘 맞는 값을 고른다.

    **빗나감 한 번은 이르게 눌렀는지 늦게 눌렀는지 알려주지 않는다.** 체력이
    안 줄었다는 것만 알 뿐, 어느 쪽으로 빗나갔는지는 화면에 남지 않는다. 그래서
    처음에는 "빗나가면 한 방향으로 밀고, 세 번 이어 빗나가면 뒤집는다"로 만들었는데
    시험해 보니 **제자리를 맴돌기만 했다** (게임 지연 30ms를 넣어도 lead 가 8ms에서
    안 움직이고 명중률 12%).

    그래서 방식을 바꿨다. 후보 값 몇 개를 **돌려 가며 써 보고 성적을 적어 둔 뒤,
    가장 잘 맞는 값을 쓴다.** 가끔은 옆 값도 써 본다 — 게임이나 컴퓨터 사정이
    달라지면 정답도 달라지기 때문이다.

    낚시는 하루에도 수백 번 하므로, 이 표를 판을 넘겨 이어 가면 금방 수렴한다.
    **음수도 후보다** — 게임이 조금 지난 화면으로 판정하면 겹친 뒤에 눌러야 맞는다.
    """

    # 후보 (ms). 양수 = 겹치기 전에 미리, 음수 = 겹친 뒤에 누른다.
    #
    # 양쪽으로 똑같이 벌려 둔다. 게임이 클릭을 늦게 받으면 미리 눌러야 하고
    # (양수), 이미 지난 화면으로 판정하면 늦게 눌러야 한다(음수). 어느 쪽인지는
    # 게임과 컴퓨터 사정에 달렸으므로 한쪽만 넓게 두면 그쪽으로만 맞출 수 있다.
    GRID = tuple(float(v) for v in range(-60, 61, 10))
    MIN_TRIALS = 4  # 후보마다 최소 이만큼은 써 봐야 성적을 믿는다
    # 처음에는 자주 곁눈질하고, 자리를 잡으면 뜸하게 본다. 계속 8번에 한 번씩
    # 옆 값을 써 보면 그 시도가 대부분 빗나가서 안정 구간 명중률을 갉아먹는다
    # (시험에서 정착 후 lead 0의 성적은 1109/1109인데 전체 평균은 83%였다).
    EXPLORE_EARLY = 8
    EXPLORE_LATE = 60
    SETTLED = 120  # 이만큼 쏘고 나면 자리를 잡은 것으로 본다

    def __init__(self, ms: float | None = None) -> None:
        self.stats: dict[float, list[int]] = {v: [0, 0] for v in self.GRID}
        self.shots = 0
        self.current = 0.0 if ms is None else self._nearest(ms)

    def _nearest(self, ms: float) -> float:
        return min(self.GRID, key=lambda v: abs(v - ms))

    @property
    def ms(self) -> float:
        return self.current

    def pick(self) -> float:
        """이번에 쓸 값을 고른다. 쏘기 직전에 부른다."""
        every = self.EXPLORE_EARLY if self.shots < self.SETTLED else self.EXPLORE_LATE
        thin = [v for v in self.GRID if self.stats[v][1] < self.MIN_TRIALS]
        if thin:
            self.current = thin[0]
        elif self.shots % every == 0:
            # 가끔 가장 좋은 값의 이웃도 써 본다.
            best = self.best
            index = self.GRID.index(best)
            side = 1 if (self.shots // every) % 2 else -1
            self.current = self.GRID[min(max(index + side, 0), len(self.GRID) - 1)]
        else:
            self.current = self.best
        return self.current

    @property
    def best(self) -> float:
        """가장 잘 맞는 후보. 아직 아무것도 안 써 봤으면 0.

        점수가 모두 0일 때 max()는 목록의 첫 값(-60)을 고른다. 그러면 배운 것이
        없는데도 "보정된 lead -60ms"라고 내보이게 되어, 아직 아무 근거가 없다는
        사실이 화면에서 사라진다.
        """
        if not any(shots for _h, shots in self.stats.values()):
            return 0.0

        def score(value):
            hits, shots = self.stats[value]
            return (hits / shots) if shots else 0.0
        return max(self.GRID, key=score)

    def hit(self) -> None:
        self.stats[self.current][0] += 1
        self.stats[self.current][1] += 1
        self.shots += 1

    def miss(self) -> None:
        self.stats[self.current][1] += 1
        self.shots += 1

    @property
    def hits(self) -> int:
        return sum(h for h, _s in self.stats.values())

    @property
    def misses(self) -> int:
        return sum(s - h for h, s in self.stats.values())

    @property
    def rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def load(self, stats: dict, ms: float | None = None) -> "Lead":
        """저장해 둔 성적을 되살린다. 낚시는 하루에도 수백 번이라, 판마다
        처음부터 배우면 그 판은 늘 탐색만 하다 끝난다."""
        for key, value in (stats or {}).items():
            try:
                slot = self._nearest(float(key))
            except (TypeError, ValueError):
                continue
            hits, shots = int(value[0]), int(value[1])
            if shots >= hits >= 0:
                self.stats[slot] = [hits, shots]
        self.shots = sum(shot for _h, shot in self.stats.values())
        if ms is not None:
            self.current = self._nearest(ms)
        return self

    def save(self) -> dict:
        """저장할 성적. 키는 JSON을 위해 문자열로."""
        return {f"{k:.0f}": list(v) for k, v in self.stats.items() if v[1]}

    def table(self) -> str:
        parts = []
        for value in self.GRID:
            hits, shots = self.stats[value]
            if shots:
                parts.append(f"{value:+.0f}:{hits}/{shots}")
        return " ".join(parts)


# --------------------------------------------------------------------------
# 미니게임 한 판 (화면 읽기는 밖에서 넣어 준다 — 시험할 수 있게)
# --------------------------------------------------------------------------
CLEAR = "clear"
TIMEOUT = "timeout"
ABORTED = "aborted"


@dataclass
class Result:
    outcome: str
    shots: int = 0  # 노린 구간 수
    clicks: int = 0  # 실제로 누른 횟수 (한 구간에 여러 번)
    hits: int = 0
    misses: int = 0
    skipped: int = 0
    seconds: float = 0.0
    lead_ms: float = 0.0
    hit_px: float = 0.0  # 이 판에서 실제로 쓴 '겹쳤다고 볼 거리'
    ratio: float = 0.0  # 잰 폭의 몇 배였나
    note: str = ""

    @property
    def rate(self) -> float:
        return self.hits / self.shots if self.shots else 0.0

    def describe(self) -> str:
        mark = {CLEAR: "클리어", TIMEOUT: "시간 초과", ABORTED: "중단"}[self.outcome]
        return (
            f"{mark} · {self.seconds:.1f}초 · 노린 겹침 {self.shots}회 "
            f"(맞음 {self.hits} 빗나감 {self.misses}) 명중률 {self.rate * 100:.0f}% · "
            f"클릭 {self.clicks}번 · 넘긴 겹침 {self.skipped}회 · "
            f"보정된 lead {self.lead_ms:.1f}ms"
        )


class Board:
    """미니게임 화면을 읽고 클릭을 보내는 쪽.

    시계도 여기서 받는다. 그래야 시험할 때 **가상 시계**로 바꿔 끼워서 20초짜리
    판을 순식간에 수백 번 돌려 볼 수 있다. 실시간으로만 시험할 수 있으면 표본이
    모자라 "명중률 몇 %"를 믿을 수 없다.
    """

    def now(self) -> float:
        return time.perf_counter()

    def touch(self) -> float | None:
        """지금 **겹친 폭**(px). 0 이상이면 닿아 있다. 모르면 None.

        중심 거리로 되짚는 것보다 이쪽이 곧바르다 — 그림이 좌우로 안 고른
        물고기에서도 어긋나지 않는다.
        """
        return None

    def read(self) -> tuple[float, float | None, float | None, int] | None:
        """(시각, 막대 x, 물고기 x, 남은 체력). 창이 닫혔으면 None."""
        raise NotImplementedError

    def track_range(self, which: str = "bar") -> tuple[float, float]:
        """그 물체의 **중심**이 오가는 좌우 끝.

        막대와 물고기는 폭이 달라서 튕기는 자리도 다르다. 트랙 양 끝을 그대로
        쓰면 폭의 절반만큼 어긋나고, 그만큼 끝 근처 예측이 통째로 틀린다.
        """
        raise NotImplementedError

    def click(self) -> None:
        raise NotImplementedError

    def rearm(self) -> None:
        """다음 구간을 위해 겨눔을 푼다.

        한 구간 안에서는 **한 자리를 계속 누른다.** 클릭마다 커서를 옮기면 그
        비용이 고스란히 클릭 수를 깎고, 게임이 끌기로 볼 위험도 있다. 자리를
        바꾸는 것은 구간과 구간 사이면 충분하다.
        """

    def sleep_until(self, when: float) -> None:
        raise NotImplementedError

    def alive(self) -> bool:
        return True

    def closed_verdict(self, health_before) -> str:
        """창이 사라졌을 때 무엇으로 볼지.

        마지막 한 방과 창이 닫히는 사이는 몇 ms뿐이라 **체력 0을 못 보고 지나갈
        수 있다.** 실제 화면에서는 거의 매번 그렇다. 그래서 실물 판은 '거의 다
        깎였으면 깬 것'으로 보도록 이 자리를 열어 둔다.
        """
        return CLEAR if health_before == 0 else ABORTED


class Ratio:
    """겹쳤다고 볼 거리를 잰 폭의 **몇 배로 잡을지.** 써 보고 고른다.

    잰 폭에서 뽑은 거리는 "두 그림의 가장자리가 닿는 순간"이다. 그런데 **게임이
    맞았다고 치는 자리는 그보다 훨씬 좁을 수 있다.** 물고기 그림이 90px이라고
    게임이 90px 내내 맞다고 해 주지는 않는다 — 그림에는 지느러미며 여백이 있고,
    판정은 보통 그 안쪽 어딘가에서만 선다.

    실제로 이것 때문에 크게 틀렸다. 잰 폭으로 창을 잡고 그 안에서 쉬지 않고
    눌렀더니 **누른 것의 여든에 하나 꼴로만 맞고 나머지는 도로 체력을 채워 줬다.**

    ## 명중률로 고르면 안 된다 — 여기서 한 번 크게 틀렸다

    처음에는 lead와 똑같이 **명중률**로 후보를 골랐다. 그랬더니 배수가 0.2까지
    쪼그라들었다. 아주 좁게 잡으면 누르는 족족 맞으니 명중률은 100%가 되는데,
    **판당 클릭이 15번에서 8번으로 줄어 물고기가 안 죽는다.** 시늉으로 재 보니
    클리어율이 100%에서 28%로 무너졌다.

    맞히는 것이 목적이 아니라 **판을 끝내는 것**이 목적이다. 그래서 지금은
    **초당 깎은 체력**으로 고른다. 빗나가면 체력이 도로 차오르므로 그 손해까지
    저절로 셈에 들어간다 — 넓게 잡아 헛클릭이 많으면 점수가 떨어지고, 좁게 잡아
    기회를 놓쳐도 점수가 떨어진다. 그 사이 어딘가가 가장 좋은 값이다.

    **시간은 고른 순간부터 잰다.** 판정이 난 순간까지가 아니라, 그 배수를 쓰기로
    한 때부터 결과가 나올 때까지를 통째로 센다. 그래야 "좁게 잡아 겹침 자체를
    통째로 놓친" 시간도 그 배수의 잘못으로 셈해진다.
    """

    # 후보. 1.0 = 가장자리가 닿기만 하면, 0.5 = 절반 안쪽에서만.
    #
    # **0.2까지 내려 보다가 크게 데었다.** 잰 폭이 40px일 때 배수 0.2면 창이
    # 8px이다. 게임이 40px 안이면 맞다고 쳐 주는데 8px만 노리면, 두 물체가
    # 스치듯 지나가는 겹침은 **가장 가까운 순간조차 8px 안에 안 들어와** 그 구간을
    # 통째로 건너뛴다. 시늉으로 세 보니 겹침 여섯 번 중 두 번만 눌렀다.
    #
    # 아래를 0.5로 잘랐다. 그보다 좁혀야 이득인 게임이라면 애초에 잰 폭이 잘못
    # 잡힌 것이고, 그건 색과 영역을 다시 골라야 할 일이지 창을 좁혀 때울 일이 아니다.
    GRID = (0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
    MIN_TRIALS = 4  # 후보마다 최소 이만큼은 써 봐야 성적을 믿는다
    EXPLORE_EARLY = 8
    EXPLORE_LATE = 40
    SETTLED = 80

    def __init__(self, value: float | None = None,
                 learn: bool = True) -> None:
        # 후보마다 [깎은 체력 합, 쓴 시간 합(ms), 써 본 횟수]
        self.stats: dict[float, list[int]] = {v: [0, 0, 0] for v in self.GRID}
        self.shots = 0
        self.learn = learn
        self.current = 1.0 if value is None else self._nearest(value)

    def _nearest(self, value: float) -> float:
        return min(self.GRID, key=lambda v: abs(v - value))

    @property
    def value(self) -> float:
        return self.current

    def pick(self) -> float:
        """이번 묶음에 쓸 배수. 고르는 규칙은 lead와 같다.

        **안 배우기로 했으면 정해진 값을 그대로 쓴다.** 여기서 한 번 데었다 —
        배수를 안 넘겨 준 쪽에서도 배우는 놈이 만들어져 후보를 돌아다녔고, 첫
        후보가 0.2라 창이 5분의 1로 쪼그라들었다. 판당 클릭이 15번에서 6번으로
        줄고 클리어율이 100%에서 17%로 무너졌는데, 아무도 배우라고 한 적이 없었다.
        """
        if not self.learn:
            return self.current
        every = (self.EXPLORE_EARLY if self.shots < self.SETTLED
                 else self.EXPLORE_LATE)
        # 아직 안 써 본 후보부터 채운다. **넓은 쪽부터** 본다 — 좁은 쪽으로
        # 시작하면 배우는 동안 겹침을 놓쳐 그 판을 통째로 버리게 된다.
        thin = [v for v in reversed(self.GRID)
                if self.stats[v][2] < self.MIN_TRIALS]
        if thin:
            self.current = thin[0]
        elif self.shots % every == 0:
            best = self.best
            index = self.GRID.index(best)
            side = 1 if (self.shots // every) % 2 else -1
            self.current = self.GRID[min(max(index + side, 0),
                                         len(self.GRID) - 1)]
        else:
            self.current = self.best
        return self.current

    def score(self, value: float) -> float:
        """그 배수의 성적 — 초당 깎은 체력."""
        damage, spent_ms, tries = self.stats[value]
        if tries <= 0 or spent_ms <= 0:
            return 0.0
        return damage * 1000.0 / spent_ms

    @property
    def best(self) -> float:
        """가장 잘 깎는 배수. 아직 아무것도 안 써 봤으면 1.0(예전 그대로)."""
        if not any(tries for _d, _t, tries in self.stats.values()):
            return 1.0
        return max(self.GRID, key=self.score)

    def reward(self, damage: int, seconds: float) -> None:
        """이번 묶음에서 얼마나 깎았고 얼마나 걸렸나."""
        if not self.learn:
            return
        self._reward(damage, seconds)

    def _reward(self, damage: int, seconds: float) -> None:
        # damage 는 줄어든 체력. 빗나가 도로 차올랐으면 **음수**로 들어온다.
        slot = self.stats[self.current]
        slot[0] += int(damage)
        slot[1] += max(1, int(seconds * 1000.0))
        slot[2] += 1
        self.shots += 1

    # lead와 같은 이름을 쓰는 자리들 — play()가 둘을 나란히 다룬다.
    def hit(self) -> None:
        pass

    def miss(self) -> None:
        pass

    @property
    def rate(self) -> float:
        return self.score(self.best)

    def load(self, stats: dict) -> "Ratio":
        for key, value in (stats or {}).items():
            try:
                slot = self._nearest(float(key))
            except (TypeError, ValueError):
                continue
            if not isinstance(value, (list, tuple)) or len(value) < 3:
                continue
            self.stats[slot] = [int(value[0]), int(value[1]), int(value[2])]
        self.shots = sum(t for _d, _s, t in self.stats.values())
        return self

    def save(self) -> dict:
        return {f"{k:.2f}": list(v) for k, v in self.stats.items() if v[2]}

    def table(self) -> str:
        parts = []
        for value in self.GRID:
            damage, _ms, tries = self.stats[value]
            if tries:
                parts.append(f"{value:.1f}:{self.score(value):.0f}/초")
        return " ".join(parts)


def press_decision(edge: float, bar_wide: float, fish_wide: float,
                   share: float) -> tuple[bool, float]:
    """겹친 폭을 보고 누를지. (누른다, 누르려면 필요한 겹친 폭 px).

    **풀이기와 인식 검사가 같은 함수를 쓴다.** 검사 창이 따로 셈하면 "검사에서는
    겹침!인데 실제로는 안 눌렀다"가 생기고, 그러면 검사가 아무것도 못 짚는다.

    배수가 1.0이면 닿기만 해도(0px) 누르고, 0.5면 좁은 쪽 폭의 절반은 물려야 누른다.
    """
    thin = min(bar_wide, fish_wide) if bar_wide and fish_wide else 0.0
    need = (1.0 - share) * thin
    return (edge >= need, need)


def play(board: Board, lead: Lead, limit_s: float,
         hit_px: float = 10.0, ratio: "Ratio | None" = None) -> Result:
    """미니게임 한 판을 푼다.

    ## 규칙은 하나다 — **보이면 누른다**

    앞서는 겹칠 시각을 미리 계산해 그 자리로 자러 갔다가, 도착해서 겹쳐 있는지
    보고 눌렀다. 계산이 맞을 때는 잘 돌았지만 **틀리면 한 번도 못 눌렀다.**
    도착해 보니 안 겹쳐 있으면 그대로 지나가 버렸기 때문이다. 겹침은 계속
    일어나고 있는데도 그렇다.

    지금은 뒤집었다. 화면은 어차피 쉬지 않고 읽는다(초당 140장). 그러니

        읽는다 → 겹쳐 있으면 누른다 → 또 읽는다 → 또 누른다 → …

    이것뿐이다. **예측이 틀려도 겹침을 놓치지 않는다.** 예측은 화면이 안 보일
    때(둘이 겹치면 하나가 다른 하나를 가린다)와, 게임이 클릭을 늦게 처리할 때
    "지금 눌러도 판정 시점에 여전히 겹쳐 있는가"를 따지는 데만 쓴다.

    겹쳐 있는 동안 누르는 횟수를 막지 않는다. 누를수록 체력이 빨리 깎인다.

    **다만 "겹쳤다"의 폭은 스스로 좁힌다.** 잰 그림 폭대로 잡으면 게임이 맞다고
    치는 자리보다 훨씬 넓을 수 있고, 그러면 넓은 만큼이 고스란히 빗나감이 되어
    깎아 둔 체력을 도로 채워 준다. 얼마나 좁혀야 하는지는 눌러 보고 배운다
    ([Ratio]).

    **이 반복문 안에서는 로그를 남기지 않는다.** 로그 한 줄이 큐에 들어가고 화면이
    깨어나는 데 몇 ms가 튀는데, 그 몇 ms가 그대로 빗나감이 된다. 끝난 뒤 한 줄로
    요약한다.
    """
    started = board.now()
    bar_samples: list[tuple[float, float]] = []
    fish_samples: list[tuple[float, float]] = []

    result = Result(outcome=TIMEOUT)
    health_before = None
    zero_since = None  # 체력이 0으로 읽히기 시작한 때
    bar = fish = None
    blind_since = None  # 표본이 끊긴 시각
    last_gap = None  # 마지막으로 **눈으로 본** 거리
    last_gap_at = 0.0

    # 겹쳐 있는 동안의 한 묶음. 몇 번을 누르든 성적은 묶음 단위로 센다.
    run_open = False
    run_health = 0
    run_closest = None  # 이 묶음에서 가장 가까웠던 거리
    pending = None  # 묶음이 끝나고 결과를 기다리는 중
    lead_s = lead.pick() / 1000.0
    if ratio is None:
        # 안 넘겨 줬으면 **배우지 않는다.** 잰 폭 그대로 쓴다(예전 그대로).
        ratio = Ratio(1.0, learn=False)
    # 이번 묶음에서 "겹쳤다"고 볼 거리. 묶음마다 새로 고른다.
    # 넘겨받은 값은 **아직 못 쟀을 때 쓸 값**일 뿐이다. 판이 도는 동안 폭을
    # 제대로 재면 창도 따라 넓어져야 한다.
    base_px = hit_px
    share = ratio.pick()
    near_px = base_px * share
    # 두 물체의 폭. 가장자리로 볼 때 "얼마나 물려야 하는지"를 여기서 뽑는다.
    bar_wide = fish_wide = 0.0
    # **닿아 있는 것을 눈으로 마지막으로 본 시각.** 가려진 동안을 메우는 근거다.
    touch_at = -1.0
    # 이 배수를 쓰기로 한 시각. 결과가 날 때까지를 통째로 그 배수의 몫으로 센다 —
    # 좁게 잡아 겹침을 통째로 놓친 시간도 그 배수의 잘못이기 때문이다.
    ratio_since = board.now()

    while True:
        if not board.alive():
            result.outcome = ABORTED
            break
        now = board.now()
        if now - started > limit_s:
            break

        got = board.read()
        if got is None:
            # 창이 닫혔다 — 체력을 다 깎았으면 클리어다.
            result.outcome = board.closed_verdict(health_before)
            break
        when, xb, xf, health = got

        # **창을 다시 잰다.** 여기서 한 번 크게 데었다 — 넘겨받은 값을 그대로
        # 끝까지 쓰다가, 폭을 못 잰 채 시작한 판에서 창이 10px에 굳어 **클릭이
        # 한 번도 안 나갔다.** 폭은 읽을 때마다 좋아지므로 창도 따라가야 한다.
        live = getattr(board, "hit_px", None)
        if live:
            base_px = live
            near_px = base_px * share
        widths = getattr(board, "_width", None)
        if widths:
            bar_wide = widths.get("bar", 0.0)
            fish_wide = widths.get("fish", 0.0)

        # **체력이 0으로 읽혀도 곧바로 손을 떼지 않는다.**
        #
        # 예전에는 한 장이라도 0이면 그 자리에서 "깼다"로 보고 끝냈다. 그런데 판이
        # 뜰 때 체력 막대가 차오르는 중이거나, 3%쯤 얇게 남으면 0으로 읽히는 장이
        # 끼어든다 — 그러면 **물고기가 살아 있는데 클릭이 끊겼다.** 진짜로 깼으면
        # 판이 곧 사라지므로(read()가 None) 거기서 끝난다. 0이 한참 이어질 때만
        # 깬 것으로 보고 끝낸다.
        if health <= 0:
            if zero_since is None:
                zero_since = when
            elif when - zero_since >= ZERO_HOLD_S:
                result.outcome = CLEAR
                break
        else:
            zero_since = None

        # 지난 묶음의 결과 확인 — 체력이 줄었으면 맞은 것이다.
        #
        # **정해진 시각에 한 번 보고 판정하면 안 된다.** 게임이 클릭을 늦게
        # 처리하면 그 시각에는 아직 아무 일도 안 일어나 있고, 그러면 맞은 것을
        # 빗나갔다고 세게 된다. 줄어드는 것을 보면 맞음, 기한까지 안 줄면 빗나감.
        if pending is not None:
            if health < pending[1]:
                lead.hit()
                result.hits += 1
                ratio.reward(pending[1] - health, when - ratio_since)
                ratio_since = when
                pending = None
            elif when >= pending[0]:
                lead.miss()
                result.misses += 1
                # 빗나가면 체력이 도로 차오른다. 그 손해가 음수로 들어간다.
                ratio.reward(pending[1] - health, when - ratio_since)
                ratio_since = when
                pending = None
        health_before = health

        # -- 지금 겹쳐 있는가 ---------------------------------------------
        overlapping = False
        if xb is None or xf is None:
            # 한 장 못 읽었다고 모델을 버리지 않는다. 겹치는 순간에는 하나가
            # 다른 하나를 가려서 **하필 가장 중요한 때** 못 읽는다.
            if blind_since is None:
                blind_since = when
            elif (when - blind_since) > BLIND_GRACE_S:
                bar_samples.clear()
                fish_samples.clear()
                bar = fish = None
                blind_since = None
                last_gap = None
            # **방금까지 닿아 있었다면 지금도 닿아 있다.**
            #
            # 막대가 물고기를 덮으면 물고기 색이 안 보이는데, 그때가 가장 깊이
            # 겹친 순간이다. 여기서 손을 떼면 겹침 하나에 한 번밖에 못 누른다 —
            # 실제로 그랬다. 모델이 있든 없든 이건 눈으로 본 사실에서 나온다.
            if touch_at >= 0 and (when - touch_at) <= HIDDEN_S:
                overlapping = True

            # 모델이 겹쳤다고 하고, 직전까지 붙어 오고 있었다면 겹친 것으로 친다.
            # 멀리 있다가 갑자기 안 보이는 것은 겹침이 아니라 그냥 놓친 것이다.
            if bar is not None and fish is not None and last_gap is not None:
                judged = when + lead_s
                near = abs(bar.where(judged) - fish.where(judged)) <= near_px
                fresh = (when - last_gap_at) <= BLIND_MEMORY_S
                closing = last_gap <= near_px
                trusted = max(bar.residual, fish.residual) <= TRUST_PX
                overlapping = overlapping or (near and fresh and closing
                                              and trusted)
        else:
            blind_since = None
            bar_samples.append((when, xb))
            fish_samples.append((when, xf))
            if len(bar_samples) > TRACK_SAMPLES:
                del bar_samples[0]
                del fish_samples[0]
            last_gap = abs(xb - xf)
            last_gap_at = when

            # **닿았는지는 가장자리로 본다.**
            #
            # 중심 거리로 되짚으면 두 군데서 틀린다. 물고기 그림은 좌우가
            # 안 고르므로 색의 무게중심이 기하학적 가운데가 아니고, 폭을 잘못
            # 재면 창까지 통째로 어긋난다. 가장자리는 그 둘을 다 건너뛴다 —
            # 겹친 폭이 곧 답이다.
            #
            # 얼마나 깊이 물려야 누를지는 배수가 정한다. 1.0이면 **닿기만 하면**
            # 누르고, 0.5면 좁은 쪽 폭의 절반은 물려야 누른다.
            edge = board.touch()
            if edge is not None:
                overlapping, _need = press_decision(edge, bar_wide, fish_wide,
                                                    share)
                last_gap = max(0.0, -edge)  # 안 보일 때 쓸 "얼마나 떨어졌나"
                if overlapping:
                    touch_at = when   # 눈으로 닿은 것을 봤다
                else:
                    # 둘 다 보이는데 갈라섰다. 기억을 지워야 다음 가림에서
                    # 엉뚱하게 이어 누르지 않는다.
                    touch_at = -1.0
            else:
                overlapping = last_gap <= near_px

            # 겹쳐 있지 않을 때만 모델을 다시 세운다. 겹친 동안은 누르는 데
            # 시간을 다 쓴다 — 모델은 조금 묵어도 상관없다.
            if not overlapping:
                got_bar = fit_motion(bar_samples, *board.track_range("bar"))
                got_fish = fit_motion(fish_samples, *board.track_range("fish"))
                if got_bar is not None:
                    bar = got_bar
                if got_fish is not None:
                    fish = got_fish
            else:
                # **여기에 거부권을 두었다가 크게 데었다.**
                #
                # "게임이 늦게 판정하니 lead만큼 앞을 내다봐서 그때도 겹쳐 있어야
                # 누른다"로 두었다. 그럴듯했지만, lead는 후보를 -60~+60ms로 돌려
                # 가며 배우는 값이다. 두 물체가 초당 490px로 다가올 때 60ms면
                # 29px이 지나가고, 창이 41px이니 **틀린 lead 하나가 그 겹침을
                # 통째로 걷어냈다.**
                #
                # 게다가 스스로 못 빠져나온다. 안 누르면 맞았는지 빗나갔는지
                # 알 수 없고, 그러면 그 lead 후보는 성적이 안 쌓여 계속 뽑힌다.
                # 시늉으로 세 보니 겹침 여섯 번 중 네 번이 내리 0번이었다
                # ([13, 0, 0, 0, 0, 4]).
                #
                # 그래서 뺐다. **보이면 누른다** — 그것이 이 풀이기의 규칙이고,
                # 예측에 거부권을 주는 순간 그 규칙이 무너진다. lead는 화면이
                # 가려졌을 때 메우는 데만 쓴다.
                pass
                # **여기서 한때 클릭을 스스로 깎아 먹었다.**
                #
                # 예전에는 "가장 가까웠던 데서 4px이라도 벌어지면 그만 누른다"는
                # 규칙이 있었다. 멀어지는 쪽이 위험하다는 생각이었는데, 그건 이미
                # 바로 위의 판정-시각 검사가 맡고 있다. 이 규칙이 한 일은 따로
                # 있었다 —
                #
                # 두 물체가 **같은 쪽으로 비슷한 속도**로 갈 때는 겹친 채로 한참
                # 함께 간다. 가장 오래 누를 수 있는, 가장 좋은 순간이다. 그런데
                # 그동안 거리가 조금씩 출렁이므로 "가장 가까웠던 데서 4px"은
                # 금방 넘어가고, 그러면 **아직 겹쳐 있는데도 클릭을 멈췄다.**
                # 한 번 만날 때마다 한두 번밖에 못 누르던 까닭이 이것이다.
                #
                # 지금은 **창 안에 있으면 계속 누른다.** 창의 너비는 이미 성적을
                # 보고 배운 값이라(Ratio), 그 안에 있다는 것 자체가 눌러도 좋다는
                # 뜻이다. 벗어나면 다음 읽기에서 저절로 멈춘다.
                run_closest = (last_gap if run_closest is None
                               else min(run_closest, last_gap))

        # -- 겹쳤으면 누른다 ------------------------------------------------
        if overlapping:
            if not run_open:
                run_open = True
                run_health = health
                run_closest = last_gap
                result.shots += 1
            board.click()
            result.clicks += 1
            continue

        if run_open:
            # 방금 벌어졌다. 이 묶음의 결과를 기다린다.
            run_open = False
            run_closest = None
            board.rearm()
            pending = (board.now() + VERDICT_WAIT, run_health)
            lead_s = lead.pick() / 1000.0
            share = ratio.pick()
            near_px = base_px * share

    result.seconds = board.now() - started
    result.lead_ms = lead.ms
    result.ratio = ratio.best
    # **실제로 쓴 창을 남긴다.** 넘겨받은 hit_px로 적으면 기록이 거짓말을 한다 —
    # 판이 도는 동안 폭을 다시 재서 창이 넓어져도 기록에는 처음 값이 남아,
    # "창 10px"이라는 줄만 보고 엉뚱한 데를 뒤지게 된다.
    result.hit_px = near_px
    return result
