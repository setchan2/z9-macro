"""메인 창."""

from __future__ import annotations

import re
import threading
import tkinter as tk
from collections import deque
from tkinter import messagebox, ttk

from .. import elevation
from ..engine import Engine
from ..hooks import HOOKS
from ..win32 import enable_dpi_awareness
from . import decor, fonts, theme
from .status import StatusWindow
from .tab_achievements import AchievementTab
from .tab_craft import CraftTab
from .tab_fishing import FishingTab
from .tab_help import HelpTab
from .tab_library import LibraryTab
from .tab_lumber import LumberTab
from .tab_macros import MacroTab
from .tab_scenario import ScenarioTab
from .tab_settings import SettingsTab

POLL_MS = 150

# 로그 칸이 적어도 이만큼(배율 1.0 기준 px)은 남게 한다. 예전에는 70px까지 눌려
# 한 줄만 보였다 — 무엇이 나갔는지 보려고 여는 칸인데 한 줄로는 쓸 수가 없다.
LOG_MIN_PX = 150

# [로그 크게 보기] 창에 담아 둘 줄 수.
LOG_KEEP = 3000

# 배율 1.0 기준값. 실제 창 크기는 화면 크기와 UI 배율에 맞춰 정한다.
BASE_MIN_W, BASE_MIN_H = 960, 720
BASE_MAX_W, BASE_MAX_H = 1600, 1060
# 화면을 꽉 채우지는 않는다. 게임 창을 옆에 두고 쓰는 도구라 여백이 있어야 한다.
SCREEN_FILL_W, SCREEN_FILL_H = 0.86, 0.90

_GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-]\d+)([+-]\d+)$")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Z9★ 온라인 매크로")

        # 스타일보다 엔진이 먼저다 — 글꼴 배율을 저장된 설정에서 읽어야 한다.
        self.engine = Engine()
        settings = self.engine.settings
        # 테마와 글꼴을 먼저 고른다. 스타일을 입힐 때 그 팔레트와 글꼴을 쓴다.
        if settings.ui_theme not in theme.THEMES:
            settings.ui_theme = theme.DEFAULT_THEME  # 손으로 고친 파일의 모르는 이름
        theme.use(settings.ui_theme, settings.ui_colors)
        family = fonts.resolve(self, settings.ui_font)
        if family is not None:
            settings.ui_font = family
            theme.set_family(family)
        else:
            # 글꼴 폴더를 지웠거나 옮겼다. 조용히 엉뚱한 글꼴로 뜨지 않게 알린다.
            self.after(500, lambda: self.engine.log(
                f"글꼴 '{settings.ui_font}'을(를) 찾지 못해 맑은 고딕으로 엽니다 "
                "(fonts 폴더를 확인하세요)"))
            theme.set_family("")
        self.palette = theme.apply(self, settings.ui_scale)
        self._apply_geometry()
        # 같은 프로그램을 두 개 띄웠을 때 서로를 대상으로 잡지 않도록,
        # 자기 창 제목을 자동 탐색에서 제외한다.
        self.engine.resolver.exclude_titles.add(self.title())
        # 워커 스레드가 세운 플래그를 GUI 스레드의 폴링에서 읽는다.
        # tkinter는 스레드 안전하지 않으므로 콜백에서 위젯을 직접 건드리지 않는다.
        self._state_dirty = threading.Event()

        self._build()

        # 꾸미기 — 배경 이미지와 창 아이콘. 못 읽어도 창은 떠야 하므로 로그만 남긴다.
        self.backdrop = decor.Backdrop(self, self._set_margin)
        for message in (
            self.backdrop.show(settings.ui_background, settings.ui_bg_margin),
            decor.apply_icon(self, settings.ui_icon),
        ):
            if message:
                self.engine.log(message)

        self.engine.set_callbacks(
            on_record_toggle=self.macro_tab.request_record_toggle,
            on_observe_toggle=self.scenario_tab.request_observe_toggle,
            on_state_change=self._state_dirty.set,
        )

        HOOKS.on_listener_error = lambda msg: self.engine.log(f"훅 리스너 오류: {msg}")
        HOOKS.on_hook_recovered = lambda: self.engine.log(
            "전역 훅이 시스템에 의해 제거되어 자동으로 다시 설치했습니다."
        )

        try:
            self.engine.start()
        except RuntimeError as exc:
            messagebox.showerror("훅 설치 실패", str(exc))
            self._append_log(f"[치명적] {exc}")

        # 창이 먼저 그려진 뒤에 경고를 띄운다 (모달이라 __init__을 막는다).
        self.after(300, self._report_privilege)

        self.status_window: StatusWindow | None = None

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------
    # 창 크기 · 분할선
    # ------------------------------------------------------------------
    def _min_size(self) -> tuple[int, int]:
        """최소 창 크기. 배율을 키워도 화면보다 커지지는 않게 자른다.

        자르지 않으면 1920x1080에서 배율 150%를 골랐을 때 최소 높이가 화면
        높이를 넘어, 창을 줄일 수도 옮길 수도 없게 된다.
        """
        scale = theme.SCALE
        width = min(int(BASE_MIN_W * scale), int(self.winfo_screenwidth() * 0.85))
        height = min(int(BASE_MIN_H * scale), int(self.winfo_screenheight() * 0.80))
        return width, height

    def _default_geometry(self) -> str:
        """화면 크기와 UI 배율에 맞춰 창 크기를 정하고 가운데에 놓는다.

        예전에는 1100x760 고정이었다. 1920x1080에서는 화면의 절반쯤밖에 안 써서
        이벤트 목록처럼 늘어나야 할 곳이 좁게 남았다.
        """
        scale = theme.SCALE
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        min_w, min_h = self._min_size()
        width = min(int(BASE_MAX_W * scale), int(screen_w * SCREEN_FILL_W))
        height = min(int(BASE_MAX_H * scale), int(screen_h * SCREEN_FILL_H))
        width = max(width, min_w)
        height = max(height, min_h)
        x = max((screen_w - width) // 2, 0)
        # 세로는 정가운데보다 조금 위가 자연스럽다.
        y = max((screen_h - height) // 3, 0)
        return f"{width}x{height}+{x}+{y}"

    def _usable_geometry(self, saved: str) -> str | None:
        """저장해 둔 창 크기·위치를 쓸 수 있는지 본다.

        모니터를 바꾸거나 떼어 낸 뒤라면 저장된 자리가 화면 밖일 수 있다.
        그대로 되살리면 창이 안 보이는 채로 뜨므로, 그럴 때는 버린다.
        """
        match = _GEOMETRY_RE.match((saved or "").strip())
        if match is None:
            return None
        width, height = int(match.group(1)), int(match.group(2))
        x, y = int(match.group(3)), int(match.group(4))
        min_w, min_h = self._min_size()
        if width < min_w or height < min_h:
            return None
        if width > self.winfo_screenwidth() or height > self.winfo_screenheight():
            return None
        # 제목 표시줄이 화면 위로 넘어가면 창을 다시 잡을 방법이 없다.
        # 가로는 왼쪽에 붙은 보조 모니터가 있을 수 있어 넉넉히 봐준다.
        if y < -20 or x < -(width - 160) or x > self.winfo_screenwidth() + width:
            return None
        return f"{width}x{height}+{x}+{y}"

    def _apply_geometry(self) -> None:
        self.minsize(*self._min_size())
        saved = self._usable_geometry(self.engine.settings.window_geometry)
        self.geometry(saved or self._default_geometry())

    def _place_sash(self, _event: object = None) -> None:
        """탭 영역과 로그 사이 분할선을 창이 그려진 뒤 한 번 놓는다."""
        if self._sash_placed:
            return
        height = self.split.winfo_height()
        # 창이 자리를 잡기 전의 어중간한 크기에 맞춰 두면 분할선이 엉뚱하게 박힌다.
        if height < theme.px(320):
            return
        self._sash_placed = True
        # 기본은 로그에 여섯 줄쯤. 다만 창이 낮을 때까지 그만큼 떼어 주면
        # 정작 편집 화면이 눌리므로, 창 높이의 1/5을 넘기지 않는다.
        log_share = min(theme.px(190), int(height * 0.2))
        want = self.engine.settings.sash_main or (height - log_share)
        low = theme.px(200)
        high = max(low, height - theme.px(LOG_MIN_PX))
        try:
            self.split.sashpos(0, int(max(low, min(want, high))))
        except tk.TclError:
            pass

    def grow_to_fit(self) -> None:
        """배율을 키운 직후, 창이 새 최소 크기보다 작으면 그만큼만 늘린다.

        사용자가 맞춰 둔 크기를 통째로 갈아엎지는 않는다. 모자란 쪽만 채운다.
        """
        min_w, min_h = self._min_size()
        self.minsize(min_w, min_h)
        self.update_idletasks()
        width = max(self.winfo_width(), min_w)
        height = max(self.winfo_height(), min_h)
        width = min(width, int(self.winfo_screenwidth() * SCREEN_FILL_W))
        height = min(height, int(self.winfo_screenheight() * SCREEN_FILL_H))
        if (width, height) != (self.winfo_width(), self.winfo_height()):
            self.geometry(f"{width}x{height}")

    def reset_layout(self) -> None:
        """[창 크기·분할 초기화] — 저장된 자리를 버리고 기본값으로 되돌린다."""
        settings = self.engine.settings
        settings.window_geometry = ""
        settings.sash_main = 0
        settings.sash_list = 0
        settings.sash_events = 0
        self.geometry(self._default_geometry())
        self.update_idletasks()
        self._sash_placed = False
        self._place_sash()
        for tab in (*self.editor_tabs, self.achievement_tab, self.help_tab):
            tab.reset_sash()

    def _store_layout(self) -> None:
        """창 크기·분할선 자리를 설정에 담는다. 저장은 부르는 쪽에서 한다."""
        settings = self.engine.settings
        try:
            if self.state() == "normal":  # 최대화·최소화 상태는 담지 않는다
                settings.window_geometry = self.winfo_geometry()
            settings.sash_main = int(self.split.sashpos(0))
        except tk.TclError:
            pass
        # 두 편집 탭이 같은 값을 쓴다. 분할선 자리는 곧 왼쪽 목록의 너비라서,
        # 어느 탭에서 맞춰 놓든 나머지도 같은 너비인 편이 덜 어수선하다.
        for tab in self.editor_tabs:
            value = tab.sash_value()
            if value > 0:
                settings.sash_list = value
        value = self.macro_tab.event_sash_value()
        if value > 0:
            settings.sash_events = value

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self._log_lines: deque[str] = deque(maxlen=LOG_KEEP)
        self.log_window: LogWindow | None = None
        # -- 상단 상태 바 ------------------------------------------------
        top = ttk.Frame(self, padding=(12, 10, 12, 6))
        top.pack(fill="x")
        self.top = top

        self.admin_var = tk.StringVar(value="")
        self.admin_label = ttk.Label(top, textvariable=self.admin_var)
        self.admin_label.pack(side="left", padx=(0, 14))

        ttk.Label(top, text="대상 창", style="Muted.TLabel").pack(side="left")
        self.status_var = tk.StringVar(value="확인 중…")
        ttk.Label(top, textvariable=self.status_var, style="Accent.TLabel").pack(
            side="left", padx=(8, 12)
        )

        # 창에서 유일하게 진한 색을 쓰는 버튼. 급할 때 눈에 바로 들어와야 한다.
        ttk.Button(
            top, text="■ 비상 정지", style="Danger.TButton", command=self.engine.panic
        ).pack(side="right")

        self.panic_hint = ttk.Label(top, text="", style="Muted.TLabel")
        self.panic_hint.pack(side="right", padx=12)

        ttk.Button(
            top, text="실행 상태", style="Small.TButton", command=self.open_status
        ).pack(side="right")
        ttk.Button(
            top, text="로그 크게 보기", style="Small.TButton", command=self.open_log
        ).pack(side="right", padx=(0, 6))

        # -- 탭 + 로그 ------------------------------------------------------
        # 로그가 8줄로 못 박혀 있으면, 창을 키워도 늘어나는 몫이 전부 탭으로 가고
        # 반대로 로그를 길게 보고 싶을 때는 방법이 없었다. 분할선으로 바꿔서
        # 이벤트 목록과 로그 사이 비율을 직접 정하게 한다.
        self.split = ttk.PanedWindow(self, orient="vertical")
        self.split.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._sash_placed = False
        self.split.bind("<Configure>", self._place_sash, add="+")
        # 분할선을 끌어 로그를 한 줄로 눌러 버리지 못하게, 놓는 순간 되돌린다.
        self.split.bind("<ButtonRelease-1>", self._keep_log_room, add="+")

        notebook = ttk.Notebook(self.split)
        self.notebook = notebook

        # 실제로 돌리는 것은 시나리오뿐이라, 상시 탭은 넷만 둔다.
        # 연타 · 경로 · 조건 · 버프 · 예약 · 관찰 · 프리셋은 시나리오 편집기의
        # [설정 열기]에서 같은 화면을 창으로 띄운다.
        self.scenario_tab = ScenarioTab(notebook, self.engine)
        self.macro_tab = MacroTab(notebook, self.engine)
        self.library_tab = LibraryTab(notebook, self.engine, self._refresh_all)
        self.settings_tab = SettingsTab(notebook, self.engine)
        self.achievement_tab = AchievementTab(notebook, self.engine)
        self.fishing_tab = FishingTab(notebook, self.engine)
        self.lumber_tab = LumberTab(notebook, self.engine)
        self.craft_tab = CraftTab(notebook, self.engine)
        self.help_tab = HelpTab(notebook, self.engine)

        notebook.add(self.scenario_tab, text="  시나리오 편집기  ")
        notebook.add(self.macro_tab, text="  녹화 · 재생  ")
        notebook.add(self.library_tab, text="  보관함  ")
        notebook.add(self.settings_tab, text="  설정  ")
        notebook.add(self.achievement_tab, text="  업적  ")
        notebook.add(self.fishing_tab, text="  낚시  ")
        notebook.add(self.lumber_tab, text="  벌목  ")
        notebook.add(self.craft_tab, text="  제작  ")
        notebook.add(self.help_tab, text="  도움말  ")
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self.editor_tabs = (self.scenario_tab, self.macro_tab)

        # -- 로그 ----------------------------------------------------------
        log_frame = ttk.LabelFrame(self.split, text="로그", padding=(6, 4))

        self.log_text = tk.Text(log_frame, height=4, wrap="none", state="disabled")
        theme.style_text(self.log_text, mono=True)
        self.log_text.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        bar.pack(side="left", fill="y")
        self.log_text.configure(yscrollcommand=bar.set)

        # 늘어난 자리는 탭이 가진다. 로그는 필요할 때 끌어서 키운다.
        self.split.add(notebook, weight=4)
        self.split.add(log_frame, weight=1)

    def _set_margin(self, margin: int | None) -> None:
        """배경 그림이 보일 테두리. None이면 그림이 없는 원래 배치로 되돌린다."""
        if margin is None:
            self.top.pack_configure(padx=0, pady=0)
            self.split.pack_configure(padx=12, pady=(0, 12))
            return
        self.top.pack_configure(padx=margin, pady=(margin, 0))
        self.split.pack_configure(padx=max(margin, 1), pady=(0, max(margin, 1)))

    # ------------------------------------------------------------------
    def _report_privilege(self) -> None:
        admin = elevation.is_elevated()
        self.admin_var.set("● 관리자 권한" if admin else "● 일반 권한")
        self.admin_label.configure(style="Ok.TLabel" if admin else "Danger.TLabel")

        ok, message = self.engine.privilege_report()
        self.engine.log(("권한 확인: " if ok else "권한 경고: ") + message)
        if not ok:
            messagebox.showwarning(
                "관리자 권한이 필요합니다",
                message + "\n\n[설정] 탭에서 관리자 권한으로 다시 실행할 수 있습니다.",
                parent=self,
            )

    def _refresh_all(self) -> None:
        """프리셋 생성 등으로 프로필이 바뀌었을 때 모든 목록을 다시 그린다."""
        for tab in self.editor_tabs:
            # 바깥에서 바뀐 내용이므로 폼까지 다시 채운다. 예약이나 매크로를
            # 지우면 그것을 가리키던 시나리오 단계도 곧바로 그렇게 보여야 한다.
            tab.refresh(reload_form=True)
        self.library_tab._refresh_items()
        self.achievement_tab.refresh()
        self.fishing_tab.refresh()
        self.lumber_tab.refresh()
        self.craft_tab.refresh()
        self.scenario_tab.refresh_sources()
        self.scenario_tab.refresh_tools()

    def _on_tab_change(self, _event: object = None) -> None:
        # 탭을 떠날 때 편집 중인 값이 날아가지 않도록 전부 커밋한다.
        for tab in self.editor_tabs:
            tab.commit()
        self.library_tab._refresh_items()
        # 게임을 나중에 켰을 수도 있으니 설정 탭을 열 때마다 다시 본다.
        self.settings_tab.refresh_privilege()

    def open_status(self) -> "StatusWindow":
        if self.status_window is None or not self.status_window.winfo_exists():
            self.status_window = StatusWindow(self)
        self.status_window.show()
        return self.status_window

    def _auto_show_status(self) -> None:
        """무언가 돌고 있으면 상태 창이 떠 있게 한다.

        닫혀 있으면 다시 띄운다. 무엇이 언제 나가는지 모르는 채로 매크로가
        도는 편보다, 창 하나가 계속 떠 있는 편이 낫다. 실행이 끝나면 더는
        되살리지 않으므로 그때 닫으면 닫힌 채로 있는다.
        """
        window = self.status_window
        if window is None or not window.winfo_exists():
            self.status_window = StatusWindow(self)
            self.status_window.show()
            return
        if window.state() == "withdrawn":
            window.show()

    def _keep_log_room(self, _event: object = None) -> None:
        height = self.split.winfo_height()
        limit = height - theme.px(LOG_MIN_PX)
        try:
            if limit > theme.px(200) and self.split.sashpos(0) > limit:
                self.split.sashpos(0, limit)
        except tk.TclError:
            pass

    def open_log(self) -> "LogWindow":
        """로그를 큰 창으로 따로 본다. 닫아도 쌓인 줄은 남는다."""
        window = getattr(self, "log_window", None)
        if window is None or not window.winfo_exists():
            window = self.log_window = LogWindow(self, list(self._log_lines))
        window.deiconify()
        window.lift()
        return window

    def _append_log(self, line: str) -> None:
        self._log_lines.append(line)
        window = getattr(self, "log_window", None)
        if window is not None and window.winfo_exists():
            window.add(line)
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        # 로그가 무한히 쌓이지 않도록 상한을 둔다
        if int(self.log_text.index("end-1c").split(".")[0]) > 500:
            self.log_text.delete("1.0", "200.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll(self) -> None:
        for line in self.engine.drain_logs():
            self._append_log(line)

        self.status_var.set(self.engine.window_status())

        recording = self.engine.recorder.recording
        running = self.engine.running_keys()
        if self.engine.observer.running:
            hint = f"● 관찰 중 (중지: {self.engine.settings.observe_hotkey})"
        elif recording:
            hint = f"● 녹화 중 — 이벤트 {self.engine.recorder.count}개"
        elif running:
            hint = "실행 중: " + ", ".join(name for _kind, name in running)
        else:
            panic_key = self.engine.settings.panic_hotkey
            hint = f"대기 중 (비상 정지: {panic_key})" if panic_key else "대기 중"
        self.panic_hint.configure(text=hint)

        # 녹화나 관찰이 함께 돌고 있어도 실행 중이면 상태 창은 떠 있어야 한다.
        if running:
            self._auto_show_status()

        # 녹화·재생 탭이나 설정 창에서 매크로를 고치면 시나리오 흐름에 적힌
        # 이벤트 수·길이도 같이 달라져야 한다. 값이 실제로 바뀌었을 때만 다시
        # 그리므로 평소에는 비교 한 번으로 끝난다.
        self.scenario_tab.sync_flow()

        if self._state_dirty.is_set():
            self._state_dirty.clear()
            for tab in self.editor_tabs:
                tab.on_state_change()

        self.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        for tab in self.editor_tabs:
            tab.commit()
        self._store_layout()
        self.scenario_tab.close_tools()
        if self.status_window is not None and self.status_window.winfo_exists():
            self.status_window.destroy()
        try:
            self.engine.save()
        except OSError as exc:
            messagebox.showwarning("저장 실패", f"프로필을 저장하지 못했습니다:\n{exc}")
        self.engine.shutdown()
        self.destroy()


class LogWindow(tk.Toplevel):
    """로그를 크게 보는 창. 메인 창의 로그 칸은 좁아 몇 줄밖에 안 보인다.

    메인 창과 같은 줄을 받는다. 스크롤을 올려 지난 줄을 읽는 동안에는 새 줄이 와도
    끌려 내려가지 않게 [새 줄 따라가기]를 끌 수 있다.
    """

    def __init__(self, master: tk.Misc, lines: list[str]) -> None:
        super().__init__(master)
        self.title("로그")
        self.geometry(theme.scale_geometry("980x620", self))
        self.minsize(theme.px(480), theme.px(300))
        self.configure(background=theme.PALETTE["bg"])
        self.protocol("WM_DELETE_WINDOW", self.withdraw)

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.text = tk.Text(frame, wrap="none", state="disabled")
        theme.style_text(self.text, mono=True)
        self.text.grid(row=0, column=0, sticky="nsew")
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        ybar.grid(row=0, column=1, sticky="ns")
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.text.xview)
        xbar.grid(row=1, column=0, sticky="ew")
        self.text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)

        foot = ttk.Frame(frame)
        foot.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self.follow_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(foot, text="새 줄 따라가기",
                        variable=self.follow_var).pack(side="left")
        ttk.Button(foot, text="화면 비우기", style="Small.TButton",
                   command=self.clear).pack(side="left", padx=(12, 0))
        ttk.Button(foot, text="닫기", command=self.withdraw).pack(side="right")

        self.text.configure(state="normal")
        self.text.insert("end", "".join(line + "\n" for line in lines))
        self.text.configure(state="disabled")
        self.text.see("end")

    def add(self, line: str) -> None:
        self.text.configure(state="normal")
        self.text.insert("end", line + "\n")
        if int(self.text.index("end-1c").split(".")[0]) > LOG_KEEP:
            self.text.delete("1.0", f"{LOG_KEEP // 4}.0")
        self.text.configure(state="disabled")
        if self.follow_var.get():
            self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


def main() -> None:
    mode = enable_dpi_awareness()
    # exe 하나만 옮겨 와도 되게, 담아 온 설정·라이브러리를 **없을 때만** 풀어 놓는다.
    # 엔진이 설정을 읽기 전에 해야 한다.
    from .. import storage

    seeded = storage.seed_from_bundle()
    # 딸린 글꼴은 창을 만들기 전에 올린다. Tk가 글꼴 목록을 볼 때 이미 있어야 한다.
    loaded = fonts.load_bundled()
    app = App()
    if seeded:
        app.engine.log("처음 실행 — exe에 담아 온 것을 옆에 풀었습니다: "
                       + ", ".join(seeded))
    if loaded:
        app.engine.log(f"딸린 글꼴 {loaded}개를 올렸습니다 ({fonts.FONT_DIR})")
    app.engine.log(f"DPI 인식 모드: {mode}")
    app.mainloop()
