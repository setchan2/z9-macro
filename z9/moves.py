"""대기 시간에 끼워 넣는 짧은 이동.

매크로가 긴 대기에 들어가면 캐릭터는 그 시간 내내 못 박힌 듯 서 있다. 여기서는
미리 녹화해 둔 짧은 방향키 이동 중 하나를 그 틈에 재생해서, 서 있는 시간을 줄인다.

**이것은 탐지 회피 수단이 아니다.** 입력을 자동으로 넣는다는 사실 자체는 그대로
드러난다. 여기서 하는 일은 "대기 중에도 가끔 움직인다"뿐이다.

끼워 넣는 자리를 고르는 규칙:
  - 대기가 충분히 길어야 한다 (기본 5초). 짧은 틈에 밀어 넣으면 뒤 이벤트와 겹친다.
  - 대기가 시작하자마자 움직이지 않는다 (기본 1.5초는 그대로 둔다).
  - 이동이 끝나고도 여유가 남아야 한다. 다음 이벤트가 나갈 때 방향키가 눌린 채로
    남아 있으면 그다음 동작이 통째로 어긋난다.
  - 조건을 만족해도 **매번 넣지는 않는다.** 늘 움직이면 그것대로 규칙적이다.
"""

from __future__ import annotations

import random
from typing import Any

from .keys import vk_of

# 이동에 쓸 수 있는 키. 방향키만 받는다 — 대기 중에 스킬이나 아이템이 나가면
# 매크로가 의도한 흐름이 깨진다.
MOVE_KEYS = ("Left", "Right", "Up", "Down")
MOVE_VKS = frozenset(v for v in (vk_of(k) for k in MOVE_KEYS) if v is not None)

# 움직임 슬롯 개수. 늘리기보다 이 정도를 채워 쓰는 편이 낫다.
SLOT_COUNT = 10

# 한 움직임이 가질 수 있는 최대 길이(초).
MAX_SECONDS = 3.0


def filter_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """방향키 누름/뗌만 남긴다."""
    return [
        e for e in events
        if e.get("kind") == "key" and e.get("vk") in MOVE_VKS
    ]


def truncate(events: list[dict[str, Any]], seconds: float = MAX_SECONDS) -> list[dict]:
    """정해진 길이까지만 남기고, 그 시점에 눌려 있던 키는 떼 준다.

    자르기만 하면 누른 채로 끝나는 키가 생긴다. 그러면 재생할 때 방향키가 눌린
    채로 남아 캐릭터가 계속 걸어간다.
    """
    kept = [e for e in events if e.get("t", 0.0) <= seconds]
    held: list[int] = []
    for event in kept:
        vk = event.get("vk")
        if event.get("down"):
            if vk not in held:
                held.append(vk)
        elif vk in held:
            held.remove(vk)
    for vk in held:
        kept.append({"t": seconds, "kind": "key", "vk": vk, "down": False})
    return kept


def duration(events: list[dict[str, Any]]) -> float:
    return max((e.get("t", 0.0) for e in events), default=0.0)


def usable(moves) -> list:
    """지금 끼워 넣을 수 있는 움직임들 (켜져 있고 내용이 있는 것)."""
    return [m for m in moves if m.enabled and m.events]


def plan(
    gap: float,
    moves,
    settings,
    rng: random.Random | None = None,
) -> tuple[Any, float] | None:
    """이 대기에 무엇을 언제 끼워 넣을지. 넣지 않기로 했으면 None.

    gap은 대기의 길이(초). 반환은 (움직임, 대기 시작 후 몇 초에 시작할지).
    """
    rng = rng or random
    if gap < max(settings.move_min_gap_s, 0.1):
        return None

    candidates = usable(moves)
    if not candidates:
        return None

    lead = max(settings.move_lead_s, 0.0)
    tail = max(settings.move_tail_s, 0.0)
    # 리드인과 꼬리 여유를 뺀 나머지 안에 들어갈 수 있는 것만 고른다.
    room = gap - lead - tail
    fits = [m for m in candidates if 0 < duration(m.events) <= room]
    if not fits:
        return None

    if rng.random() * 100.0 >= max(min(settings.move_chance, 100), 0):
        return None

    move = rng.choice(fits)
    latest = gap - tail - duration(move.events)
    start = rng.uniform(lead, latest) if latest > lead else lead
    return (move, start)


__all__ = [
    "MOVE_KEYS",
    "MOVE_VKS",
    "SLOT_COUNT",
    "MAX_SECONDS",
    "filter_events",
    "truncate",
    "duration",
    "usable",
    "plan",
]
