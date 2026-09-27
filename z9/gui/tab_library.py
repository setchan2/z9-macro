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
from .widgets import ScrollFrame


class LibraryTab(ScrollFrame):
    """보관함 탭.

    **세로로 넘치면 스크롤된다.** 보관함 목록 · 올리기 · 전체 백업이 차례로
    놓이는데, 노트북처럼 세로가 짧은 화면에서는 아래쪽(백업 목록과 단추)이
    통째로 잘려 아예 못 썼다. 이 탭만 창 높이에 기대고 있었다.
    """

    def __init__(self, parent: tk.Misc, engine: Engine, on_changed) -> None:
        super().__init__(parent)
        self.body = ttk.Frame(self.inner, padding=12)
        self.body.pack(fill="both", expand=True)
        self.engine = engine
        self.on_changed = on_changed
        self._entries: dict[str, library.LibraryEntry] = {}
        self._save_targets: list[tuple[str, object]] = []

        self.body.columnconfigure(0, weight=1)

        self._build_header()
        # **전체 백업을 맨 위에 둔다.** 아래쪽에 두었더니 노트북처럼 세로가 짧은
        # 화면에서는 목록도 단추도 통째로 잘려 아예 못 썼다.
        self._build_backup()
        self._build_browser()
        self._build_saver()
        self.refresh()

    # ------------------------------------------------------------------
    def _build_header(self) -> None:
        box = ttk.Frame(self.body)
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
        box = ttk.LabelFrame(self.body, text="보관함", padding=10)
        box.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        wrap = ttk.Frame(box)
        wrap.grid(row=0, column=0, sticky="nsew")

        self.tree = ttk.Treeview(
            wrap, columns=("type",), show="tree headings", selectmode="browse", height=7
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
        box = ttk.LabelFrame(self.body,
                             text="보관함에 올리기 (녹화 매크로 · 시나리오)",
                             padding=10)
        box.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        box.columnconfigure(1, weight=1)

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=760,
            text=("보관함은 지금 가진 녹화 매크로 · 시나리오와 똑같이 맞춰집니다. "
                  "같은 이름은 새로 저장하고, 지금 가진 것이 아닌 항목 파일은 "
                  "data\\보관함_지운것 폴더로 옮겨 둡니다(지우지 않습니다). "
                  "감지 아이콘 같은 그림은 건드리지 않습니다."),
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
    # 전체 백업 — 이 컴퓨터의 설정을 통째로 담고, 다른 컴퓨터에서 그대로 쓴다.
    # ------------------------------------------------------------------
    def _build_backup(self) -> None:
        box = ttk.LabelFrame(self.body,
                             text="전체 백업 (다른 컴퓨터로 그대로 옮기기)",
                             padding=10)
        box.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)

        ttk.Label(
            box, style="Faint.TLabel", justify="left", wraplength=760,
            text=("설정 전부(매크로 · 시나리오 · 조건 · 이동 · 예약 · 낚시 · "
                  "벌목 · 제작)와 보관함 그림 · 숫자 글꼴을 파일 하나에 담습니다. "
                  "다른 컴퓨터로 옮겨 [파일에서 가져오기] → [되돌리기] 하면 그 "
                  "컴퓨터가 이 설정과 똑같아집니다. 되돌리기 전에는 지금 설정을 "
                  "자동으로 한 벌 담아 둡니다."),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        wrap = ttk.Frame(box)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.backup_tree = ttk.Treeview(
            wrap, columns=("when", "what", "size"), show="headings",
            selectmode="browse", height=4)
        self.backup_tree.heading("when", text="만든 때")
        self.backup_tree.column("when", width=150, stretch=False)
        self.backup_tree.heading("what", text="담긴 것")
        self.backup_tree.column("what", width=420, stretch=True)
        self.backup_tree.heading("size", text="크기")
        self.backup_tree.column("size", width=80, anchor="e", stretch=False)
        self.backup_tree.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.backup_tree.yview)
        bar.pack(side="left", fill="y")
        self.backup_tree.configure(yscrollcommand=bar.set)

        actions = ttk.Frame(box)
        actions.grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Button(actions, text="지금 백업 만들기", style="Accent.TButton",
                   command=self._backup_now).pack(side="left")
        ttk.Button(actions, text="↩ 고른 백업으로 되돌리기",
                   command=self._backup_restore).pack(side="left", padx=8)
        ttk.Button(actions, text="파일에서 가져오기",
                   command=self._backup_import).pack(side="left")
        ttk.Button(actions, text="파일로 내보내기",
                   command=self._backup_export).pack(side="left", padx=8)
        ttk.Button(actions, text="폴더 열기",
                   command=self._backup_folder).pack(side="left")
        ttk.Button(actions, text="지우기", style="SmallDanger.TButton",
                   command=self._backup_delete).pack(side="left", padx=8)

    def _data_dir(self):
        from .. import storage

        return storage.DATA_DIR

    def _refresh_backups(self) -> None:
        from .. import backup

        self.backup_tree.delete(*self.backup_tree.get_children())
        self._backups = {}
        for row in backup.listing(self._data_dir()):
            counts = row.get("counts") or {}
            what = " · ".join(f"{k} {v}" for k, v in counts.items() if v)
            if row.get("library_files"):
                what += f" · 보관함 {row['library_files']}개"
            if row.get("computer"):
                what += f"  ({row['computer']})"
            if not row.get("ok"):
                what = "⚠ 설정이 없는 파일 — 되돌릴 수 없습니다"
            when = row["made_at"].replace("T", " ")
            size = (f"{row['size'] / 1048576:.1f}MB" if row["size"] > 1048576
                    else f"{row['size'] // 1024}KB")
            key = self.backup_tree.insert(
                "", "end", values=(when, what or row["name"], size))
            self._backups[key] = row

    def _picked_backup(self):
        picked = self.backup_tree.selection()
        if not picked:
            messagebox.showinfo("전체 백업", "목록에서 백업을 먼저 고르세요.",
                                parent=self)
            return None
        return self._backups.get(picked[0])

    def _backup_now(self) -> None:
        try:
            path = self.engine.backup_now()
        except OSError as exc:
            messagebox.showerror("전체 백업", f"백업을 못 만들었습니다:\n{exc}",
                                 parent=self)
            return
        self._refresh_backups()
        messagebox.showinfo(
            "전체 백업",
            f"지금 설정을 담았습니다.\n\n{path.name}\n{path.parent}", parent=self)

    def _backup_restore(self) -> None:
        row = self._picked_backup()
        if row is None:
            return
        if not row.get("ok"):
            messagebox.showwarning("전체 백업",
                                   "이 파일에는 설정이 들어 있지 않습니다.",
                                   parent=self)
            return
        counts = " · ".join(f"{k} {v}"
                            for k, v in (row.get("counts") or {}).items() if v)
        if not messagebox.askyesno(
                "되돌리기",
                f"{row['made_at'].replace('T', ' ')} 에 담은 설정으로 "
                f"되돌릴까요?\n\n담긴 것: {counts}\n\n"
                "지금 설정(매크로 · 시나리오 · 조건 · 낚시 · 벌목 · 제작)은 "
                "이 백업의 것으로 모두 바뀝니다.\n"
                "되돌리기 직전 설정은 자동으로 한 벌 담아 둡니다.",
                parent=self):
            return
        try:
            report = self.engine.restore_backup(row["path"])
        except Exception as exc:  # noqa: BLE001 — 창으로 알려 준다
            messagebox.showerror("되돌리기", f"되돌리지 못했습니다:\n{exc}",
                                 parent=self)
            return
        self.on_changed()
        self._refresh_backups()
        messagebox.showinfo(
            "되돌리기",
            f"설정을 되돌렸습니다.\n\n보관함 파일 {report['library_files']}개도 "
            f"함께 되돌렸습니다.\n직전 설정은 {report['safety'].name} 에 있습니다.",
            parent=self)

    def _backup_import(self) -> None:
        from .. import backup

        picked = filedialog.askopenfilename(
            title="백업 파일 가져오기", parent=self,
            filetypes=[("Z9 백업", f"*{backup.SUFFIX}"), ("모든 파일", "*.*")])
        if not picked:
            return
        try:
            path = backup.bring_in(picked, self._data_dir())
        except OSError as exc:
            messagebox.showerror("가져오기", f"가져오지 못했습니다:\n{exc}",
                                 parent=self)
            return
        self._refresh_backups()
        self.engine.log(f"백업 가져옴: {path.name}")
        messagebox.showinfo(
            "가져오기",
            f"{path.name} 을(를) 목록에 넣었습니다.\n\n"
            "목록에서 고르고 [되돌리기]를 누르면 이 컴퓨터가 그 설정과 "
            "똑같아집니다.", parent=self)

    def _backup_export(self) -> None:
        import shutil

        row = self._picked_backup()
        if row is None:
            return
        target = filedialog.asksaveasfilename(
            title="백업 파일 내보내기", parent=self,
            initialfile=row["name"], defaultextension=row["path"].suffix)
        if not target:
            return
        try:
            shutil.copy2(row["path"], target)
        except OSError as exc:
            messagebox.showerror("내보내기", f"내보내지 못했습니다:\n{exc}",
                                 parent=self)
            return
        self.engine.log(f"백업 내보냄: {target}")

    def _backup_folder(self) -> None:
        from .. import backup

        folder = backup.folder_of(self._data_dir())
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # noqa: S606 — 탐색기로 폴더만 연다

    def _backup_delete(self) -> None:
        row = self._picked_backup()
        if row is None:
            return
        if not messagebox.askyesno("지우기", f"{row['name']} 을(를) 지울까요?",
                                   parent=self):
            return
        try:
            row["path"].unlink()
        except OSError as exc:
            messagebox.showerror("지우기", f"지우지 못했습니다:\n{exc}",
                                 parent=self)
            return
        self._refresh_backups()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        root = self.engine.library_root
        self.path_var.set(str(root))
        self._refresh_backups()

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
