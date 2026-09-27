"""[제작] 탭 — 치트엔진으로 배속을 걸고, 끊기면 스스로 다시 접속한다.

돌아가는 차례는 z9/craft.py 에 적혀 있다. 여기서는 그 차례에 필요한 것들을
정한다: 부를 매크로 둘, 치트엔진에서 누를 자리들, 제작 소리, 다시 접속하는 길.

**자리는 손으로 적지 않고 찍는다.** [찍기]를 누르면 화면에서 누를 곳을 직접
클릭하면 되고, 그 클릭은 대상 프로그램으로 넘어가지 않는다. 치트엔진과
브라우저는 창을 옮길 수 있으므로 **창 안쪽 좌표**로 적어 둔다 — 창이 움직여도
그대로 눌린다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..window import GameWindow, find_window
from . import theme
from .tab_fishing import SoundRow
from .widgets import ScrollFrame, capture_click_point, get_float


class CraftTab(ScrollFrame):
    INTRO = (
        "치트엔진으로 제작 속도를 올려 두고, 경험치가 안 들어오면 스스로 다시 "
        "접속합니다. 시작하기 전에 치트엔진을 관리자 권한으로 켜 두고, 게임과 "
        "지구별 홈페이지를 열어 두세요.\n"
        "① 마이홈 개설·이동 (녹화 매크로)  →  ② 치트엔진 Open Process → 게임 → "
        "Speedhack → Apply  →  ③ 제작 (띠링 소리를 듣습니다)  →  ④ 소리가 멎으면 "
        "게임을 끄고 홈페이지 [게임 시작] → [Start] → 채널 접속 매크로  →  다시 ①"
    )

    def __init__(self, master: tk.Misc, engine) -> None:
        super().__init__(master)
        self.engine = engine
        self._loading = False
        inner = self.inner
        inner.columnconfigure(0, weight=1)

        self.home_var = tk.StringVar()
        self.channel_var = tk.StringVar()
        self.ce_var = tk.StringVar()
        self.plist_var = tk.StringVar()
        self.target_var = tk.StringVar()
        self.speed_var = tk.StringVar()
        self.double_var = tk.BooleanVar(value=True)
        self.quiet_var = tk.StringVar()
        self.site_var = tk.StringVar()
        self.url_var = tk.StringVar()
        self.names_var = tk.StringVar()
        self.client_var = tk.StringVar()
        self.cwait_var = tk.StringVar()
        self.gwait_var = tk.StringVar()
        self.tries_var = tk.StringVar()
        self.load_var = tk.StringVar()
        self.kill_var = tk.StringVar()
        self.gap_var = tk.StringVar()
        self.retry_var = tk.StringVar()
        self.spot_vars: dict[str, tk.StringVar] = {}
        self.ready_var = tk.StringVar()

        row = 0
        ttk.Label(inner, text="제작", style="Title.TLabel").grid(
            row=row, column=0, sticky="w")

        row += 1
        ttk.Label(inner, style="Faint.TLabel", justify="left",
                  wraplength=theme.px(760), text=self.INTRO).grid(
            row=row, column=0, sticky="w", pady=(4, 10))

        # -- ① 매크로 ------------------------------------------------------
        row += 1
        macros = ttk.LabelFrame(inner, text="① 부를 매크로", padding=theme.pad(8))
        macros.grid(row=row, column=0, sticky="ew")
        self.home_box = self._macro_row(
            macros, 0, "마이홈 개설·이동", self.home_var,
            "한 바퀴가 시작될 때 돌립니다")
        self.channel_box = self._macro_row(
            macros, 1, "채널 접속", self.channel_var,
            "다시 접속한 뒤 돌립니다 (닫기 → 서버 → 캐릭터 → 채널)")
        ttk.Button(macros, text="매크로 목록 새로 읽기", style="Small.TButton",
                   command=self._reload_macros).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # -- ② 치트엔진 ----------------------------------------------------
        row += 1
        ce = ttk.LabelFrame(inner, text="② 치트엔진", padding=theme.pad(8))
        ce.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        titles = ttk.Frame(ce)
        titles.grid(row=0, column=0, sticky="w")
        self._title_entry(titles, "치트엔진 창", self.ce_var, 22)
        self._title_entry(titles, "프로세스 목록 창", self.plist_var, 16)
        line = ttk.Frame(ce)
        line.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._title_entry(line, "목록에서 고를 것", self.target_var, 18)
        ttk.Label(line, text="배속").pack(side="left", padx=(14, 4))
        ttk.Entry(line, textvariable=self.speed_var, width=8).pack(side="left")
        ttk.Label(line, text="배").pack(side="left", padx=(3, 0))
        ttk.Checkbutton(ce, text="목록에서 두 번 눌러 고르기 (더블클릭)",
                        variable=self.double_var, command=self._save).grid(
            row=2, column=0, sticky="w", pady=(6, 0))

        ttk.Label(
            ce, style="Faint.TLabel", justify="left", wraplength=theme.px(720),
            text=("단추와 목록은 글씨로 스스로 찾습니다. '목록에서 고를 것'에 "
                  "적은 이름과 똑같은 줄을 찾아 누르므로, 떠 있는 프로그램이 "
                  "늘거나 줄어 줄이 밀려도 맞습니다. 이 프로그램 창"
                  "('Z9★ 온라인 매크로')과도 구별합니다.\n"
                  "아래 자리들은 스스로 못 찾을 때만 쓰는 예비입니다. "
                  "안 찍어 두어도 됩니다.")
        ).grid(row=3, column=0, sticky="w", pady=(8, 0))

        spots = ttk.Frame(ce)
        spots.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        for i, (attr, label) in enumerate(
                (("open_process", "Open Process 단추"),
                 ("pick_row", "목록에서 게임 줄"),
                 ("speed_check", "Enable Speedhack 체크칸"),
                 ("speed_field", "배속 적는 칸"),
                 ("apply_btn", "Apply 단추"))):
            where = self.plist_var if attr == "pick_row" else self.ce_var
            self._spot_row(spots, i, attr, label, where)

        # -- ③ 제작 소리 ---------------------------------------------------
        row += 1
        self.sound_row = SoundRow(
            inner, engine, lambda: self.engine.profile.craft, self._on_sound,
            attr="craft_sound", title="③ 제작 소리 (띠링)",
            intro=("제작이 한 번 될 때마다 나는 소리입니다. 배속이 크면 인터넷이 "
                   "끊겨도 화면은 멀쩡해 보이고 경험치만 안 들어오므로, 화면이 "
                   "아니라 이 소리로 가립니다.\n"
                   "게임 소리만 따로 듣기 때문에 윈도 스피커 볼륨을 꺼 두어도 "
                   "됩니다."),
            how=("[효과음 배우기]를 누르면 3초 동안 듣습니다. 그 사이에 제작이 "
                 "한 번 되어 띠링 소리가 나게 하세요.\n"
                 "배속을 걸어 둔 상태에서 배우는 편이 좋습니다 — 그때 나는 "
                 "소리를 그대로 알아봐야 하기 때문입니다."),
            prompt="지금 제작이 한 번 되게 해 주세요")
        self.sound_row.grid(row=row, column=0, sticky="ew", pady=(10, 0))

        row += 1
        quiet = ttk.Frame(inner)
        quiet.grid(row=row, column=0, sticky="w", pady=(6, 0))
        ttk.Label(quiet, text="소리가").pack(side="left")
        ttk.Entry(quiet, textvariable=self.quiet_var, width=6).pack(
            side="left", padx=4)
        ttk.Label(quiet, text="초 동안 한 번도 안 들리면 끊긴 것으로 보고 "
                             "다시 접속합니다").pack(side="left")

        # -- ④ 다시 접속 ---------------------------------------------------
        row += 1
        again = ttk.LabelFrame(inner, text="④ 다시 접속", padding=theme.pad(8))
        again.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(again, style="Faint.TLabel", justify="left",
                  wraplength=theme.px(720),
                  text=("게임을 강제로 끄고, 홈페이지 [GAME START]를 누릅니다. "
                        "클라이언트 창이 뜨면 정한 시간만큼 기다렸다가 "
                        "[Start]를 누릅니다.\n"
                        "[Start]를 눌렀는데 게임 창이 안 뜨면 남은 클라이언트 "
                        "창을 끄고 홈페이지부터 다시 합니다.")).grid(
            row=0, column=0, sticky="w", pady=(0, 6))
        line = ttk.Frame(again)
        line.grid(row=1, column=0, sticky="w")
        self._title_entry(line, "홈페이지 창 제목", self.site_var, 14)
        ttk.Label(line, text="클라이언트 창이 뜨면").pack(side="left", padx=(14, 4))
        ttk.Entry(line, textvariable=self.load_var, width=5).pack(side="left")
        ttk.Label(line, text="초 뒤에 [Start]").pack(side="left", padx=(3, 0))
        waits = ttk.Frame(again)
        waits.grid(row=6, column=0, sticky="w", pady=(6, 0))
        ttk.Label(waits, text="클라이언트 창 기다리기").pack(side="left", padx=(0, 4))
        ttk.Entry(waits, textvariable=self.cwait_var, width=5).pack(side="left")
        ttk.Label(waits, text="초  ·  게임 창 기다리기").pack(side="left", padx=(3, 4))
        ttk.Entry(waits, textvariable=self.gwait_var, width=5).pack(side="left")
        ttk.Label(waits, text="초  ·  게임이 안 뜨면 홈페이지부터").pack(
            side="left", padx=(3, 4))
        ttk.Entry(waits, textvariable=self.tries_var, width=4).pack(side="left")
        ttk.Label(waits, text="번까지 다시").pack(side="left", padx=(3, 0))
        url = ttk.Frame(again)
        url.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Label(url, text="창이 없으면 이 주소를 엽니다").pack(side="left",
                                                               padx=(0, 6))
        ttk.Entry(url, textvariable=self.url_var, width=42).pack(side="left")
        names = ttk.Frame(again)
        names.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Label(names, text="홈페이지에서 찾을 단추 이름").pack(side="left",
                                                                 padx=(0, 6))
        ttk.Entry(names, textvariable=self.names_var, width=28).pack(side="left")
        ttk.Label(names, text="(쉼표로 여러 개)  ·  클라이언트 창").pack(
            side="left", padx=(6, 6))
        ttk.Entry(names, textvariable=self.client_var, width=12).pack(side="left")
        ttk.Label(
            again, style="Faint.TLabel", justify="left",
            wraplength=theme.px(720),
            text=("홈페이지 단추는 이름으로 찾아 누릅니다 — 창을 옮기거나 "
                  "스크롤을 내려도 맞습니다. 아래 '홈페이지 [게임 시작]' 자리는 "
                  "이름으로 못 찾을 때만 쓰는 예비입니다.\n"
                  "[Start]는 클라이언트 창이 뜨기를 기다렸다가, 그 창 기준으로 "
                  "찍어 둔 자리를 누릅니다.")
        ).grid(row=4, column=0, sticky="w", pady=(6, 0))
        spots2 = ttk.Frame(again)
        spots2.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        self._spot_row(spots2, 0, "start_game", "홈페이지 [게임 시작] (예비)",
                       self.site_var)
        self._spot_row(spots2, 1, "start_btn", "클라이언트 [Start]",
                       self.client_var)

        # -- ⑤ 버프 --------------------------------------------------------
        row += 1
        buffs = ttk.LabelFrame(inner, text="⑤ 버프", padding=theme.pad(8))
        buffs.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(
            buffs, style="Faint.TLabel", justify="left",
            wraplength=theme.px(730),
            text=("한 바퀴가 시작될 때, 마이홈 매크로를 돌리기 **직전에** 주기가 "
                  "된 버프만 씁니다. 여러 개면 2초씩 띄워 누릅니다.\n"
                  "주기를 고치면 다음 사용부터 그 주기로 돕니다. [이번만]은 "
                  "다음 한 번의 남은 시간만 바꾸는 것입니다 — 예를 들어 6시간짜리 "
                  "버프를 밖에서 3시간 전에 이미 걸어 두었다면 180을 넣으세요. "
                  "그 다음부터는 다시 6시간으로 돕니다.").replace("**", "")
        ).grid(row=0, column=0, columnspan=8, sticky="w", pady=(0, 6))

        head = ("켬", "키", "이름", "주기(분)", "다음 사용", "", "이번만(분)", "")
        for col, text in enumerate(head):
            if text:
                ttk.Label(buffs, text=text, style="Faint.TLabel").grid(
                    row=1, column=col, sticky="w", padx=(0, 6))
        self.buff_rows = []
        for i in range(len(self.engine.profile.craft.buffs)):
            self.buff_rows.append(self._buff_row(buffs, i + 2, i))
        gapline = ttk.Frame(buffs)
        gapline.grid(row=2 + len(self.buff_rows), column=0, columnspan=8,
                     sticky="w", pady=(8, 0))
        ttk.Label(gapline, text="한 바퀴 시작할 때 [Esc]").pack(side="left",
                                                                padx=(0, 4))
        self.esc_var = tk.StringVar()
        ttk.Entry(gapline, textvariable=self.esc_var, width=4).pack(side="left")
        ttk.Label(gapline, text="번 · 간격").pack(side="left", padx=(3, 4))
        self.escgap_var = tk.StringVar()
        ttk.Entry(gapline, textvariable=self.escgap_var, width=5).pack(side="left")
        ttk.Label(gapline, text="초").pack(side="left", padx=(3, 14))
        ttk.Label(gapline, text="버프 키 사이 간격").pack(side="left", padx=(0, 4))
        self.bgap_var = tk.StringVar()
        ttk.Entry(gapline, textvariable=self.bgap_var, width=5).pack(side="left")
        ttk.Label(gapline, text="초").pack(side="left", padx=(3, 12))
        ttk.Button(gapline, text="버프만 해보기", style="Small.TButton",
                   command=lambda: self._try("buffs")).pack(side="left")

        # -- ⑥ 시간 --------------------------------------------------------
        row += 1
        times = ttk.LabelFrame(inner, text="⑤ 시간", padding=theme.pad(8))
        times.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        grid = ttk.Frame(times)
        grid.pack(anchor="w")
        self._time_row(grid, 0, "게임 끄고 쉬기", self.kill_var,
                       "창이 다 사라지기를 기다립니다")
        self._time_row(grid, 1, "누름 사이 쉬기", self.gap_var,
                       "치트엔진 단추 사이의 기본 간격입니다")
        self._time_row(grid, 2, "어긋나면 다시 하기", self.retry_var,
                       "창을 못 찾거나 실패하면 이만큼 쉬었다가 다시 합니다")

        # -- 실행 ----------------------------------------------------------
        row += 1
        ttk.Label(inner, textvariable=self.ready_var, style="Muted.TLabel",
                  justify="left", wraplength=theme.px(760)).grid(
            row=row, column=0, sticky="w", pady=(12, 0))

        row += 1
        runs = ttk.Frame(inner)
        runs.grid(row=row, column=0, sticky="w", pady=(10, 0))
        ttk.Button(runs, text="▶ 제작 시작", style="Accent.TButton",
                   command=self._start).pack(side="left")
        ttk.Button(runs, text="■ 정지", command=self.engine.stop_all).pack(
            side="left", padx=6)
        ttk.Button(runs, text="치트엔진만 해보기", style="Small.TButton",
                   command=lambda: self._try("speedhack")).pack(side="left", padx=(16, 4))
        ttk.Button(runs, text="다시 접속만 해보기", style="Small.TButton",
                   command=lambda: self._try("reconnect")).pack(side="left", padx=4)
        ttk.Button(runs, text="한 바퀴만 돌려보기", style="Small.TButton",
                   command=lambda: self._try("one")).pack(side="left", padx=4)

        row += 1
        ttk.Label(inner, style="Faint.TLabel", justify="left",
                  wraplength=theme.px(760),
                  text=("시작하기 전에 하나씩 눌러 보면 어디가 어긋나는지 바로 "
                        "보입니다. [치트엔진만 해보기]는 배속을 거는 데까지, "
                        "[다시 접속만 해보기]는 게임을 끄고 다시 들어오는 데까지, "
                        "[한 바퀴만]은 ①~④를 한 번만 돕니다.")).grid(
            row=row, column=0, sticky="w", pady=(6, 0))

        for var in (self.home_var, self.channel_var, self.ce_var, self.plist_var,
                    self.target_var, self.speed_var, self.quiet_var,
                    self.site_var, self.url_var, self.names_var,
                    self.client_var, self.cwait_var, self.gwait_var,
                    self.tries_var, self.load_var, self.kill_var,
                    self.gap_var, self.retry_var):
            var.trace_add("write", lambda *_a: self._save())
        for var in (self.bgap_var, self.esc_var, self.escgap_var):
            var.trace_add("write", lambda *_a: self._save_buffs())
        self.refresh()
        self._tick()   # 남은 시간을 1초마다 새로 적는다

    # ------------------------------------------------------------------
    def _macro_row(self, parent, row: int, label: str, var, hint: str):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=3)
        box = ttk.Combobox(parent, textvariable=var, width=34, state="readonly")
        box.grid(row=row, column=1, sticky="w", padx=(8, 8))
        ttk.Label(parent, text=hint, style="Faint.TLabel").grid(
            row=row, column=2, sticky="w")
        return box

    def _buff_row(self, parent, row: int, index: int) -> dict:
        """버프 한 줄 — 켬 · 키 · 이름 · 주기 · 남은 시간 · [지금] · [이번만]."""
        on = tk.BooleanVar()
        key = tk.StringVar()
        name = tk.StringVar()
        period = tk.StringVar()
        left = tk.StringVar()
        once = tk.StringVar()
        ttk.Checkbutton(parent, variable=on, command=self._save_buffs).grid(
            row=row, column=0, sticky="w")
        ttk.Entry(parent, textvariable=key, width=4).grid(
            row=row, column=1, sticky="w", padx=(0, 6))
        ttk.Entry(parent, textvariable=name, width=10).grid(
            row=row, column=2, sticky="w", padx=(0, 6))
        ttk.Entry(parent, textvariable=period, width=7).grid(
            row=row, column=3, sticky="w", padx=(0, 6))
        ttk.Label(parent, textvariable=left, width=16).grid(
            row=row, column=4, sticky="w", padx=(0, 6))
        ttk.Button(parent, text="지금", style="Small.TButton",
                   command=lambda i=index: self._buff_now(i)).grid(
            row=row, column=5, sticky="w", padx=(0, 10))
        ttk.Entry(parent, textvariable=once, width=7).grid(
            row=row, column=6, sticky="w", padx=(0, 4))
        ttk.Button(parent, text="이번만 적용", style="Small.TButton",
                   command=lambda i=index: self._buff_once(i)).grid(
            row=row, column=7, sticky="w")
        for var in (key, name, period):
            var.trace_add("write", lambda *_a: self._save_buffs())
        return {"on": on, "key": key, "name": name, "period": period,
                "left": left, "once": once}

    def _buff_now(self, index: int) -> None:
        """다음 바퀴에 바로 쓰게 한다 (남은 시간 0)."""
        self.engine.profile.craft.buffs[index].due_at = 0.0
        self.engine.save()
        self._sync_buffs()

    def _buff_once(self, index: int) -> None:
        """이번 한 번만 남은 시간을 바꾼다. 주기는 그대로."""
        import time

        row = self.buff_rows[index]
        minutes = get_float(row["once"], -1)
        if minutes < 0:
            messagebox.showinfo("제작", "몇 분 뒤에 쓸지 적어 주세요.", parent=self)
            return
        buff = self.engine.profile.craft.buffs[index]
        buff.hold(time.time(), minutes)
        self.engine.save()
        self._sync_buffs()
        self.engine.log(f"제작 버프 '{buff.name}': 이번만 {minutes:g}분 뒤에 "
                        f"씁니다 (주기 {buff.period_min:g}분은 그대로).")

    def _save_buffs(self) -> None:
        if self._loading:
            return
        setup = self.engine.profile.craft
        for row, buff in zip(self.buff_rows, setup.buffs):
            buff.on = bool(row["on"].get())
            buff.key = row["key"].get().strip()
            buff.name = row["name"].get().strip()
            buff.period_min = max(0.0, min(10080.0, get_float(row["period"], 0)))
        setup.buff_gap_s = max(0.1, min(30.0, get_float(self.bgap_var, 2.0)))
        setup.esc_times = max(0, min(10, int(get_float(self.esc_var, 2))))
        setup.esc_gap_s = max(0.05, min(5.0, get_float(self.escgap_var, 0.3)))
        self.engine.save()

    def _sync_buffs(self) -> None:
        """남은 시간을 새로 적는다. 1초마다 저절로 돈다."""
        import time

        now = time.time()
        self._loading = True
        for row, buff in zip(self.buff_rows, self.engine.profile.craft.buffs):
            if row["on"].get() != buff.on:
                row["on"].set(buff.on)
            if row["key"].get() != buff.key:
                row["key"].set(buff.key)
            if row["name"].get() != buff.name:
                row["name"].set(buff.name)
            if get_float(row["period"], -1) != buff.period_min:
                row["period"].set(f"{buff.period_min:g}")
            row["left"].set(buff.describe(now))
        setup = self.engine.profile.craft
        if get_float(self.bgap_var, -1) != setup.buff_gap_s:
            self.bgap_var.set(f"{setup.buff_gap_s:g}")
        if get_float(self.esc_var, -1) != setup.esc_times:
            self.esc_var.set(str(setup.esc_times))
        if get_float(self.escgap_var, -1) != setup.esc_gap_s:
            self.escgap_var.set(f"{setup.esc_gap_s:g}")
        self._loading = False

    def _tick(self) -> None:
        try:
            if self.winfo_exists():
                self._sync_buffs()
        finally:
            self.after(1000, self._tick)

    def _title_entry(self, parent, label: str, var, width: int) -> None:
        ttk.Label(parent, text=label).pack(side="left", padx=(0, 4))
        ttk.Entry(parent, textvariable=var, width=width).pack(side="left",
                                                              padx=(0, 10))

    def _spot_row(self, parent, row: int, attr: str, label: str,
                  where_var) -> None:
        """자리 한 줄 — [찍기] · 지금 값 · 지우기."""
        var = tk.StringVar(value="")
        self.spot_vars[attr] = var
        ttk.Label(parent, text=label, width=24).grid(row=row, column=0,
                                                     sticky="w", pady=2)
        ttk.Button(parent, text="🎯 찍기", style="Small.TButton",
                   command=lambda a=attr, w=where_var: self._pick(a, w)).grid(
            row=row, column=1, padx=(6, 6))
        ttk.Label(parent, textvariable=var, style="Faint.TLabel").grid(
            row=row, column=2, sticky="w")
        ttk.Button(parent, text="지우기", style="Small.TButton",
                   command=lambda a=attr: self._clear_spot(a)).grid(
            row=row, column=3, padx=(8, 0))

    def _time_row(self, grid, row: int, label: str, var, hint: str) -> None:
        ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(grid, textvariable=var, width=6).grid(row=row, column=1,
                                                        padx=(8, 4))
        ttk.Label(grid, text="초").grid(row=row, column=2, sticky="w")
        ttk.Label(grid, text=hint, style="Faint.TLabel").grid(
            row=row, column=3, sticky="w", padx=(12, 0))

    # ------------------------------------------------------------------
    def _pick(self, attr: str, where_var) -> None:
        """그 자리를 화면에서 직접 클릭해 정한다.

        창 제목을 적어 둔 자리는 **그 창 안쪽 좌표**로 적는다. 제목이 비어 있거나
        창을 못 찾으면 화면 절대좌표로 적는다 — 로딩 창처럼 제목을 모르는 것도
        있기 때문이다.
        """
        title = (where_var.get().strip() if where_var is not None else "")
        window = None
        if title:
            info = find_window(title)
            if info is None:
                if not messagebox.askyesno(
                        "제작",
                        f"'{title}' 창을 지금 못 찾았습니다.\n\n"
                        "화면 기준 좌표로 찍을까요?\n"
                        "(그 창을 먼저 띄워 두면 창 기준으로 찍습니다 — "
                        "창을 옮겨도 그대로 눌립니다)", parent=self):
                    return
            else:
                window = GameWindow(info.hwnd, info.title)

        got = capture_click_point(self.winfo_toplevel(), window)
        if got is None:
            return
        cx, cy, _color = got
        spot = getattr(self.engine.profile.craft, attr)
        spot.where = title if window is not None else ""
        spot.x, spot.y = int(cx), int(cy)
        self.engine.save()
        self._sync_spots()
        self.engine.log(f"제작: '{attr}' 자리를 {spot.describe()}로 정했습니다.")

    def _clear_spot(self, attr: str) -> None:
        spot = getattr(self.engine.profile.craft, attr)
        spot.where, spot.x, spot.y = "", -1, -1
        self.engine.save()
        self._sync_spots()

    def _on_sound(self) -> None:
        self.engine.save()
        self._sync_ready()

    def _reload_macros(self) -> None:
        names = [m.name for m in self.engine.profile.macros]
        self.home_box.configure(values=names)
        self.channel_box.configure(values=names)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        setup = self.engine.profile.craft
        self._loading = True
        self.home_var.set(setup.home_macro)
        self.channel_var.set(setup.channel_macro)
        self.ce_var.set(setup.ce_title)
        self.plist_var.set(setup.plist_title)
        self.target_var.set(setup.target_name)
        self.speed_var.set(setup.speed_value)
        self.double_var.set(bool(setup.row_double))
        self.quiet_var.set(f"{setup.quiet_s:g}")
        self.site_var.set(setup.site_title)
        self.url_var.set(setup.site_url)
        self.names_var.set(setup.start_names)
        self.client_var.set(setup.client_title)
        self.cwait_var.set(f"{setup.client_wait_s:g}")
        self.gwait_var.set(f"{setup.game_wait_s:g}")
        self.tries_var.set(str(setup.connect_tries))
        self.load_var.set(f"{setup.load_wait_s:g}")
        self.kill_var.set(f"{setup.after_kill_s:g}")
        self.gap_var.set(f"{setup.step_gap_s:g}")
        self.retry_var.set(f"{setup.retry_s:g}")
        self._loading = False
        self._reload_macros()
        self.sound_row.refresh()
        self._sync_spots()
        self._sync_buffs()

    def _sync_spots(self) -> None:
        setup = self.engine.profile.craft
        for attr, var in self.spot_vars.items():
            var.set(getattr(setup, attr).describe())
        self._sync_ready()

    def _sync_ready(self) -> None:
        setup = self.engine.profile.craft
        problems = setup.problems()
        if problems:
            self.ready_var.set("아직 못 정한 것: " + " · ".join(problems))
        else:
            self.ready_var.set(
                f"준비됐습니다 — 배속 {setup.speed_value}배 · 무음 "
                f"{setup.quiet_s:g}초 · 여태 {setup.cycles}바퀴")

    def _save(self) -> None:
        if self._loading:
            return
        setup = self.engine.profile.craft
        setup.home_macro = self.home_var.get().strip()
        setup.channel_macro = self.channel_var.get().strip()
        setup.ce_title = self.ce_var.get().strip() or "Cheat Engine"
        setup.plist_title = self.plist_var.get().strip() or "Process List"
        setup.target_name = self.target_var.get().strip()
        setup.speed_value = self.speed_var.get().strip() or "17000"
        setup.row_double = bool(self.double_var.get())
        setup.quiet_s = max(1.0, min(600.0, get_float(self.quiet_var, 10.0)))
        setup.site_title = self.site_var.get().strip()
        setup.site_url = self.url_var.get().strip()
        setup.start_names = self.names_var.get().strip() or "GAME START"
        setup.client_title = self.client_var.get().strip() or "Z9Star"
        setup.client_wait_s = max(5.0, min(600.0, get_float(self.cwait_var, 10.0)))
        setup.game_wait_s = max(5.0, min(600.0, get_float(self.gwait_var, 10.0)))
        setup.connect_tries = max(1, min(10, int(get_float(self.tries_var, 3))))
        setup.load_wait_s = max(0.0, min(300.0, get_float(self.load_var, 10.0)))
        setup.after_kill_s = max(0.0, min(60.0, get_float(self.kill_var, 2.0)))
        setup.step_gap_s = max(0.05, min(10.0, get_float(self.gap_var, 0.8)))
        setup.retry_s = max(1.0, min(120.0, get_float(self.retry_var, 5.0)))
        self.engine.save()
        self._sync_ready()

    # ------------------------------------------------------------------
    def _start(self) -> None:
        setup = self.engine.profile.craft
        problems = setup.problems()
        if problems:
            messagebox.showwarning(
                "제작", "먼저 정해 주세요:\n\n· " + "\n· ".join(problems),
                parent=self)
            return
        self.engine.run("craft", "제작")

    def _try(self, what: str) -> None:
        """한 단계만 돌려 본다. 어디가 어긋나는지 보는 용도."""
        labels = {"buffs": "제작 · 버프만",
                  "speedhack": "제작 · 치트엔진만",
                  "reconnect": "제작 · 다시 접속만",
                  "one": "제작 · 한 바퀴만"}
        self.engine.run(f"craft:{what}", labels[what])
