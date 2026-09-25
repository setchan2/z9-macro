"""컨트롤러: 프로필 + 훅 + 핫키 + 실행 중인 작업들을 한 곳에서 관리한다.

GUI는 이 클래스만 호출한다. 스레드 관련 처리는 전부 여기 있다.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from . import elevation, moves as movelib
from . import pixel, postinput, progress, sender, storage, tasks
from .hooks import HOOKS
from .hotkeys import HotkeyManager
from .keys import vk_of
from .library import TYPES as library_types
from .library import Library, import_into
from .model import (
    Macro,
    PathMacro,
    PixelRule,
    Profile,
    RepeatTask,
    Scenario,
    ScheduledTask,
)
from .model import FOCUS_STOP, INPUT_POST, BuffItem, Movement
from .observer import Observer
from .player import (
    RunContext,
    has_pointer_events,
    play_macro,
    play_path,
    play_scenario,
)
from .recorder import Recorder, balance_keys
from .window import GameWindow, WindowResolver, list_windows

TaskKey = tuple[str, str]  # (종류, 이름)

# 진행 상황 게시판 제목에 쓸 이름.
KIND_LABELS = {
    "macro": "매크로",
    "path": "이동 경로",
    "repeat": "연타",
    "rule": "조건 감시",
    "scenario": "시나리오",
    "schedule": "예약",
    "move": "움직임",
    "fishing": "낚시",
    "lumber": "벌목",
}


class RunningTask:
    def __init__(self, key: TaskKey, ctx: RunContext, thread: threading.Thread) -> None:
        self.key = key
        self.ctx = ctx
        self.thread = thread
        self.started = time.monotonic()

    @property
    def alive(self) -> bool:
        return self.thread.is_alive()


class Engine:
    def __init__(self, profile_path: Path | None = None) -> None:
        self.profile_path = profile_path
        self.profile: Profile = storage.load(profile_path)
        self.resolver = WindowResolver(self.profile.settings.window_pattern)
        self.recorder = Recorder()
        self.observer = Observer(log=self.log)
        # 벌목을 사람이 직접 하는 동안 입력과 화면을 남긴다 (매크로를 만들 자료).
        self.hotkeys = HotkeyManager(on_error=self.log)
        self.logs: queue.Queue[str] = queue.Queue()
        self._running: dict[TaskKey, RunningTask] = {}
        self._lock = threading.Lock()
        self._started = False
        self._on_record_toggle: Callable[[], None] | None = None
        self._on_observe_toggle: Callable[[], None] | None = None
        self._on_state_change: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # 수명 주기
    # ------------------------------------------------------------------
    def start(self) -> None:
        if self._started:
            return
        HOOKS.start()
        self.hotkeys.attach()
        self.rebind_hotkeys()
        self._started = True
        self.log("엔진 시작. 전역 훅이 활성화되었습니다.")

    def shutdown(self) -> None:
        self.stop_all(reason="종료")
        self.recorder.cancel()
        if self.observer.running:
            self.observer.stop()
        self.hotkeys.detach()
        HOOKS.stop()
        self._started = False

    def set_callbacks(
        self,
        on_record_toggle: Callable[[], None] | None = None,
        on_observe_toggle: Callable[[], None] | None = None,
        on_state_change: Callable[[], None] | None = None,
    ) -> None:
        self._on_record_toggle = on_record_toggle
        self._on_observe_toggle = on_observe_toggle
        self._on_state_change = on_state_change

    # ------------------------------------------------------------------
    # 로그
    # ------------------------------------------------------------------
    def log(self, message: str) -> None:
        self.logs.put(f"[{time.strftime('%H:%M:%S')}] {message}")

    def drain_logs(self, limit: int = 200) -> list[str]:
        out: list[str] = []
        while len(out) < limit:
            try:
                out.append(self.logs.get_nowait())
            except queue.Empty:
                break
        return out

    def _notify(self) -> None:
        if self._on_state_change:
            try:
                self._on_state_change()
            except Exception:  # noqa: BLE001 - GUI 콜백 실패로 엔진이 죽지 않게
                pass

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------
    def save(self) -> None:
        self.profile.settings.window_pattern = self.resolver.pattern
        path = storage.save(self.profile, self.profile_path)
        self.log(f"프로필 저장: {path}")

    # ------------------------------------------------------------------
    # 라이브러리
    # ------------------------------------------------------------------
    @property
    def library_root(self) -> Path:
        configured = (self.settings.library_dir or "").strip()
        # 정해 둔 폴더가 **없으면** 프로그램(exe) 옆 library/ 를 쓴다. exe를 다른
        # 컴퓨터나 폴더로 옮기면 예전 절대 경로는 사라지는데, 그대로 따라가면
        # 피로도 숫자 글꼴 같은 것을 못 찾아 조건이 조용히 안 선다.
        if configured and Path(configured).is_dir():
            return Path(configured)
        return storage.DEFAULT_LIBRARY

    @property
    def library(self) -> Library:
        # 설정에서 폴더를 바꿀 수 있으니 매번 현재 경로로 만든다.
        return Library(self.library_root)

    def set_library_dir(self, path: str) -> None:
        self.settings.library_dir = str(path or "").strip()
        self.log(f"라이브러리 폴더: {self.library_root}")

    def save_to_library(self, item, category: str = "") -> Path:
        path = self.library.save(item, category=category)
        where = f"{category}/" if category else ""
        self.log(f"라이브러리에 저장: {where}{path.name}")
        return path

    def library_keep(self) -> set[tuple[str, str]]:
        """보관함에 남길 것 — 지금 가진 매크로 · 시나리오 (종류, 이름)."""
        profile = self.profile
        return ({("macro", m.name) for m in profile.macros}
                | {("scenario", s.name) for s in profile.scenarios})

    def upload_to_library(self, items: list | None = None, category: str = "",
                          dry_run: bool = False):
        """매크로 · 시나리오를 보관함에 올리고, 지금 가진 것이 아닌 항목 파일은 치운다.

        items를 안 주면 지금 가진 매크로 · 시나리오 전부를 올린다.
        """
        from . import library as library_mod

        # 정해 둔 폴더가 잠깐 없으면(원드라이브 오프라인 · USB 뺌) library_root는 기본
        # 폴더로 넘어간다. 그 상태에서 올리면 엉뚱한 기본 보관함을 비우게 되므로 멈춘다.
        configured = (self.settings.library_dir or "").strip()
        if configured and not Path(configured).is_dir():
            raise library_mod.LibraryError(
                f"정해 둔 보관함 폴더가 없습니다: {configured}\n폴더를 연결하거나 "
                "[폴더 변경]으로 다시 골라 주세요.")
        if items is None:
            items = list(self.profile.macros) + list(self.profile.scenarios)
        report = library_mod.upload(self.library, items, self.library_keep(),
                                    category=category, dry_run=dry_run)
        if dry_run:
            return report
        self.log(f"보관함 올리기 — {report.summary()} ({self.library_root})")
        for name in report.replaced:
            self.log(f"  같은 이름이라 바꿔 올림: {name}")
        for name in report.removed:
            self.log(f"  지금 가진 것이 아니라 치움: {name}")
        for line in report.failed:
            self.log(f"  실패: {line}")
        if report.backup is not None:
            self.log(f"  치운 것은 여기 옮겨 두었습니다: {report.backup}")
        return report

    def import_from_library(self, path: Path) -> tuple[str, str]:
        """(종류 코드, 실제로 등록된 이름)."""
        type_code, item = self.library.load(path)
        name = import_into(self.profile, type_code, item)
        self.rebind_hotkeys()
        self.log(f"라이브러리에서 불러옴: '{name}' ({library_types[type_code][2]})")
        return (type_code, name)

    # ------------------------------------------------------------------
    # 창
    # ------------------------------------------------------------------
    @property
    def settings(self):
        return self.profile.settings

    def window(self) -> GameWindow | None:
        return self.resolver.get()

    def window_status(self) -> str:
        win = self.window()
        if win is None:
            return f"창 없음 (패턴: {self.resolver.pattern})"
        cw, ch = win.client_size()
        front = "활성" if win.is_foreground() else "비활성"
        return f"{win.title} — 클라이언트 {cw}x{ch} — {front}"

    def candidate_windows(self, pattern: str = "") -> list[tuple[int, str]]:
        return [(w.hwnd, w.title) for w in list_windows(pattern)]

    # ------------------------------------------------------------------
    # 입력 전달 경로 진단
    # ------------------------------------------------------------------
    PROBE_VK = 0x7E  # F15 — 어떤 프로그램도 기본 매핑을 갖지 않는다

    def privilege_report(self) -> tuple[bool, str]:
        """(문제없음, 설명). 권한 때문에 입력이 막힐 상황인지 판정한다."""
        we_are_admin = elevation.is_elevated()
        win = self.window()
        if win is None:
            state = "관리자" if we_are_admin else "일반"
            return (True, f"게임 창 미발견 — 이 프로그램은 {state} 권한으로 실행 중")

        pid = elevation.window_process_id(win.hwnd)
        name = elevation.process_name(pid)
        game_admin = elevation.process_elevated(pid)

        if we_are_admin:
            return (True, f"관리자 권한으로 실행 중 — 대상 {name}")
        if game_admin is False:
            return (True, f"권한 동일 — 대상 {name} (둘 다 일반 권한)")

        reason = "관리자 권한" if game_admin else "더 높은 권한(조회 불가)"
        return (
            False,
            f"게임({name})이 {reason}으로 실행 중인데 이 프로그램은 일반 권한입니다. "
            "이 상태에서는 Windows가 입력을 조용히 차단합니다 — 오류 없이 아무 "
            "일도 일어나지 않습니다. [설정] 탭에서 관리자 권한으로 다시 실행하세요.",
        )

    def background_input_test(
        self, key_name: str = "Right", seconds: float = 1.5
    ) -> tuple[bool, str]:
        """배경 입력이 이 게임에 통하는지 실제로 넣어 보고 판정한다.

        통하는지 알아낼 방법은 하나뿐이다 — 넣어 보고 게임이 반응하는지 보는 것.
        코드로는 알 수 없다. 게임 화면은 가만 둬도 계속 바뀌므로(애니메이션),
        **아무것도 안 보낸 구간**을 먼저 재서 그 변화량을 기준선으로 삼고,
        입력을 넣은 구간이 그보다 뚜렷하게 더 변했는지 본다.

        반환: (통한 것 같다, 설명)
        """
        vk = vk_of(key_name)
        if vk is None:
            return (False, f"알 수 없는 키: {key_name}")

        win = self.window()
        if win is None:
            return (False, f"게임 창을 찾지 못했습니다 (패턴: {self.resolver.pattern}).")
        if win.minimized:
            return (
                False,
                "창이 최소화돼 있으면 화면을 읽을 수 없어 판정할 수 없습니다. "
                "창을 띄운 채 다른 창을 클릭해 뒤로 보낸 상태에서 시험하세요.",
            )

        cw, ch = win.client_size()
        if cw <= 0 or ch <= 0:
            return (False, "창 크기를 읽지 못했습니다.")
        left, top = win.client_to_screen(0, 0)

        def grab():
            return pixel.capture_region(left, top, cw, ch).buf

        def diff(a: bytes, b: bytes) -> float:
            """달라진 픽셀의 비율. 촘촘히 볼 필요가 없어 듬성듬성 훑는다."""
            if len(a) != len(b) or not a:
                return 1.0
            step = 4 * 37  # 픽셀 37개마다 하나씩 — 서로 다른 줄을 고르게 짚는다
            changed = total = 0
            for i in range(0, len(a) - 3, step):
                total += 1
                if abs(a[i] - b[i]) > 12 or abs(a[i + 1] - b[i + 1]) > 12:
                    changed += 1
            return changed / total if total else 0.0

        try:
            # 1) 아무것도 보내지 않은 구간 — 이 게임 화면이 스스로 얼마나 변하는가
            before = grab()
            time.sleep(seconds)
            idle = diff(before, grab())

            # 2) 배경 입력을 넣은 구간
            before = grab()
            deadline = time.monotonic() + seconds
            posts = 0
            while time.monotonic() < deadline:
                postinput.key(win.hwnd, vk, True)
                time.sleep(0.05)
                postinput.key(win.hwnd, vk, False)
                time.sleep(0.05)
                posts += 1
            active = diff(before, grab())
        except (pixel.CaptureError, postinput.PostError, OSError) as exc:
            return (False, f"시험 중 오류: {exc}")

        detail = (
            f"[{key_name}] {posts}회 전송 · 화면 변화 "
            f"가만히 뒀을 때 {idle * 100:.1f}% → 입력했을 때 {active * 100:.1f}%"
        )
        # 애니메이션 잡음을 감안해 넉넉히 잡는다. 배경이 거의 정지 화면이면
        # 절대량으로, 계속 움직이는 화면이면 배수로 판정한다.
        works = active > max(idle * 2.0, idle + 0.02)
        if works:
            return (True, f"통하는 것 같습니다. {detail}")
        return (
            False,
            f"반응이 없어 보입니다. {detail}\n"
            "이 게임이 창 메시지를 읽지 않는 방식(DirectInput 등)일 수 있습니다. "
            "그렇다면 배경 입력은 쓸 수 없고, 창을 앞에 두고 돌려야 합니다.",
        )

    def live_input_test(self, timeout: float = 0.5) -> bool:
        """실제로 키를 하나 보내보고 입력 큐에 들어갔는지 훅으로 확인한다.

        SendInput이 성공을 반환해도 UIPI에 막히면 입력 큐에 들어가지 않는다.
        그래서 반환값이 아니라 훅 관측 여부로 판정해야 한다.
        """
        if not HOOKS.running:
            return False
        observed = threading.Event()

        def probe_listener(event) -> bool:
            if event.kind == "key" and event.vk == self.PROBE_VK:
                observed.set()
                return True  # 게임에 전달되지 않게 삼킨다
            return False

        HOOKS.add_listener(probe_listener)
        try:
            sender.key_tap(
                self.PROBE_VK, hold_ms=5, use_scancode=self.settings.use_scancode
            )
            return observed.wait(timeout)
        except OSError:
            return False
        finally:
            HOOKS.remove_listener(probe_listener)

    def diagnose(self) -> str:
        """설정 탭의 [입력 전달 테스트] 버튼용 — 사람이 읽는 진단 결과."""
        lines: list[str] = []
        ok, message = self.privilege_report()
        lines.append(("정상" if ok else "문제") + f": {message}")

        win = self.window()
        if win is not None:
            lines.append(f"대상 창: {win.title} (활성: {'예' if win.is_foreground() else '아니오'})")
            if not win.is_foreground():
                lines.append(
                    "※ 입력 전달 테스트는 게임 창이 활성 상태일 때만 정확합니다."
                )

        delivered = self.live_input_test()
        lines.append(
            "입력 전달: 성공 (키가 시스템 입력 큐에 들어갔습니다)"
            if delivered
            else "입력 전달: 실패 — 보낸 키가 시스템에 도달하지 않았습니다."
        )
        if HOOKS.hook_deaths:
            lines.append(f"※ 훅이 {HOOKS.hook_deaths}회 제거되어 자동 재설치했습니다.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 핫키 바인딩
    # ------------------------------------------------------------------
    def rebind_hotkeys(self) -> None:
        self.hotkeys.clear()
        settings = self.settings

        if settings.panic_hotkey:
            self.hotkeys.register(settings.panic_hotkey, self.panic)
        if settings.record_hotkey:
            self.hotkeys.register(settings.record_hotkey, self._hotkey_record_toggle)
        if settings.observe_hotkey:
            self.hotkeys.register(settings.observe_hotkey, self._hotkey_observe_toggle)

        for macro in self.profile.macros:
            if macro.hotkey:
                self.hotkeys.register(
                    macro.hotkey, self._make_toggle("macro", macro.name)
                )
        for path in self.profile.paths:
            if path.hotkey:
                self.hotkeys.register(path.hotkey, self._make_toggle("path", path.name))
        for repeat in self.profile.repeats:
            if repeat.hotkey:
                self.hotkeys.register(
                    repeat.hotkey, self._make_toggle("repeat", repeat.name)
                )
        for scenario in self.profile.scenarios:
            if scenario.hotkey:
                self.hotkeys.register(
                    scenario.hotkey, self._make_toggle("scenario", scenario.name)
                )
        for schedule in self.profile.schedules:
            if schedule.hotkey:
                self.hotkeys.register(
                    schedule.hotkey, self._make_toggle("schedule", schedule.name)
                )

    def _make_toggle(self, kind: str, name: str) -> Callable[[], None]:
        def _toggle() -> None:
            self.toggle(kind, name)

        return _toggle

    def _hotkey_record_toggle(self) -> None:
        if self._on_record_toggle:
            self._on_record_toggle()

    def _hotkey_observe_toggle(self) -> None:
        if self._on_observe_toggle:
            self._on_observe_toggle()

    def reserved_vks(self) -> set[int]:
        """녹화 시 무시할 키 (핫키로 쓰이는 키들)."""
        out: set[int] = set()
        candidates: Iterable[str] = [
            self.settings.panic_hotkey,
            self.settings.record_hotkey,
            self.settings.observe_hotkey,
            *(m.hotkey for m in self.profile.macros),
            *(p.hotkey for p in self.profile.paths),
            *(r.hotkey for r in self.profile.repeats),
            *(s.hotkey for s in self.profile.scenarios),
            *(s.hotkey for s in self.profile.schedules),
        ]
        for hotkey in candidates:
            if not hotkey:
                continue
            main = hotkey.split("+")[-1].strip()
            vk = vk_of(main)
            if vk is not None:
                out.add(vk)
        return out

    # ------------------------------------------------------------------
    # 조회
    # ------------------------------------------------------------------
    def find_macro(self, name: str) -> Macro | None:
        return next((m for m in self.profile.macros if m.name == name), None)

    def find_path(self, name: str) -> PathMacro | None:
        return next((p for p in self.profile.paths if p.name == name), None)

    def find_repeat(self, name: str) -> RepeatTask | None:
        return next((r for r in self.profile.repeats if r.name == name), None)

    def find_rule(self, name: str) -> PixelRule | None:
        return next((r for r in self.profile.rules if r.name == name), None)

    def find_scenario(self, name: str) -> Scenario | None:
        return next((s for s in self.profile.scenarios if s.name == name), None)

    def find_schedule(self, name: str) -> ScheduledTask | None:
        return next((s for s in self.profile.schedules if s.name == name), None)

    def find_buff(self, name: str) -> BuffItem | None:
        return next((b for b in self.profile.buffs if b.name == name), None)

    # ------------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------------
    def is_running(self, kind: str, name: str) -> bool:
        with self._lock:
            task = self._running.get((kind, name))
            return task is not None and task.alive

    def running_keys(self) -> list[TaskKey]:
        with self._lock:
            self._reap()
            return list(self._running.keys())

    def _reap(self) -> None:
        dead = [k for k, t in self._running.items() if not t.alive]
        for key in dead:
            del self._running[key]

    def toggle(self, kind: str, name: str) -> None:
        if self.is_running(kind, name):
            self.stop(kind, name)
        else:
            self.run(kind, name)

    def run(self, kind: str, name: str) -> bool:
        key = (kind, name)
        with self._lock:
            self._reap()
            if key in self._running:
                self.log(f"'{name}'은(는) 이미 실행 중입니다.")
                return False

        if self.recorder.recording:
            self.log("녹화 중에는 매크로를 실행할 수 없습니다.")
            return False

        win = self.window()
        if win is None:
            self.log(f"게임 창을 찾지 못했습니다 (패턴: {self.resolver.pattern}).")
            return False

        # 권한이 모자라면 입력이 조용히 버려진다. 실행해봐야 아무 일도 일어나지
        # 않으므로, 시작하는 시늉을 하지 말고 이유를 알려주고 멈춘다.
        privileged, message = self.privilege_report()
        if not privileged:
            self.log(f"실행 불가 — {message}")
            return False

        # 어떤 창에 입력이 갈지 매번 남긴다. 패턴이 느슨해서 엉뚱한 창이
        # 잡히는 사고를 바로 알아챌 수 있어야 한다.
        if win.title.strip() != self.resolver.pattern.strip():
            self.log(f"⚠ 대상 창: '{win.title}' (패턴과 정확히 일치하지 않음)")
        else:
            self.log(f"대상 창: '{win.title}'")

        if not self._bring_to_front(win):
            return False

        ctx = RunContext(self.settings, win, self.log)
        ctx.moves = self.profile.moves
        # 그림 조건이 감지용 아이콘을 여기서 찾는다.
        ctx.library_root = self.library_root
        # 낚시 단계가 설정을 여기서 꺼낸다.
        ctx.fishing = self.profile.fishing
        # 무엇이 어떻게 진행되는지 화면에서 볼 수 있도록 게시판을 연다.
        ctx.board = progress.REGISTRY.open(key, f"{KIND_LABELS.get(kind, kind)} · {name}")
        target = self._build_target(kind, name, ctx)
        if target is None:
            self.log(f"실행 대상을 찾지 못했습니다: {kind}/{name}")
            return False

        thread = threading.Thread(
            target=self._wrap(key, target), name=f"z9-{kind}-{name}", daemon=True
        )
        with self._lock:
            self._running[key] = RunningTask(key, ctx, thread)
        thread.start()
        self._notify()
        return True

    def _bring_to_front(self, win: GameWindow) -> bool:
        """돌리기 전에 게임 창을 앞으로 가져온다.

        창이 뒤에 있는 채로 SendInput 을 쏘면 남의 창에 들어간다. 그래서 이건
        설정에 맡기지 않고 늘 한다 — 껐다 켜는 것은 "앞으로 가져오지 못했을 때
        어떻게 할지"뿐이다. 배경 입력은 창을 건드릴 이유가 없으니 건너뛴다.
        """
        if self.settings.input_mode == INPUT_POST:
            return True
        if win.is_foreground():
            return True

        # 한 번에 안 될 수 있다. Windows 가 포그라운드 뺏기를 잠깐 막는 경우가 있어
        # 몇 번 두드려 본다.
        for _ in range(3):
            if win.activate():
                return True
        if self.settings.focus_policy == FOCUS_STOP:
            self.log(
                "게임 창을 앞으로 가져오지 못해 실행하지 않았습니다. 창을 직접 "
                "클릭한 뒤 다시 시도하세요."
            )
            return False
        self.log(
            "게임 창을 앞으로 가져오지 못했습니다. 일단 시작하고 계속 시도합니다."
        )
        return True

    def _build_target(
        self, kind: str, name: str, ctx: RunContext
    ) -> Callable[[], None] | None:
        if kind == "macro":
            macro = self.find_macro(name)
            return (lambda: play_macro(macro, ctx)) if macro else None
        if kind == "path":
            path = self.find_path(name)
            return (lambda: play_path(path, ctx)) if path else None
        if kind == "move":
            move = self.find_move(name)
            if move is None or not move.events:
                return None
            # 움직임은 방향키 시퀀스일 뿐이라 매크로 재생기로 그대로 돌린다.
            as_macro = Macro(name=move.name, events=list(move.events), repeat=1)
            return lambda: play_macro(as_macro, ctx)
        if kind == "repeat":
            repeat = self.find_repeat(name)
            return (lambda: tasks.run_repeat(repeat, ctx)) if repeat else None
        if kind == "rule":
            rule = self.find_rule(name)
            if rule is None:
                return None
            return lambda: tasks.run_pixel_rule(
                rule, ctx, self.find_macro, self.find_path
            )
        if kind == "scenario":
            scenario = self.find_scenario(name)
            if scenario is None:
                return None
            return lambda: play_scenario(
                scenario, ctx, self.find_macro, self.find_rule,
                self.find_buff, self.library_root,
                self.find_repeat, self.find_path,
                self.find_schedule, self.find_scenario,
            )
        if kind == "fishing":
            setup = self.profile.fishing
            # 배운 lead 는 설정 안에 쌓인다. 끝나면 저장해 둬야 다음에 이어진다.
            def _fish() -> None:
                from . import fishtask

                try:
                    fishtask.run_fishing(setup, ctx, find_macro=self.find_macro,
                                         find_rule=self.find_rule)
                finally:
                    self.save()

            return _fish

        if kind == "lumber":
            setup = self.profile.lumber

            # 걸으며 배운 화면↔미니맵 비율이 설정에 쌓인다. 끝나면 저장해 둔다.
            def _cut() -> None:
                from . import lumber

                try:
                    lumber.run_lumber(setup, ctx)
                finally:
                    self.save()

            return _cut

        if kind == "schedule":
            schedule = self.find_schedule(name)
            if schedule is None:
                return None
            return lambda: tasks.run_schedule(
                schedule, ctx, self.find_macro, self.find_path,
                self.find_scenario, self.find_rule,
                self.find_buff, self.library_root,
                self.find_repeat, self.find_schedule,
            )
        return None

    def _wrap(self, key: TaskKey, target: Callable[[], None]) -> Callable[[], None]:
        def _run() -> None:
            note = "끝남"
            try:
                # 재생 함수들은 "끝까지 갔는가"를 돌려준다. False면 중간에
                # 끊긴 것이므로 끝났다고 적으면 안 된다 — 왜 멈췄는지 찾을 때
                # 이 한 글자가 헷갈림의 시작이 된다.
                if target() is False:
                    note = "중단됨"
            except Exception as exc:  # noqa: BLE001
                from .player import Aborted

                if isinstance(exc, Aborted):
                    # [정지]를 누른 것이다. 오류가 아니다 — "오류: Aborted()"로 적으면
                    # 무엇이 고장 났는지 찾아 헤매게 된다.
                    note = "정지됨"
                else:
                    note = f"오류: {exc!r}"
                    self.log(f"'{key[1]}' 실행 중 오류: {exc!r}")
            finally:
                with self._lock:
                    task = self._running.pop(key, None)
                if task is not None and task.ctx.stopped and note == "끝남":
                    note = "정지됨"
                progress.REGISTRY.close(key, note)
                self._notify()

        return _run

    def stop(self, kind: str, name: str) -> None:
        with self._lock:
            task = self._running.get((kind, name))
        if task is not None:
            task.ctx.stop()
            self.log(f"'{name}' 정지 요청.")

    def stop_all(self, reason: str = "") -> None:
        with self._lock:
            running = list(self._running.values())
        for task in running:
            task.ctx.stop()
        for task in running:
            task.thread.join(timeout=1.0)
        with self._lock:
            self._reap()
        if running:
            self.log(f"실행 중이던 작업 {len(running)}개 정지. {reason}".strip())
        self._notify()

    def panic(self) -> None:
        """비상 정지: 모든 작업 중단 + 눌린 키 강제 해제."""
        self.stop_all(reason="[비상 정지]")
        self.recorder.cancel()
        if self.observer.running:
            self.observer.stop()
        try:
            released = sender.release_all(use_scancode=self.settings.use_scancode)
            self.log(
                f"비상 정지 완료. 눌려 있던 키 {len(released)}개 해제."
                if released
                else "비상 정지 완료."
            )
        except OSError as exc:
            self.log(f"키 해제 실패: {exc}")

    # ------------------------------------------------------------------
    # 녹화
    # ------------------------------------------------------------------
    def start_recording(self) -> bool:
        if self.recorder.recording:
            return False
        self.stop_all(reason="녹화 시작")
        win = self.window()
        if win is None:
            self.log(
                "⚠ 게임 창을 찾지 못했습니다. 화면 절대좌표로 녹화되므로 창을 "
                "옮기면 마우스가 어긋납니다. [설정] 탭에서 대상 창을 먼저 지정하세요."
            )
        self.recorder.start(
            win,
            record_move=self.settings.record_mouse_move,
            move_sample_ms=self.settings.move_sample_ms,
            ignore_vks=self.reserved_vks(),
        )
        self.log("녹화 시작.")
        self._notify()
        return True

    def stop_recording(self, name: str) -> Macro | None:
        if not self.recorder.recording:
            return None
        macro = self.recorder.stop(name=name)
        macro.events = balance_keys(macro.events)
        if not macro.events:
            self.log("녹화된 이벤트가 없습니다.")
            self._notify()
            return None
        macro.name = self._unique_macro_name(name)
        self.profile.macros.append(macro)
        basis = "화면 절대좌표" if macro.absolute else "창 기준 좌표"
        self.log(
            f"'{macro.name}' 녹화 완료 — 이벤트 {len(macro.events)}개, "
            f"{macro.duration:.1f}초, {basis}."
        )
        if macro.absolute and has_pointer_events(macro.events):
            self.log(
                "⚠ 마우스 입력이 화면 절대좌표로 저장되었습니다. 창을 옮기면 "
                "어긋납니다 — [창 기준 좌표로 변환]을 쓰거나 다시 녹화하세요."
            )
        self._notify()
        return macro

    # ------------------------------------------------------------------
    # 대기 중 움직임
    # ------------------------------------------------------------------
    def find_move(self, name: str) -> Movement | None:
        return next((m for m in self.profile.moves if m.name == name), None)

    def run_movement(self, index: int) -> bool:
        """움직임 하나를 지금 한 번 재생해 본다 (어떻게 움직이는지 확인용)."""
        moves = self.ensure_moves()
        if not (0 <= index < len(moves)) or not moves[index].events:
            return False
        return self.run("move", moves[index].name)

    def ensure_moves(self) -> list[Movement]:
        """슬롯을 정해진 개수만큼 채워 둔다.

        빈 칸도 자리를 차지하고 있어야 "몇 번 슬롯"이라는 말이 통한다.
        """
        moves = self.profile.moves
        while len(moves) < movelib.SLOT_COUNT:
            moves.append(Movement(name=f"움직임 {len(moves) + 1}", events=[]))
        del moves[movelib.SLOT_COUNT:]
        return moves

    def start_move_recording(self, index: int) -> bool:
        """움직임 하나를 녹화하기 시작한다. 방향키만, 최대 3초."""
        moves = self.ensure_moves()
        if not (0 <= index < len(moves)):
            return False
        if self.recorder.recording:
            self.log("이미 녹화 중입니다.")
            return False
        if self.observer.running:
            self.log("관찰 중에는 녹화할 수 없습니다.")
            return False

        win = self.window()
        # 마우스는 담지 않는다. 대기 중에 클릭이 나가면 매크로 흐름이 깨진다.
        self.stop_all(reason="움직임 녹화 시작")
        self.recorder.start(win, record_move=False, ignore_vks=self.reserved_vks())
        self._move_slot = index
        self.log(
            f"[{moves[index].name}] 녹화 시작 — 방향키만, "
            f"{movelib.MAX_SECONDS:.0f}초까지."
        )
        self._notify()
        return True

    def stop_move_recording(self) -> Movement | None:
        """녹화를 끝내고 방향키만 남겨 3초로 자른다."""
        index = getattr(self, "_move_slot", None)
        if index is None or not self.recorder.recording:
            return None
        self._move_slot = None

        macro = self.recorder.stop(name="움직임")
        moves = self.ensure_moves()
        move = moves[index]

        events = movelib.filter_events(balance_keys(macro.events))
        events = movelib.truncate(events, movelib.MAX_SECONDS)
        events = balance_keys(events)
        move.events = events

        if not events:
            self.log(
                f"[{move.name}] 방향키 입력이 없어 비워 두었습니다. "
                "녹화 중에는 방향키만 기록됩니다."
            )
        else:
            self.log(
                f"[{move.name}] 녹화 완료 — 이벤트 {len(events)}개, "
                f"{move.duration:.1f}초."
            )
        self._notify()
        return move

    @property
    def recording_move(self) -> int | None:
        """지금 녹화 중인 움직임 슬롯 번호. 아니면 None."""
        return getattr(self, "_move_slot", None) if self.recorder.recording else None

    # ------------------------------------------------------------------
    # 관찰 모드
    # ------------------------------------------------------------------
    def start_observing(self) -> bool:
        if self.observer.running:
            return False
        if self.recorder.recording:
            self.log("녹화 중에는 관찰을 시작할 수 없습니다.")
            return False

        win = self.window()
        if win is None:
            self.log(f"게임 창을 찾지 못했습니다 (패턴: {self.resolver.pattern}).")
            return False

        # 권한이 낮으면 캡처는 되지만 게임으로 가는 키 입력이 훅에 잡히지 않는다.
        # 화면만 있고 입력이 없으면 분석이 불가능하므로 미리 막는다.
        privileged, message = self.privilege_report()
        if not privileged:
            self.log(f"관찰 불가 — {message}")
            return False

        self.stop_all(reason="관찰 시작")
        settings = self.settings
        started = self.observer.start(
            win,
            step=max(1, settings.observe_step),
            interval_ms=max(10, settings.observe_interval_ms),
            max_seconds=max(5, settings.observe_seconds),
        )
        if started:
            self.log(
                f"관찰 시작 — 게임 창으로 전환해 평소처럼 플레이하세요. "
                f"중지: {settings.observe_hotkey or '(핫키 없음)'}"
            )
            self._notify()
        return started

    def stop_observing(self):
        if not self.observer.running and self.observer.observation is None:
            return None
        observation = self.observer.stop()
        self._notify()
        return observation

    def _unique_macro_name(self, name: str) -> str:
        existing = {m.name for m in self.profile.macros}
        if name not in existing:
            return name
        i = 2
        while f"{name} ({i})" in existing:
            i += 1
        return f"{name} ({i})"
