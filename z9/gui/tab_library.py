"""탭 — 매크로 라이브러리.

작업 목록(지금 켜져 있고 핫키가 걸린 것들)과 보관함을 분리한다. 만들어 둔
매크로를 카테고리별 폴더에 개별 파일로 정리해 두고, 필요할 때 꺼내 쓴다.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .. import library
from ..engine import Engine


class LibraryTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine: Engine, on_changed) -> None:
        super().__init__(parent, padding=12)
        self.engine = engine
        self.on_changed = on_changed
        self._entries: dict[str, library.LibraryEntry] = {}
        self._save_targets: list[tuple[str, object]] = []

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._build_header()
        self._build_browser()
        self._build_saver()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_header(self) -> None:
        box = ttk.Frame(self)
        box.grid(row=0, column=0, sticky="ew")

        ttk.Label(box, text="보관 폴더").pack(side="left")
        self.path_var = tk.StringVar()
        entry = ttk.Entry(box, textvariable=self.path_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(box, text="폴더 변경", command=self._choose_folder).pack(side="left")
        ttk.Button(box, text="탐색기에서 열기", command=self._open_folder).pack(
            side="left", padx=6
        )

    def _build_browser(self) -> None:
        box = ttk.LabelFrame(self, text="보관함", padding=10)
        box.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        wrap = ttk.Frame(box)
        wrap.grid(row=0, column=0, sticky="nsew")

        self.tree = ttk.Treeview(
            wrap, columns=("type",), show="tree headings", selectmode="browse", height=13
        )
        self.tree.heading("#0", text="이름")
        self.tree.column("#0", width=340, stretch=True)
        self.tree.heading("type", text="종류")
        self.tree.column("type", width=100, anchor="w", stretch=False)
        self.tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        bar.pack(side="left", fill="y")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<Double-1>", lambda _e: self._import())

        buttons = ttk.Frame(box)
        buttons.grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Button(buttons, text="작업 목록으로 불러오기", command=self._import).pack(
            side="left"
        )
        ttk.Button(buttons, text="이름 변경", command=self._rename).pack(side="left", padx=6)
        ttk.Button(buttons, text="삭제", command=self._delete).pack(side="left")
        ttk.Button(buttons, text="새 카테고리", command=self._new_category).pack(
            side="left", padx=(16, 0)
        )
        ttk.Button(buttons, text="새로고침", command=self.refresh).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="")
        ttk.Label(box, textvariable=self.status_var, style="Muted.TLabel").grid(
            row=2, column=0, sticky="w", pady=(8, 0)
        )

    def _build_saver(self) -> None:
        box = ttk.LabelFrame(self, text="보관함에 올리기 (녹화 매크로 · 시나리오)", padding=10)
        box.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=760,
            text=("보관함은 지금 가진 녹화 매크로 · 시나리오와 똑같이 맞춰집니다.\n"
                  "· 올릴 때 같은 이름이 보관함에 있으면 보관함 쪽을 치우고 새로 저장합니다 "
                  "(원래 있던 카테고리에).\n"
                  "· 지금 가진 매크로 · 시나리오가 아닌 항목 파일(지난 매크로, 조건, 예약 등)은 "
                  "올릴 때마다 자동으로 치웁니다.\n"
                  "· 치운 것은 지우지 않고 data\\보관함_지운것 폴더에 옮겨 둡니다. 감지 아이콘 "
                  "같은 그림 파일은 건드리지 않습니다."),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

        ttk.Label(box, text="올릴 항목").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.item_var = tk.StringVar()
        self.item_box = ttk.Combobox(
            box, textvariable=self.item_var, state="readonly", width=48
        )
        self.item_box.grid(row=0, column=1, sticky="ew")

        ttk.Label(box, text="카테고리").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        self.category_var = tk.StringVar()
        self.category_box = ttk.Combobox(box, textvariable=self.category_var, width=28)
        self.category_box.grid(row=1, column=1, sticky="w", pady=(8, 0))

        actions = ttk.Frame(box)
        actions.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Button(actions, text="선택 항목 올리기", command=self._save_selected).pack(side="left")
        ttk.Button(actions, text="매크로 · 시나리오 전체 올리기", style="Accent.TButton",
                   command=self._save_all).pack(side="left", padx=8)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        root = self.engine.library_root
        self.path_var.set(str(root))

        self.tree.delete(*self.tree.get_children())
        self._entries.clear()

        lib = self.engine.library
        entries = lib.entries()
        categories = lib.categories()

        nodes: dict[str, str] = {}
        for category in categories:
            nodes[category] = self.tree.insert(
                "", "end", text=f"📁 {category}", values=("",), open=True
            )

        for entry in entries:
            parent = nodes.get(entry.category, "")
            if entry.category and parent == "":
                parent = self.tree.insert(
                    "", "end", text=f"📁 {entry.category}", values=("",), open=True
                )
                nodes[entry.category] = parent
            iid = self.tree.insert(
                parent, "end", text=entry.name, values=(entry.type_label,)
            )
            self._entries[iid] = entry

        self.status_var.set(
            f"항목 {len(entries)}개, 카테고리 {len(categories)}개"
            if entries or categories
            else "보관함이 비어 있습니다. 아래에서 항목을 저장해 보세요."
        )

        self.category_box.configure(values=categories)
        self._refresh_items()

    def _refresh_items(self) -> None:
        # 보관함에 올리는 것은 녹화 매크로와 시나리오뿐이다.
        self._save_targets = [
            (code, item) for code, item in library.collect_profile_items(self.engine.profile)
            if code in library.UPLOAD_TYPES
        ]
        labels = [
            f"[{library.TYPES[code][2]}] {item.name}"
            for code, item in self._save_targets
        ]
        self.item_box.configure(values=labels)
        if labels and self.item_var.get() not in labels:
            self.item_var.set(labels[0])
        elif not labels:
            self.item_var.set("")

    # ------------------------------------------------------------------
    def _choose_folder(self) -> None:
        chosen = filedialog.askdirectory(
            title="매크로를 보관할 폴더를 고르세요",
            initialdir=str(self.engine.library_root.parent),
            parent=self,
        )
        if not chosen:
            return
        self.engine.set_library_dir(chosen)
        self.engine.save()
        self.refresh()

    def _open_folder(self) -> None:
        root = self.engine.library_root
        try:
            root.mkdir(parents=True, exist_ok=True)
            os.startfile(str(root))  # noqa: S606 - 사용자가 고른 폴더를 여는 것
        except (OSError, AttributeError) as exc:
            messagebox.showwarning("열지 못했습니다", str(exc), parent=self)

    def _new_category(self) -> None:
        name = simpledialog.askstring(
            "새 카테고리", "카테고리 이름 (예: 농사, 목장)", parent=self
        )
        if not name:
            return
        self.engine.library.create_category(name)
        self.refresh()
        self.category_var.set(library.safe_name(name))

    # ------------------------------------------------------------------
    def _selected_entry(self) -> library.LibraryEntry | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self._entries.get(selection[0])

    def _import(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            self.status_var.set("불러올 항목을 고르세요.")
            return
        try:
            _code, name = self.engine.import_from_library(entry.path)
        except library.LibraryError as exc:
            messagebox.showerror("불러오기 실패", str(exc), parent=self)
            return
        self.on_changed()
        self._refresh_items()
        self.status_var.set(
            f"'{name}'을(를) 작업 목록에 추가했습니다. 해당 탭에서 편집·실행할 수 있습니다."
        )

    def _rename(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        name = simpledialog.askstring(
            "이름 변경", "새 이름", initialvalue=entry.name, parent=self
        )
        if not name:
            return
        try:
            self.engine.library.rename(entry.path, name)
        except library.LibraryError as exc:
            messagebox.showerror("이름 변경 실패", str(exc), parent=self)
            return
        self.refresh()

    def _delete(self) -> None:
        entry = self._selected_entry()
        if entry is None:
            return
        if not messagebox.askyesno(
            "삭제 확인",
            f"'{entry.name}' 파일을 지웁니다.\n{entry.path}\n\n"
            "작업 목록에 이미 불러온 항목은 그대로 남습니다. 계속할까요?",
            parent=self,
        ):
            return
        try:
            self.engine.library.delete(entry.path)
        except library.LibraryError as exc:
            messagebox.showerror("삭제 실패", str(exc), parent=self)
            return
        self.refresh()

    # ------------------------------------------------------------------
    def _save_selected(self) -> None:
        label = self.item_var.get()
        labels = list(self.item_box.cget("values"))
        if label not in labels:
            self.status_var.set("저장할 항목을 고르세요.")
            return
        _code, item = self._save_targets[labels.index(label)]
        profile = self.engine.profile
        if not any(item is x for x in (*profile.macros, *profile.scenarios)):
            # 다른 창에서 지운 항목이 목록에 남아 있었다.
            self._refresh_items()
            self.status_var.set("목록이 바뀌었습니다 — 올릴 항목을 다시 고르세요.")
            return
        self.upload([item])

    def _save_all(self) -> None:
        self.upload(None)

    def upload(self, items, ask: bool = True,
               category: str | None = None) -> "library.UploadReport | None":
        """올리고 치운다. 다른 탭(시나리오 편집기 · 녹화·재생)의 [보관함에 올리기]도 이것을 쓴다.

        치울 것이 있으면 무엇을 치우는지 **먼저 보여 주고** 묻는다. 옮겨 두기는 하지만
        보관함에서 사라지는 것이라, 모르는 사이에 없어지면 안 된다.
        category를 안 주면 이 탭에서 고른 카테고리를 쓴다.
        """
        if category is None:
            category = self.category_var.get().strip()
        try:
            plan = self.engine.upload_to_library(items, category=category, dry_run=True)
        except library.LibraryError as exc:
            messagebox.showerror("보관함에 올리기", str(exc), parent=self)
            return None
        count = len(plan.saved) + len(plan.replaced)
        if not count:
            self.status_var.set("올릴 녹화 매크로 · 시나리오가 없습니다.")
            return None
        if ask and (plan.removed or items is None):
            def listing(names):
                shown = "\n".join(f"   · {n}" for n in names[:12])
                return shown + (f"\n   … 외 {len(names) - 12}개" if len(names) > 12 else "")

            lines = [f"보관함에 {count}개를 올립니다. (카테고리: {category or '원래 자리 / 최상위'})"]
            if plan.replaced:
                lines.append(f"\n같은 이름이라 보관함 쪽을 바꿔 올림 {len(plan.replaced)}개")
            if plan.removed:
                lines.append(f"\n지금 가진 매크로 · 시나리오가 아니라 보관함에서 치움 "
                             f"{len(plan.removed)}개:\n{listing(plan.removed)}")
                lines.append("\n치운 것은 data\\보관함_지운것 폴더에 옮겨 둡니다.")
            lines.append("\n계속할까요?")
            if not messagebox.askyesno("보관함에 올리기", "\n".join(lines), parent=self):
                return None
        try:
            report = self.engine.upload_to_library(items, category=category)
        except Exception as exc:  # noqa: BLE001 — 무슨 일이든 화면은 새로고침하고 알린다
            self.refresh()
            self.engine.log(f"보관함 올리기 실패: {exc!r}")
            messagebox.showerror(
                "올리기 실패",
                f"{exc}\n\n보관함이 일부만 바뀌었을 수 있습니다. 로그와 data\\보관함_지운것 "
                "폴더를 확인하세요.", parent=self)
            return None
        self.refresh()
        self.status_var.set(report.summary()
                            + (f" — 치운 것: {report.backup}" if report.backup else ""))
        if report.failed:
            messagebox.showwarning("일부 실패", "\n".join(report.failed[:15]), parent=self)
        return report
