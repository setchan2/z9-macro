"""입력 중재 — 여러 작업이 동시에 키를 쏘지 않도록 조율한다.

연타, 매크로 재생, 조건부 실행, 예약 실행은 각자 다른 스레드에서 돈다. 평소에는
사용자가 겹쳐 켠 것이니 그대로 두는 게 맞다. 문제는 **예약 실행**처럼 "끼어드는"
쪽이다. 돌아가는 매크로 한복판에 다른 입력이 섞이면 게임 입장에서는 뒤죽박죽인
입력이 된다.

그래서 두 가지를 한곳에서 본다.

1. **지금 눌려 있는 키/버튼이 있는가** — 있으면 어떤 동작이 진행 중이라는 뜻이라
   끼어들면 안 된다. 이것이 "이벤트가 비어있는 시간"의 판단 기준이다.
2. **배타 구간** — 끼어드는 쪽이 이 문을 잠그면, 다른 재생은 다음 이벤트를 보내기
   직전에 멈춰 서서 기다린다. 이미 보낸 입력을 되돌릴 수는 없으니 '이벤트 사이'가
   유일하게 안전한 지점이다.

일반 재생은 이벤트 하나를 보내는 아주 짧은 동안만 문을 잡았다 놓는다. 그래서
끼어드는 쪽은 이벤트와 이벤트 사이에 문을 얻는다.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager


class InputArbiter:
    def __init__(self) -> None:
        # 재진입 가능해야 한다. 배타 구간을 잡은 스레드가 그 안에서 매크로를
        # 재생하면 같은 문을 다시 잡게 된다.
        self._gate = threading.RLock()
        self._held_lock = threading.Lock()
        self._held = 0
        self._last_send = 0.0

    # -- 눌려 있는 입력 추적 ------------------------------------------------
    def note_press(self) -> None:
        with self._held_lock:
            self._held += 1
            self._last_send = time.monotonic()

    def note_release(self) -> None:
        with self._held_lock:
            self._held = max(0, self._held - 1)
            self._last_send = time.monotonic()

    def note_send(self) -> None:
        with self._held_lock:
            self._last_send = time.monotonic()

    @property
    def held(self) -> int:
        with self._held_lock:
            return self._held

    def quiet_for(self) -> float:
        """마지막 입력 이후 흐른 시간(초)."""
        with self._held_lock:
            return time.monotonic() - self._last_send if self._last_send else 1e9

    def is_idle(self, quiet_s: float = 0.0) -> bool:
        """지금이 '이벤트가 비어있는 시간'인가."""
        return self.held == 0 and self.quiet_for() >= quiet_s

    # -- 문 ---------------------------------------------------------------
    @contextmanager
    def dispatch(self):
        """일반 재생이 이벤트 하나를 보내는 동안 잡는다."""
        self._gate.acquire()
        try:
            yield
        finally:
            self._gate.release()

    def wait_for_gap(
        self,
        timeout_s: float,
        quiet_s: float = 0.05,
        stop_check=None,
        poll_s: float = 0.02,
    ) -> bool:
        """입력이 비는 순간까지 기다렸다가 문을 잠근다.

        성공하면 True를 돌려주고 **문을 잡은 채로** 반환한다. 부른 쪽이
        release_gap()으로 반드시 풀어야 한다.
        """
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while True:
            if stop_check and stop_check():
                return False
            if self.is_idle(quiet_s) and self._gate.acquire(blocking=False):
                # 문을 잡는 사이에 누가 키를 눌렀을 수 있으니 한 번 더 본다.
                if self.held == 0:
                    return True
                self._gate.release()
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll_s)

    def release_gap(self) -> None:
        try:
            self._gate.release()
        except RuntimeError:
            # 잡지 않은 문을 푸는 경우 — 호출 순서가 어긋난 것이라 무시해도 안전하다.
            pass


ARBITER = InputArbiter()
