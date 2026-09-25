"""관찰 데이터 분석 — 화면 변화와 입력의 시간 관계에서 규칙을 추려낸다.

핵심 아이디어는 단순하다. 사용자가 상호작용 키를 누르는 순간을 **기준점(anchor)**
으로 삼고, "그 직전에 색이 변한 픽셀"을 모든 기준점에 대해 세어 본다.

  · 매번 변했다  → 그게 신호다 (작물이 다 자람, 게이지 참, 입질 등)
  · 가끔 변했다  → 애니메이션이나 캐릭터 움직임 같은 잡음이다

잡음을 더 확실히 걸러내려고 **대조군**도 본다. 기준점에서 멀리 떨어진 임의
시점에서도 똑같이 변하는 픽셀은, 키와 무관하게 늘 변하는 것이므로 버린다.

  일관성(consistency) = 기준점 중 몇 %에서 변했나
  특이성(specificity) = 대조군에서 안 변한 비율
  점수 = 일관성 × 특이성
"""

from __future__ import annotations

import bisect
import statistics
from collections import Counter, deque
from dataclasses import dataclass, field

from .keys import MODIFIER_VKS, name_of
from .model import PixelPoint, PixelRule, RepeatTask
from .observer import ObservedFrame, Observation

RGB = tuple[int, int, int]


@dataclass
class SignalPoint:
    x: int  # 게임 창 클라이언트 좌표
    y: int
    signal: RGB  # 키를 누르기 직전의 색 (= 감지하고 싶은 상태)
    baseline: RGB  # 그 전 평상시 색
    consistency: float  # 0~1
    specificity: float  # 0~1
    spread: int  # 신호 색의 관측 편차 (허용 오차 산정에 씀)
    cluster_size: int

    @property
    def score(self) -> float:
        return self.consistency * self.specificity


@dataclass
class KeyStat:
    vk: int
    name: str
    count: int
    mean_gap_ms: float = 0.0
    min_gap_ms: float = 0.0
    max_gap_ms: float = 0.0
    stdev_ms: float = 0.0


@dataclass
class AnalysisResult:
    anchor_vk: int = 0
    anchor_name: str = ""
    anchor_count: int = 0
    key_stats: list[KeyStat] = field(default_factory=list)
    key_sequence: str = ""
    signal_points: list[SignalPoint] = field(default_factory=list)
    after_points: list[SignalPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @property
    def has_signal(self) -> bool:
        return bool(self.signal_points)


# --------------------------------------------------------------------------
# 프레임 조회
# --------------------------------------------------------------------------
class _FrameIndex:
    def __init__(self, frames: list[ObservedFrame]) -> None:
        self.frames = frames
        self.times = [f.t for f in frames]

    def at(self, t: float) -> ObservedFrame | None:
        """t 이하 시각의 가장 최근 프레임."""
        if not self.frames:
            return None
        i = bisect.bisect_right(self.times, t) - 1
        return self.frames[i] if i >= 0 else None


def _changed_indices(
    obs: Observation, later: ObservedFrame, earlier: ObservedFrame, threshold: int
) -> set[int]:
    """두 프레임 사이에서 채널 최대 차이가 threshold 이상인 격자 인덱스."""
    n = obs.grid_w * obs.grid_h
    lr, lg, lb = later.data[0:n], later.data[n : 2 * n], later.data[2 * n : 3 * n]
    er, eg, eb = earlier.data[0:n], earlier.data[n : 2 * n], earlier.data[2 * n : 3 * n]

    out: set[int] = set()
    add = out.add
    for i in range(n):
        if (
            abs(lr[i] - er[i]) >= threshold
            or abs(lg[i] - eg[i]) >= threshold
            or abs(lb[i] - eb[i]) >= threshold
        ):
            add(i)
    return out


def _cluster(obs: Observation, indices: set[int]) -> list[list[int]]:
    """격자 위에서 인접(상하좌우)한 인덱스끼리 묶는다."""
    gw = obs.grid_w
    remaining = set(indices)
    clusters: list[list[int]] = []

    while remaining:
        seed = remaining.pop()
        group = [seed]
        queue = deque([seed])
        while queue:
            cur = queue.popleft()
            cy, cx = divmod(cur, gw)
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < gw and 0 <= ny < obs.grid_h):
                    continue
                nb = ny * gw + nx
                if nb in remaining:
                    remaining.discard(nb)
                    group.append(nb)
                    queue.append(nb)
        clusters.append(group)

    clusters.sort(key=len, reverse=True)
    return clusters


# --------------------------------------------------------------------------
# 키 통계
# --------------------------------------------------------------------------
def _key_stats(obs: Observation) -> list[KeyStat]:
    downs: dict[int, list[float]] = {}
    for key in obs.keys:
        if key.down and key.vk not in MODIFIER_VKS:
            downs.setdefault(key.vk, []).append(key.t)

    stats: list[KeyStat] = []
    for vk, times in downs.items():
        times.sort()
        # 키 반복(auto-repeat)은 간격이 극단적으로 짧다. 50ms 미만은 한 번으로 본다.
        pressed = [times[0]]
        for t in times[1:]:
            if t - pressed[-1] >= 0.05:
                pressed.append(t)
        gaps = [(pressed[i + 1] - pressed[i]) * 1000 for i in range(len(pressed) - 1)]
        stat = KeyStat(vk=vk, name=name_of(vk), count=len(pressed))
        if gaps:
            stat.mean_gap_ms = statistics.mean(gaps)
            stat.min_gap_ms = min(gaps)
            stat.max_gap_ms = max(gaps)
            stat.stdev_ms = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
        stats.append(stat)

    stats.sort(key=lambda s: s.count, reverse=True)
    return stats


def _sequence_summary(obs: Observation, limit: int = 24) -> str:
    """눌린 키 순서를 'Space×12, Right, Space×9' 형태로 압축."""
    names = [
        name_of(k.vk) for k in obs.keys if k.down and k.vk not in MODIFIER_VKS
    ]
    if not names:
        return "(키 입력 없음)"
    parts: list[str] = []
    current, count = names[0], 1
    for name in names[1:]:
        if name == current:
            count += 1
        else:
            parts.append(current if count == 1 else f"{current}×{count}")
            current, count = name, 1
    parts.append(current if count == 1 else f"{current}×{count}")
    if len(parts) > limit:
        parts = parts[:limit] + [f"... (총 {len(parts)}구간)"]
    return ", ".join(parts)


# --------------------------------------------------------------------------
# 본 분석
# --------------------------------------------------------------------------
def analyze(
    obs: Observation,
    anchor_vk: int | None = None,
    lookback_ms: int = 500,
    guard_ms: int = 40,
    after_ms: int = 200,
    threshold: int = 24,
    min_score: float = 0.65,
    max_points: int = 5,
    progress=None,
) -> AnalysisResult:
    result = AnalysisResult()
    note = progress or (lambda _m: None)

    result.key_stats = _key_stats(obs)
    result.key_sequence = _sequence_summary(obs)

    if not obs.frames:
        result.warnings.append("캡처된 프레임이 없습니다.")
        return result
    if not result.key_stats:
        result.warnings.append(
            "관찰 중 키 입력이 없습니다. 게임 창을 활성화한 상태로 직접 플레이해야 합니다."
        )
        return result

    # -- 기준 키 선택 ---------------------------------------------------
    if anchor_vk is None:
        anchor_vk = result.key_stats[0].vk
    result.anchor_vk = anchor_vk
    result.anchor_name = name_of(anchor_vk)

    anchors = sorted(
        k.t for k in obs.keys if k.down and k.vk == anchor_vk
    )
    # 오토리피트 제거
    trimmed: list[float] = []
    for t in anchors:
        if not trimmed or t - trimmed[-1] >= 0.05:
            trimmed.append(t)
    anchors = trimmed
    result.anchor_count = len(anchors)

    if len(anchors) < 3:
        result.warnings.append(
            f"기준 키 [{result.anchor_name}] 입력이 {len(anchors)}회뿐입니다. "
            "최소 5회 이상 반복해야 신호를 구분할 수 있습니다."
        )
        return result

    index = _FrameIndex(obs.frames)
    lookback = lookback_ms / 1000.0
    guard = guard_ms / 1000.0
    after = after_ms / 1000.0

    # -- 대조군 시점: 기준점에서 충분히 떨어진 곳 -------------------------
    controls: list[float] = []
    for i in range(len(anchors) - 1):
        mid = (anchors[i] + anchors[i + 1]) / 2
        if mid - anchors[i] > lookback * 1.5 and anchors[i + 1] - mid > lookback * 1.5:
            controls.append(mid)

    n = obs.grid_w * obs.grid_h
    note(f"격자 {obs.grid_w}x{obs.grid_h} ({n:,}점), 기준점 {len(anchors)}개, "
         f"대조군 {len(controls)}개 비교 중…")

    def scan(times: list[float], offset_late: float, offset_early: float) -> Counter:
        counter: Counter = Counter()
        for t in times:
            later = index.at(t + offset_late)
            earlier = index.at(t + offset_early)
            if later is None or earlier is None or later is earlier:
                continue
            counter.update(_changed_indices(obs, later, earlier, threshold))
        return counter

    before_counts = scan(anchors, -guard, -lookback)
    control_counts = scan(controls, -guard, -lookback) if controls else Counter()
    note("기준점 직전 변화 분석 완료. 직후 변화 분석 중…")
    after_counts = scan(anchors, after, -guard)

    result.signal_points = _select_points(
        obs, index, anchors, before_counts, control_counts,
        len(anchors), len(controls), -guard, -lookback,
        min_score, max_points,
    )
    result.after_points = _select_points(
        obs, index, anchors, after_counts, Counter(),
        len(anchors), 0, after, -guard,
        min_score, 3,
    )

    _add_findings(obs, result)
    return result


def _select_points(
    obs: Observation,
    index: _FrameIndex,
    anchors: list[float],
    counts: Counter,
    control_counts: Counter,
    n_anchors: int,
    n_controls: int,
    offset_late: float,
    offset_early: float,
    min_score: float,
    max_points: int,
) -> list[SignalPoint]:
    if not counts or n_anchors == 0:
        return []

    keep: set[int] = set()
    scores: dict[int, tuple[float, float]] = {}
    for idx, hits in counts.items():
        consistency = hits / n_anchors
        if n_controls:
            specificity = 1.0 - (control_counts.get(idx, 0) / n_controls)
        else:
            specificity = 1.0
        if consistency * specificity >= min_score:
            keep.add(idx)
            scores[idx] = (consistency, specificity)

    if not keep:
        return []

    points: list[SignalPoint] = []
    for group in _cluster(obs, keep)[:max_points]:
        # 무리 안에서 점수가 가장 높은 점을 대표로 삼는다.
        best = max(group, key=lambda i: scores[i][0] * scores[i][1])
        consistency, specificity = scores[best]

        signal_colors: list[RGB] = []
        base_colors: list[RGB] = []
        for t in anchors:
            later = index.at(t + offset_late)
            earlier = index.at(t + offset_early)
            if later is None or earlier is None:
                continue
            signal_colors.append(obs.color_at(later, best))
            base_colors.append(obs.color_at(earlier, best))
        if not signal_colors:
            continue

        signal = _median_color(signal_colors)
        baseline = _median_color(base_colors)
        spread = max(
            max(abs(c[ch] - signal[ch]) for c in signal_colors) for ch in range(3)
        )

        x, y = obs.to_client(best)
        points.append(
            SignalPoint(
                x=x,
                y=y,
                signal=signal,
                baseline=baseline,
                consistency=consistency,
                specificity=specificity,
                spread=spread,
                cluster_size=len(group),
            )
        )

    points.sort(key=lambda p: (p.score, p.cluster_size), reverse=True)
    return points


def _median_color(colors: list[RGB]) -> RGB:
    return (
        int(statistics.median(c[0] for c in colors)),
        int(statistics.median(c[1] for c in colors)),
        int(statistics.median(c[2] for c in colors)),
    )


def _add_findings(obs: Observation, result: AnalysisResult) -> None:
    if obs.dropped > len(obs.frames) * 0.1:
        result.warnings.append(
            f"캡처가 {obs.dropped}회 밀렸습니다. 캡처 간격을 늘리거나 격자 간격을 "
            "키우면 정확해집니다."
        )

    anchor_stat = next((s for s in result.key_stats if s.vk == result.anchor_vk), None)
    others = [s for s in result.key_stats if s.vk != result.anchor_vk and s.count >= 3]

    if anchor_stat and others:
        top_other = others[0]
        if top_other.count >= anchor_stat.count * 0.6:
            result.warnings.append(
                f"[{result.anchor_name}] 외에 [{top_other.name}]도 "
                f"{top_other.count}회 눌렸습니다. 누를 키가 매번 달라지는 방식이라면 "
                "픽셀 색만으로는 부족하고 '무엇이 떴는지' 식별하는 기능이 필요합니다."
            )

    if not result.signal_points:
        result.warnings.append(
            "키를 누르기 직전에 일관되게 변하는 화면 영역을 찾지 못했습니다. "
            "가능한 이유: (1) 신호 없이 시간 간격만으로 반복하는 콘텐츠다 "
            "(2) 신호가 캡처 격자보다 작다 — 격자 간격을 2로 줄여 다시 관찰 "
            "(3) 반응이 너무 빨라 감지 구간을 벗어났다 — 되돌아보기 시간을 늘려볼 것"
        )

    if anchor_stat and anchor_stat.count >= 3:
        result.suggestions.append(
            f"연타 설정: [{anchor_stat.name}] 키, 간격 "
            f"{anchor_stat.mean_gap_ms:.0f}ms "
            f"(관측 범위 {anchor_stat.min_gap_ms:.0f}~{anchor_stat.max_gap_ms:.0f}ms, "
            f"편차 {anchor_stat.stdev_ms:.0f}ms)"
        )
        if anchor_stat.stdev_ms > anchor_stat.mean_gap_ms * 0.25:
            result.suggestions.append(
                "간격 편차가 큽니다. 고정 주기 연타보다 아래 감지 조건을 쓰는 편이 "
                "정확합니다."
            )

    if result.signal_points:
        result.suggestions.append(
            f"감지 조건: 신호 점 {len(result.signal_points)}개를 찾았습니다. "
            "가장 점수가 높은 2~3개만 쓰는 것을 권합니다."
        )
    if result.after_points:
        result.suggestions.append(
            f"키를 누른 직후 변하는 점도 {len(result.after_points)}개 찾았습니다. "
            "성공/실패 판정이나 쿨다운 확인에 쓸 수 있습니다."
        )


# --------------------------------------------------------------------------
# 결과 → 프로필 항목
# --------------------------------------------------------------------------
def build_repeat_task(result: AnalysisResult, name: str) -> RepeatTask | None:
    stat = next((s for s in result.key_stats if s.vk == result.anchor_vk), None)
    if stat is None or stat.count < 2:
        return None
    return RepeatTask(
        name=name,
        key=stat.name,
        mode="tap",
        interval_ms=max(int(round(stat.mean_gap_ms)), 10),
        hold_ms=40,
        jitter_ms=0,
    )


def build_pixel_rule(
    result: AnalysisResult, name: str, use_points: int = 3
) -> PixelRule | None:
    points = result.signal_points[:use_points]
    if not points:
        return None

    rule = PixelRule(
        name=name,
        points=[
            PixelPoint(x=p.x, y=p.y, r=p.signal[0], g=p.signal[1], b=p.signal[2])
            for p in points
        ],
        # 관측된 편차보다 조금 넉넉하게. 너무 좁으면 프레임마다 놓친다.
        tolerance=max(8, min(40, max(p.spread for p in points) + 6)),
        match_mode="all",
        condition="match",
        action_kind="key",
        action_key=result.anchor_name,
        check_ms=80,
        cooldown_ms=400,
        edge_only=True,
    )
    return rule
