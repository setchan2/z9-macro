"""탭 5 — 설정 (대상 창, 안전장치, 전역 핫키)."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from .. import elevation
from ..engine import Engine
from ..keys import KEY_CHOICES
from ..model import (
    FOCUS_IGNORE,
    FOCUS_REFOCUS,
    FOCUS_STOP,
    INPUT_POST,
    INPUT_SEND,
)
from . import decor, fonts, theme
from .widgets import HotkeyField, ScrollFrame, get_int, int_entry

# 화면 배율 — 글씨 크기와 목록 행 높이가 함께 커진다.
SCALE_LABELS = {
    1.0: "100 % (기본)",
    1.1: "110 %",
    1.25: "125 %",
    1.5: "150 %",
    1.75: "175 %",
    2.0: "200 %",
}
SCALE_BY_LABEL = {v: k for k, v in SCALE_LABELS.items()}


def _scale_label(value: float) -> str:
    """저장된 배율에 가장 가까운 항목을 고른다 (손으로 고친 값도 받아 준다)."""
    nearest = min(SCALE_LABELS, key=lambda v: abs(v - theme.clamp_scale(value)))
    return SCALE_LABELS[nearest]

FOCUS_LABELS = {
    FOCUS_REFOCUS: "다시 앞으로 가져오고 계속",
    FOCUS_STOP: "중단한다",
    FOCUS_IGNORE: "무시하고 계속 보낸다",
}
FOCUS_BY_LABEL = {v: k for k, v in FOCUS_LABELS.items()}
FOCUS_HINTS = {
    FOCUS_REFOCUS: "실수로 다른 창을 눌러도 매크로가 끊기지 않습니다. 게임 창을 "
    "다시 앞으로 끌어와 이어서 진행합니다. 다만 그동안은 다른 일을 하기 어렵습니다.",
    FOCUS_STOP: "예전 동작입니다. 안전하지만, 창을 한 번 잘못 클릭하면 그 자리에서 멈춥니다.",
    FOCUS_IGNORE: "SendInput은 항상 맨 앞 창으로 갑니다. 게임이 뒤에 있으면 "
    "다른 프로그램에 키가 들어갑니다 — 아래 [배경 입력]을 켰을 때만 안전합니다.",
}

MODE_LABELS = {
    INPUT_SEND: "일반 (SendInput) — 게임이 맨 앞에 있어야 함",
    INPUT_POST: "배경 입력 (창 메시지) — 뒤에 있어도 전달 시도",
}
MODE_BY_LABEL = {v: k for k, v in MODE_LABELS.items()}
MODE_HINTS = {
    INPUT_SEND: "실제 키보드·마우스를 흉내 냅니다. 거의 모든 게임에서 통하지만 "
    "게임 창이 반드시 맨 앞에 있어야 하고, 도는 동안 컴퓨터를 함께 쓸 수 없습니다.",
    INPUT_POST: "게임 창에 메시지를 직접 넣습니다. 창이 뒤에 있거나 최소화돼 있어도 "
    "되고, 그동안 마우스·키보드를 자유롭게 쓸 수 있습니다. 다만 게임이 이 방식을 "
    "받아들이지 않으면(DirectInput 등) 아무 일도 일어나지 않습니다 — 반드시 아래 "
    "[배경 입력 시험]으로 확인하세요. 또 화면을 읽는 기능(조건 감시·버프 아이콘 "
    "찾기)은 창이 최소화돼 있으면 쓸 수 없습니다.",
}


class SettingsTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine: Engine) -> None:
        super().__init__(parent, padding=12)
        self.engine = engine
        settings = engine.settings

        self.pattern_var = tk.StringVar(value=settings.window_pattern)
        self.activate_var = tk.BooleanVar(value=settings.activate_before_run)
        self.foreground_var = tk.BooleanVar(value=settings.require_foreground)
        self.move_var = tk.BooleanVar(value=settings.record_mouse_move)
        self.sample_var = tk.StringVar(value=str(settings.move_sample_ms))
        self.scancode_var = tk.BooleanVar(value=settings.use_scancode)
        self.release_var = tk.BooleanVar(value=settings.release_keys_on_stop)
        self.verbose_var = tk.BooleanVar(value=settings.verbose_log)
        self.focus_var = tk.StringVar(value=FOCUS_LABELS.get(settings.focus_policy, ""))
        self.mode_var = tk.StringVar(value=MODE_LABELS.get(settings.input_mode, ""))
        self.bg_key_var = tk.StringVar(value="Right")
        self.scale_var = tk.StringVar(value=_scale_label(settings.ui_scale))
        self.resync_var = tk.BooleanVar(value=settings.resync_cycles > 0)
        self.resync_every_var = tk.StringVar(value=str(max(1, settings.resync_cycles)))

        # 항목이 많아 창 높이에 따라 아래쪽(핫키·저장 버튼)이 잘린다.
        # 통째로 스크롤되는 칸에 담아 어느 크기에서도 끝까지 닿게 한다.
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.scroller = ScrollFrame(self)
        self.scroller.grid(row=0, column=0, sticky="nsew")
        body = self.scroller.inner

        # -- 권한 / 진단 ------------------------------------------------------
        # 이 도구가 "아무 반응 없음"이 되는 1순위 원인이라 맨 위에 둔다.
        diag = ttk.LabelFrame(body, text="권한 및 입력 전달 진단", padding=10)
        diag.pack(fill="x", pady=(0, 12))

        self.diag_var = tk.StringVar(value="확인 중…")
        self.diag_label = ttk.Label(
            diag, textvariable=self.diag_var, justify="left", wraplength=700
        )
        self.diag_label.pack(anchor="w")

        diag_buttons = ttk.Frame(diag)
        diag_buttons.pack(anchor="w", pady=(10, 0))
        ttk.Button(diag_buttons, text="입력 전달 테스트", command=self._run_diagnosis).pack(
            side="left"
        )
        self.admin_button = ttk.Button(
            diag_buttons, text="관리자 권한으로 다시 실행", command=self._relaunch
        )
        self.admin_button.pack(side="left", padx=8)

        # -- 대상 창 ---------------------------------------------------------
        target = ttk.LabelFrame(body, text="대상 게임 창", padding=10)
        target.pack(fill="x")

        row = ttk.Frame(target)
        row.pack(fill="x")
        ttk.Label(row, text="창 제목 (부분 일치)").pack(side="left")
        ttk.Entry(row, textvariable=self.pattern_var, width=28).pack(side="left", padx=8)
        ttk.Button(row, text="적용", command=self._apply_pattern).pack(side="left")
        ttk.Button(row, text="창 목록 새로고침", command=self._refresh_windows).pack(
            side="left", padx=6
        )

        self.window_list = ttk.Treeview(
            target, columns=("hwnd", "title"), show="headings", height=6, selectmode="browse"
        )
        self.window_list.heading("hwnd", text="HWND")
        self.window_list.column("hwnd", width=90, anchor="w", stretch=False)
        self.window_list.heading("title", text="창 제목")
        self.window_list.column("title", width=460, anchor="w")
        self.window_list.pack(fill="x", pady=(10, 6))

        ttk.Button(target, text="선택한 창으로 고정", command=self._pin_window).pack(anchor="w")

        # -- 안전장치 ---------------------------------------------------------
        safety = ttk.LabelFrame(body, text="동작 / 안전장치", padding=10)
        safety.pack(fill="x", pady=(12, 0))

        # 실행 전 활성화는 이제 끄고 켜는 것이 아니다. 창이 뒤에 있는 채로
        # SendInput 을 쏘면 남의 창에 들어가므로 늘 해야 한다.
        ttk.Label(
            safety,
            style="Faint.TLabel",
            text="실행하면 게임 창을 먼저 앞으로 가져옵니다. (배경 입력을 켠 "
            "경우에는 창을 건드리지 않습니다.)",
        ).pack(anchor="w", pady=(0, 6))
        focus = ttk.Frame(safety)
        focus.pack(fill="x", pady=(2, 6))
        ttk.Label(focus, text="실행 중 게임 창이 뒤로 밀리면").pack(side="left")
        focus_box = ttk.Combobox(
            focus, textvariable=self.focus_var,
            values=list(FOCUS_LABELS.values()), width=28, state="readonly",
        )
        focus_box.pack(side="left", padx=(8, 0))
        self.focus_hint = ttk.Label(safety, style="Faint.TLabel", text="", wraplength=760)
        self.focus_hint.pack(anchor="w", pady=(0, 4))
        focus_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_focus_hint())
        ttk.Checkbutton(
            safety,
            text="정지할 때 눌려 있는 키를 강제로 떼기 (키 고착 방지)",
            variable=self.release_var,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            safety,
            text="키를 스캔코드로 전송 (구형/DirectInput 게임 호환성 ↑, 권장)",
            variable=self.scancode_var,
        ).pack(anchor="w", pady=2)
        ttk.Checkbutton(
            safety,
            text="이벤트 하나하나를 로그에 남기기 (촘촘한 매크로에서는 로그가 "
            "금방 넘칩니다 — 평소에는 [실행 상태] 창을 쓰세요)",
            variable=self.verbose_var,
        ).pack(anchor="w", pady=2)

        ttk.Separator(safety, orient="horizontal").pack(fill="x", pady=(10, 8))

        resync_row = ttk.Frame(safety)
        resync_row.pack(fill="x")
        ttk.Checkbutton(
            resync_row,
            text="시나리오 사이클마다 입력 상태 자동 교정",
            variable=self.resync_var,
            command=self._sync_resync,
        ).pack(side="left")
        ttk.Label(resync_row, text="몇 사이클마다").pack(side="left", padx=(14, 6))
        self.resync_entry = int_entry(resync_row, self.resync_every_var, width=5)
        self.resync_entry.pack(side="left")

        ttk.Label(
            safety,
            style="Faint.TLabel",
            justify="left",
            wraplength=760,
            text="오래 돌릴수록 처음 설정한 것과 실제 상태가 조금씩 벌어집니다. "
            "사이클과 사이클 사이(입력이 하나도 안 나가 있는 순간)에 세 가지를 "
            "되돌립니다 — 창을 되찾느라 멈췄던 시간을 털어 시각 기준을 다시 잡고, "
            "눌린 채 남아 있는 키·버튼을 떼고, 게임 창 크기가 달라졌으면 알립니다. "
            "무언가 실제로 고쳤을 때만 로그에 남습니다.",
        ).pack(anchor="w", pady=(6, 0))

        # -- 입력 전달 방법 -----------------------------------------------------
        delivery = ttk.LabelFrame(body, text="입력 전달 방법", padding=10)
        delivery.pack(fill="x", pady=(12, 0))

        row = ttk.Frame(delivery)
        row.pack(fill="x")
        ttk.Label(row, text="보내는 방식").pack(side="left")
        mode_box = ttk.Combobox(
            row, textvariable=self.mode_var,
            values=list(MODE_LABELS.values()), width=34, state="readonly",
        )
        mode_box.pack(side="left", padx=(8, 0))
        mode_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_mode_hint())

        self.mode_hint = ttk.Label(
            delivery, style="Faint.TLabel", text="", wraplength=760, justify="left"
        )
        self.mode_hint.pack(anchor="w", pady=(6, 0))

        test = ttk.Frame(delivery)
        test.pack(fill="x", pady=(8, 0))
        ttk.Button(
            test, text="배경 입력 시험", style="Small.TButton",
            command=self._test_background,
        ).pack(side="left")
        ttk.Label(test, text="  보낼 키").pack(side="left")
        ttk.Combobox(
            test, textvariable=self.bg_key_var, values=list(KEY_CHOICES),
            width=10, state="readonly",
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            test, style="Faint.TLabel",
            text="  게임 창을 띄운 채 다른 창을 클릭해 뒤로 보낸 뒤 누르세요.",
        ).pack(side="left")

        self.bg_result = ttk.Label(
            delivery, style="Faint.TLabel", text="", wraplength=760, justify="left"
        )
        self.bg_result.pack(anchor="w", pady=(6, 0))

        self._sync_focus_hint()
        self._sync_mode_hint()
        self._sync_resync()

        # -- 녹화 -------------------------------------------------------------
        record = ttk.LabelFrame(body, text="녹화", padding=10)
        record.pack(fill="x", pady=(12, 0))

        ttk.Checkbutton(
            record, text="마우스 이동 경로도 녹화", variable=self.move_var
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(record, text="이동 기록 최소 간격 (ms)").grid(
            row=1, column=0, sticky="w", pady=4, padx=(0, 8)
        )
        int_entry(record, self.sample_var, width=8).grid(row=1, column=1, sticky="w")

        # -- 화면 -------------------------------------------------------------
        screen = ttk.LabelFrame(body, text="화면", padding=10)
        screen.pack(fill="x", pady=(12, 0))

        row = ttk.Frame(screen)
        row.pack(fill="x")
        ttk.Label(row, text="글씨 · 행 높이 배율").pack(side="left")
        scale_box = ttk.Combobox(
            row, textvariable=self.scale_var,
            values=list(SCALE_LABELS.values()), width=12, state="readonly",
        )
        scale_box.pack(side="left", padx=(8, 6))
        scale_box.bind("<<ComboboxSelected>>", lambda _e: self._apply_scale())
        ttk.Button(
            row, text="창 크기 · 분할 초기화", style="Small.TButton",
            command=self._reset_layout,
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            screen,
            style="Faint.TLabel",
            justify="left",
            wraplength=760,
            text="1920x1080처럼 넓은 화면에서 글씨가 작게 느껴지면 배율을 키우세요. "
            "고르면 바로 반영되고, 목록 열 너비처럼 일부는 다시 시작해야 완전히 "
            "맞춰집니다. 창 크기와 분할선 자리는 끌어서 맞춘 대로 저장되며, "
            "[초기화]는 그것을 화면 크기에 맞는 기본값으로 되돌립니다.",
        ).pack(anchor="w", pady=(6, 0))

        # -- 꾸미기 -----------------------------------------------------------
        look = ttk.LabelFrame(body, text="꾸미기 (테마 · 색 · 배경 · 아이콘)",
                              padding=10)
        look.pack(fill="x", pady=(12, 0))
        self._build_look(look)

        # -- 전역 핫키 ---------------------------------------------------------
        hotkeys = ttk.LabelFrame(body, text="전역 핫키", padding=10)
        hotkeys.pack(fill="x", pady=(12, 0))

        ttk.Label(hotkeys, text="비상 정지 (모든 작업 중단 + 키 해제)").grid(
            row=0, column=0, sticky="w", pady=4, padx=(0, 10)
        )
        self.panic_field = HotkeyField(hotkeys)
        self.panic_field.set(settings.panic_hotkey)
        self.panic_field.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(hotkeys, text="녹화 시작 / 정지").grid(
            row=1, column=0, sticky="w", pady=4, padx=(0, 10)
        )
        self.record_field = HotkeyField(hotkeys)
        self.record_field.set(settings.record_hotkey)
        self.record_field.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(hotkeys, text="관찰 시작 / 정지").grid(
            row=2, column=0, sticky="w", pady=4, padx=(0, 10)
        )
        self.observe_field = HotkeyField(hotkeys)
        self.observe_field.set(settings.observe_hotkey)
        self.observe_field.grid(row=2, column=1, sticky="w", pady=4)

        # -- 저장 -------------------------------------------------------------
        bottom = ttk.Frame(body)
        bottom.pack(fill="x", pady=(16, 0))
        ttk.Button(bottom, text="설정 적용 및 저장", command=self.apply).pack(side="left")
        self.status_var = tk.StringVar(value="")
        ttk.Label(bottom, textvariable=self.status_var, style="Ok.TLabel").pack(
            side="left", padx=12
        )

        self._refresh_windows()
        self.refresh_privilege()

    # ------------------------------------------------------------------
    def refresh_privilege(self) -> None:
        ok, message = self.engine.privilege_report()
        self.diag_var.set(("✔ " if ok else "⚠ ") + message)
        self.diag_label.configure(style="Ok.TLabel" if ok else "Danger.TLabel")
        self.admin_button.configure(
            state="disabled" if elevation.is_elevated() else "normal"
        )

    def _run_diagnosis(self) -> None:
        self.diag_var.set("테스트 중…")
        self.update_idletasks()
        report = self.engine.diagnose()
        blocked = "실패" in report or "문제" in report
        self.diag_var.set(report)
        self.diag_label.configure(style="Danger.TLabel" if blocked else "Ok.TLabel")
        self.engine.log("입력 진단:\n" + report)

    def _relaunch(self) -> None:
        if not messagebox.askyesno(
            "관리자 권한으로 다시 실행",
            "이 프로그램을 종료하고 관리자 권한으로 다시 시작합니다.\n"
            "저장하지 않은 변경은 먼저 저장됩니다. 계속할까요?",
            parent=self,
        ):
            return
        try:
            self.engine.save()
        except OSError:
            pass
        if elevation.relaunch_as_admin():
            self.winfo_toplevel().after(200, self.winfo_toplevel()._on_close)
        else:
            messagebox.showwarning(
                "재실행 취소됨",
                "관리자 권한 실행이 취소되었거나 실패했습니다.",
                parent=self,
            )

    def _refresh_windows(self) -> None:
        self.window_list.delete(*self.window_list.get_children())
        for hwnd, title in self.engine.candidate_windows(""):
            self.window_list.insert("", "end", iid=str(hwnd), values=(hwnd, title))

    def _apply_pattern(self) -> None:
        pattern = self.pattern_var.get().strip()
        self.engine.resolver.set_pattern(pattern)
        self.engine.settings.window_pattern = pattern
        window = self.engine.window()
        if window is None:
            self.status_var.set("일치하는 창을 찾지 못했습니다.")
        else:
            self.status_var.set(f"연결됨: {window.title}")
        self.refresh_privilege()

    def _pin_window(self) -> None:
        selection = self.window_list.selection()
        if not selection:
            return
        hwnd = int(selection[0])
        title = self.window_list.item(selection[0], "values")[1]
        self.engine.resolver.pin(hwnd, title)
        self.pattern_var.set(title)
        self.engine.settings.window_pattern = title
        self.status_var.set(f"고정됨: {title}")
        self.engine.log(f"대상 창 고정: {title} (HWND {hwnd})")
        self.refresh_privilege()

    def _sync_resync(self) -> None:
        self.resync_entry.configure(
            state="normal" if self.resync_var.get() else "disabled"
        )

    def _sync_focus_hint(self) -> None:
        policy = FOCUS_BY_LABEL.get(self.focus_var.get(), FOCUS_REFOCUS)
        self.focus_hint.configure(text=FOCUS_HINTS[policy])

    def _sync_mode_hint(self) -> None:
        mode = MODE_BY_LABEL.get(self.mode_var.get(), INPUT_SEND)
        self.mode_hint.configure(text=MODE_HINTS[mode])

    def _apply_scale(self) -> None:
        """고른 배율을 이미 떠 있는 창들에 바로 입힌다."""
        scale = SCALE_BY_LABEL.get(self.scale_var.get(), 1.0)
        settings = self.engine.settings
        if abs(settings.ui_scale - scale) < 1e-6:
            return
        settings.ui_scale = scale
        root = self.winfo_toplevel()
        theme.apply(root, scale)
        theme.restyle_widgets()
        for tab in getattr(root, "editor_tabs", ()):
            if hasattr(tab, "refresh_fonts"):
                tab.refresh_fonts()
        # 배율이 커지면 지금 창으로는 내용이 다 안 들어간다. 최소 크기를 다시
        # 잡고, 모자라면 그만큼 늘려 준다. 사용자가 맞춰 둔 자리는 건드리지 않는다.
        if hasattr(root, "grow_to_fit"):
            root.grow_to_fit()
        try:
            self.engine.save()
        except OSError as exc:
            self.engine.log(f"설정 저장 실패: {exc}")
        self.status_var.set(f"화면 배율 {self.scale_var.get()} 적용")
        self.after(2500, lambda: self.status_var.set(""))

    # -- 꾸미기 ------------------------------------------------------------
    def _build_look(self, look: ttk.LabelFrame) -> None:
        settings = self.engine.settings

        row = ttk.Frame(look)
        row.pack(fill="x")
        ttk.Label(row, text="테마").pack(side="left")
        self.theme_var = tk.StringVar(
            value=settings.ui_theme if settings.ui_theme in theme.THEMES
            else theme.DEFAULT_THEME)
        box = ttk.Combobox(row, textvariable=self.theme_var,
                           values=list(theme.THEMES), width=12, state="readonly")
        box.pack(side="left", padx=(8, 6))
        box.bind("<<ComboboxSelected>>", lambda _e: self._pick_theme())
        ttk.Button(row, text="바꾼 색 되돌리기", style="Small.TButton",
                   command=self._reset_colors).pack(side="left", padx=(6, 0))

        # 글꼴. fonts/ 폴더에 딸린 글꼴과 윈도우 기본을 고른다.
        font_row = ttk.Frame(look)
        font_row.pack(fill="x", pady=(8, 0))
        ttk.Label(font_row, text="글꼴").pack(side="left")
        self._font_choices = fonts.choices(self)
        current = settings.ui_font or fonts.SYSTEM_DEFAULT
        label = next((lbl for lbl, fam in self._font_choices if fam == current),
                     fonts.SYSTEM_LABEL)
        self.font_var = tk.StringVar(value=label)
        font_box = ttk.Combobox(
            font_row, textvariable=self.font_var, width=34, state="readonly",
            values=[lbl for lbl, _fam in self._font_choices])
        font_box.pack(side="left", padx=(8, 6))
        font_box.bind("<<ComboboxSelected>>", lambda _e: self._pick_font())
        ttk.Button(font_row, text="글꼴 폴더 열기", style="Small.TButton",
                   command=self._open_font_dir).pack(side="left", padx=(6, 0))
        self.font_preview = tk.Label(
            look, text="가나다라 ABC 123 — 피로도 : 5780000 / 5780000",
            anchor="w", background=theme.PALETTE["bg"],
            foreground=theme.PALETTE["text"],
            font=(theme.BASE_FAMILY, theme.font_size(theme.TITLE_SIZE)))
        self.font_preview.pack(fill="x", pady=(4, 0))

        # 색 여섯 가지. 네모를 누르거나 [바꾸기]를 누르면 색 고르는 창이 뜬다.
        colors = ttk.Frame(look)
        colors.pack(fill="x", pady=(8, 0))
        self.swatches: dict[str, tk.Label] = {}
        for index, (role, label) in enumerate(theme.COLOR_ROLES):
            cell = ttk.Frame(colors)
            cell.grid(row=index // 3, column=index % 3, sticky="w",
                      padx=(0, 22), pady=3)
            chip = tk.Label(cell, width=4, relief="solid", borderwidth=1,
                            cursor="hand2")
            chip.pack(side="left")
            chip.bind("<Button-1>", lambda _e, r=role: self._pick_color(r))
            ttk.Label(cell, text=label, width=12).pack(side="left", padx=(6, 4))
            ttk.Button(cell, text="바꾸기", style="Small.TButton",
                       command=lambda r=role: self._pick_color(r)).pack(side="left")
            self.swatches[role] = chip

        back = ttk.Frame(look)
        back.pack(fill="x", pady=(10, 0))
        ttk.Label(back, text="배경 이미지", width=10).pack(side="left")
        self.bg_path_var = tk.StringVar()
        ttk.Label(back, textvariable=self.bg_path_var, style="Muted.TLabel",
                  width=20).pack(side="left", padx=(4, 8))
        ttk.Button(back, text="이미지 고르기", style="Small.TButton",
                   command=self._pick_background).pack(side="left")
        ttk.Button(back, text="지우기", style="Small.TButton",
                   command=self._clear_background).pack(side="left", padx=(4, 14))
        ttk.Label(back, text="보이는 테두리").pack(side="left")
        self.margin_var = tk.StringVar(value=str(settings.ui_bg_margin))
        spin = ttk.Spinbox(back, textvariable=self.margin_var, from_=0, to=120,
                           increment=4, width=5, command=self._apply_margin)
        spin.pack(side="left", padx=(6, 2))
        spin.bind("<Return>", lambda _e: self._apply_margin())
        spin.bind("<FocusOut>", lambda _e: self._apply_margin())
        ttk.Label(back, text="px").pack(side="left")

        icon = ttk.Frame(look)
        icon.pack(fill="x", pady=(6, 0))
        ttk.Label(icon, text="창 아이콘", width=10).pack(side="left")
        self.icon_path_var = tk.StringVar()
        ttk.Label(icon, textvariable=self.icon_path_var, style="Muted.TLabel",
                  width=20).pack(side="left", padx=(4, 8))
        ttk.Button(icon, text="이미지 고르기", style="Small.TButton",
                   command=self._pick_icon).pack(side="left")
        ttk.Button(icon, text="지우기", style="Small.TButton",
                   command=self._clear_icon).pack(side="left", padx=(4, 0))

        self.look_var = tk.StringVar(value="")
        ttk.Label(look, textvariable=self.look_var, style="Ok.TLabel",
                  justify="left", wraplength=760).pack(anchor="w", pady=(6, 0))
        ttk.Label(
            look, style="Faint.TLabel", justify="left", wraplength=760,
            text=(f"창 아이콘: {decor.ICON_ADVICE}. 256처럼 128·64·32·16으로 딱 "
                  "나뉘는 크기면 제목 표시줄의 작은 아이콘도 또렷합니다.\n"
                  f"배경 이미지: {decor.BACKGROUND_ADVICE}. 가운데를 기준으로 넘치는 "
                  "부분은 잘립니다. 창보다 2배 넘게 크면 1/2·1/3로 줄이고, 창의 절반보다 "
                  "작으면 정수배로 키워 흐려집니다. JPG는 못 읽으니 PNG로 저장해 주세요.\n"
                  "배경은 목록·입력칸 뒤가 아니라 창 둘레의 [보이는 테두리]만큼에 "
                  "보입니다 — 판을 반투명하게 만들 수 없어, 글씨가 잘 읽히게 내용 판은 "
                  "불투명하게 둡니다. 고른 이미지는 data/ui 폴더에 복사해 둡니다."),
        ).pack(anchor="w", pady=(6, 0))
        self._sync_look()

    def _sync_look(self) -> None:
        settings = self.engine.settings
        for role, chip in self.swatches.items():
            chip.configure(background=theme.PALETTE[role])
        self.font_preview.configure(background=theme.PALETTE["bg"],
                                    foreground=theme.PALETTE["text"])
        self.bg_path_var.set(Path(settings.ui_background).name
                             if settings.ui_background else "없음")
        self.icon_path_var.set(Path(settings.ui_icon).name
                               if settings.ui_icon else "기본 (깃털)")

    def _say(self, text: str) -> None:
        self.look_var.set(text)
        self.after(5000, lambda: self.look_var.get() == text
                   and self.look_var.set(""))

    def _save_look(self) -> None:
        try:
            self.engine.save()
        except OSError as exc:
            self.engine.log(f"설정 저장 실패: {exc}")

    def _apply_look(self, message: str) -> None:
        """테마·색을 이미 떠 있는 창들에 바로 입힌다."""
        settings = self.engine.settings
        root = self.winfo_toplevel()
        old = theme.use(settings.ui_theme, settings.ui_colors)
        theme.apply(root, settings.ui_scale)
        # 색 값으로 옮겨 칠한 뒤, 역할을 아는 것들(글상자 · 줄무늬)을 역할대로
        # 덮어 칠한다. 반대로 하면 옮겨 칠하기가 방금 맞춘 색을 다시 건드린다.
        theme.recolor(root, old, theme.PALETTE)
        theme.restyle_widgets()
        backdrop = getattr(root, "backdrop", None)
        if backdrop is not None:
            backdrop.refresh_color()
        self._sync_look()
        self._save_look()
        self._say(message)

    def _pick_font(self) -> None:
        family = dict(self._font_choices).get(self.font_var.get(),
                                              fonts.SYSTEM_DEFAULT)
        settings = self.engine.settings
        chosen = "" if family == fonts.SYSTEM_DEFAULT else family
        if chosen == settings.ui_font:
            return
        settings.ui_font = chosen
        root = self.winfo_toplevel()
        theme.set_family(chosen)
        theme.apply(root, settings.ui_scale)
        theme.restyle_widgets()
        # 글꼴마다 글자 폭이 달라 넓은 글꼴이면 창이 모자랄 수 있다.
        if hasattr(root, "grow_to_fit"):
            root.grow_to_fit()
        self.font_preview.configure(
            font=(theme.BASE_FAMILY, theme.font_size(theme.TITLE_SIZE)))
        self._save_look()
        self._say(f"글꼴 '{theme.BASE_FAMILY}' 적용 — 목록 열 너비처럼 일부는 다시 "
                  "켜야 완전히 맞춰집니다")

    def _open_font_dir(self) -> None:
        import os

        fonts.FONT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(fonts.FONT_DIR))  # type: ignore[attr-defined]
        except OSError as exc:
            self._say(f"폴더를 열지 못했습니다: {exc}")
            return
        self._say("글꼴 폴더에 새 폴더를 만들고 .ttf/.otf 를 넣은 뒤 프로그램을 다시 "
                  "켜면 목록에 뜹니다")

    def _pick_theme(self) -> None:
        settings = self.engine.settings
        name = self.theme_var.get()
        if name == settings.ui_theme and not settings.ui_colors:
            return
        # 테마를 고르면 그 테마 색 그대로 시작한다. 전에 직접 바꾼 색이 남아 있으면
        # 새 테마와 섞여 서로 안 어울린다.
        settings.ui_theme = name
        dropped = len(settings.ui_colors)
        settings.ui_colors = {}
        self._apply_look(f"테마 '{name}' 적용"
                         + (f" (직접 바꾼 색 {dropped}개는 비웠습니다)" if dropped
                            else ""))

    def _pick_color(self, role: str) -> None:
        label = dict(theme.COLOR_ROLES).get(role, role)
        _rgb, chosen = colorchooser.askcolor(
            color=theme.PALETTE[role], parent=self, title=f"{label} 색 고르기")
        if not chosen:
            return
        settings = self.engine.settings
        settings.ui_colors = {**settings.ui_colors, role: chosen.lower()}
        self._apply_look(f"{label} 색을 {chosen.lower()}로 바꿨습니다 — 테두리·"
                         "마우스 올렸을 때 색은 거기에 맞춰 저절로 바뀝니다")

    def _reset_colors(self) -> None:
        settings = self.engine.settings
        if not settings.ui_colors:
            self._say("직접 바꾼 색이 없습니다.")
            return
        settings.ui_colors = {}
        self._apply_look(f"'{settings.ui_theme}' 테마 색으로 되돌렸습니다")

    def _pick_image(self, title: str, name: str) -> Path | None:
        path = filedialog.askopenfilename(parent=self, title=title,
                                          filetypes=decor.IMAGE_TYPES)
        if not path:
            return None
        try:
            decor.load_photo(self, path)
            return decor.keep_copy(path, name)
        except (decor.ImageError, OSError) as exc:
            messagebox.showwarning(title, str(exc), parent=self)
            return None

    def _pick_background(self) -> None:
        stored = self._pick_image("배경 이미지 고르기", "background")
        if stored is None:
            return
        settings = self.engine.settings
        settings.ui_background = str(stored)
        backdrop = getattr(self.winfo_toplevel(), "backdrop", None)
        message = (backdrop.show(settings.ui_background, settings.ui_bg_margin)
                   if backdrop is not None else "")
        if settings.ui_bg_margin <= 0:
            message += " — 테두리가 0px라 안 보입니다. [보이는 테두리]를 키우세요"
        self._sync_look()
        self._save_look()
        self._say(message or "배경 이미지를 골랐습니다 (다시 켜면 보입니다)")

    def _clear_background(self) -> None:
        settings = self.engine.settings
        settings.ui_background = ""
        backdrop = getattr(self.winfo_toplevel(), "backdrop", None)
        if backdrop is not None:
            backdrop.show("", settings.ui_bg_margin)
        self._sync_look()
        self._save_look()
        self._say("배경 이미지를 없앴습니다")

    def _apply_margin(self) -> None:
        settings = self.engine.settings
        margin = max(0, min(120, get_int(self.margin_var, settings.ui_bg_margin)))
        if str(margin) != self.margin_var.get():
            self.margin_var.set(str(margin))
        if margin == settings.ui_bg_margin:
            return
        settings.ui_bg_margin = margin
        backdrop = getattr(self.winfo_toplevel(), "backdrop", None)
        if backdrop is not None:
            backdrop.set_margin(margin)
        self._save_look()
        self._say(f"테두리 {margin}px" if settings.ui_background
                  else f"테두리 {margin}px — 배경 이미지를 고르면 보입니다")

    def _pick_icon(self) -> None:
        stored = self._pick_image("창 아이콘 고르기", "icon")
        if stored is None:
            return
        settings = self.engine.settings
        settings.ui_icon = str(stored)
        message = decor.apply_icon(self.winfo_toplevel(), settings.ui_icon)
        self._sync_look()
        self._save_look()
        self._say(message)

    def _clear_icon(self) -> None:
        settings = self.engine.settings
        settings.ui_icon = ""
        self._sync_look()
        self._save_look()
        self._say("창 아이콘을 비웠습니다 — 기본 깃털 아이콘은 프로그램을 다시 켜면 "
                  "돌아옵니다")

    def _reset_layout(self) -> None:
        root = self.winfo_toplevel()
        if not hasattr(root, "reset_layout"):
            return
        root.reset_layout()
        try:
            self.engine.save()
        except OSError as exc:
            self.engine.log(f"설정 저장 실패: {exc}")
        self.status_var.set("창 크기와 분할선을 기본값으로 되돌렸습니다.")
        self.after(2500, lambda: self.status_var.set(""))

    def _test_background(self) -> None:
        self.bg_result.configure(text="시험 중… (약 3초)")
        self.update_idletasks()
        works, message = self.engine.background_input_test(self.bg_key_var.get())
        self.bg_result.configure(text=("O  " if works else "X  ") + message)
        self.engine.log(("배경 입력 시험: 통함 — " if works else "배경 입력 시험: 안 통함 — ")
                        + message.replace("\n", " "))

    def apply(self) -> None:
        settings = self.engine.settings
        settings.window_pattern = self.pattern_var.get().strip()
        # 이제 항상 앞으로 가져온다. 값은 구버전 호환으로만 남겨 둔다.
        settings.activate_before_run = True
        settings.record_mouse_move = bool(self.move_var.get())
        settings.move_sample_ms = max(get_int(self.sample_var, 20), 1)
        settings.use_scancode = bool(self.scancode_var.get())
        settings.release_keys_on_stop = bool(self.release_var.get())
        settings.verbose_log = bool(self.verbose_var.get())
        settings.resync_cycles = (
            max(1, get_int(self.resync_every_var, 1)) if self.resync_var.get() else 0
        )
        settings.focus_policy = FOCUS_BY_LABEL.get(self.focus_var.get(), FOCUS_REFOCUS)
        settings.input_mode = MODE_BY_LABEL.get(self.mode_var.get(), INPUT_SEND)
        # 구버전과 오가더라도 값이 어긋나지 않게 맞춰 둔다.
        settings.require_foreground = settings.focus_policy == FOCUS_STOP
        settings.panic_hotkey = self.panic_field.get()
        settings.record_hotkey = self.record_field.get()
        settings.observe_hotkey = self.observe_field.get()
        settings.ui_scale = SCALE_BY_LABEL.get(self.scale_var.get(), settings.ui_scale)

        self.engine.resolver.set_pattern(settings.window_pattern)
        self.engine.rebind_hotkeys()
        self.engine.save()
        self.status_var.set("저장했습니다.")
        self.after(2500, lambda: self.status_var.set(""))
