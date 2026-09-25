"""목록 + 편집 폼 형태의 탭 공통 뼈대.

4개 탭이 전부 "왼쪽에 항목 목록, 오른쪽에 편집 폼, 아래에 실행/정지" 구조라
공통부를 여기 모았다. 하위 클래스는 항목 종류에 따른 부분만 구현한다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from ..engine import Engine
from . import theme


class ListEditorTab(ttk.Frame):
    kind = ""  # engine.run/stop에 쓰는 종류 문자열
    noun = "항목"

    def __init__(self, parent: tk.Misc, engine: Engine) -> None:
        super().__init__(parent, padding=10)
        self.engine = engine
        self._current: Any = None
        self._loading = False

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # 왼쪽 목록과 오른쪽 편집 폼 사이를 끌어서 넓힐 수 있게 한다.
        # 고정 비율로 두면 화면이 커져도 이벤트 목록 몫이 그대로라, 넓은
        # 모니터에서 오른쪽만 휑하고 정작 목록은 좁은 채로 남는다.
        self.split = ttk.PanedWindow(self, orient="horizontal")
        self.split.grid(row=0, column=0, sticky="nsew")
        self._sash_placed = False
        self.split.bind("<Configure>", self._place_sash, add="+")

        # -- 왼쪽: 목록 --------------------------------------------------
        left = ttk.Frame(self.split, padding=(0, 0, 8, 0))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        cols = self.columns()
        self.tree = ttk.Treeview(
            left,
            columns=[c[0] for c in cols],
            show="headings",
            selectmode="browse",
            height=14,
        )
        self._list_width = 0
        for cid, text, width in cols:
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=theme.px(width), anchor="w", stretch=False)
            self._list_width += theme.px(width)
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        buttons = ttk.Frame(left)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(
            buttons, text=f"＋ {self.noun}", style="Small.TButton", command=self._add
        ).pack(side="left")
        ttk.Button(
            buttons, text="복제", style="Small.TButton", command=self._duplicate
        ).pack(side="left", padx=4)
        ttk.Button(
            buttons, text="삭제", style="SmallDanger.TButton", command=self._delete
        ).pack(side="left")
        # 녹화 매크로 · 시나리오는 이 자리에서 곧바로 보관함에 올린다. 보관함 탭과 같은
        # 흐름(같은 이름 바꿔 올리기 · 지금 없는 것 치우기 · 확인 창)을 그대로 쓴다.
        if self.kind in ("macro", "scenario"):
            ttk.Button(
                buttons, text="보관함에 올리기", style="Small.TButton",
                command=self._upload_to_library,
            ).pack(side="left", padx=(8, 0))

        # -- 오른쪽: 편집 폼 ----------------------------------------------
        right = ttk.Frame(self.split, padding=(4, 0, 0, 0))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.form = ttk.LabelFrame(right, text=f"{self.noun} 설정", padding=12)
        self.form.grid(row=0, column=0, sticky="nsew")

        self.actions = ttk.Frame(right)
        self.actions.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.run_button = ttk.Button(
            self.actions, text="▶ 실행", style="Accent.TButton", command=self._run
        )
        self.run_button.pack(side="left")
        ttk.Button(self.actions, text="■ 정지", command=self._stop).pack(
            side="left", padx=6
        )
        self.build_actions(self.actions)

        # 넓어진 만큼은 전부 편집 폼(이벤트 목록이 있는 쪽)이 가져간다.
        self.split.add(left, weight=0)
        self.split.add(right, weight=1)

        self.build_form(self.form)
        self.refresh()

    # ------------------------------------------------------------------
    def _default_sash(self) -> int:
        """저장된 값이 없을 때 쓸 목록 칸 너비. 열 너비 합 + 스크롤바 몫."""
        return self._list_width + theme.px(46)

    def _place_sash(self, _event: object = None) -> None:
        """창이 실제로 그려진 뒤 딱 한 번 분할선을 놓는다.

        위젯이 만들어지는 시점에는 너비가 1이라 sashpos가 먹지 않는다.
        노트북의 안 보이는 탭은 한참 뒤에야 그려지므로 <Configure>를 기다린다.
        """
        if self._sash_placed:
            return
        width = self.split.winfo_width()
        if width < theme.px(520):
            return
        self._sash_placed = True
        want = self.engine.settings.sash_list or self._default_sash()
        # 어느 한쪽이 아예 사라지지 않게 양끝을 잘라 둔다.
        low = theme.px(150)
        high = max(low, width - theme.px(320))
        try:
            self.split.sashpos(0, int(max(low, min(want, high))))
        except tk.TclError:
            pass

    def sash_value(self) -> int:
        """지금 분할선 자리. 저장해 두었다가 다음 실행 때 되돌린다."""
        if not self._sash_placed:
            return 0
        try:
            return int(self.split.sashpos(0))
        except tk.TclError:
            return 0

    def reset_sash(self) -> None:
        """분할선을 기본 자리로 되돌린다."""
        self._sash_placed = False
        self._place_sash()

    # ------------------------------------------------------------------
    # 하위 클래스가 구현
    # ------------------------------------------------------------------
    def items(self) -> list:
        raise NotImplementedError

    def columns(self) -> list[tuple[str, str, int]]:
        raise NotImplementedError

    def row_values(self, item: Any) -> tuple:
        raise NotImplementedError

    def new_item(self) -> Any:
        raise NotImplementedError

    def copy_item(self, item: Any) -> Any:
        raise NotImplementedError

    def build_form(self, parent: ttk.Frame) -> None:
        raise NotImplementedError

    def load_form(self, item: Any) -> None:
        raise NotImplementedError

    def save_form(self, item: Any) -> None:
        raise NotImplementedError

    def build_actions(self, parent: ttk.Frame) -> None:
        """추가 버튼이 필요하면 하위 클래스에서 붙인다."""

    def item_name(self, item: Any) -> str:
        return getattr(item, "name", "")

    def unique_name(self, base: str) -> str:
        existing = {self.item_name(i) for i in self.items()}
        if base not in existing:
            return base
        i = 2
        while f"{base} ({i})" in existing:
            i += 1
        return f"{base} ({i})"

    # ------------------------------------------------------------------
    # 목록 동작
    # ------------------------------------------------------------------
    def refresh(self, select_name: str | None = None, reload_form: bool = False) -> None:
        """목록을 다시 그린다.

        reload_form은 **바깥에서 데이터가 바뀌었을 때만** 켠다. 폼 안에서 뭔가를
        고친 직후(단계 추가 등)에 켜면, 방금 잡아 둔 하위 목록 선택이 풀려서
        이어지는 조작이 엉뚱한 곳에 걸린다.
        """
        keep = select_name or (self.item_name(self._current) if self._current else None)
        self.tree.delete(*self.tree.get_children())
        target = ""
        for index, item in enumerate(self.items()):
            iid = str(index)
            self.tree.insert("", "end", iid=iid, values=self.row_values(item))
            if self.item_name(item) == keep:
                target = iid
        if target:
            self.tree.selection_set(target)
            # 같은 항목이 그대로 선택돼 있으면 _on_select가 "이미 보고 있다"고
            # 걸러 낸다. 바깥에서 데이터가 바뀐 경우에는 그대로 두면 지워진
            # 항목을 가리키는 단계 같은 게 옛 모습으로 남으므로 직접 채운다.
            if reload_form:
                self._reload_form()
        elif self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        else:
            self._current = None
            self._set_form_state(False)

    def selected(self) -> Any:
        selection = self.tree.selection()
        if not selection:
            return None
        index = int(selection[0])
        items = self.items()
        return items[index] if 0 <= index < len(items) else None

    def _on_select(self, _event: object = None) -> None:
        item = self.selected()
        # 이미 보고 있는 항목이면 폼을 다시 채우지 않는다.
        # selection_set이 만드는 <<TreeviewSelect>>는 그 자리에서가 아니라 조금
        # 뒤에 처리되는데, 그때 폼을 다시 채우면 그 사이에 잡아 둔 하위 목록
        # 선택(이벤트 · 단계 · 감지 점)이 풀려 버린다.
        if item is not None and item is self._current:
            return

        self.commit()
        self._current = item
        if item is None:
            self._set_form_state(False)
            return
        self._loading = True
        try:
            self.load_form(item)
        finally:
            self._loading = False
        self._set_form_state(True)

    def _reload_form(self) -> None:
        """선택은 그대로 두고 폼만 다시 채운다.

        commit()은 하지 않는다. 여기로 오는 경우는 데이터가 바깥에서 이미
        바뀐 뒤라, 화면에 남아 있던 옛 값을 되쓰면 그 변경을 덮어쓴다.
        """
        item = self.selected()
        if item is None:
            self._current = None
            self._set_form_state(False)
            return
        self._current = item
        self._loading = True
        try:
            self.load_form(item)
        finally:
            self._loading = False
        self._set_form_state(True)

    def commit(self) -> None:
        """편집 중인 폼 내용을 현재 항목에 반영한다."""
        if self._current is None or self._loading:
            return
        try:
            self.save_form(self._current)
        except Exception as exc:  # noqa: BLE001
            self.engine.log(f"입력값 저장 실패: {exc}")

    def _set_form_state(self, enabled: bool) -> None:
        """선택 항목 유무를 알린다.

        위젯을 실제로 disable하지는 않는다. ttk의 readonly 엔트리를 disable했다가
        되돌리면 readonly가 풀려버려서, 대신 선택이 없을 때 commit()이 무시되는
        방식으로 처리한다.
        """
        self.run_button.configure(state="normal" if enabled else "disabled")

    def _add(self) -> None:
        self.commit()
        item = self.new_item()
        item.name = self.unique_name(item.name)
        self.items().append(item)
        self.engine.rebind_hotkeys()
        self.refresh(select_name=item.name)

    def _upload_to_library(self) -> None:
        """고른 항목 하나를 보관함에 올린다. 고른 것이 없으면 고르라고만 한다.

        전부 올리기는 보관함 탭의 [매크로 · 시나리오 전체 올리기]가 맡는다 — 목록에서
        아무것도 안 고른 채 눌렀다고 전부 올리고 치우면 뜻밖의 일이 된다.
        """
        root = self.winfo_toplevel()
        library_tab = getattr(root, "library_tab", None)
        if library_tab is None:
            return
        # 편집 중인 값이 올라가게 한다. 이 탭만이 아니라 편집 탭 전부 — 올리고 나서
        # 지금 가진 것이 아닌 항목을 치우므로, 다른 탭에서 방금 바꾼 이름도 반영돼야 한다.
        for tab in getattr(root, "editor_tabs", (self,)):
            if hasattr(tab, "commit"):
                tab.commit()
        item = self.selected()
        if item is None:
            from tkinter import messagebox

            messagebox.showinfo("보관함에 올리기",
                                f"올릴 {self.noun}을(를) 왼쪽 목록에서 고르세요.", parent=self)
            return
        # 보관함 탭에서 마지막으로 고른 카테고리를 몰래 쓰지 않는다 — 새 항목은 최상위로,
        # 같은 이름이 있으면 그것이 있던 자리로.
        report = library_tab.upload([item], category="")
        if report is not None:
            self.engine.log(f"보관함에 올림: '{item.name}' — {report.summary()}")

    def _duplicate(self) -> None:
        self.commit()
        item = self.selected()
        if item is None:
            return
        clone = self.copy_item(item)
        clone.name = self.unique_name(f"{item.name} 복사")
        if hasattr(clone, "hotkey"):
            clone.hotkey = ""  # 같은 핫키가 둘에 걸리지 않게 비운다
        self.items().append(clone)
        self.engine.rebind_hotkeys()
        self.refresh(select_name=clone.name)

    def _delete(self) -> None:
        item = self.selected()
        if item is None:
            return
        if not messagebox.askyesno(
            "삭제 확인", f"'{self.item_name(item)}'을(를) 삭제할까요?", parent=self
        ):
            return
        self.engine.stop(self.kind, self.item_name(item))
        self.items().remove(item)
        self._current = None
        self.engine.rebind_hotkeys()
        self.refresh()

    # ------------------------------------------------------------------
    # 실행
    # ------------------------------------------------------------------
    def _run(self) -> None:
        self.commit()
        item = self.selected()
        if item is None:
            return
        self.engine.run(self.kind, self.item_name(item))

    def _stop(self) -> None:
        item = self.selected()
        if item is None:
            self.engine.stop_all()
            return
        self.engine.stop(self.kind, self.item_name(item))

    def on_state_change(self) -> None:
        """엔진에서 작업 시작/종료가 있을 때 호출된다."""
        item = self.selected()
        if item is None:
            return
        running = self.engine.is_running(self.kind, self.item_name(item))
        self.run_button.configure(text="■ 실행 중 (클릭 시 정지)" if running else "▶ 실행")
        self.run_button.configure(command=self._stop if running else self._run)
