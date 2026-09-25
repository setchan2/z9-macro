"""탭 — 관찰 학습.

사용자가 직접 플레이하는 동안 화면과 입력을 함께 기록해서, 감지 좌표·기준 색·
반복 주기를 자동으로 추려낸다. 게임 규칙을 손으로 옮겨 적는 과정을 없애는 것이
목적이다.
"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from .. import analysis, pixel
from ..engine import Engine
from ..keys import name_of
from ..model import Macro
from ..observer import estimate_bytes, grid_size, to_macro_events
from ..recorder import balance_keys
from . import theme
from .widgets import get_int, int_entry


class ObserveTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine: Engine, on_saved) -> None:
        super().__init__(parent, padding=12)
        self.engine = engine
        self.on_saved = on_saved
        self._result: analysis.AnalysisResult | None = None
        self._observation = None
        self._busy = False
        self._pending: list = []
        self._pending_lock = threading.Lock()

        settings = engine.settings
        self.interval_var = tk.StringVar(value=str(settings.observe_interval_ms))
        self.step_var = tk.StringVar(value=str(settings.observe_step))
        self.seconds_var = tk.StringVar(value=str(settings.observe_seconds))
        self.name_var = tk.StringVar(value="농사")
        self.anchor_var = tk.StringVar(value="(자동)")
        self.lookback_var = tk.StringVar(value="500")
        self.threshold_var = tk.StringVar(value="24")

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        self._build_intro()
        self._build_capture()
        self._build_analysis()
        self._build_result()

        self._update_estimate()
        self.after(300, self._drain)

    # ------------------------------------------------------------------
    def _build_intro(self) -> None:
        box = ttk.Frame(self)
        box.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            box, text="관찰 학습", style="Title.TLabel"
        ).pack(anchor="w")
        ttk.Label(
            box,
            justify="left",
            style="Muted.TLabel",
            text=(
                "게임 규칙을 글로 옮길 필요 없이, 평소처럼 플레이하면 도구가 지켜보고\n"
                "감지 좌표 · 기준 색 · 반복 주기를 스스로 찾아냅니다.\n\n"
                "1. [관찰 시작]을 누르고 게임 창으로 전환\n"
                "2. 농사(또는 목장) 동작을 평소 속도로 5~10회 반복\n"
                "3. F10으로 중지 → [분석 실행]"
            ),
        ).pack(anchor="w", pady=(4, 0))

    def _build_capture(self) -> None:
        box = ttk.LabelFrame(self, text="1. 관찰", padding=10)
        box.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="캡처 간격(ms)").pack(side="left")
        e1 = int_entry(row, self.interval_var, width=6)
        e1.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="격자 간격(px)").pack(side="left")
        e2 = int_entry(row, self.step_var, width=5)
        e2.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="최대 시간(초)").pack(side="left")
        e3 = int_entry(row, self.seconds_var, width=6)
        e3.pack(side="left", padx=(6, 16))
        for entry in (e1, e2, e3):
            entry.bind("<KeyRelease>", lambda _e: self._update_estimate())

        self.estimate_var = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.estimate_var, style="Muted.TLabel").pack(
            anchor="w", pady=(8, 0)
        )

        buttons = ttk.Frame(box)
        buttons.pack(anchor="w", pady=(10, 0))
        self.observe_button = ttk.Button(
            buttons, text="● 관찰 시작", command=self.toggle_observe
        )
        self.observe_button.pack(side="left")
        self.progress_var = tk.StringVar(value="대기 중")
        ttk.Label(buttons, textvariable=self.progress_var, style="Accent.TLabel").pack(
            side="left", padx=12
        )

    def _build_analysis(self) -> None:
        box = ttk.LabelFrame(self, text="2. 분석", padding=10)
        box.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="기준 키").pack(side="left")
        self.anchor_box = ttk.Combobox(
            row, textvariable=self.anchor_var, width=12, state="readonly",
            values=["(자동)"],
        )
        self.anchor_box.pack(side="left", padx=(6, 16))
        ttk.Label(row, text="되돌아보기(ms)").pack(side="left")
        int_entry(row, self.lookback_var, width=6).pack(side="left", padx=(6, 16))
        ttk.Label(row, text="색 변화 임계값").pack(side="left")
        int_entry(row, self.threshold_var, width=5).pack(side="left", padx=(6, 0))

        ttk.Label(
            box,
            style="Muted.TLabel",
            justify="left",
            text=(
                "되돌아보기 = 키를 누르기 몇 ms 전까지 거슬러 올라가 화면 변화를 볼지.\n"
                "임계값 = 이만큼 색이 달라져야 '변했다'고 봅니다 (낮출수록 민감)."
            ),
        ).pack(anchor="w", pady=(8, 0))

        self.analyze_button = ttk.Button(
            box, text="분석 실행", command=self._analyze, state="disabled"
        )
        self.analyze_button.pack(anchor="w", pady=(10, 0))

    def _build_result(self) -> None:
        box = ttk.LabelFrame(self, text="3. 결과", padding=10)
        box.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        wrap = ttk.Frame(box)
        wrap.grid(row=0, column=0, sticky="nsew")
        self.result_text = tk.Text(
            wrap, height=14, wrap="word", state="disabled"
        )
        theme.style_text(self.result_text, mono=True)
        self.result_text.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.result_text.yview)
        bar.pack(side="left", fill="y")
        self.result_text.configure(yscrollcommand=bar.set)

        save = ttk.Frame(box)
        save.grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Label(save, text="이름 접두어").pack(side="left")
        ttk.Entry(save, textvariable=self.name_var, width=14).pack(
            side="left", padx=(6, 12)
        )
        self.save_repeat_button = ttk.Button(
            save, text="연타 설정으로 저장", command=self._save_repeat, state="disabled"
        )
        self.save_repeat_button.pack(side="left")
        self.save_rule_button = ttk.Button(
            save, text="감지 조건으로 저장", command=self._save_rule, state="disabled"
        )
        self.save_rule_button.pack(side="left", padx=8)
        self.save_macro_button = ttk.Button(
            save, text="키 입력을 매크로로 저장", command=self._save_macro, state="disabled"
        )
        self.save_macro_button.pack(side="left")

    # ------------------------------------------------------------------
    def _update_estimate(self) -> None:
        win = self.engine.window()
        if win is None:
            self.estimate_var.set("게임 창을 찾지 못했습니다.")
            return
        cw, ch = win.client_size()
        step = max(1, get_int(self.step_var, 4))
        interval = max(10, get_int(self.interval_var, 50))
        seconds = max(5, get_int(self.seconds_var, 90))
        size = estimate_bytes(cw, ch, step, interval, seconds)
        gw, gh = grid_size(cw, ch, step)
        self.estimate_var.set(
            f"게임 창 {cw}x{ch} → 격자 {gw}x{gh} ({gw * gh:,}점) · "
            f"최대 {seconds}초 기록 시 약 {size / 1048576:.0f}MB"
        )

    # ------------------------------------------------------------------
    def toggle_observe(self) -> None:
        if self.engine.observer.running:
            self._stop_observe()
        else:
            self._start_observe()

    def request_observe_toggle(self) -> None:
        """훅 스레드에서 호출 — GUI 스레드로 넘긴다."""
        self.after(0, self.toggle_observe)

    def _start_observe(self) -> None:
        settings = self.engine.settings
        settings.observe_interval_ms = max(10, get_int(self.interval_var, 50))
        settings.observe_step = max(1, get_int(self.step_var, 4))
        settings.observe_seconds = max(5, get_int(self.seconds_var, 90))
        if self.engine.start_observing():
            self.observe_button.configure(text="■ 관찰 중지")
            self._write("관찰 중… 게임 창으로 전환해 평소처럼 플레이하세요.")

    def _stop_observe(self) -> None:
        observation = self.engine.stop_observing()
        self.observe_button.configure(text="● 관찰 시작")
        self._observation = observation
        if observation is None or not observation.frames:
            self._write("기록된 프레임이 없습니다.")
            return

        names = ["(자동)"] + [
            f"{name_of(vk)}" for vk in _down_vks(observation)
        ]
        self.anchor_box.configure(values=names)
        self.analyze_button.configure(state="normal")
        # 매크로 저장은 분석과 무관하다 — 키 입력만 있으면 바로 쓸 수 있다.
        self.save_macro_button.configure(
            state="normal" if observation.keys else "disabled"
        )
        self._write(
            f"기록 완료 — 프레임 {len(observation.frames)}개 "
            f"({observation.duration:.1f}초), "
            f"키 입력 {len(observation.keys)}개, "
            f"{observation.nbytes / 1048576:.0f}MB\n\n"
            "[분석 실행]을 누르세요."
        )

    # ------------------------------------------------------------------
    def _analyze(self) -> None:
        if self._observation is None or self._busy:
            return
        self._busy = True
        self.analyze_button.configure(state="disabled")
        self._write("분석 중…")

        anchor_vk = None
        chosen = self.anchor_var.get()
        if chosen and chosen != "(자동)":
            from ..keys import vk_of

            anchor_vk = vk_of(chosen)

        lookback = max(50, get_int(self.lookback_var, 500))
        threshold = max(2, get_int(self.threshold_var, 24))
        observation = self._observation

        def work() -> None:
            try:
                result = analysis.analyze(
                    observation,
                    anchor_vk=anchor_vk,
                    lookback_ms=lookback,
                    threshold=threshold,
                    progress=lambda m: self._push(("progress", m)),
                )
                self._push(("done", result))
            except Exception as exc:  # noqa: BLE001
                self._push(("error", exc))

        threading.Thread(target=work, name="z9-analyze", daemon=True).start()

    def _push(self, item) -> None:
        with self._pending_lock:
            self._pending.append(item)

    def _drain(self) -> None:
        with self._pending_lock:
            items, self._pending = self._pending, []
        for kind, payload in items:
            if kind == "progress":
                self._write(f"분석 중… {payload}")
            elif kind == "error":
                self._busy = False
                self.analyze_button.configure(state="normal")
                self._write(f"분석 실패: {payload!r}")
            elif kind == "done":
                self._busy = False
                self.analyze_button.configure(state="normal")
                self._show_result(payload)

        if self.engine.observer.running:
            obs = self.engine.observer.observation
            if obs is not None:
                self.progress_var.set(
                    f"● 관찰 중 — {obs.duration:.0f}초, 프레임 {len(obs.frames)}, "
                    f"키 {len(obs.keys)}, {obs.nbytes / 1048576:.0f}MB"
                )
        elif self.observe_button.cget("text").startswith("■"):
            # 최대 시간 도달 등으로 스레드가 알아서 끝난 경우
            self._stop_observe()
        else:
            self.progress_var.set("대기 중")

        self.after(300, self._drain)

    # ------------------------------------------------------------------
    def _show_result(self, result: analysis.AnalysisResult) -> None:
        self._result = result
        lines: list[str] = []

        lines.append("── 키 입력 ──")
        for stat in result.key_stats[:6]:
            mark = " ←기준" if stat.vk == result.anchor_vk else ""
            gap = (
                f"평균 {stat.mean_gap_ms:6.0f}ms "
                f"({stat.min_gap_ms:.0f}~{stat.max_gap_ms:.0f}, ±{stat.stdev_ms:.0f})"
                if stat.count > 1
                else ""
            )
            lines.append(f"  {stat.name:<10} {stat.count:>3}회  {gap}{mark}")
        lines.append(f"  순서: {result.key_sequence}")
        lines.append("")

        lines.append(f"── 키 직전 화면 변화 (기준점 {result.anchor_count}개) ──")
        if result.signal_points:
            for i, p in enumerate(result.signal_points, 1):
                lines.append(
                    f"  {i}. ({p.x:>4}, {p.y:>4})  "
                    f"{pixel.to_hex(p.baseline)} → {pixel.to_hex(p.signal)}  "
                    f"일관성 {p.consistency:.0%} 특이성 {p.specificity:.0%} "
                    f"영역 {p.cluster_size}점"
                )
        else:
            lines.append("  (없음)")
        lines.append("")

        if result.after_points:
            lines.append("── 키 직후 화면 변화 (성공 판정용 후보) ──")
            for i, p in enumerate(result.after_points, 1):
                lines.append(
                    f"  {i}. ({p.x:>4}, {p.y:>4})  "
                    f"{pixel.to_hex(p.baseline)} → {pixel.to_hex(p.signal)}  "
                    f"일관성 {p.consistency:.0%}"
                )
            lines.append("")

        if result.suggestions:
            lines.append("── 제안 ──")
            lines += [f"  · {s}" for s in result.suggestions]
            lines.append("")

        if result.warnings:
            lines.append("── 확인 필요 ──")
            lines += [f"  ! {w}" for w in result.warnings]

        self._write("\n".join(lines))

        self.save_repeat_button.configure(
            state="normal" if result.anchor_count >= 2 else "disabled"
        )
        self.save_rule_button.configure(
            state="normal" if result.has_signal else "disabled"
        )

    def _write(self, text: str) -> None:
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)
        self.result_text.configure(state="disabled")

    # ------------------------------------------------------------------
    def _save_repeat(self) -> None:
        if self._result is None:
            return
        prefix = self.name_var.get().strip() or "관찰"
        task = analysis.build_repeat_task(self._result, f"[{prefix}] 연타 (관찰)")
        if task is None:
            return
        task.name = _unique(task.name, [t.name for t in self.engine.profile.repeats])
        self.engine.profile.repeats.append(task)
        self.engine.rebind_hotkeys()
        self.on_saved()
        self.engine.log(
            f"'{task.name}' 생성 — [{task.key}] {task.interval_ms}ms 간격"
        )

    def _save_macro(self) -> None:
        """관찰 중 기록된 실제 조작을 그대로 매크로로 만든다.

        관찰은 화면 분석이 목적이지만 사용자의 입력도 이미 시각과 함께 남아 있다.
        같은 동작을 다시 녹화할 필요가 없다.
        """
        if self._observation is None:
            return
        events = to_macro_events(self._observation)
        if not events:
            self._write("기록된 키 입력이 없습니다.")
            return
        events = balance_keys(events)

        prefix = self.name_var.get().strip() or "관찰"
        macro = Macro(
            name=_unique(
                f"[{prefix}] 매크로 (관찰)",
                [m.name for m in self.engine.profile.macros],
            ),
            events=events,
            client_w=self._observation.client_w,
            client_h=self._observation.client_h,
            absolute=False,
            repeat=1,
        )
        self.engine.profile.macros.append(macro)
        self.engine.rebind_hotkeys()
        self.on_saved()
        self.engine.log(
            f"'{macro.name}' 생성 — 이벤트 {len(macro.events)}개, "
            f"{macro.duration:.1f}초. [녹화 · 재생] 탭에서 편집할 수 있습니다."
        )

    def _save_rule(self) -> None:
        if self._result is None:
            return
        prefix = self.name_var.get().strip() or "관찰"
        rule = analysis.build_pixel_rule(self._result, f"[{prefix}] 감지 (관찰)")
        if rule is None:
            return
        rule.name = _unique(rule.name, [r.name for r in self.engine.profile.rules])
        self.engine.profile.rules.append(rule)
        self.on_saved()
        self.engine.log(
            f"'{rule.name}' 생성 — 감지 점 {len(rule.points)}개, "
            f"허용 오차 {rule.tolerance}, 동작 [{rule.action_key}]"
        )


def _down_vks(observation) -> list[int]:
    seen: list[int] = []
    for key in observation.keys:
        if key.down and key.vk not in seen:
            seen.append(key.vk)
    return seen


def _unique(name: str, existing: list[str]) -> str:
    if name not in existing:
        return name
    i = 2
    while f"{name} ({i})" in existing:
        i += 1
    return f"{name} ({i})"
