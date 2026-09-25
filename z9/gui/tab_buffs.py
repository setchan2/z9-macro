"""탭 — 버프 아이템.

지속시간이 정해져 있는 아이템을 등록해 두면, 시나리오 그룹이 한 사이클 돌 때마다
만료된 것만 골라 다시 쓴다. 남은 시간은 화면에서 읽지 않고 **쓴 시각 + 지속시간**
으로 계산한다 — 지속시간이 고정이라 이게 더 정확하고 아이콘이 가려져도 동작한다.
"""

from __future__ import annotations

import copy
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import buffs as buffmod
from .. import imagematch, png
from ..keys import KEY_CHOICES
from ..model import KNOWN_BUFFS, BuffItem
from ..player import RunContext
from .base import ListEditorTab
from .icon_watch import IconWatchPanel
from .widgets import ScrollFrame, capture_click_point, get_int, int_entry

DETECT_LABELS = {
    "timer": "시간으로 (쓴 시각 + 지속시간)",
    "icon": "화면으로 (버프바에서 아이콘을 찾음)",
}
DETECT_BY_LABEL = {v: k for k, v in DETECT_LABELS.items()}
DETECT_HINTS = {
    "timer": "지속시간이 정해진 아이템에 가장 확실합니다. 버프바가 가려져 있어도 "
    "동작하고, 화면을 읽지 않으니 공짜입니다.",
    "icon": "버프바에서 그 효과의 아이콘을 찾아 없으면 다시 씁니다. 다른 데서 이미 "
    "걸어 둔 버프까지 챙기고, 지속시간이 들쭉날쭉해도 맞습니다. 대신 버프바가 "
    "가려지면 못 보고, 확인 한 번에 0.1초쯤 듭니다.",
}

USE_LABELS = {"quickslot": "퀵슬롯 키", "inventory": "인벤토리 아이콘"}
USE_BY_LABEL = {v: k for k, v in USE_LABELS.items()}

# 게임의 퀵슬롯 자리
QUICKSLOT_KEYS = ["5", "6", "7", "8", "9", "0", "-", "="]


class BuffTab(ListEditorTab):
    kind = "buff"
    noun = "버프"

    # ------------------------------------------------------------------
    def items(self) -> list[BuffItem]:
        return self.engine.profile.buffs

    def columns(self) -> list[tuple[str, str, int]]:
        return [
            ("name", "이름", 130),
            ("dur", "지속", 60),
            ("how", "사용", 90),
            ("left", "남은 시간", 80),
        ]

    def row_values(self, item: BuffItem) -> tuple:
        now = time.time()
        if item.detect_kind == "icon":
            left_text = "화면 감지"
            duration = "화면"
        else:
            duration = f"{item.duration_min}분"
            left = item.remaining(now)
            if item.last_used <= 0:
                left_text = "미사용"
            elif left <= 0:
                left_text = "만료됨"
            else:
                left_text = f"{left / 60:.0f}분"
        how = item.key if item.use_kind == "quickslot" else (item.icon or "그림 없음")
        return (item.name, duration, how, left_text)

    def new_item(self) -> BuffItem:
        return BuffItem(name="새 버프")

    def copy_item(self, item: BuffItem) -> BuffItem:
        clone = copy.deepcopy(item)
        clone.last_used = 0.0
        return clone

    # ------------------------------------------------------------------
    def build_form(self, outer: ttk.Frame) -> None:
        # 감지 방식까지 들어가면서 폼이 길어졌다. 창을 줄여도 아래가 잘리지
        # 않도록 통째로 스크롤되는 칸에 담는다.
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        scroller = ScrollFrame(outer)
        scroller.grid(row=0, column=0, sticky="nsew")
        parent = scroller.inner

        self.detect_var = tk.StringVar(value=DETECT_LABELS["timer"])
        self.name_var = tk.StringVar()
        self.duration_var = tk.StringVar(value="15")
        self.use_var = tk.StringVar(value=USE_LABELS["quickslot"])
        self.key_var = tk.StringVar(value="5")
        self.icon_var = tk.StringVar(value="")
        self.open_var = tk.StringVar(value="I")
        self.close_var = tk.StringVar(value="I")
        self.wait_var = tk.StringVar(value="500")
        self.button_var = tk.StringVar(value="right")
        self.tol_var = tk.StringVar(value="30")
        self.area_var = tk.StringVar(value="")

        row = 0
        ttk.Label(parent, text="이름").grid(row=row, column=0, sticky="w", pady=4)
        name_box = ttk.Combobox(
            parent, textvariable=self.name_var, width=24,
            values=[n for n, _m in KNOWN_BUFFS],
        )
        name_box.grid(row=row, column=1, sticky="w", pady=4)
        name_box.bind("<<ComboboxSelected>>", lambda _e: self._fill_known())

        ttk.Label(parent, text="지속시간(분)").grid(row=row, column=2, sticky="w", padx=(14, 6))
        self.duration_entry = int_entry(parent, self.duration_var, width=6)
        self.duration_entry.grid(row=row, column=3, sticky="w")

        row += 1
        ttk.Label(
            parent, style="Faint.TLabel",
            text="알려진 지속시간 — 직업별 왕관 15분 · 갈비탕 30분 · 경카 1시간 · 점검사 6시간",
        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(0, 8))

        # -- 남은 시간을 무엇으로 아는가 ----------------------------------
        # 이 프로그램에서 버프가 "끊겼다"를 판단하는 방식은 이 둘뿐이고,
        # 어느 쪽을 고르느냐가 나머지 설정을 전부 바꾼다. 그래서 맨 위에 둔다.
        row += 1
        detect = ttk.LabelFrame(parent, text="남은 시간을 무엇으로 아는가", padding=10)
        detect.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        detect.columnconfigure(0, weight=1)

        detect_box = ttk.Combobox(
            detect, textvariable=self.detect_var, values=list(DETECT_LABELS.values()),
            width=34, state="readonly",
        )
        detect_box.grid(row=0, column=0, sticky="w")
        detect_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_detect())

        self.detect_hint = ttk.Label(
            detect, style="Faint.TLabel", justify="left", wraplength=620, text=""
        )
        self.detect_hint.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.watch_frame = ttk.Frame(detect)
        self.watch_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.watch_frame.columnconfigure(0, weight=1)

        confirm_row = ttk.Frame(self.watch_frame)
        confirm_row.grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Label(confirm_row, text="몇 번 연속 안 보이면 끝난 것으로 볼지").pack(side="left")
        self.confirm_var = tk.StringVar(value="2")
        int_entry(confirm_row, self.confirm_var, width=5).pack(side="left", padx=(8, 6))
        ttk.Label(
            confirm_row, style="Faint.TLabel",
            text="다른 창이 잠깐 겹쳤다고 멀쩡한 버프를 덧씌우지 않게 합니다",
        ).pack(side="left")

        self.watch_panel = IconWatchPanel(self.watch_frame, self.engine, show_expect=False)
        self.watch_panel.grid(row=1, column=0, sticky="ew")

        # -- 사용 방법 ---------------------------------------------------
        row += 1
        how = ttk.LabelFrame(parent, text="어떻게 쓰는가", padding=10)
        how.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        use_box = ttk.Combobox(
            how, textvariable=self.use_var, values=list(USE_LABELS.values()),
            width=16, state="readonly",
        )
        use_box.grid(row=0, column=0, sticky="w")
        use_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_use())

        ttk.Label(how, text="퀵슬롯 키").grid(row=0, column=1, sticky="w", padx=(14, 6))
        self.key_box = ttk.Combobox(
            how, textvariable=self.key_var, width=6,
            values=QUICKSLOT_KEYS + KEY_CHOICES,
        )
        self.key_box.grid(row=0, column=2, sticky="w")

        # -- 인벤토리 방식 ------------------------------------------------
        self.inv = ttk.Frame(how)
        self.inv.grid(row=1, column=0, columnspan=5, sticky="ew", pady=(10, 0))

        ttk.Label(self.inv, text="아이콘 그림").grid(row=0, column=0, sticky="w")
        ttk.Entry(self.inv, textvariable=self.icon_var, width=26, state="readonly").grid(
            row=0, column=1, sticky="w", padx=6
        )
        ttk.Button(
            self.inv, text="🎯 화면에서 잘라내기", style="Small.TButton",
            command=self._capture_icon,
        ).grid(row=0, column=2, sticky="w")
        ttk.Button(
            self.inv, text="PNG 불러오기", style="Small.TButton", command=self._load_icon
        ).grid(row=0, column=3, sticky="w", padx=6)

        ttk.Label(self.inv, text="인벤토리 열기").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            self.inv, textvariable=self.open_var, values=KEY_CHOICES, width=6
        ).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(self.inv, text="닫기").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Combobox(
            self.inv, textvariable=self.close_var, values=KEY_CHOICES, width=6
        ).grid(row=1, column=3, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(self.inv, text="열릴 때까지(ms)").grid(row=2, column=0, sticky="w", pady=(8, 0))
        int_entry(self.inv, self.wait_var, width=7).grid(
            row=2, column=1, sticky="w", padx=6, pady=(8, 0)
        )
        ttk.Label(self.inv, text="클릭").grid(row=2, column=2, sticky="w", pady=(8, 0))
        ttk.Combobox(
            self.inv, textvariable=self.button_var, values=["right", "left"],
            width=6, state="readonly",
        ).grid(row=2, column=3, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(self.inv, text="일치 허용 오차").grid(row=3, column=0, sticky="w", pady=(8, 0))
        int_entry(self.inv, self.tol_var, width=6).grid(
            row=3, column=1, sticky="w", padx=6, pady=(8, 0)
        )
        ttk.Button(
            self.inv, text="찾을 영역 지정", style="Small.TButton", command=self._set_area
        ).grid(row=3, column=2, sticky="w", pady=(8, 0))
        ttk.Button(
            self.inv, text="영역 해제", style="Small.TButton", command=self._clear_area
        ).grid(row=3, column=3, sticky="w", padx=6, pady=(8, 0))

        ttk.Label(self.inv, textvariable=self.area_var, style="Faint.TLabel").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0)
        )

        # -- 타이머 ------------------------------------------------------
        row += 1
        timer = ttk.LabelFrame(parent, text="남은 시간", padding=10)
        timer.grid(row=row, column=0, columnspan=4, sticky="ew", pady=(12, 0))

        self.left_var = tk.StringVar(value="")
        ttk.Label(timer, textvariable=self.left_var, style="Accent.TLabel").pack(anchor="w")

        buttons = ttk.Frame(timer)
        buttons.pack(anchor="w", pady=(8, 0))
        ttk.Button(buttons, text="지금 써보기", command=self._use_now).pack(side="left")
        ttk.Button(buttons, text="방금 쓴 걸로 표시", command=self._mark_used).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="타이머 초기화", command=self._reset_timer).pack(side="left")

        row += 1
        ttk.Label(
            parent, style="Faint.TLabel", justify="left",
            text="시나리오 편집기에서 그룹을 고르고 이 버프를 붙이면, 그룹이 한 사이클\n"
            "돌 때마다 만료된 것만 다시 씁니다. 남은 시간이 있으면 건너뜁니다.",
        ).grid(row=row, column=0, columnspan=4, sticky="w", pady=(12, 0))

        self._sync_use()
        self.after(1000, self._tick)

    def build_actions(self, parent: ttk.Frame) -> None:
        # 버프는 '실행'이라는 개념이 없다. 목록 위 버튼은 감춘다.
        self.run_button.pack_forget()

    # ------------------------------------------------------------------
    def _fill_known(self) -> None:
        for name, minutes in KNOWN_BUFFS:
            if name == self.name_var.get():
                self.duration_var.set(str(minutes))
                break

    def _sync_use(self) -> None:
        kind = USE_BY_LABEL.get(self.use_var.get(), "quickslot")
        self.key_box.configure(state="normal" if kind == "quickslot" else "disabled")
        if kind == "inventory":
            self.inv.grid()
        else:
            self.inv.grid_remove()

    def _sync_detect(self) -> None:
        kind = DETECT_BY_LABEL.get(self.detect_var.get(), "timer")
        self.detect_hint.configure(text=DETECT_HINTS[kind])
        if kind == "icon":
            self.watch_frame.grid()
        else:
            self.watch_frame.grid_remove()
        # 지속시간은 시간 방식일 때만 의미가 있다.
        state = "disabled" if kind == "icon" else "normal"
        self.duration_entry.configure(state=state)

    def _tick(self) -> None:
        if not self.winfo_exists():
            return
        item = self.selected()
        if item is not None and item.detect_kind == "icon":
            self.left_var.set(
                "화면으로 확인합니다 — 아래 [지금 확인]을 눌러 지금 보이는지 시험해 보세요."
            )
        elif item is not None:
            now = time.time()
            if item.last_used <= 0:
                self.left_var.set("아직 쓴 적이 없습니다 — 다음 사이클에 사용됩니다.")
            else:
                left = item.remaining(now)
                used_at = time.strftime("%H:%M:%S", time.localtime(item.last_used))
                self.left_var.set(
                    f"{used_at}에 사용 · "
                    + (f"{left / 60:.1f}분 남음" if left > 0 else "만료됨 — 다음 사이클에 다시 사용")
                )
        self.after(1000, self._tick)

    # ------------------------------------------------------------------
    def _capture_icon(self) -> None:
        """게임 화면에서 아이콘의 좌상단·우하단을 찍어 잘라낸다."""
        item = self.selected()
        window = self.engine.window()
        if item is None:
            return
        if window is None:
            messagebox.showwarning("게임 창 없음", "대상 게임 창을 먼저 지정하세요.", parent=self)
            return

        messagebox.showinfo(
            "아이콘 잘라내기",
            "인벤토리를 열어 아이콘이 보이게 한 뒤,\n"
            "아이콘의 왼쪽 위 → 오른쪽 아래 순서로 두 번 클릭하세요.",
            parent=self,
        )
        first = capture_click_point(self.winfo_toplevel(), window)
        if first is None:
            return
        second = capture_click_point(self.winfo_toplevel(), window)
        if second is None:
            return

        x1, y1 = min(first[0], second[0]), min(first[1], second[1])
        x2, y2 = max(first[0], second[0]), max(first[1], second[1])
        w, h = x2 - x1, y2 - y1
        if w < 4 or h < 4:
            messagebox.showwarning(
                "너무 작습니다", f"잘라낸 영역이 {w}x{h}입니다. 다시 찍어 주세요.", parent=self
            )
            return

        sx, sy = window.client_to_screen(x1, y1)
        try:
            template = imagematch.capture_template(sx, sy, w, h)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("캡처 실패", str(exc), parent=self)
            return

        folder = buffmod.icon_dir(self.engine.library_root)
        folder.mkdir(parents=True, exist_ok=True)
        from ..library import safe_name

        filename = f"{safe_name(item.name)}.png"
        try:
            png.write_rgb(folder / filename, template.width, template.height, template.data)
        except (png.PngError, OSError) as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return

        buffmod.TEMPLATES.clear()
        self.icon_var.set(filename)
        self.commit()
        self.engine.log(
            f"'{item.name}': 아이콘 {w}x{h} 저장 → {folder / filename}"
        )

    def _load_icon(self) -> None:
        item = self.selected()
        if item is None:
            return
        chosen = filedialog.askopenfilename(
            title="아이콘 PNG 고르기",
            filetypes=[("PNG 이미지", "*.png")],
            parent=self,
        )
        if not chosen:
            return
        try:
            width, height, rgb = png.read_rgb(chosen)
        except (png.PngError, OSError) as exc:
            messagebox.showerror("읽지 못했습니다", str(exc), parent=self)
            return

        folder = buffmod.icon_dir(self.engine.library_root)
        folder.mkdir(parents=True, exist_ok=True)
        from ..library import safe_name

        filename = f"{safe_name(item.name)}.png"
        try:
            png.write_rgb(folder / filename, width, height, rgb)
        except (png.PngError, OSError) as exc:
            messagebox.showerror("저장 실패", str(exc), parent=self)
            return

        buffmod.TEMPLATES.clear()
        self.icon_var.set(filename)
        self.commit()
        self.engine.log(f"'{item.name}': 아이콘 {width}x{height} 불러옴 → {filename}")

    def _set_area(self) -> None:
        item = self.selected()
        window = self.engine.window()
        if item is None or window is None:
            return
        messagebox.showinfo(
            "찾을 영역 지정",
            "인벤토리 영역의 왼쪽 위 → 오른쪽 아래 순서로 두 번 클릭하세요.\n"
            "영역을 좁힐수록 찾는 속도가 빨라집니다.",
            parent=self,
        )
        first = capture_click_point(self.winfo_toplevel(), window)
        if first is None:
            return
        second = capture_click_point(self.winfo_toplevel(), window)
        if second is None:
            return
        x1, y1 = min(first[0], second[0]), min(first[1], second[1])
        x2, y2 = max(first[0], second[0]), max(first[1], second[1])
        item.search_x, item.search_y = x1, y1
        item.search_w, item.search_h = x2 - x1, y2 - y1
        self._show_area(item)
        self.engine.log(
            f"'{item.name}': 찾을 영역 ({x1}, {y1}) {item.search_w}x{item.search_h}"
        )

    def _clear_area(self) -> None:
        item = self.selected()
        if item is None:
            return
        item.search_w = item.search_h = 0
        self._show_area(item)

    def _show_area(self, item: BuffItem) -> None:
        if item.search_w > 0 and item.search_h > 0:
            self.area_var.set(
                f"찾을 영역: ({item.search_x}, {item.search_y}) "
                f"{item.search_w}x{item.search_h}"
            )
        else:
            self.area_var.set("찾을 영역: 게임 창 전체 (느립니다 — 영역을 지정하면 빨라집니다)")

    # ------------------------------------------------------------------
    def _use_now(self) -> None:
        self.commit()
        item = self.selected()
        if item is None:
            return
        window = self.engine.window()
        if window is None:
            self.engine.log("게임 창을 찾지 못해 버프를 쓸 수 없습니다.")
            return
        privileged, message = self.engine.privilege_report()
        if not privileged:
            self.engine.log(f"버프 사용 불가 — {message}")
            return

        ctx = RunContext(self.engine.settings, window, self.engine.log)
        ctx.library_root = self.engine.library_root
        ok, detail = buffmod.use_buff(item, ctx, self.engine.library_root)
        if ok:
            item.last_used = time.time()
            self.engine.log(f"'{item.name}' 사용 — {detail}")
        else:
            self.engine.log(f"'{item.name}' 사용 실패 — {detail}")
        self.refresh(select_name=item.name)

    def _mark_used(self) -> None:
        item = self.selected()
        if item is None:
            return
        item.last_used = time.time()
        self.engine.log(f"'{item.name}': 방금 쓴 것으로 표시 ({item.duration_min}분)")
        self.refresh(select_name=item.name)

    def _reset_timer(self) -> None:
        item = self.selected()
        if item is None:
            return
        item.last_used = 0.0
        self.refresh(select_name=item.name)

    # ------------------------------------------------------------------
    def load_form(self, item: BuffItem) -> None:
        self.name_var.set(item.name)
        self.duration_var.set(str(item.duration_min))
        self.use_var.set(USE_LABELS.get(item.use_kind, USE_LABELS["quickslot"]))
        self.key_var.set(item.key)
        self.icon_var.set(item.icon)
        self.open_var.set(item.open_key)
        self.close_var.set(item.close_key)
        self.wait_var.set(str(item.open_wait_ms))
        self.button_var.set(item.click_button)
        self.tol_var.set(str(item.tolerance))
        self.detect_var.set(DETECT_LABELS.get(item.detect_kind, DETECT_LABELS["timer"]))
        self.confirm_var.set(str(max(1, item.watch_confirm)))
        self.watch_panel.load(item.watch)
        self._show_area(item)
        self._sync_use()
        self._sync_detect()

    def save_form(self, item: BuffItem) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.duration_min = max(get_int(self.duration_var, 15), 1)
        item.use_kind = USE_BY_LABEL.get(self.use_var.get(), "quickslot")
        item.key = self.key_var.get().strip() or item.key
        item.icon = self.icon_var.get().strip()
        item.open_key = self.open_var.get().strip() or "I"
        item.close_key = self.close_var.get().strip() or item.open_key
        item.open_wait_ms = max(get_int(self.wait_var, 500), 0)
        item.click_button = self.button_var.get() or "right"
        item.tolerance = max(get_int(self.tol_var, 30), 1)
        item.detect_kind = DETECT_BY_LABEL.get(self.detect_var.get(), "timer")
        item.watch_confirm = max(1, get_int(self.confirm_var, 2))
        self.watch_panel.save(item.watch)
        if renamed:
            self.refresh(select_name=item.name)
