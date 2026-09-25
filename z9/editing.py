"""매크로 이벤트 시각 보정.

GUI와 분리해 둔다. 순수하게 이벤트 목록만 다루므로 화면 없이 검증할 수 있다.
"""

from __future__ import annotations

from typing import Any

Event = dict[str, Any]

DEFAULT_HOLD_MIN_MS = 50
DEFAULT_HOLD_MAX_MS = 150
DEFAULT_GAP_MIN_MS = 200
DEFAULT_GAP_MAX_MS = 400


def _sort(events: list[Event]) -> None:
    events.sort(key=lambda e: e["t"])


def _target_key(event: Event) -> tuple[str, Any] | None:
    """누름/뗌 짝을 맞출 식별자."""
    if event["kind"] == "key":
        return ("key", event["vk"])
    if event["kind"] == "button":
        return ("button", event.get("button", "left"))
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else (high if value > high else value)


def find_pairs(events: list[Event]) -> tuple[list[tuple[int, int]], int]:
    """(누름 index, 뗌 index) 목록과 짝을 못 찾은 누름 개수."""
    pending: dict[tuple[str, Any], int] = {}
    pairs: list[tuple[int, int]] = []
    for index, event in enumerate(events):
        key = _target_key(event)
        if key is None:
            continue
        if event.get("down"):
            pending[key] = index
        else:
            start = pending.pop(key, None)
            if start is not None:
                pairs.append((start, index))
    return (pairs, len(pending))


def normalize_holds(
    events: list[Event],
    min_ms: int = DEFAULT_HOLD_MIN_MS,
    max_ms: int = DEFAULT_HOLD_MAX_MS,
    indices: set[int] | None = None,
) -> tuple[int, int]:
    """누름 → 뗌 간격을 [min, max] 안으로 맞춘다.

    너무 길면 줄이고, 너무 짧으면 늘린다. 짧은 쪽도 손보는 이유는, 몇 ms짜리
    입력은 게임이 폴링 주기 사이에 놓쳐 아예 눌리지 않은 것처럼 되기 때문이다.

    indices를 주면 그 안에 든 이벤트가 걸린 짝만 손본다. 누름이나 뗌 중 하나만
    골라도 그 짝은 함께 처리한다 — 한쪽만 옮기는 건 의미가 없기 때문이다.

    반환: (고친 개수, 짝을 못 찾은 누름 개수)
    """
    _sort(events)
    low, high = min_ms / 1000.0, max_ms / 1000.0
    if low > high:
        low, high = high, low

    pairs, unmatched = find_pairs(events)
    changed = 0
    for down_index, up_index in pairs:
        if indices is not None and down_index not in indices and up_index not in indices:
            continue
        gap = events[up_index]["t"] - events[down_index]["t"]
        target = _clamp(gap, low, high)
        if abs(target - gap) > 1e-6:
            events[up_index]["t"] = round(events[down_index]["t"] + target, 4)
            changed += 1

    _sort(events)
    return (changed, unmatched)


DEFAULT_WHEEL_GAP_MS = 250


def wheel_count(event: Event) -> int:
    """휠 이벤트가 몇 칸을 굴리는지. 옛 기록에는 필드가 없으니 1로 본다."""
    return max(int(event.get("count", 1)), 1)


def merge_wheel_runs(
    events: list[Event], max_gap_ms: int = DEFAULT_WHEEL_GAP_MS
) -> tuple[int, int]:
    """줄줄이 이어진 휠 이벤트를 하나로 합치고 '몇 칸'으로 바꾼다.

    휠을 한 번 굴리면 보통 이벤트가 수십 개 쏟아진다. 목록에서 읽기도 힘들고,
    "몇 칸 내릴지"를 고치려면 이벤트를 일일이 지우거나 복제해야 한다. 같은 방향
    같은 크기로 붙어 있는 것들을 한 줄로 묶고 횟수만 남기면 그 숫자 하나만 고치면
    된다.

    같은 방향(부호)이고 한 칸 크기가 같으며, 사이가 max_gap_ms 안쪽일 때만 묶는다.
    중간에 다른 입력이 끼어 있으면 거기서 끊는다.

    반환: (합쳐서 사라진 이벤트 수, 만들어진 묶음 수)
    """
    _sort(events)
    merged: list[Event] = []
    removed = 0
    groups = 0
    gap = max_gap_ms / 1000.0

    index = 0
    while index < len(events):
        event = events[index]
        if event["kind"] != "wheel":
            merged.append(event)
            index += 1
            continue

        total = wheel_count(event)
        end = index + 1
        while end < len(events):
            nxt = events[end]
            if nxt["kind"] != "wheel":
                break
            if (nxt["wheel"] > 0) != (event["wheel"] > 0):
                break
            if abs(nxt["wheel"]) != abs(event["wheel"]):
                break
            if nxt["t"] - events[end - 1]["t"] > gap:
                break
            total += wheel_count(nxt)
            end += 1

        if end > index + 1:
            removed += end - index - 1
            groups += 1

        collapsed = dict(event)
        collapsed["count"] = total
        merged.append(collapsed)
        index = end

    events[:] = merged
    return (removed, groups)


def set_wheel_count(events: list[Event], count: int) -> int:
    """모든 휠 이벤트의 칸 수를 한꺼번에 바꾼다. 반환: 바뀐 개수."""
    count = max(int(count), 1)
    changed = 0
    for event in events:
        if event["kind"] == "wheel" and wheel_count(event) != count:
            event["count"] = count
            changed += 1
    return changed


def _is_release_of(prev: Event, cur: Event) -> bool:
    """cur이 바로 앞 prev를 떼는 이벤트인가."""
    if not prev.get("down") or cur.get("down"):
        return False
    key = _target_key(prev)
    return key is not None and key == _target_key(cur)


def normalize_gaps(
    events: list[Event],
    min_ms: int = DEFAULT_GAP_MIN_MS,
    max_ms: int = DEFAULT_GAP_MAX_MS,
    indices: set[int] | None = None,
) -> tuple[int, float, float]:
    """이벤트 사이 간격을 [min, max] 안으로 맞춘다.

    두 가지는 건드리지 않는다.

    1. 누름 바로 뒤에 오는 그 키의 뗌 — 이건 '간격'이 아니라 누르고 있는 시간이다.
       여기서 벌려 버리면 누름-뗌 보정이 무의미해진다.
    2. 연속된 커서 이동 — 하나의 이어진 움직임이라 내부 리듬을 유지해야 한다.
       이걸 벌리면 20ms 간격 이동 100개가 20초짜리 매크로가 된다.

    indices가 없으면 전체를 정리하고 시작을 0초로 당긴다.

    indices를 주면 **고른 것들의 처음~끝 구간**만 다시 배치한다. 이때 구간의 시작
    시각은 그대로 두고(앞부분과 어긋나면 안 되므로), 뒤에 남은 이벤트는 줄거나
    늘어난 만큼 통째로 밀어 준다. 그래야 구간만 손봐도 전체가 깨지지 않는다.

    반환: (고친 간격 수, 원래 길이, 새 길이)
    """
    _sort(events)
    if len(events) < 2:
        before = events[-1]["t"] if events else 0.0
        if events and indices is None:
            events[0]["t"] = 0.0
        return (0, before, events[-1]["t"] if events else 0.0)

    low, high = min_ms / 1000.0, max_ms / 1000.0
    if low > high:
        low, high = high, low

    if indices:
        valid = sorted(i for i in indices if 0 <= i < len(events))
        if len(valid) < 2:
            return (0, events[-1]["t"] - events[0]["t"], events[-1]["t"] - events[0]["t"])
        start, end = valid[0], valid[-1]
    else:
        start, end = 0, len(events) - 1

    original = [e["t"] for e in events]
    before_duration = original[-1] - original[0]

    # 전체를 정리할 때만 0초로 당긴다. 구간 정리는 시작점을 유지해야 한다.
    new_times = [0.0 if indices is None else original[start]]
    changed = 0
    for i in range(start + 1, end + 1):
        gap = original[i] - original[i - 1]
        prev, cur = events[i - 1], events[i]
        keep_as_is = (
            _is_release_of(prev, cur)
            or (prev["kind"] == "move" and cur["kind"] == "move")
            # 대기는 사용자가 "여기서 이만큼 쉬어라"라고 직접 넣은 것이다.
            # 간격 보정이 이걸 덮어쓰면 넣은 의미가 없어진다.
            or prev["kind"] == "wait"
        )
        if keep_as_is:
            adjusted = gap
        else:
            adjusted = _clamp(gap, low, high)
            if abs(adjusted - gap) > 1e-6:
                changed += 1
        new_times.append(round(new_times[-1] + adjusted, 4))

    for offset, i in enumerate(range(start, end + 1)):
        events[i]["t"] = new_times[offset]

    # 구간이 줄거나 늘어난 만큼 뒤쪽을 밀어 준다.
    shift = round(new_times[-1] - original[end], 4)
    if shift and end + 1 < len(events):
        for i in range(end + 1, len(events)):
            events[i]["t"] = round(original[i] + shift, 4)

    _sort(events)
    return (changed, before_duration, events[-1]["t"] - events[0]["t"])
