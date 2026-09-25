"""관찰 모드 — 사용자가 직접 플레이하는 동안 화면과 입력을 함께 기록한다.

목적은 "게임 규칙을 사람이 설명해서 옮기는" 과정을 없애는 것이다. 낚시를 몇 번
해 보이면, 화면 변화와 키 입력의 시간 관계를 분석해서 감지 좌표·기준 색·타이밍을
자동으로 추려낼 수 있다.

메모리 때문에 원본 해상도를 그대로 쌓을 수는 없다. 클라이언트 영역을 한 번에
캡처한 뒤 격자로 솎아서 저장한다. 1024x768 화면을 4픽셀 간격으로 솎으면
256x192 = 약 49,000점, 프레임당 147KB가 된다.

저장 형식은 R평면 + G평면 + B평면을 이어붙인 bytes다. BGRA 버퍼에서 step 간격으로
뽑을 때 파이썬 반복문 대신 바이트 슬라이싱(`row[2::step*4]`)을 쓸 수 있어서
프레임당 수백 번의 C 레벨 슬라이스로 끝난다.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from . import pixel
from .hooks import HOOKS, HookEvent
from .window import GameWindow

MAX_BYTES = 700 * 1024 * 1024  # 안전 상한 (약 700MB)


@dataclass
class ObservedFrame:
    t: float
    data: bytes  # R평면 + G평면 + B평면


@dataclass
class ObservedKey:
    t: float
    vk: int
    down: bool


@dataclass
class ObservedClick:
    t: float
    cx: int
    cy: int
    button: str
    down: bool


@dataclass
class Observation:
    """한 번의 관찰 세션 결과."""

    grid_w: int = 0
    grid_h: int = 0
    step: int = 4
    client_w: int = 0
    client_h: int = 0
    interval_ms: int = 50
    frames: list[ObservedFrame] = field(default_factory=list)
    keys: list[ObservedKey] = field(default_factory=list)
    clicks: list[ObservedClick] = field(default_factory=list)
    dropped: int = 0  # 캡처가 밀려 건너뛴 횟수

    @property
    def duration(self) -> float:
        return self.frames[-1].t if self.frames else 0.0

    @property
    def nbytes(self) -> int:
        return len(self.frames) * self.grid_w * self.grid_h * 3

    def pixel_count(self) -> int:
        return self.grid_w * self.grid_h

    def to_client(self, index: int) -> tuple[int, int]:
        """격자 인덱스 → 게임 창 클라이언트 좌표."""
        gy, gx = divmod(index, self.grid_w)
        return (gx * self.step, gy * self.step)

    def planes(self, frame: ObservedFrame) -> tuple[bytes, bytes, bytes]:
        n = self.grid_w * self.grid_h
        return (frame.data[0:n], frame.data[n : 2 * n], frame.data[2 * n : 3 * n])

    def color_at(self, frame: ObservedFrame, index: int) -> tuple[int, int, int]:
        n = self.grid_w * self.grid_h
        return (
            frame.data[index],
            frame.data[n + index],
            frame.data[2 * n + index],
        )

    def frames_between(self, lo: float, hi: float) -> list[ObservedFrame]:
        return [f for f in self.frames if lo <= f.t <= hi]


def to_macro_events(
    obs: "Observation", include_clicks: bool = True
) -> list[dict]:
    """관찰 중 기록된 실제 입력을 매크로 이벤트 목록으로 변환한다.

    관찰은 화면 분석이 주목적이지만, 그 과정에서 사용자의 조작이 이미 시각과 함께
    기록되어 있다. 같은 동작을 다시 녹화할 필요 없이 그대로 매크로로 쓸 수 있다.
    """
    events: list[dict] = []
    for key in obs.keys:
        events.append({"t": key.t, "kind": "key", "vk": key.vk, "down": key.down})
    if include_clicks:
        for click in obs.clicks:
            events.append(
                {
                    "t": click.t,
                    "kind": "button",
                    "button": click.button,
                    "down": click.down,
                    "cx": click.cx,
                    "cy": click.cy,
                }
            )

    events.sort(key=lambda e: e["t"])
    if events:
        offset = events[0]["t"]
        for event in events:
            event["t"] = round(event["t"] - offset, 4)
    return events


def grid_size(client_w: int, client_h: int, step: int) -> tuple[int, int]:
    """_sample이 실제로 만드는 격자 크기와 같은 계산을 쓴다."""
    step = max(1, step)
    return (len(range(0, client_w, step)), len(range(0, client_h, step)))


def estimate_bytes(client_w: int, client_h: int, step: int, interval_ms: int,
                   seconds: float) -> int:
    gw, gh = grid_size(client_w, client_h, step)
    count = int(seconds * 1000 / max(interval_ms, 1))
    return gw * gh * 3 * count


def _sample(buf: bytes, width: int, height: int, step: int) -> tuple[bytes, int, int]:
    """BGRA 버퍼를 격자로 솎아 R/G/B 평면으로 만든다."""
    gw = len(range(0, width, step))
    gh = len(range(0, height, step))
    stride = width * 4
    byte_step = step * 4
    view = memoryview(buf)

    reds: list[bytes] = []
    greens: list[bytes] = []
    blues: list[bytes] = []
    for y in range(0, height, step):
        row = view[y * stride : (y + 1) * stride]
        # BGRA 순서라 B=0, G=1, R=2. 슬라이스 길이를 gw로 맞춘다.
        blues.append(bytes(row[0::byte_step][:gw]))
        greens.append(bytes(row[1::byte_step][:gw]))
        reds.append(bytes(row[2::byte_step][:gw]))

    return (b"".join(reds) + b"".join(greens) + b"".join(blues), gw, gh)


class Observer:
    """화면 캡처 + 입력 기록을 동시에 수행한다."""

    def __init__(self, log=None) -> None:
        self.log = log or (lambda _m: None)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._observation: Observation | None = None
        self._window: GameWindow | None = None
        self._t0 = 0.0
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def observation(self) -> Observation | None:
        return self._observation

    # ------------------------------------------------------------------
    def start(
        self,
        window: GameWindow,
        step: int = 4,
        interval_ms: int = 50,
        max_seconds: float = 90.0,
    ) -> bool:
        if self.running:
            return False
        if window is None or not window.is_alive():
            self.log("게임 창을 찾지 못해 관찰을 시작할 수 없습니다.")
            return False

        cw, ch = window.client_size()
        if cw <= 0 or ch <= 0:
            self.log("게임 창 크기를 읽지 못했습니다.")
            return False

        obs = Observation(
            step=step,
            client_w=cw,
            client_h=ch,
            interval_ms=interval_ms,
        )
        self._observation = obs
        # 창 위치는 캡처할 때마다 다시 읽는다. 원점을 고정해 두면 관찰 도중 창을
        # 옮겼을 때 엉뚱한 영역을 찍게 된다. 좌표 변환 한 번은 캡처 비용(수 ms)에
        # 비하면 무시할 수준이다.
        self._window = window
        self._stop.clear()

        # 프레임 시각과 입력 시각이 같은 기준을 써야 나중에 시간 관계를 비교할 수
        # 있다. 훅 리스너를 붙이기 '전에' 기준 시각을 정한다.
        self._t0 = time.perf_counter()

        HOOKS.add_listener(self._on_input)
        self._thread = threading.Thread(
            target=self._run,
            args=(obs, max_seconds),
            name="z9-observer",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> Observation | None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=3.0)
        self._thread = None
        HOOKS.remove_listener(self._on_input)
        return self._observation

    # ------------------------------------------------------------------
    def _run(self, obs: Observation, max_seconds: float) -> None:
        window = self._window
        t0 = self._t0
        interval = obs.interval_ms / 1000.0
        next_at = time.perf_counter()
        warned_resize = False

        try:
            while not self._stop.is_set():
                now = time.perf_counter()
                if now - t0 >= max_seconds:
                    self.log(f"최대 관찰 시간({max_seconds:.0f}초)에 도달해 종료합니다.")
                    break
                if obs.nbytes > MAX_BYTES:
                    self.log("메모리 상한에 도달해 관찰을 종료합니다.")
                    break
                if not window.is_alive():
                    self.log("게임 창이 사라져 관찰을 종료합니다.")
                    break

                # 창이 움직였을 수 있으니 매번 현재 위치를 읽는다.
                ox, oy = window.client_origin()
                if not warned_resize and window.client_size() != (
                    obs.client_w,
                    obs.client_h,
                ):
                    self.log(
                        "관찰 중 게임 창 크기가 바뀌었습니다. 프레임 크기는 처음 값을 "
                        "유지하므로, 정확한 분석을 위해 다시 관찰하는 편이 좋습니다."
                    )
                    warned_resize = True

                try:
                    frame = pixel.capture_region(ox, oy, obs.client_w, obs.client_h)
                except pixel.CaptureError as exc:
                    self.log(f"캡처 실패: {exc}")
                    break

                data, gw, gh = _sample(frame.buf, obs.client_w, obs.client_h, obs.step)
                if not obs.grid_w:
                    obs.grid_w, obs.grid_h = gw, gh
                with self._lock:
                    obs.frames.append(ObservedFrame(t=now - t0, data=data))

                next_at += interval
                slack = next_at - time.perf_counter()
                if slack < 0:
                    # 캡처가 주기보다 오래 걸렸다. 기준을 현재로 당겨 폭주를 막는다.
                    obs.dropped += 1
                    next_at = time.perf_counter()
                else:
                    self._stop.wait(slack)
        finally:
            self._stop.set()

        self.log(
            f"관찰 종료 — 프레임 {len(obs.frames)}개, "
            f"{obs.duration:.1f}초, {obs.nbytes / 1048576:.0f}MB, "
            f"키 이벤트 {len(obs.keys)}개"
            + (f", 지연 {obs.dropped}회" if obs.dropped else "")
        )

    # ------------------------------------------------------------------
    def _on_input(self, event: HookEvent) -> bool:
        obs = self._observation
        if obs is None or self._stop.is_set() or event.injected:
            return False

        # HookEvent.t와 프레임 시각 모두 perf_counter 기준이라 그대로 뺄 수 있다.
        rel = event.t - self._t0
        if event.kind == "key":
            with self._lock:
                obs.keys.append(ObservedKey(t=rel, vk=event.vk, down=event.down))
        elif event.kind == "button":
            window = self._window
            cx, cy = (
                window.screen_to_client(event.x, event.y)
                if window is not None
                else (event.x, event.y)
            )
            with self._lock:
                obs.clicks.append(
                    ObservedClick(
                        t=rel,
                        cx=cx,
                        cy=cy,
                        button=event.button,
                        down=event.down,
                    )
                )
        return False  # 관찰은 절대 입력을 삼키지 않는다
