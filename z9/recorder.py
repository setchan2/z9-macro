"""키/마우스 녹화."""

from __future__ import annotations

import threading
import time
from typing import Any

from .hooks import HOOKS, HookEvent
from .model import Macro
from .window import GameWindow


class Recorder:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._recording = False
        self._t0 = 0.0
        self._window: GameWindow | None = None
        self._client_size = (0, 0)
        self._absolute = True
        self._ignore_vks: set[int] = set()
        self._record_move = True
        self._move_sample = 0.02
        self._last_move_t = 0.0
        self._holds_moves = False

    def _detach(self) -> None:
        HOOKS.remove_listener(self._on_event)
        if self._holds_moves:
            HOOKS.release_mouse_moves()
            self._holds_moves = False

    @property
    def recording(self) -> bool:
        return self._recording

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._events)

    def start(
        self,
        window: GameWindow | None,
        record_move: bool = True,
        move_sample_ms: int = 20,
        ignore_vks: set[int] | None = None,
    ) -> None:
        """녹화 시작.

        마우스 좌표는 게임 창 클라이언트 기준 상대좌표로 기록한다. 변환은 이벤트
        마다 실시간으로 하므로 녹화 중에 창을 옮겨도 좌표가 어긋나지 않는다.

        게임 창을 못 찾으면 화면 절대좌표로 기록할 수밖에 없는데, 그렇게 만든
        매크로는 창 위치가 바뀌면 엉뚱한 곳을 누른다. 호출부에서 경고해야 한다.
        """
        if self._recording:
            return
        with self._lock:
            self._events = []
        self._record_move = record_move
        self._move_sample = max(move_sample_ms, 1) / 1000.0
        self._ignore_vks = set(ignore_vks or ())
        if window is not None and window.is_alive():
            self._window = window
            self._client_size = window.client_size()
            self._absolute = False
        else:
            self._window = None
            self._client_size = (0, 0)
            self._absolute = True
        self._t0 = time.perf_counter()
        self._last_move_t = 0.0
        self._recording = True
        HOOKS.add_listener(self._on_event)
        if record_move:
            # 이동 이벤트는 평소엔 훅에서 걸러진다. 녹화 중에만 켠다.
            HOOKS.acquire_mouse_moves()
            self._holds_moves = True

    def stop(self, name: str = "녹화 매크로") -> Macro:
        if not self._recording:
            return Macro(name=name)
        self._recording = False
        self._detach()
        with self._lock:
            events = self._events
            self._events = []

        events = _trim(events)
        return Macro(
            name=name,
            events=events,
            client_w=self._client_size[0],
            client_h=self._client_size[1],
            absolute=self._absolute,
        )

    def cancel(self) -> None:
        if self._recording:
            self._recording = False
            self._detach()
            with self._lock:
                self._events = []

    # -- 훅 콜백 -----------------------------------------------------------
    def _on_event(self, event: HookEvent) -> bool:
        if not self._recording or event.injected:
            return False

        t = event.t - self._t0

        if event.kind == "key":
            if event.vk in self._ignore_vks:
                return False
            self._append({"t": t, "kind": "key", "vk": event.vk, "down": event.down})
        elif event.kind == "button":
            cx, cy = self._to_client(event.x, event.y)
            self._append(
                {
                    "t": t,
                    "kind": "button",
                    "button": event.button,
                    "down": event.down,
                    "cx": cx,
                    "cy": cy,
                }
            )
        elif event.kind == "move":
            if not self._record_move:
                return False
            if t - self._last_move_t < self._move_sample:
                return False
            self._last_move_t = t
            cx, cy = self._to_client(event.x, event.y)
            self._append({"t": t, "kind": "move", "cx": cx, "cy": cy})
        elif event.kind == "wheel":
            cx, cy = self._to_client(event.x, event.y)
            self._append(
                {"t": t, "kind": "wheel", "wheel": event.wheel, "cx": cx, "cy": cy}
            )
        return False  # 녹화는 절대 입력을 삼키지 않는다

    def _to_client(self, x: int, y: int) -> tuple[int, int]:
        """화면 좌표 → 게임 창 클라이언트 좌표.

        기준점을 캐시하지 않고 이벤트마다 실시간으로 변환한다. 녹화 도중 창을
        옮겨도 좌표가 어긋나지 않게 하려는 것이다. ScreenToClient는 커널 호출
        한 번이라 훅 콜백 안에서 써도 부담이 없다.
        """
        window = self._window
        if self._absolute or window is None:
            return (x, y)
        return window.screen_to_client(x, y)

    def _append(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.append(event)


def _trim(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """앞쪽 빈 시간을 없애고 t를 0부터 시작하도록 맞춘다."""
    if not events:
        return events
    offset = events[0]["t"]
    for event in events:
        event["t"] = round(event["t"] - offset, 4)
    return events


def balance_keys(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """녹화가 끝난 시점에 안 떼진 키/버튼이 있으면 마지막에 keyup을 붙인다.

    이걸 안 하면 재생 후 게임에서 키가 눌린 채로 남는다.
    """
    if not events:
        return events
    held_keys: dict[int, dict] = {}
    held_buttons: dict[str, dict] = {}
    for event in events:
        if event["kind"] == "key":
            if event["down"]:
                held_keys[event["vk"]] = event
            else:
                held_keys.pop(event["vk"], None)
        elif event["kind"] == "button":
            if event["down"]:
                held_buttons[event["button"]] = event
            else:
                held_buttons.pop(event["button"], None)

    last_t = events[-1]["t"]
    extra: list[dict[str, Any]] = []
    for vk in held_keys:
        extra.append({"t": last_t + 0.02, "kind": "key", "vk": vk, "down": False})
    for button, src in held_buttons.items():
        extra.append(
            {
                "t": last_t + 0.02,
                "kind": "button",
                "button": button,
                "down": False,
                "cx": src.get("cx", 0),
                "cy": src.get("cy", 0),
            }
        )
    return events + extra
