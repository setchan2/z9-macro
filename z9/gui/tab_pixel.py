"""탭 4 — 조건부 실행 (픽셀 색 감지)."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import ttk

from .. import pixel
from ..keys import KEY_CHOICES
from ..model import IconWatch, NumberWatch, PixelPoint, PixelRule
from ..player import RunContext
from ..tasks import evaluate_rule
from . import theme
from .base import ListEditorTab
from .icon_watch import EXPECT_LABELS, IconWatchPanel
from .number_watch import NumberWatchPanel
from .widgets import ScrollFrame, capture_click_point, get_int, int_entry

MATCH_LABELS = {"all": "모두 성립해야", "any": "하나라도 성립하면"}
MATCH_BY_LABEL = {v: k for k, v in MATCH_LABELS.items()}

COND_LABELS = {"match": "성립할 때", "differ": "어긋났을 때"}
COND_BY_LABEL = {v: k for k, v in COND_LABELS.items()}

ACTION_LABELS = {
    "key": "키 입력",
    "click": "찾은 그림 누르기",
    "macro": "녹화 매크로 실행",
    "path": "이동 경로 실행",
}
ACTION_BY_LABEL = {v: k for k, v in ACTION_LABELS.items()}


class PixelTab(ListEditorTab):
    kind = "rule"
    noun = "조건"

    def items(self) -> list[PixelRule]:
        return self.engine.profile.rules

    def columns(self) -> list[tuple[str, str, int]]:
        return [("name", "이름", 150), ("what", "감지", 70), ("action", "동작", 90)]

    def row_values(self, item: PixelRule) -> tuple:
        target = item.action_key if item.action_kind == "key" else item.action_target
        what = []
        if item.points:
            what.append(f"점{len(item.points)}")
        if item.icons:
            what.append(f"그림{len(item.icons)}")
        if item.numbers:
            what.append(f"숫자{len(item.numbers)}")
        return (
            item.name,
            " ".join(what) or "-",
            f"{ACTION_LABELS[item.action_kind]}: {target}",
        )

    def new_item(self) -> PixelRule:
        return PixelRule(name="새 조건")

    def copy_item(self, item: PixelRule) -> PixelRule:
        return copy.deepcopy(item)

    def item_name(self, item: PixelRule) -> str:
        return item.name

    # ------------------------------------------------------------------
    def build_form(self, parent: ttk.Frame) -> None:
        # 조건 하나에 들어가는 설정이 많아 창 높이에 따라 아래가 잘린다.
        # 통째로 스크롤되는 칸에 담아 어느 크기에서도 끝까지 닿게 한다.
        parent.rowconfigure(0, weight=1)
        parent.columnconfigure(0, weight=1)
        scroller = ScrollFrame(parent)
        scroller.grid(row=0, column=0, sticky="nsew")
        body = scroller.inner
        body.columnconfigure(0, weight=1)

        self.name_var = tk.StringVar()
        self.tol_var = tk.StringVar(value="12")
        self.match_var = tk.StringVar(value=MATCH_LABELS["all"])
        self.cond_var = tk.StringVar(value=COND_LABELS["match"])
        self.check_var = tk.StringVar(value="300")
        self.cool_var = tk.StringVar(value="1500")
        self.confirm_var = tk.StringVar(value="1")
        self.edge_var = tk.BooleanVar(value=True)
        self.action_kind_var = tk.StringVar(value=ACTION_LABELS["key"])
        self.action_key_var = tk.StringVar(value="Z")
        self.action_target_var = tk.StringVar(value="")
        # 지금 그림·숫자 칸에서 고치고 있는 것. 목록에서 다른 것을 고를 때
        # 여기 있던 값을 먼저 되돌려 넣어야 편집이 날아가지 않는다.
        self._editing_icon = None
        self._editing_number = None

        head = ttk.Frame(body)
        head.grid(row=0, column=0, sticky="ew")

        ttk.Label(head, text="이름").grid(row=0, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Entry(head, textvariable=self.name_var, width=24).grid(row=0, column=1, sticky="w")
        ttk.Label(head, text="점 허용 오차").grid(row=0, column=2, sticky="w", padx=(16, 8))
        int_entry(head, self.tol_var, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(head, text="판정").grid(row=1, column=0, sticky="w", pady=4, padx=(0, 8))
        ttk.Combobox(
            head,
            textvariable=self.match_var,
            values=list(MATCH_LABELS.values()),
            width=21,
            state="readonly",
        ).grid(row=1, column=1, sticky="w")
        ttk.Label(head, text="트리거").grid(row=1, column=2, sticky="w", padx=(16, 8))
        ttk.Combobox(
            head,
            textvariable=self.cond_var,
            values=list(COND_LABELS.values()),
            width=16,
            state="readonly",
        ).grid(row=1, column=3, sticky="w")

        ttk.Label(head, text="확인 주기(ms)").grid(row=2, column=0, sticky="w", pady=4, padx=(0, 8))
        int_entry(head, self.check_var, width=8).grid(row=2, column=1, sticky="w")
        ttk.Label(head, text="쿨다운(ms)").grid(row=2, column=2, sticky="w", padx=(16, 8))
        int_entry(head, self.cool_var, width=8).grid(row=2, column=3, sticky="w")

        ttk.Label(head, text="연속 확인 횟수").grid(row=3, column=0, sticky="w", pady=4, padx=(0, 8))
        int_entry(head, self.confirm_var, width=6).grid(row=3, column=1, sticky="w")
        ttk.Label(
            head,
            style="Faint.TLabel",
            text="이만큼 연달아 성립해야 진짜로 봅니다 (한 프레임 깜빡임 방지)",
        ).grid(row=3, column=2, columnspan=2, sticky="w", padx=(16, 0))

        ttk.Checkbutton(
            head,
            text="조건이 거짓에서 참으로 바뀔 때만 실행 (연속 발동 방지)",
            variable=self.edge_var,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # -- 동작 -----------------------------------------------------------
        action = ttk.LabelFrame(body, text="조건 성립 시 동작", padding=8)
        action.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        ttk.Label(action, text="종류").grid(row=0, column=0, sticky="w", padx=(0, 6))
        kind_box = ttk.Combobox(
            action,
            textvariable=self.action_kind_var,
            values=list(ACTION_LABELS.values()),
            width=18,
            state="readonly",
        )
        kind_box.grid(row=0, column=1, sticky="w")
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._sync_action())

        ttk.Label(action, text="키").grid(row=0, column=2, sticky="w", padx=(12, 6))
        self.action_key_box = ttk.Combobox(
            action, textvariable=self.action_key_var, values=KEY_CHOICES, width=10, height=20
        )
        self.action_key_box.grid(row=0, column=3, sticky="w")

        ttk.Label(action, text="대상").grid(row=1, column=0, sticky="w", pady=(8, 0), padx=(0, 6))
        self.action_target_box = ttk.Combobox(
            action, textvariable=self.action_target_var, width=30, state="readonly"
        )
        self.action_target_box.grid(row=1, column=1, columnspan=3, sticky="w", pady=(8, 0))

        # -- 무엇을 볼 것인가 -------------------------------------------------
        # 점과 그림은 성격이 아주 다르다. 점은 자리가 고정된 것(체력바, 창이
        # 열렸는지)에, 그림은 자리가 밀리는 것(버프 아이콘)에 쓴다. 섞어 쓸 수
        # 있지만 화면에서는 나눠 두는 편이 헷갈리지 않는다.
        watch = ttk.Notebook(body)
        watch.grid(row=2, column=0, sticky="ew", pady=(14, 0))

        points_page = ttk.Frame(watch, padding=8)
        icons_page = ttk.Frame(watch, padding=8)
        numbers_page = ttk.Frame(watch, padding=8)
        watch.add(points_page, text="  감지 점 (고정 좌표의 색)  ")
        watch.add(icons_page, text="  감지 그림 (자리가 밀리는 아이콘)  ")
        watch.add(numbers_page, text="  감지 숫자 (피로도 등 값 읽기)  ")

        self._build_points_page(points_page)
        self._build_icons_page(icons_page)
        self._build_numbers_page(numbers_page)

        self.test_var = tk.StringVar(value="")
        ttk.Label(body, textvariable=self.test_var, style="Muted.TLabel", wraplength=620).grid(
            row=3, column=0, sticky="w", pady=(10, 0)
        )

        self._sync_action()

    # ------------------------------------------------------------------
    def _build_points_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page,
            style="Faint.TLabel",
            text="여러 점을 쓰면 오탐이 크게 줄어듭니다. 자리가 바뀌는 것에는 쓸 수 없습니다.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        wrap = ttk.Frame(page)
        wrap.grid(row=1, column=0, sticky="ew")

        self.points_tree = ttk.Treeview(
            wrap,
            columns=("n", "xy", "color"),
            show="headings",
            selectmode="browse",
            height=6,
        )
        self.points_tree.heading("n", text="#")
        self.points_tree.column("n", width=theme.px(32), anchor="e", stretch=False)
        self.points_tree.heading("xy", text="좌표 (창 기준)")
        self.points_tree.column("xy", width=theme.px(140), anchor="w", stretch=False)
        self.points_tree.heading("color", text="기준 색")
        self.points_tree.column("color", width=theme.px(110), anchor="w")
        self.points_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.points_tree.yview)
        bar.pack(side="left", fill="y")
        self.points_tree.configure(yscrollcommand=bar.set)

        tools = ttk.Frame(page)
        tools.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            tools, text="점 추가 (화면 클릭)", style="Small.TButton", command=self._add_point
        ).pack(side="left")
        ttk.Button(
            tools, text="색 다시 읽기", style="Small.TButton", command=self._resample
        ).pack(side="left", padx=6)
        ttk.Button(
            tools, text="점 삭제", style="Small.TButton", command=self._delete_point
        ).pack(side="left")

    # ------------------------------------------------------------------
    def _build_icons_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page,
            style="Faint.TLabel",
            justify="left",
            wraplength=620,
            text="영역 안 어딘가에 있는 그림을 찾습니다. 버프 아이콘처럼 앞엣것이 "
            "끝나면 뒤엣것이 당겨져 자리가 바뀌는 표시는 이쪽으로만 잡을 수 있습니다.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        wrap = ttk.Frame(page)
        wrap.grid(row=1, column=0, sticky="ew")
        self.icons_tree = ttk.Treeview(
            wrap,
            columns=("name", "icon", "expect"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for cid, text, width in (
            ("name", "이름", 140), ("icon", "그림", 150), ("expect", "성립 조건", 110)
        ):
            self.icons_tree.heading(cid, text=text)
            self.icons_tree.column(cid, width=theme.px(width), anchor="w")
        self.icons_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.icons_tree.yview)
        bar.pack(side="left", fill="y")
        self.icons_tree.configure(yscrollcommand=bar.set)
        self.icons_tree.bind("<<TreeviewSelect>>", self._on_icon_select)

        tools = ttk.Frame(page)
        tools.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            tools, text="＋ 그림 조건", style="Small.TButton", command=self._add_icon
        ).pack(side="left")
        ttk.Button(
            tools, text="삭제", style="Small.TButton", command=self._delete_icon
        ).pack(side="left", padx=6)
        ttk.Label(tools, text="이름").pack(side="left", padx=(14, 4))
        self.icon_name_var = tk.StringVar(value="")
        entry = ttk.Entry(tools, textvariable=self.icon_name_var, width=18)
        entry.pack(side="left")
        entry.bind("<FocusOut>", lambda _e: self._rename_icon())
        entry.bind("<Return>", lambda _e: self._rename_icon())

        self.icon_panel = IconWatchPanel(
            page, self.engine, show_expect=True, on_change=self._on_icon_edit
        )
        self.icon_panel.grid(row=3, column=0, sticky="ew", pady=(10, 0))

    # ------------------------------------------------------------------
    def _build_numbers_page(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        ttk.Label(
            page,
            style="Faint.TLabel",
            justify="left",
            wraplength=620,
            text="화면에 적힌 숫자를 실제로 읽어 견줍니다. 피로도처럼 "
            "'10502 / 540000'이라 적힌 것을 읽어, 앞 값이 뒤 값에 닿으면 성립하게 "
            "할 수 있습니다. 최대값을 어디에도 적어 두지 않으므로 최대값이 "
            "달라지는 날에도 그대로 맞습니다.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        wrap = ttk.Frame(page)
        wrap.grid(row=1, column=0, sticky="ew")
        self.numbers_tree = ttk.Treeview(
            wrap,
            columns=("name", "font", "when"),
            show="headings",
            selectmode="browse",
            height=4,
        )
        for cid, text, width in (
            ("name", "이름", 130), ("font", "글꼴", 110), ("when", "성립 조건", 200)
        ):
            self.numbers_tree.heading(cid, text=text)
            self.numbers_tree.column(cid, width=theme.px(width), anchor="w")
        self.numbers_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.numbers_tree.yview)
        bar.pack(side="left", fill="y")
        self.numbers_tree.configure(yscrollcommand=bar.set)
        self.numbers_tree.bind("<<TreeviewSelect>>", self._on_number_select)

        tools = ttk.Frame(page)
        tools.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Button(
            tools, text="＋ 숫자 조건", style="Small.TButton", command=self._add_number
        ).pack(side="left")
        ttk.Button(
            tools, text="삭제", style="Small.TButton", command=self._delete_number
        ).pack(side="left", padx=6)
        ttk.Label(tools, text="이름").pack(side="left", padx=(14, 4))
        self.number_name_var = tk.StringVar(value="")
        entry = ttk.Entry(tools, textvariable=self.number_name_var, width=18)
        entry.pack(side="left")
        entry.bind("<FocusOut>", lambda _e: self._rename_number())
        entry.bind("<Return>", lambda _e: self._rename_number())

        self.number_panel = NumberWatchPanel(
            page, self.engine, on_change=self._on_number_edit
        )
        self.number_panel.grid(row=3, column=0, sticky="ew", pady=(10, 0))

    # ------------------------------------------------------------------
    # 숫자 조건
    # ------------------------------------------------------------------
    def _fill_numbers(self, item: PixelRule, select: int | None = None) -> None:
        self.numbers_tree.delete(*self.numbers_tree.get_children())
        for index, watch in enumerate(item.numbers):
            self.numbers_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    watch.name or f"숫자 {index + 1}",
                    watch.font or "(안 익힘)",
                    watch.describe(),
                ),
            )
        if select is None and item.numbers:
            select = 0
        if select is not None and 0 <= select < len(item.numbers):
            self.numbers_tree.selection_set(str(select))
            # selection_set이 만드는 이벤트는 조금 뒤에 처리된다. 그 사이에 고친
            # 값이 엉뚱한 항목에 들어가지 않도록 편집 칸을 여기서 직접 맞춘다.
            # 다만 보던 것 그대로면 손대지 않는다 — 목록만 다시 그린 것뿐인데
            # 편집 칸까지 비우면 익히던 것이 날아간다.
            if item.numbers[select] is not self._editing_number:
                self._show_number(item.numbers[select])
        else:
            self._show_number(None)

    def _selected_number(self):
        item = self.selected()
        selection = self.numbers_tree.selection()
        if item is None or not selection:
            return None
        index = int(selection[0])
        return item.numbers[index] if 0 <= index < len(item.numbers) else None

    def _show_number(self, watch) -> None:
        self._editing_number = watch
        self.number_name_var.set(watch.name if watch is not None else "")
        self.number_panel.load(watch if watch is not None else NumberWatch())

    def _commit_number(self) -> None:
        if self._editing_number is not None:
            self.number_panel.save(self._editing_number)

    def _on_number_select(self, _event: object = None) -> None:
        watch = self._selected_number()
        # 그림 쪽과 같은 이유로, 보던 것을 다시 고르면 그대로 둔다. 익히는
        # 도중에 다시 채우면 잘라 둔 글자가 통째로 사라진다.
        if watch is not None and watch is self._editing_number:
            return
        self._commit_number()
        self._show_number(watch)

    def _on_number_edit(self) -> None:
        item = self.selected()
        if item is None:
            return
        self._commit_number()
        selection = self.numbers_tree.selection()
        keep = int(selection[0]) if selection else None
        self._fill_numbers(item, select=keep)

    def _add_number(self) -> None:
        item = self.selected()
        if item is None:
            return
        self._commit_number()
        item.numbers.append(NumberWatch(name=f"숫자 {len(item.numbers) + 1}"))
        self._fill_numbers(item, select=len(item.numbers) - 1)
        self.refresh(select_name=item.name)

    def _delete_number(self) -> None:
        item = self.selected()
        selection = self.numbers_tree.selection()
        if item is None or not selection:
            return
        index = int(selection[0])
        if not (0 <= index < len(item.numbers)):
            return
        del item.numbers[index]
        self._editing_number = None
        self._fill_numbers(item)
        self.refresh(select_name=item.name)

    def _rename_number(self) -> None:
        watch = self._editing_number
        if watch is None:
            return
        name = self.number_name_var.get().strip()
        if not name or name == watch.name:
            return
        watch.name = name
        self._on_number_edit()

    def build_actions(self, parent: ttk.Frame) -> None:
        ttk.Button(parent, text="지금 판정 확인", command=self._test_now).pack(
            side="left", padx=(16, 0)
        )

    # ------------------------------------------------------------------
    def _sync_action(self) -> None:
        kind = ACTION_BY_LABEL.get(self.action_kind_var.get(), "key")
        # '찾은 그림 누르기'는 키 대신 어느 버튼으로 누를지를 고른다.
        if kind == "click":
            self.action_key_box.configure(values=["left", "right"], state="readonly")
            if self.action_key_var.get() not in ("left", "right"):
                self.action_key_var.set("left")
        else:
            self.action_key_box.configure(values=KEY_CHOICES, state="normal"
                                          if kind == "key" else "disabled")
        if kind == "macro":
            names = [m.name for m in self.engine.profile.macros]
        elif kind == "path":
            names = [p.name for p in self.engine.profile.paths]
        else:
            names = []
        self.action_target_box.configure(
            values=names, state="readonly" if names else "disabled"
        )

    def load_form(self, item: PixelRule) -> None:
        self.name_var.set(item.name)
        self.tol_var.set(str(item.tolerance))
        self.match_var.set(MATCH_LABELS.get(item.match_mode, MATCH_LABELS["all"]))
        self.cond_var.set(COND_LABELS.get(item.condition, COND_LABELS["match"]))
        self.check_var.set(str(item.check_ms))
        self.cool_var.set(str(item.cooldown_ms))
        self.edge_var.set(item.edge_only)
        self.action_kind_var.set(ACTION_LABELS.get(item.action_kind, ACTION_LABELS["key"]))
        self.action_key_var.set(item.action_key)
        self._sync_action()
        self.action_target_var.set(item.action_target)
        self.confirm_var.set(str(max(1, item.confirm_count)))
        self._fill_points(item)
        self._fill_icons(item)
        self._fill_numbers(item)
        self.test_var.set("")

    def save_form(self, item: PixelRule) -> None:
        new_name = self.name_var.get().strip() or item.name
        renamed = new_name != item.name
        item.name = new_name
        item.tolerance = max(get_int(self.tol_var, 12), 0)
        item.match_mode = MATCH_BY_LABEL.get(self.match_var.get(), "all")
        item.condition = COND_BY_LABEL.get(self.cond_var.get(), "match")
        item.check_ms = max(get_int(self.check_var, 300), 30)
        item.cooldown_ms = max(get_int(self.cool_var, 1500), 0)
        item.edge_only = bool(self.edge_var.get())
        item.confirm_count = max(1, get_int(self.confirm_var, 1))
        # 그림 칸에 지금 떠 있는 값도 함께 거둔다. 폼을 떠날 때만 저장하면
        # 허용 오차를 고쳐 놓고 [실행]을 눌렀을 때 옛 값으로 돌아 버린다.
        self._commit_icon()
        self._commit_number()
        item.action_kind = ACTION_BY_LABEL.get(self.action_kind_var.get(), "key")
        item.action_key = self.action_key_var.get().strip() or "Z"
        item.action_target = self.action_target_var.get().strip()
        if renamed:
            self.refresh(select_name=item.name)

    def _fill_points(self, item: PixelRule, select: int | None = None) -> None:
        self.points_tree.delete(*self.points_tree.get_children())
        for index, point in enumerate(item.points):
            self.points_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(index + 1, f"({point.x}, {point.y})", pixel.to_hex(point.color)),
            )
        if select is not None and 0 <= select < len(item.points):
            self.points_tree.selection_set(str(select))

    def _selected_point(self) -> int | None:
        selection = self.points_tree.selection()
        return int(selection[0]) if selection else None

    # ------------------------------------------------------------------
    def _add_point(self) -> None:
        item = self.selected()
        if item is None:
            return
        result = capture_click_point(self.winfo_toplevel(), self.engine.window())
        if result is None:
            return
        cx, cy, color = result
        point = PixelPoint(x=cx, y=cy)
        point.set_color(color)
        item.points.append(point)
        self._fill_points(item, select=len(item.points) - 1)
        self.refresh(select_name=item.name)
        self.engine.log(f"감지 점 추가: ({cx}, {cy}) {pixel.to_hex(color)}")

    def _resample(self) -> None:
        item = self.selected()
        window = self.engine.window()
        if item is None or window is None or not item.points:
            self.test_var.set("게임 창 또는 감지 점이 없습니다.")
            return
        screen = [window.client_to_screen(p.x, p.y) for p in item.points]
        try:
            colors = pixel.sample_points(screen)
        except pixel.CaptureError as exc:
            self.test_var.set(str(exc))
            return
        for point, color in zip(item.points, colors):
            point.set_color(color)
        self._fill_points(item)
        self.engine.log(f"'{item.name}': 기준 색 {len(colors)}개를 현재 화면으로 갱신.")

    def _delete_point(self) -> None:
        item = self.selected()
        index = self._selected_point()
        if item is None or index is None or index >= len(item.points):
            return
        del item.points[index]
        self._fill_points(item)
        self.refresh(select_name=item.name)

    # ------------------------------------------------------------------
    # 그림 조건
    # ------------------------------------------------------------------
    def _fill_icons(self, item: PixelRule, select: int | None = None) -> None:
        self.icons_tree.delete(*self.icons_tree.get_children())
        for index, watch in enumerate(item.icons):
            self.icons_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    watch.name or f"그림 {index + 1}",
                    watch.icon or "(그림 없음)",
                    EXPECT_LABELS.get(watch.expect, watch.expect),
                ),
            )
        if select is None and item.icons:
            select = 0
        if select is not None and 0 <= select < len(item.icons):
            self.icons_tree.selection_set(str(select))
            # selection_set이 만드는 <<TreeviewSelect>>는 그 자리에서가 아니라
            # 조금 뒤에 처리된다. 그때까지 편집 칸이 옛 항목을 가리키고 있으면
            # 그 사이에 고친 값이 엉뚱한 항목에 들어간다. 그래서 직접 맞춘다.
            # 보던 것 그대로면 손대지 않는다 (마스크 편집이 날아가지 않게).
            if item.icons[select] is not self._editing_icon:
                self._show_icon(item.icons[select])
        else:
            self._show_icon(None)

    def _selected_icon(self):
        """지금 고른 그림 조건. 없으면 None."""
        item = self.selected()
        selection = self.icons_tree.selection()
        if item is None or not selection:
            return None
        index = int(selection[0])
        return item.icons[index] if 0 <= index < len(item.icons) else None

    def _show_icon(self, watch) -> None:
        self._editing_icon = watch
        self.icon_name_var.set(watch.name if watch is not None else "")
        self.icon_panel.load(watch if watch is not None else IconWatch())

    def _commit_icon(self) -> None:
        """편집 칸의 값을 지금 고른 그림 조건에 되돌려 넣는다."""
        watch = getattr(self, "_editing_icon", None)
        if watch is not None:
            self.icon_panel.save(watch)

    def _on_icon_select(self, _event: object = None) -> None:
        watch = self._selected_icon()
        # 이미 보고 있는 것이면 다시 채우지 않는다. selection_set이 만드는
        # <<TreeviewSelect>>는 조금 뒤에 처리되는데, 그때 무턱대고 다시 채우면
        # 그 사이에 해 둔 것(잘라 둔 그림, 적어 둔 값)이 날아간다.
        if watch is not None and watch is self._editing_icon:
            return
        self._commit_icon()
        self._show_icon(watch)

    def _on_icon_edit(self) -> None:
        """편집 칸에서 그림·영역·마스크가 바뀌었을 때 목록을 따라 그린다."""
        item = self.selected()
        if item is None:
            return
        self._commit_icon()
        selection = self.icons_tree.selection()
        keep = int(selection[0]) if selection else None
        self._fill_icons(item, select=keep)

    def _add_icon(self) -> None:
        item = self.selected()
        if item is None:
            return
        self._commit_icon()
        watch = IconWatch(name=f"그림 {len(item.icons) + 1}")
        item.icons.append(watch)
        self._fill_icons(item, select=len(item.icons) - 1)
        self.refresh(select_name=item.name)

    def _delete_icon(self) -> None:
        item = self.selected()
        selection = self.icons_tree.selection()
        if item is None or not selection:
            return
        index = int(selection[0])
        if not (0 <= index < len(item.icons)):
            return
        del item.icons[index]
        self._editing_icon = None
        self._fill_icons(item)
        self.refresh(select_name=item.name)

    def _rename_icon(self) -> None:
        watch = getattr(self, "_editing_icon", None)
        if watch is None:
            return
        name = self.icon_name_var.get().strip()
        if not name or name == watch.name:
            return
        watch.name = name
        self._on_icon_edit()

    # ------------------------------------------------------------------
    def _test_now(self) -> None:
        self.commit()
        item = self.selected()
        if item is None:
            return
        window = self.engine.window()
        ctx = RunContext(self.engine.settings, window, self.engine.log)
        ctx.library_root = self.engine.library_root
        triggered, detail = evaluate_rule(item, ctx, self.engine.library_root)
        verdict = "조건 성립 ✔" if triggered else "조건 불성립 ✘"
        self.test_var.set(f"{verdict}   현재 색: {detail}")
