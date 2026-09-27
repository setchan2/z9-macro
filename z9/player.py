"""녹화 매크로 / 이동 경로 재생.

타이밍 정확도의 핵심은 **절대 시각 스케줄링**이다. 이벤트마다 "직전 이벤트와의
간격만큼 sleep"하면 sleep 오차가 매번 누적돼 30초짜리 매크로가 32초가 된다.
대신 시작 시각을 기준으로 각 이벤트의 목표 시각을 계산해서 그 시각까지 기다린다.
"""

from __future__ import annotations

import copy
import threading
from typing import Any, Callable

from . import moves as movelib
from . import postinput, sender
from .arbiter import ARBITER
from .keys import vk_of
from .model import (
    FOCUS_IGNORE,
    FOCUS_STOP,
    INPUT_POST,
    Macro,
    PathMacro,
    PathStep,
    Scenario,
    ScenarioGroup,
    Settings,
    TRIGGER_CYCLE,
    TRIGGER_STEP,
)
from .progress import describe_event
from .window import GameWindow

Log = Callable[[str], None]


class Aborted(Exception):
    """사용자 정지 또는 창 상실로 중단됨."""


# 창을 되찾지 못하고 있을 때 몇 초마다 한 번씩 알릴지. 되찾기 자체는 창이
# 살아 있는 한 포기하지 않는다 — 중단은 사용자가 비상 정지를 눌렀을 때만.
REFOCUS_NOTICE_S = 10.0


class RunContext:
    """실행 중인 작업 하나의 상태."""

    def __init__(self, settings: Settings, window: GameWindow | None, log: Log) -> None:
        self.settings = settings
        self.window = window
        self.log = log
        # 진행 상황 게시판. 없으면(None) 아무것도 보고하지 않는다 — 테스트나
        # 내부 호출에서 굳이 화면용 상태를 만들 필요가 없다.
        self.board = None
        self.stop_event = threading.Event()
        self._pressed_vks: set[int] = set()
        self._pressed_buttons: set[str] = set()
        # 창을 되찾느라 멈춰 있던 누적 시간. 재생은 절대 시각으로 돌아가므로
        # 이만큼 밀어 주지 않으면 되찾는 순간 밀린 이벤트가 쏟아진다.
        self._drift = 0.0
        # 배경 입력에서는 커서를 옮기지 않고 좌표를 메시지에 실어 보낸다.
        self._cursor = (0, 0)
        # 대기 중에 끼워 넣을 움직임 목록. 비어 있으면 아무것도 하지 않는다.
        self.moves: list = []
        # 감지용 그림을 찾을 보관함 폴더. 그림 조건을 쓰는 판정이 여기를 본다.
        self.library_root = None
        # 낚시 설정. 시나리오의 낚시 단계가 여기서 꺼내 쓴다. 조회 함수를
        # 하나 더 넘기는 것보다, 실행 맥락에 얹는 편이 손댈 곳이 적다.
        self.fishing = None

    def spawn(self) -> "RunContext":
        """같은 설정·창·정지 신호를 공유하는 하위 실행 맥락.

        정지 신호를 공유해야 [정지] 한 번에 안쪽까지 함께 멈춘다. 손으로
        만들면 library_root 같은 것을 옮기는 걸 자꾸 빠뜨리게 되어 여기 모았다.
        """
        sub = RunContext(self.settings, self.window, self.log)
        sub.stop_event = self.stop_event
        sub.library_root = self.library_root
        sub.moves = self.moves
        sub.fishing = self.fishing
        return sub

    # -- 정지 --------------------------------------------------------------
    def stop(self) -> None:
        self.stop_event.set()

    @property
    def stopped(self) -> bool:
        return self.stop_event.is_set()

    @property
    def background(self) -> bool:
        """창 메시지로 보내는 중인가. 그렇다면 포그라운드는 상관없다."""
        return self.settings.input_mode == INPUT_POST and self.window is not None

    def check(self) -> None:
        if self.stop_event.is_set():
            raise Aborted()
        if self.window is None:
            return
        if not self.window.is_alive():
            raise Aborted("게임 창이 사라졌습니다.")
        # 배경 입력은 창이 뒤에 있든 최소화돼 있든 그 창으로 곧장 간다.
        # 앞으로 끌어올 이유가 없다 — 끌어오면 오히려 사용자를 방해한다.
        if self.background or self.window.is_foreground():
            return
        self._focus_lost()

    def _focus_lost(self) -> None:
        """게임 창이 앞에서 밀려났다. 정책대로 처리한다.

        되찾기 정책에서는 **되찾을 때까지 여기서 붙잡는다.** 그냥 통과시키면
        그동안 SendInput이 맨 앞에 있는 남의 창으로 들어간다 — 조용히 새는
        입력이 제일 위험하다.
        """
        import time

        policy = self.settings.focus_policy
        if policy == FOCUS_STOP:
            raise Aborted("게임 창이 비활성화되어 중단했습니다.")
        if policy == FOCUS_IGNORE:
            return

        blocked_from = time.perf_counter()
        # 창이 살아 있는 한 포기하지 않는다. 여기서 중단하면 그 뒤 입력이
        # 통째로 사라지는데, 그건 사용자가 비상 정지를 눌렀을 때만 일어나야 한다.
        next_notice = blocked_from
        told = False
        while True:
            if self.stop_event.is_set():
                raise Aborted()
            if not self.window.is_alive():
                raise Aborted("게임 창이 사라졌습니다.")
            if self.window.is_foreground() or self.window.activate():
                lost = time.perf_counter() - blocked_from
                if told:
                    self.log(f"게임 창을 되찾았습니다. 이어서 진행합니다 ({lost:.1f}초 멈춤).")
                # 멈춰 있던 만큼 남은 이벤트의 목표 시각을 뒤로 민다. 안 그러면
                # 되찾는 순간 밀린 이벤트가 한꺼번에 쏟아진다.
                self._drift += lost
                return

            # 조용히 멈춰 있으면 프로그램이 죽은 줄 안다. 다만 매번 적으면
            # 로그가 이것만으로 가득 차므로 가끔씩만 알린다.
            now = time.perf_counter()
            if now >= next_notice:
                waited = now - blocked_from
                self.log(
                    f"게임 창을 앞으로 가져오지 못했습니다 ({waited:.0f}초째). "
                    "될 때까지 계속 시도합니다 — 멈추려면 "
                    f"{self.settings.panic_hotkey or '비상 정지'}."
                    + ("" if told else " 배경 입력을 켜면 창을 앞에 두지 않아도 됩니다.")
                )
                told = True
                next_notice = now + REFOCUS_NOTICE_S
            # 자는 동안에도 정지 신호는 먹는다.
            self.sleep(0.15)

    def sleep(self, seconds: float) -> None:
        if not sender.precise_sleep(seconds, stop_check=self.stop_event.is_set):
            raise Aborted()

    def sleep_until(self, deadline: float) -> None:
        import time

        remaining = deadline + self._drift - time.perf_counter()
        if remaining > 0:
            self.sleep(remaining)

    # -- 시간 기준 --------------------------------------------------------
    #
    # _drift 는 "창을 되찾느라 멈춘 만큼, **이번 회차의 남은 이벤트**를 뒤로
    # 민다"는 뜻이다. 그래서 회차가 새로 시작할 때는 반드시 털어야 한다.
    # 털지 않고 기준 시각만 새로 잡으면, 새 기준에 옛 밀림이 그대로 더해져
    # **바퀴마다** 그만큼씩 죽은 시간이 새로 생긴다.
    #
    #   실측 — 0.05초짜리 매크로를 3바퀴 (정상이면 3바퀴째가 0.10초에 시작)
    #     2초 멈춘 적 없음 → 0.000s, 0.051s, 0.101s   (정상)
    #     2초 멈춘 적 있음 → 2.001s, 4.051s, 6.101s   (바퀴마다 2초씩 늘어남)
    #
    # 열 시간을 돌리는 동안 창이 몇 번만 밀려도 이렇게 벌어진다.

    def rebase(self) -> float:
        """새 회차의 기준 시각. 밀려 있던 몫은 여기서 끝난다."""
        import time

        self._drift = 0.0
        return time.perf_counter()

    def timebase(self) -> float:
        """지금을 0으로 삼는 기준 시각. 밀림 보정은 그대로 둔다.

        회차 한복판에서 짧은 것(대기 중 움직임)을 끼워 넣을 때 쓴다. 바깥
        회차의 밀림은 유지해야 하므로 털지 않고, 대신 sleep_until()이 더할
        만큼을 미리 빼 둬서 이 자리에서 곧바로 시작하게 한다.
        """
        import time

        return time.perf_counter() - self._drift

    @property
    def drift(self) -> float:
        """창을 되찾느라 멈춰 있던 누적 시간(초)."""
        return self._drift

    # -- 입력 추적 (중단 시 정리용) ------------------------------------------
    def key_down(self, vk: int) -> None:
        if self.background:
            postinput.key(self.window.hwnd, vk, True)
        else:
            sender.key_down(vk, self.settings.use_scancode)
        if vk not in self._pressed_vks:
            ARBITER.note_press()
        self._pressed_vks.add(vk)

    def key_up(self, vk: int) -> None:
        if self.background:
            postinput.key(self.window.hwnd, vk, False)
        else:
            sender.key_up(vk, self.settings.use_scancode)
        if vk in self._pressed_vks:
            ARBITER.note_release()
        self._pressed_vks.discard(vk)

    def button_down(self, button: str) -> None:
        if self.background:
            postinput.button(self.window.hwnd, button, True, *self._cursor)
        else:
            sender.mouse_button(button, up=False)
        if button not in self._pressed_buttons:
            ARBITER.note_press()
        self._pressed_buttons.add(button)

    def button_up(self, button: str) -> None:
        if self.background:
            postinput.button(self.window.hwnd, button, False, *self._cursor)
        else:
            sender.mouse_button(button, up=True)
        if button in self._pressed_buttons:
            ARBITER.note_release()
        self._pressed_buttons.discard(button)

    # -- 포인터 ------------------------------------------------------------
    def point_to(self, client_xy: tuple, screen_xy: tuple) -> None:
        """다음 클릭·휠이 향할 곳을 정한다.

        보통은 커서를 실제로 옮긴다. 배경 입력에서는 커서를 건드리지 않는다 —
        사용자가 쓰고 있는 마우스를 낚아채면 안 되기 때문이다. 대신 좌표를
        기억해 두었다가 메시지에 실어 보낸다.
        """
        self._cursor = client_xy
        if self.background:
            held = 0
            for name in self._pressed_buttons:
                entry = postinput.BUTTON_MESSAGES.get(name)
                if entry is not None:
                    held |= entry[2]
            postinput.move(self.window.hwnd, client_xy[0], client_xy[1], buttons=held)
        else:
            sender.mouse_move(screen_xy[0], screen_xy[1])

    def scroll(self, delta: int, screen_xy: tuple) -> None:
        if self.background:
            postinput.wheel(self.window.hwnd, delta, screen_xy[0], screen_xy[1])
        else:
            sender.mouse_wheel(delta)

    def release_stuck(self) -> list[str]:
        """지금 눌린 채로 남아 있는 키·버튼을 뗀다. 뗀 것들의 이름을 돌려준다.

        cleanup()과 쓰임이 다르다. cleanup은 작업을 끝내고 나갈 때 부르고, 이쪽은
        **돌아가는 중간에** 부른다. 그래서 우리 장부(_pressed_*)뿐 아니라 OS에
        눌린 채 남은 것까지 훑는다 — 게임이나 다른 프로그램이 키 뗌을 한 번
        놓치면 그 뒤 입력이 전부 어긋나는데, 그건 우리 장부에는 안 남는다.

        배경 입력에서는 OS 키 상태를 건드리지 않는다. 그쪽은 실제 키보드를
        쓰지 않으므로 훑을 것이 없고, 훑으면 사용자가 누르고 있던 키가 떼진다.
        """
        from .keys import name_of

        released: list[str] = []
        background = self.background

        for vk in list(self._pressed_vks):
            try:
                self.key_up(vk)
                released.append(name_of(vk))
            except OSError:
                pass
        for button in list(self._pressed_buttons):
            try:
                self.button_up(button)
                released.append(f"마우스 {button}")
            except OSError:
                pass

        if not background and self.settings.release_keys_on_stop:
            try:
                for vk in sender.release_all(use_scancode=self.settings.use_scancode):
                    released.append(name_of(vk))
            except OSError:
                pass
        return released

    def cleanup(self) -> None:
        """중단됐든 끝났든, 우리가 누른 것은 반드시 떼고 나간다."""
        background = self.background
        for vk in list(self._pressed_vks):
            try:
                if background:
                    postinput.key(self.window.hwnd, vk, False)
                else:
                    sender.key_up(vk, self.settings.use_scancode)
            except OSError:
                pass
            ARBITER.note_release()
        self._pressed_vks.clear()
        for button in list(self._pressed_buttons):
            try:
                if background:
                    postinput.button(self.window.hwnd, button, False, *self._cursor)
                else:
                    sender.mouse_button(button, up=True)
            except OSError:
                pass
            ARBITER.note_release()
        self._pressed_buttons.clear()
        # 배경 입력은 실제 키보드 상태를 건드리지 않으므로 강제 해제할 것이 없다.
        # 오히려 여기서 release_all을 부르면 사용자가 누르고 있던 키가 떼진다.
        if self.settings.release_keys_on_stop and not background:
            try:
                released = sender.release_all(use_scancode=self.settings.use_scancode)
                if released:
                    self.log(f"눌린 키 {len(released)}개를 강제 해제했습니다.")
            except OSError:
                pass


# --------------------------------------------------------------------------
# 자동 교정 (재동기화)
# --------------------------------------------------------------------------
# 몇 시간씩 돌리면 처음 설정한 것과 실제 상태가 조금씩 벌어진다. 벌어지는 곳은
# 늘 정해져 있다.
#
#   · 창을 되찾느라 멈춘 시간이 뒤 회차의 시각 계산에 남는다
#   · 키 뗌을 한 번 놓치면 그 키가 눌린 채로 남아 뒤 입력이 전부 어긋난다
#   · 게임 창 크기가 바뀌면 녹화해 둔 좌표가 빗나간다
#
# 이 셋을 사이클 경계마다 원래대로 돌려놓는다. 경계에서만 하는 이유는, 이벤트를
# 보내는 도중에 손대면 그 매크로가 반쯤 눌린 상태로 끊기기 때문이다.

# 창 크기가 이만큼 넘게 달라졌을 때만 알린다. 1~2픽셀은 테두리 계산 차이다.
SIZE_TOLERANCE = 4


def resync(ctx: RunContext, expect_size: tuple[int, int] | None = None) -> list[str]:
    """어긋난 것을 설정해 둔 상태로 되돌린다. 실제로 고친 것들을 돌려준다.

    아무 문제가 없으면 빈 목록이다. 부르는 쪽은 비어 있지 않을 때만 로그를
    남긴다 — 매 사이클 "이상 없음"을 적으면 로그가 그것만으로 찬다.
    """
    fixed: list[str] = []

    drifted = ctx.drift
    ctx.rebase()
    if drifted > 0.05:
        fixed.append(f"밀려 있던 {drifted:.1f}초를 털고 시각 기준을 다시 잡음")

    stuck = ctx.release_stuck()
    if stuck:
        fixed.append(f"눌린 채 남아 있던 {len(stuck)}개 해제 ({', '.join(stuck[:6])})")

    if expect_size and ctx.window is not None:
        now_w, now_h = ctx.window.client_size()
        want_w, want_h = expect_size
        if now_w > 0 and now_h > 0 and (
            abs(now_w - want_w) > SIZE_TOLERANCE or abs(now_h - want_h) > SIZE_TOLERANCE
        ):
            fixed.append(
                f"⚠ 게임 창 크기가 {want_w}x{want_h} → {now_w}x{now_h}로 바뀌었습니다. "
                "매크로마다 [창 크기 변화 시 좌표 비례 보정]을 켜 두세요"
            )

    return fixed


# --------------------------------------------------------------------------
# 좌표 변환
# --------------------------------------------------------------------------
POINTER_KINDS = ("move", "button", "wheel")

# 휠을 여러 칸 굴릴 때 칸 사이 간격(초).
WHEEL_STEP_S = 0.02


def has_pointer_events(events: list[dict[str, Any]]) -> bool:
    return any(e.get("kind") in POINTER_KINDS for e in events)


# --------------------------------------------------------------------------
# 진행 상황 표시용 문구
# --------------------------------------------------------------------------
def _play_movement(move, ctx: RunContext) -> None:
    """움직임 하나를 지금 자리에서 재생한다.

    별도 스레드로 돌리지 않는다. 같은 스레드에서 순서대로 내보내야 매크로의
    입력과 뒤섞이지 않고, 중단됐을 때 눌린 방향키도 확실히 떼진다.
    """
    import time

    ctx.log(f"  대기 중 움직임: {move.name} ({move.duration:.1f}초)")
    if ctx.board is not None:
        ctx.board.set(움직임=f"{move.name} · {move.duration:.1f}초")
    # 매크로 회차 한복판이므로 바깥의 밀림은 건드리지 않는다.
    base = ctx.timebase()
    try:
        for event in move.events:
            ctx.check()
            ctx.sleep_until(base + event.get("t", 0.0))
            with ARBITER.dispatch():
                if event.get("down"):
                    ctx.key_down(event["vk"])
                else:
                    ctx.key_up(event["vk"])
            if ctx.board is not None:
                ctx.board.sent(describe_event(event), move.name)
    finally:
        # 여기서 방향키가 남아 있으면 매크로의 다음 동작이 통째로 어긋난다.
        for vk in list(ctx._pressed_vks):
            if vk in movelib.MOVE_VKS:
                ctx.key_up(vk)
        if ctx.board is not None:
            ctx.board.set(움직임="")


def _wait_with_move(ctx: RunContext, target_at: float, gap: float, macro: Macro) -> None:
    """다음 이벤트 시각까지 기다리되, 틈이 넉넉하면 움직임을 하나 끼워 넣는다."""
    if not macro.use_moves or not ctx.moves:
        ctx.sleep_until(target_at)
        return

    chosen = movelib.plan(gap, ctx.moves, ctx.settings)
    if chosen is None:
        ctx.sleep_until(target_at)
        return

    move, offset = chosen
    # 대기가 시작된 시각 = 목표 시각에서 대기 길이를 뺀 값.
    ctx.sleep_until(target_at - gap + offset)
    _play_movement(move, ctx)
    ctx.sleep_until(target_at)


def _macro_line(macro: Macro, loop: int, span: float) -> str:
    total = f"/{macro.repeat}" if macro.repeat > 0 else ""
    speed = f" ×{macro.speed:g}배속" if macro.speed != 1.0 else ""
    return f"{macro.name} · {loop}{total}바퀴 · 한 바퀴 {span:.2f}초{speed}"


def _event_line(index: int, total: int, event: dict[str, Any], speed: float) -> str:
    at = event.get("t", 0.0) / (speed if speed > 0 else 1.0)
    return f"{index + 1}/{total} · {at:.2f}초 · {describe_event(event)}"



def _resolve_point(
    ctx: RunContext,
    cx: int,
    cy: int,
    absolute: bool,
    rec_w: int,
    rec_h: int,
    scale: bool,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """(클라이언트 좌표, 화면 좌표).

    SendInput은 화면 좌표로 커서를 옮겨야 하고, 창 메시지는 클라이언트 좌표를
    실어 보내야 한다. 어느 쪽을 쓸지는 보내는 쪽이 정하므로 둘 다 돌려준다.
    """
    if absolute or ctx.window is None:
        # 화면 절대좌표로 녹화된 매크로. 클라이언트 좌표를 알 수 없으니
        # 되돌려 계산해 본다 (창이 있으면).
        if ctx.window is not None:
            return (ctx.window.screen_to_client(cx, cy), (cx, cy))
        return ((cx, cy), (cx, cy))
    if scale and rec_w > 0 and rec_h > 0:
        cur_w, cur_h = ctx.window.client_size()
        if cur_w > 0 and cur_h > 0 and (cur_w != rec_w or cur_h != rec_h):
            cx = round(cx * cur_w / rec_w)
            cy = round(cy * cur_h / rec_h)
    return ((cx, cy), ctx.window.client_to_screen(cx, cy))


# --------------------------------------------------------------------------
# 녹화 매크로 재생
# --------------------------------------------------------------------------
def play_macro(macro: Macro, ctx: RunContext, quiet: bool = False) -> bool:
    """끝까지 재생했으면 True, 중단됐으면 False.

    반환값이 있어야 시나리오처럼 여러 개를 이어 돌리는 쪽에서 "앞 단계가 멈췄으니
    나머지도 그만둔다"를 판단할 수 있다.
    """
    import time

    if not macro.events:
        ctx.log(f"'{macro.name}': 이벤트가 없습니다.")
        return True

    # 화면 절대좌표로 저장된 매크로는 창을 옮기면 엉뚱한 곳을 누른다.
    # 조용히 빗나가는 것보다 이유를 알려주는 편이 낫다.
    if macro.absolute and has_pointer_events(macro.events) and ctx.window is not None:
        ctx.log(
            f"⚠ '{macro.name}'은 화면 절대좌표로 저장되어 있습니다. 게임 창을 "
            "옮겼다면 마우스가 엉뚱한 곳을 누릅니다. [녹화 · 재생] 탭의 "
            "[창 기준 좌표로 변환]을 쓰거나 다시 녹화하세요."
        )

    # 창 크기가 녹화 때와 다른데 비례 보정이 꺼져 있으면 좌표가 그대로 빗나간다.
    # 조용히 빗나가면 "왜 가끔 안 맞지"로만 남으므로 한 번은 짚어 준다.
    if (
        not macro.absolute
        and not macro.scale_to_window
        and macro.client_w > 0
        and ctx.window is not None
        and has_pointer_events(macro.events)
    ):
        now_w, now_h = ctx.window.client_size()
        if now_w > 0 and (
            abs(now_w - macro.client_w) > SIZE_TOLERANCE
            or abs(now_h - macro.client_h) > SIZE_TOLERANCE
        ):
            ctx.log(
                f"⚠ '{macro.name}': 녹화 때 창은 {macro.client_w}x{macro.client_h}인데 "
                f"지금은 {now_w}x{now_h}입니다. [창 크기 변화 시 좌표 비례 보정]이 "
                "꺼져 있어 좌표가 빗나갑니다."
            )

    board = ctx.board
    speed = macro.speed if macro.speed > 0 else 1.0
    # 맨 끝에 놓인 대기는 뒤따르는 이벤트가 없어서 "다음 이벤트 시각까지 기다리기"
    # 만으로는 쉬어지지 않는다. 한 바퀴의 총 길이를 미리 재 두고 거기까지 채운다.
    span = macro.duration
    loop = 0
    try:
        while True:
            loop += 1
            if macro.repeat > 0 and loop > macro.repeat:
                break
            ctx.check()
            # 바퀴마다 기준을 새로 잡는다. 밀려 있던 몫도 여기서 턴다 —
            # 안 그러면 창을 한 번 되찾을 때마다 그 시간이 바퀴마다 되풀이된다.
            base = ctx.rebase()
            if board is not None:
                board.set(매크로=_macro_line(macro, loop, span))
            total = len(macro.events)
            verbose = ctx.settings.verbose_log
            previous = 0.0
            for index, event in enumerate(macro.events):
                ctx.check()
                if verbose:
                    ctx.log(f"  · {_event_line(index, total, event, speed)}")
                # 예고는 **기다리기 전에** 남긴다. 깨어난 직후에 남기면 그만큼
                # 입력이 늦게 나간다.
                if board is not None:
                    board.set(다음=_event_line(index, total, event, speed))
                at = event["t"] / speed
                _wait_with_move(ctx, base + at, at - previous, macro)
                previous = at
                with ARBITER.dispatch():
                    _apply_event(event, macro, ctx)
                if board is not None:
                    board.sent(describe_event(event), macro.name)
            # 맨 끝에 붙은 대기도 서 있는 시간이다. 여기도 틈으로 본다.
            _wait_with_move(ctx, base + span / speed, span / speed - previous, macro)

            if macro.repeat > 0 and loop >= macro.repeat:
                break
            if macro.interval_ms > 0:
                ctx.sleep(macro.interval_ms / 1000.0)
        if not quiet:
            ctx.log(f"'{macro.name}' 재생 완료 ({loop}회).")
        return True
    except Aborted as exc:
        ctx.log(f"'{macro.name}' 중단됨. {exc.args[0] if exc.args else ''}".strip())
        return False
    finally:
        ctx.cleanup()


def _apply_event(event: dict[str, Any], macro: Macro, ctx: RunContext) -> None:
    kind = event["kind"]
    if kind == "wait":
        # 대기는 보내는 게 없다. 쉬는 시간은 뒤따르는 이벤트의 시각에 이미 들어가
        # 있고, 재생은 그 절대 시각에 맞춰 기다린다. 여기서 또 자면 두 번 쉰다.
        return
    if kind == "key":
        if event["down"]:
            ctx.key_down(event["vk"])
        else:
            ctx.key_up(event["vk"])
        return

    client, screen = _resolve_point(
        ctx,
        event.get("cx", 0),
        event.get("cy", 0),
        macro.absolute,
        macro.client_w,
        macro.client_h,
        macro.scale_to_window,
    )
    if kind == "move":
        ctx.point_to(client, screen)
    elif kind == "button":
        ctx.point_to(client, screen)
        if event["down"]:
            ctx.button_down(event["button"])
        else:
            ctx.button_up(event["button"])
    elif kind == "wheel":
        ctx.point_to(client, screen)
        count = max(int(event.get("count", 1)), 1)
        for index in range(count):
            ctx.check()
            ctx.scroll(event["wheel"], screen)
            # 칸 사이에 아주 짧은 틈이 있어야 게임이 각각을 따로 센다.
            # 한 번에 몰아 보내면 여러 칸이 한 칸으로 뭉개지는 경우가 있다.
            if index < count - 1:
                ctx.sleep(WHEEL_STEP_S)


# --------------------------------------------------------------------------
# 이동 경로 재생
# --------------------------------------------------------------------------
def play_path(path: PathMacro, ctx: RunContext, quiet: bool = False) -> bool:
    if not path.steps:
        ctx.log(f"'{path.name}': 단계가 없습니다.")
        return True

    loop = 0
    try:
        while True:
            loop += 1
            if path.repeat > 0 and loop > path.repeat:
                break
            for number, step in enumerate(path.steps, start=1):
                ctx.check()
                if ctx.settings.verbose_log:
                    ctx.log(f"  · {number}/{len(path.steps)} {step.label()}")
                if ctx.board is not None:
                    ctx.board.set(
                        경로=f"{path.name} · {loop}바퀴",
                        다음=f"{number}/{len(path.steps)} {step.label()}",
                    )
                with ARBITER.dispatch():
                    _apply_step(step, path, ctx)
                if ctx.board is not None:
                    ctx.board.sent(step.label(), path.name)

            if path.repeat > 0 and loop >= path.repeat:
                break
            if path.interval_ms > 0:
                ctx.sleep(path.interval_ms / 1000.0)
        if not quiet:
            ctx.log(f"'{path.name}' 실행 완료 ({loop}회).")
        return True
    except Aborted as exc:
        ctx.log(f"'{path.name}' 중단됨. {exc.args[0] if exc.args else ''}".strip())
        return False
    finally:
        ctx.cleanup()


# --------------------------------------------------------------------------
# 시나리오 — 매크로를 순서대로 이어 실행
# --------------------------------------------------------------------------
# 그룹 사이를 오갈 수 있는 최대 횟수. goto 조건이 서로를 가리켜 무한히 도는 것을
# 막는 안전장치다. 정상적인 시나리오는 이 근처에도 못 간다.
MAX_GROUP_TRANSITIONS = 10_000


class _StopScenario(Exception):
    """조건이 '시나리오 중지'를 지시했을 때."""


# 게시판에서 단계 종류를 한눈에 알아보게 하는 기호. 편집기 아이콘과 맞춘다.
STEP_MARKS = {
    "macro": "▶", "repeat": "⟳", "path": "↷", "wait": "…", "schedule": "⏰",
    "fishing": "낚",
}


def _scenario_line(scenario: Scenario, loop: int) -> str:
    total = f"/{scenario.repeat}" if scenario.repeat > 0 else " (무한)"
    return f"{scenario.name} · {loop}{total}바퀴"


def _run_macro_step(
    name: str, ctx: RunContext, find_macro, label: str,
    wheel_count: int = -1, repeat: int | None = None, quiet: bool = False,
    edit=None,
) -> bool:
    """매크로 하나를 하위 컨텍스트에서 실행한다. 중단되면 False."""
    macro = find_macro(name)
    if macro is None:
        ctx.log(f"{label}: 매크로 '{name}'을(를) 찾지 못해 건너뜁니다.")
        return True

    if not quiet:
        ctx.log(f"{label} — {macro.name}")

    # 하위 매크로는 정지 신호를 공유해야 비상 정지가 즉시 먹는다.
    sub = ctx.spawn()
    sub.board = ctx.board
    sub.moves = ctx.moves

    target = macro
    if repeat is not None and repeat != macro.repeat:
        target = copy.copy(macro)
        target.repeat = repeat
        if not quiet:
            ctx.log(f"  ※ 이 단계에서는 {repeat}회 반복합니다.")
    elif macro.repeat == 0:
        # 무한 반복 매크로를 그대로 넣으면 다음 단계로 넘어가지 못한다.
        target = copy.copy(macro)
        target.repeat = 1
        ctx.log(
            f"  ※ '{macro.name}'은 무한 반복 설정입니다. "
            "시나리오 안에서는 1회만 실행합니다."
        )

    if edit is not None:
        # 이번 실행에만 이벤트를 갈아 끼운다 (예: 제작의 채널 단추 자리).
        # **원본은 절대 건드리지 않는다** — 설정에 저장된 매크로가 바뀌면 안 된다.
        fresh = edit(target.events)
        if fresh is not None and fresh is not target.events:
            if target is macro:
                target = copy.copy(macro)
            target.events = fresh

    if wheel_count >= 0 and any(e.get("kind") == "wheel" for e in target.events):
        # 원본은 그대로 두고, 이번 실행에만 휠 칸 수를 갈아 끼운다.
        if target is macro:
            target = copy.copy(macro)
        count = max(wheel_count, 1)
        target.events = [
            ({**e, "count": count} if e.get("kind") == "wheel" else e)
            for e in target.events
        ]
        ctx.log(f"  ※ 휠을 {count}칸으로 바꿔 실행합니다.")

    return play_macro(target, sub, quiet=quiet)


# 연타 단계에 시간 제한이 없으면 시나리오가 그 자리에서 멈춰 버린다.
# 사용자가 값을 안 정했을 때 쓰는 기본 길이.
DEFAULT_REPEAT_SECONDS = 10


def _repeat_until(ctx: RunContext, seconds: float, once) -> bool:
    """정해진 시간이 찰 때까지 once()를 되풀이한다.

    한 번 시작한 동작은 중간에 자르지 않는다. 매크로를 반쯤 재생하다 끊으면
    누른 키가 남거나 게임 상태가 어중간해지기 때문이다. 그래서 마감 시각을
    넘어선 뒤에 멈추며, 실제 길이는 마지막 한 바퀴만큼 더 걸릴 수 있다.
    """
    import time

    deadline = time.perf_counter() + max(seconds, 0.0)
    rounds = 0
    while True:
        ctx.check()
        if not once():
            return False
        rounds += 1
        if time.perf_counter() >= deadline:
            ctx.log(f"  {seconds:.1f}초 동안 {rounds}회 실행")
            return True


def _run_schedule_step(step, ctx: RunContext, label: str, lookups: dict) -> bool:
    """예약 시각이 지나갔으면 실행하고, 아니면 그냥 지나간다.

    시나리오는 앞 단계가 끝나야 여기 도달하므로 정각에 딱 맞춰 올 수 없다.
    그래서 "지금이 정각인가"가 아니라 **"지난번 확인 이후로 정각이 지나갔는가"**
    를 본다. 지나갔으면 조금 늦더라도 한 번 실행하고, 같은 회차를 두 번 하지
    않도록 확인한 시각을 기록해 둔다.
    """
    import time

    from .tasks import describe_schedule, fire_schedule, next_fire_time, prev_fire_time

    task = lookups["schedule"](step.target)
    if task is None:
        ctx.log(f"{label}: 예약 '{step.target}'을(를) 찾지 못해 건너뜁니다.")
        return True

    # 자기 자신을 다시 돌리면 끝없이 겹쳐 들어간다.
    if task.action_kind == "scenario" and task.action_target == lookups["scenario_name"]:
        ctx.log(
            f"{label}: 예약 '{task.name}'이 지금 돌고 있는 시나리오를 가리켜 "
            "건너뜁니다."
        )
        return True

    state = lookups["schedule_state"]
    now = time.time()
    # 처음 만나는 예약의 기준선은 시나리오를 켠 순간이다. 그래야 켜기 직전에
    # 지나간 정각까지 소급해 실행하는 일이 없다.
    last = state.get(task.name, lookups["schedule_since"])
    due = prev_fire_time(task, now)

    if due <= last:
        nxt = next_fire_time(task, now)
        ctx.log(
            f"{label} — 예약 '{task.name}' 아직 아님 "
            f"({describe_schedule(task)} · 다음 "
            f"{time.strftime('%H:%M:%S', time.localtime(nxt))})"
        )
        return True

    state[task.name] = now
    late = now - due
    ctx.log(
        f"{label} — 예약 '{task.name}' 시각 지남 "
        f"({time.strftime('%H:%M:%S', time.localtime(due))}"
        f"{f', {late:.0f}초 늦음' if late >= 1 else ''}) → 실행"
    )
    fire_schedule(
        task,
        ctx,
        lookups["macro"],
        lookups["path"],
        lookups["scenario"],
        lookups["rule"],
        lookups["buff"],
        lookups["library_root"],
    )
    return not ctx.stop_event.is_set()


def _run_step(step, ctx: RunContext, label: str, lookups: dict) -> bool:
    """단계 하나를 종류에 맞게 실행한다. 중단되면 False."""
    if step.kind == "schedule":
        return _run_schedule_step(step, ctx, label, lookups)

    if step.kind == "fishing":
        setup = getattr(ctx, "fishing", None)
        if setup is None:
            ctx.log(f"{label}: 낚시 설정이 없어 건너뜁니다.")
            return True
        from .fishtask import run_fishing

        if step.timed:
            seconds = step.effective_seconds()
            ctx.log(f"{label} — 낚시 ({seconds:.1f}초 동안)")
            run_fishing(setup, _child(ctx), seconds=seconds,
                        find_macro=lookups["macro"],
                        find_rule=lookups["rule"])
        else:
            rounds = max(1, step.effective_repeat(1))
            ctx.log(f"{label} — 낚시 ({rounds}판)")
            run_fishing(setup, _child(ctx), rounds=rounds,
                        find_macro=lookups["macro"],
                        find_rule=lookups["rule"])
        return not ctx.stop_event.is_set()

    if step.kind == "wait":
        ctx.log(f"{label} — 대기 {step.wait_ms}ms")
        ctx.sleep(max(step.wait_ms, 0) / 1000.0)
        return True

    if step.kind == "path":
        path = lookups["path"](step.target)
        if path is None:
            ctx.log(f"{label}: 이동 경로 '{step.target}'을(를) 찾지 못해 건너뜁니다.")
            return True

        sub_ctx = lambda: _child(ctx)  # noqa: E731
        if step.timed:
            seconds = step.effective_seconds()
            ctx.log(f"{label} — 경로 {path.name} ({seconds:.1f}초 동안)")
            single = copy.copy(path)
            single.repeat = 1
            return _repeat_until(
                ctx, seconds, lambda: play_path(single, sub_ctx(), quiet=True)
            )

        times = step.effective_repeat(path.repeat)
        ctx.log(f"{label} — 경로 {path.name} (×{times})")
        target = path
        if times != path.repeat:
            target = copy.copy(path)
            target.repeat = times
            if path.repeat == 0 and not step.custom_repeat:
                ctx.log("  ※ 무한 반복 경로라 1회만 실행합니다.")
        return play_path(target, sub_ctx())

    if step.kind == "repeat":
        task = lookups["repeat"](step.target)
        if task is None:
            ctx.log(f"{label}: 연타 '{step.target}'을(를) 찾지 못해 건너뜁니다.")
            return True

        seconds = step.effective_seconds(task.duration_s)
        if seconds <= 0:
            seconds = DEFAULT_REPEAT_SECONDS
            ctx.log(
                f"  ※ '{task.name}'에 시간 제한이 없어 {seconds}초만 돌립니다. "
                "단계 설정에서 원하는 길이를 정하세요."
            )
        ctx.log(f"{label} — 연타 {task.name} ({seconds:.1f}초)")

        bounded = copy.copy(task)
        bounded.duration_s = seconds
        from .tasks import run_repeat

        if ctx.board is not None:
            ctx.board.set(
                다음=f"연타 [{task.key}] {task.interval_ms}ms 간격 · {seconds:.1f}초"
            )
        run_repeat(bounded, _child(ctx))
        return not ctx.stop_event.is_set()

    macro = lookups["macro"](step.target)
    if macro is None:
        ctx.log(f"{label}: 매크로 '{step.target}'을(를) 찾지 못해 건너뜁니다.")
        return True

    if step.timed:
        seconds = step.effective_seconds()
        ctx.log(f"{label} — {macro.name} ({seconds:.1f}초 동안)")
        return _repeat_until(
            ctx,
            seconds,
            lambda: _run_macro_step(
                step.target, ctx, lookups["macro"], "",
                wheel_count=step.wheel_count, repeat=1, quiet=True,
            ),
        )

    times = step.effective_repeat(macro.repeat)
    return _run_macro_step(
        step.target, ctx, lookups["macro"], label,
        wheel_count=step.wheel_count, repeat=times,
    )


def _child(ctx: RunContext) -> RunContext:
    """정지 신호와 게시판을 공유하는 하위 컨텍스트."""
    sub = ctx.spawn()
    sub.board = ctx.board
    sub.moves = ctx.moves
    return sub


class _Interrupts:
    """조건부 그룹의 발동을 관리한다.

    조건부 그룹은 시나리오의 순서에서 빠져 있다가, 조건이 걸리면 하던 일을 잠깐
    멈추고 한 번 돈 뒤 원래 자리로 돌아온다. 그래서 두 가지를 기억해야 한다.

    · **재발동 대기** — 조건이 걸린 채로 남아 있으면 (예: 가방이 아직 가득)
      쉴 새 없이 되풀이한다. 한 번 돌고 나면 정한 시간만큼은 다시 보지 않는다.
    · **끼어들기 중인가** — 끼어든 그룹 안에서 또 끼어들면 끝없이 파고든다.
      한 겹만 허용한다.
    """

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self._last_fired: dict[str, float] = {}
        self._busy = False

    def any_for(self, when: str) -> bool:
        """그 시점에 볼 조건부 그룹이 하나라도 있는가.

        없으면 확인 자체를 건너뛴다 — 조건 하나를 보는 데 화면을 읽으므로,
        볼 것이 없을 때 도는 것만으로도 낭비다.
        """
        if self._busy:
            return False
        return any(g.trigger_when == when for g in self.scenario.watch_groups)

    def ready(self, group: ScenarioGroup, now: float) -> bool:
        wait = max(0, group.trigger_cooldown_s)
        if wait <= 0:
            return True
        last = self._last_fired.get(group.name, 0.0)
        return now - last >= wait

    def mark(self, group: ScenarioGroup, now: float) -> None:
        self._last_fired[group.name] = now

    def enter(self) -> None:
        self._busy = True

    def leave(self) -> None:
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy


def _run_group_once(
    group: ScenarioGroup, ctx: RunContext, lookups: dict, why: str
) -> bool:
    """그룹 하나를 끼어들어 돌린다. 끝까지 돌았으면 True.

    돌아올 자리를 건드리지 않는다 — 그룹 안의 조건(conditions)도 보지 않고,
    그 안에서 또 다른 조건부 그룹이 끼어들지도 않는다. 끼어들기는 짧고 예측
    가능해야 한다. 길게 이어지는 흐름이 필요하면 그건 일반 그룹의 일이다.
    """
    cycles = group.interrupt_cycles()
    ctx.log(f"  ↘ [{group.name}] 끼어들기 — {why}")
    if ctx.board is not None:
        ctx.board.set(끼어들기=f"{group.name} · {why}")
    try:
        for cycle in range(1, cycles + 1):
            ctx.check()
            for number, step in enumerate(group.steps, start=1):
                ctx.check()
                label = (
                    f"[{group.name}] 끼어들기 {cycle}/{cycles}회차 "
                    f"{number}/{len(group.steps)}"
                )
                if ctx.board is not None:
                    ctx.board.set(
                        단계=f"{number}/{len(group.steps)} "
                        f"{STEP_MARKS.get(step.kind, '·')} {step.label}",
                        매크로="", 경로="", 다음="",
                    )
                if not _run_step(step, ctx, label, lookups):
                    return False
                delay = step.effective_delay(group.interval_ms)
                if delay > 0:
                    ctx.sleep(delay / 1000.0)
    finally:
        if ctx.board is not None:
            ctx.board.set(끼어들기="")
    ctx.log(f"  ↗ [{group.name}] 끼어들기 끝 — 하던 자리로 돌아갑니다")
    return True


def _serve_interrupts(
    interrupts: _Interrupts, when: str, ctx: RunContext, lookups: dict
) -> bool:
    """지금 걸린 조건부 그룹이 있으면 돌린다. 중단됐으면 False.

    걸린 것이 여럿이면 **위에 있는 것 하나만** 이번에 돈다. 목록 순서가 곧
    우선순위다. 나머지는 다음 확인 때 다시 본다 — 한 번에 여럿을 몰아 돌리면
    본래 하던 일이 얼마나 밀릴지 가늠할 수 없다.
    """
    import time

    from .tasks import evaluate_rule

    if not interrupts.any_for(when):
        return True

    find_rule = lookups["rule"]
    now = time.time()
    for group in interrupts.scenario.watch_groups:
        if group.trigger_when != when:
            continue
        if not interrupts.ready(group, now):
            continue
        rule = find_rule(group.trigger)
        if rule is None:
            ctx.log(f"  조건부 그룹 '{group.name}': 조건 '{group.trigger}'을(를) 찾지 못했습니다.")
            continue
        if not group.steps:
            continue

        spots: list = []
        triggered, detail = evaluate_rule(rule, ctx, spots=spots)
        if not triggered:
            continue

        interrupts.mark(group, now)
        interrupts.enter()
        try:
            if not _run_group_once(
                group, ctx, lookups, f"조건 '{group.trigger}' 성립 [{detail}]"
            ):
                return False
        finally:
            interrupts.leave()
        # 한 번에 하나만.
        return True
    return True


def _check_conditions(
    group: ScenarioGroup, ctx: RunContext, find_macro, find_rule
) -> tuple[str, str] | None:
    """그룹의 조건을 위에서부터 확인한다.

    **먼저 걸리는 조건 하나만** 발동한다. 목록 순서가 곧 우선순위다.
    반환: (동작, 대상) 또는 None.
    """
    from .tasks import evaluate_rule  # 순환 참조를 피해 여기서 가져온다

    for condition in group.conditions:
        if not condition.enabled or not condition.rule:
            continue
        rule = find_rule(condition.rule)
        if rule is None:
            ctx.log(f"  조건 '{condition.rule}'을(를) 찾지 못해 건너뜁니다.")
            continue

        triggered, detail = evaluate_rule(rule, ctx)
        if not triggered:
            continue

        ctx.log(f"  조건 성립: '{condition.rule}' [{detail}]")
        if condition.action == "stop":
            raise _StopScenario(condition.rule)
        if condition.action == "goto":
            return ("goto", condition.target)
        if condition.action == "group":
            # goto와 다르다. 그 그룹을 한 번 돌고 **이 자리로 돌아온다.**
            return ("group", condition.target)
        if condition.action == "click":
            from .tasks import click_spot

            click_spot(rule, ctx, spots)
            return ("click", "")
        if condition.action == "run" and condition.target:
            if not _run_macro_step(
                condition.target, ctx, find_macro, "  조건 동작"
            ):
                raise Aborted()
        return ("run", condition.target)
    return None


def play_scenario(
    scenario: Scenario,
    ctx: RunContext,
    find_macro,
    find_rule,
    find_buff=None,
    library_root=None,
    find_repeat=None,
    find_path=None,
    find_schedule=None,
    find_scenario=None,
) -> bool:
    """그룹을 순서대로 돌되, 각 그룹은 사이클마다 조건과 버프를 확인한다."""
    import time

    from .buffs import WatchState

    if not scenario.groups:
        ctx.log(f"'{scenario.name}': 그룹이 없습니다.")
        return True

    # 화면으로 버프를 보는 경우, "몇 번 연속 안 보였나"를 사이클을 넘겨 기억해야
    # 한다. 사이클마다 새로 만들면 연속 확인이 늘 1회에서 끊긴다.
    watch_state = WatchState()

    lookups = {
        "macro": find_macro,
        "repeat": find_repeat or (lambda _n: None),
        "path": find_path or (lambda _n: None),
        "schedule": find_schedule or (lambda _n: None),
        "scenario": find_scenario or (lambda _n: None),
        "rule": find_rule,
        "buff": find_buff,
        "library_root": library_root,
        "scenario_name": scenario.name,
        # 예약 단계가 "지난번 확인 이후"를 재는 기준. 시작 시각을 기준선으로
        # 두면 켜기 직전에 지나간 정각을 소급 실행하지 않는다.
        "schedule_since": time.time(),
        "schedule_state": {},
    }
    # 조건부 그룹은 차례에서 빠진다. 조건이 걸릴 때만 끼어든다.
    ordered = scenario.ordered_groups
    if not ordered:
        ctx.log(
            f"'{scenario.name}': 순서대로 돌 그룹이 없습니다 "
            "(전부 조건부 그룹입니다). 일반 그룹을 하나는 두세요."
        )
        return True
    names = [g.name for g in ordered]
    interrupts = _Interrupts(scenario)
    watching = scenario.watch_groups
    if watching:
        ctx.log(
            f"  조건부 그룹 {len(watching)}개 감시: "
            + ", ".join(f"{g.name}({g.trigger})" for g in watching)
        )
        # '단계마다' + 재발동 대기 0은, 조건이 걸린 채로 남아 있으면 단계 하나
        # 돌 때마다 끼어든다. 그러면 본작업이 사실상 멈춘다.
        for g in watching:
            if g.trigger_when == TRIGGER_STEP and g.trigger_cooldown_s <= 0:
                ctx.log(
                    f"  ⚠ '{g.name}'은 [단계마다] 확인인데 재발동 대기가 0입니다. "
                    "조건이 계속 걸려 있으면 단계마다 끼어들어 본작업이 밀립니다 — "
                    "대기를 몇 초라도 주세요."
                )
    loop = 0
    # 시작할 때의 창 크기를 기억해 둔다. 돌아가는 중에 창 크기가 달라지면
    # 녹화해 둔 좌표가 빗나가므로 알려야 한다.
    start_size = ctx.window.client_size() if ctx.window is not None else None
    every = max(0, getattr(ctx.settings, "resync_cycles", 1))
    cycles_done = 0
    try:
        while True:
            loop += 1
            if scenario.repeat > 0 and loop > scenario.repeat:
                break

            index = 0
            transitions = 0
            while index < len(ordered):
                ctx.check()
                group = ordered[index]
                next_index = index + 1
                cycle = 0

                while True:
                    ctx.check()
                    cycle += 1
                    if group.repeat > 0 and cycle > group.repeat:
                        break

                    # 사이클을 시작하기 전에 상태를 설정해 둔 대로 되돌린다.
                    # 여기가 입력이 하나도 안 나가 있는 유일하게 안전한 지점이다.
                    cycles_done += 1
                    if every and cycles_done % every == 0:
                        for note in resync(ctx, start_size):
                            ctx.log(f"  [자동 교정] {note}")

                    # 사이클을 시작하기 전에 조건부 그룹부터 본다. 하던 일을
                    # 시작하고 나서 끼어들면 그 사이클이 반쯤 끊긴다.
                    if not _serve_interrupts(interrupts, TRIGGER_CYCLE, ctx, lookups):
                        return False

                    total = f"/{group.repeat}" if group.repeat > 0 else ""
                    if ctx.board is not None:
                        ctx.board.set(
                            시나리오=_scenario_line(scenario, loop),
                            그룹=f"{group.name} · {cycle}{total}회차 "
                            f"({index + 1}/{len(ordered)}번째 그룹)",
                        )
                    for number, step in enumerate(group.steps, start=1):
                        ctx.check()
                        # 단계마다 보기로 한 조건부 그룹은 여기서 본다. 사이클이
                        # 길 때 (몇 분씩) 사이클 경계까지 기다리면 늦다.
                        if not _serve_interrupts(
                            interrupts, TRIGGER_STEP, ctx, lookups
                        ):
                            return False
                        label = (
                            f"[{group.name}] {cycle}{total}회차 "
                            f"{number}/{len(group.steps)}"
                        )
                        if ctx.board is not None:
                            ctx.board.set(
                                단계=f"{number}/{len(group.steps)} "
                                f"{STEP_MARKS.get(step.kind, '·')} {step.label}",
                                매크로="", 경로="", 다음="",
                            )
                        if not _run_step(step, ctx, label, lookups):
                            return False
                        delay = step.effective_delay(group.interval_ms)
                        if delay > 0:
                            ctx.sleep(delay / 1000.0)

                    # 한 사이클이 끝났다. 먼저 버프를 챙긴다 — 일하는 동안
                    # 버프가 끊기면 그 사이 얻는 경험치가 그냥 손해다.
                    if group.buffs and find_buff is not None:
                        from .buffs import refresh_expired

                        refresh_expired(
                            group.buffs,
                            find_buff,
                            ctx,
                            library_root,
                            margin_s=group.buff_margin_s,
                            state=watch_state,
                        )

                    # 그다음 조건을 본다.
                    outcome = _check_conditions(group, ctx, find_macro, find_rule)
                    if outcome and outcome[0] == "group":
                        target = scenario.find_group(outcome[1])
                        if target is None:
                            ctx.log(f"  → 그룹 '{outcome[1]}'을(를) 찾지 못했습니다.")
                        elif target is group:
                            ctx.log(f"  → '{group.name}'이 자기 자신을 부릅니다. 건너뜁니다.")
                        elif interrupts.busy:
                            ctx.log("  → 이미 끼어들기 중이라 건너뜁니다.")
                        else:
                            interrupts.enter()
                            try:
                                if not _run_group_once(
                                    target, ctx, lookups, f"조건 '{outcome[1]}'"
                                ):
                                    return False
                            finally:
                                interrupts.leave()
                    elif outcome and outcome[0] == "goto":
                        target = outcome[1]
                        if target in names:
                            next_index = names.index(target)
                            ctx.log(f"  → '{target}' 그룹으로 이동")
                        else:
                            ctx.log(f"  → 그룹 '{target}'을(를) 찾지 못해 그냥 진행합니다.")
                        break

                    if group.repeat > 0 and cycle >= group.repeat:
                        break

                index = next_index
                transitions += 1
                if transitions > MAX_GROUP_TRANSITIONS:
                    ctx.log(
                        "그룹 이동이 너무 많습니다. 조건이 서로를 가리키고 있는지 "
                        "확인하세요. 시나리오를 중단합니다."
                    )
                    return False
                if index < len(scenario.groups) and scenario.interval_ms > 0:
                    ctx.sleep(scenario.interval_ms / 1000.0)

            if scenario.repeat > 0 and loop >= scenario.repeat:
                break

        ctx.log(f"'{scenario.name}' 시나리오 완료 ({loop}회).")
        return True
    except _StopScenario as stop:
        ctx.log(f"'{scenario.name}': 조건 '{stop.args[0]}'에 따라 시나리오를 마칩니다.")
        return True
    except Aborted as exc:
        ctx.log(f"'{scenario.name}' 중단됨. {exc.args[0] if exc.args else ''}".strip())
        return False
    finally:
        ctx.cleanup()


def _apply_step(step: PathStep, path: PathMacro, ctx: RunContext) -> None:
    if step.kind == "wait":
        ctx.sleep(step.duration_ms / 1000.0)
        return

    if step.kind == "key":
        vk = vk_of(step.key)
        if vk is None:
            ctx.log(f"알 수 없는 키: {step.key} — 건너뜁니다.")
            return
        ctx.key_down(vk)
        try:
            ctx.sleep(step.duration_ms / 1000.0)
        finally:
            ctx.key_up(vk)
        return

    client, screen = _resolve_point(
        ctx, step.x, step.y, False, path.client_w, path.client_h, path.scale_to_window
    )
    if step.kind == "move":
        ctx.point_to(client, screen)
    elif step.kind == "click":
        ctx.point_to(client, screen)
        ctx.sleep(0.015)
        ctx.button_down(step.button)
        ctx.sleep(max(step.duration_ms, 20) / 1000.0)
        ctx.button_up(step.button)
