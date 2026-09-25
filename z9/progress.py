"""실행 중인 작업의 진행 상황 게시판.

재생은 작업 스레드에서 돌고 화면은 Tk 스레드에서 그린다. 작업 스레드가 위젯을
직접 건드리면 안 되므로, 여기에 값을 적어 두고 화면이 주기적으로 읽어 가게 한다.

쓰는 쪽은 **절대 오래 막히면 안 된다**. 이벤트 하나를 보내기 직전에 불리기
때문에, 여기서 지체하면 그만큼 입력 타이밍이 밀린다. 그래서 잠금 구간은 dict
갱신과 deque 추가뿐이고, 읽는 쪽이 느려도 쓰는 쪽은 기다리지 않는다(deque가
가득 차면 가장 오래된 것부터 조용히 버린다).
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Any

from .keys import name_of

# 최근 입력을 몇 개까지 들고 있을지. 연타 1초면 20개쯤 쌓이므로 넉넉히 잡는다.
TRAIL_MAX = 400

# 같은 종류의 입력이 이 횟수까지는 '드문 입력'으로 강조한다.
RARE_UNDER = 3

_DIGITS = re.compile(r"\d+(?:\.\d+)?")


def _kind_of(text: str) -> str:
    """입력의 **종류**. 숫자(좌표·몇 번째·ms)만 다른 것은 같은 종류로 본다."""
    return _DIGITS.sub("#", text)

_PRESS = {True: "누름", False: "뗌"}


def describe_event(event: dict[str, Any]) -> str:
    """이벤트 하나를 사람이 읽는 한 줄로."""
    kind = event.get("kind")
    if kind == "key":
        return f"[{name_of(event.get('vk', 0))}] {_PRESS[bool(event.get('down'))]}"
    if kind == "button":
        return (
            f"{event.get('button', '?')} {_PRESS[bool(event.get('down'))]} "
            f"({event.get('cx', 0)}, {event.get('cy', 0)})"
        )
    if kind == "move":
        return f"이동 ({event.get('cx', 0)}, {event.get('cy', 0)})"
    if kind == "wait":
        return f"{event.get('duration_ms', 0)}ms 쉬기"
    if kind == "wheel":
        count = max(int(event.get("count", 1)), 1)
        delta = int(event.get("wheel", 0))
        return f"휠 {delta:+d} × {count}칸 {'내림' if delta < 0 else '올림'}"
    return str(kind or "?")


class Board:
    """작업 하나의 진행 상황.

    state는 "지금 어디쯤인가"를 나타내는 몇 줄이고, trail은 "실제로 무엇을
    보냈는가"의 기록이다. 둘 다 화면이 통째로 읽어 간다.
    """

    def __init__(self, title: str) -> None:
        self.title = title
        self._lock = threading.Lock()
        self._state: dict[str, str] = {}
        self._trail: deque[tuple[float, str, str, str]] = deque(maxlen=TRAIL_MAX)
        # 입력 종류마다 몇 번 나갔나 — 드문 것을 가리는 데 쓴다.
        self._kinds: dict[str, int] = {}
        self.started_at = time.perf_counter()
        self.finished_at: float | None = None
        self.note = ""
        self.sent_count = 0
        # 화면이 "바뀐 게 있나"를 싸게 판단할 수 있도록.
        self.revision = 0

    # -- 쓰는 쪽 (작업 스레드) ---------------------------------------------
    def set(self, **fields: str) -> None:
        """상태 줄을 갱신한다. 값이 빈 문자열이면 그 줄을 지운다."""
        with self._lock:
            for key, value in fields.items():
                if value == "":
                    self._state.pop(key, None)
                else:
                    self._state[key] = value
            self.revision += 1

    def sent(self, text: str, tag: str = "", style: str = "") -> str:
        """실제로 내보낸 입력을 기록에 남긴다. 붙인 모양(style)을 돌려준다.

        style을 안 주면 **드물게 나가는 입력인지** 스스로 가린다. 같은 종류(숫자만
        다른 것은 같은 종류)가 아직 RARE_UNDER번이 안 됐으면 "rare"를 붙여 화면에서
        굵게 보인다. 미니게임 클릭·두드리기처럼 쏟아지는 것들은 금방 흔해져 묻히고,
        버프 · 신청 창 닫기 · 되살리기처럼 가끔 나가는 것만 눈에 띈다.
        """
        kind = _kind_of(text)
        with self._lock:
            seen = self._kinds.get(kind, 0) + 1
            self._kinds[kind] = seen
            if not style and seen <= RARE_UNDER:
                style = "rare"
            self._trail.append((time.perf_counter() - self.started_at, text, tag, style))
            self.sent_count += 1
            self.revision += 1
        return style

    def finish(self, note: str = "") -> None:
        with self._lock:
            self.finished_at = time.perf_counter()
            self.note = note
            self._state.pop("다음", None)
            self.revision += 1

    # -- 읽는 쪽 (Tk 스레드) -----------------------------------------------
    @property
    def running(self) -> bool:
        return self.finished_at is None

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.perf_counter()
        return end - self.started_at

    def seen(self, text: str) -> int:
        """그 종류의 입력이 여태 몇 번 나갔나."""
        with self._lock:
            return self._kinds.get(_kind_of(text), 0)

    def snapshot(self) -> tuple[int, dict[str, str], list[tuple[float, str, str, str]]]:
        with self._lock:
            return (self.revision, dict(self._state), list(self._trail))


class Registry:
    """지금 돌고 있는(또는 방금 끝난) 게시판들."""

    # 끝난 것도 잠깐 남겨 둔다. 짧은 매크로는 실행이 끝난 뒤에야 창을 보게 되는데
    # 그때 아무것도 없으면 무슨 일이 있었는지 알 수 없다.
    KEEP_FINISHED = 8

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._boards: list[tuple[Any, Board]] = []
        self.revision = 0

    def open(self, key: Any, title: str) -> Board:
        board = Board(title)
        with self._lock:
            self._boards = [(k, b) for k, b in self._boards if k != key]
            self._boards.append((key, board))
            self._prune()
            self.revision += 1
        return board

    def close(self, key: Any, note: str = "") -> None:
        with self._lock:
            for k, board in self._boards:
                if k == key and board.running:
                    board.finish(note)
            self._prune()
            self.revision += 1

    def _prune(self) -> None:
        """끝난 것은 최근 것만 남긴다. 호출자가 잠금을 쥐고 있어야 한다."""
        done = [i for i, (_k, b) in enumerate(self._boards) if not b.running]
        for i in done[: max(len(done) - self.KEEP_FINISHED, 0)]:
            self._boards[i] = None  # type: ignore[call-overload]
        self._boards = [entry for entry in self._boards if entry is not None]

    def boards(self) -> list[tuple[Any, Board]]:
        with self._lock:
            return list(self._boards)

    def active(self) -> list[Board]:
        return [b for _k, b in self.boards() if b.running]

    def clear(self) -> None:
        with self._lock:
            self._boards.clear()
            self.revision += 1


REGISTRY = Registry()

__all__ = ["Board", "Registry", "REGISTRY", "describe_event", "TRAIL_MAX"]
