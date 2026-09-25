"""탭 — 도움말.

왼쪽에 목차, 오른쪽에 본문. 본문은 tk.Text에 태그로 서식을 입힌다.

**왜 웹 문서가 아니라 앱 안에 두나** — 처음 쓰는 사람은 프로그램을 켠 채로 막힌다.
그때 브라우저를 찾아 열게 하면 대부분은 그냥 포기한다. exe 하나만 있어도 읽을 수
있어야 한다.

글은 helpdoc.py에 따로 두었다. 문장은 자주 고쳐지고 화면은 잘 안 바뀐다.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from . import theme
from .helpdoc import DOC

# 본문 좌우 여백(글자 수 기준). 한 줄이 너무 길면 눈이 다음 줄을 못 찾는다.
WRAP_PAD = 24


class HelpTab(ttk.Frame):
    def __init__(self, parent: tk.Misc, engine) -> None:
        super().__init__(parent, padding=10)
        self.engine = engine
        self._marks: dict[str, str] = {}
        self._hits: list[str] = []
        self._hit_at = 0
        self._last_query = ""

        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # 목차와 본문 사이도 끌어서 넓힐 수 있게 한다.
        self.split = ttk.PanedWindow(self, orient="horizontal")
        self.split.grid(row=0, column=0, sticky="nsew")
        self._sash_placed = False
        self.split.bind("<Configure>", self._place_sash, add="+")

        # -- 왼쪽: 목차 ---------------------------------------------------
        left = ttk.Frame(self.split, padding=(0, 0, 8, 0))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="목차", style="Heading.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.toc = ttk.Treeview(left, show="tree", selectmode="browse")
        # 칸이 늘어나야 분할선을 끌었을 때 긴 소제목이 실제로 다 보인다.
        self.toc.column("#0", width=theme.px(250), stretch=True)
        self.toc.grid(row=1, column=0, sticky="nsew")
        bar = ttk.Scrollbar(left, orient="vertical", command=self.toc.yview)
        bar.grid(row=1, column=1, sticky="ns")
        self.toc.configure(yscrollcommand=bar.set)
        self.toc.bind("<<TreeviewSelect>>", self._on_toc)

        # -- 오른쪽: 본문 ---------------------------------------------------
        right = ttk.Frame(self.split, padding=(4, 0, 0, 0))
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        find = ttk.Frame(right)
        find.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(find, text="찾기").pack(side="left", padx=(0, 6))
        self.query = tk.StringVar()
        entry = ttk.Entry(find, textvariable=self.query, width=26)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self._find_next())
        ttk.Button(
            find, text="다음 찾기", style="Small.TButton", command=self._find_next
        ).pack(side="left", padx=6)
        self.found_var = tk.StringVar(value="")
        ttk.Label(find, textvariable=self.found_var, style="Muted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(
            find, text="맨 위로", style="Small.TButton",
            command=lambda: self.text.yview_moveto(0.0),
        ).pack(side="right")

        wrap = ttk.Frame(right)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.text = tk.Text(wrap, wrap="word", padx=16, pady=12, cursor="arrow")
        theme.style_text(self.text)
        self.text.pack(side="left", fill="both", expand=True)
        tbar = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        tbar.pack(side="left", fill="y")
        self.text.configure(yscrollcommand=tbar.set)

        # 넓어진 만큼은 본문이 가진다. 목차는 제목이 보일 만큼만 있으면 된다.
        self.split.add(left, weight=0)
        self.split.add(right, weight=1)

        self._make_tags()
        self._render()
        self.text.configure(state="disabled")
        # 읽기 전용이지만 휠과 키보드로는 움직여야 한다.
        self.text.bind("<Key>", self._on_key)

    # ------------------------------------------------------------------
    def _place_sash(self, _event: object = None) -> None:
        if self._sash_placed:
            return
        width = self.split.winfo_width()
        if width < theme.px(500):
            return
        self._sash_placed = True
        try:
            self.split.sashpos(0, min(theme.px(270), width // 3))
        except tk.TclError:
            pass

    def _on_key(self, event: tk.Event) -> str | None:
        """읽기용이라 글자는 못 넣지만, 이동 키는 그대로 살린다."""
        if event.keysym in (
            "Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End"
        ):
            return None
        if event.state & 0x4 and event.keysym.lower() in ("c", "a"):  # Ctrl+C / Ctrl+A
            return None
        return "break"

    # ------------------------------------------------------------------
    # 서식
    # ------------------------------------------------------------------
    def _make_tags(self) -> None:
        p = theme.PALETTE
        family = theme.BASE_FAMILY
        size = theme.font_size(theme.BASE_SIZE)

        self.text.tag_configure(
            "h1",
            font=(family, theme.font_size(theme.BASE_SIZE + 5), "bold"),
            foreground=p["text"],
            spacing1=theme.px(22),
            spacing3=theme.px(10),
        )
        self.text.tag_configure(
            "h2",
            font=(family, theme.font_size(theme.BASE_SIZE + 2), "bold"),
            foreground=p["accent"],
            spacing1=theme.px(16),
            spacing3=theme.px(6),
        )
        self.text.tag_configure(
            "p", font=(family, size), spacing1=theme.px(3), spacing3=theme.px(6),
            spacing2=theme.px(3),
        )
        self.text.tag_configure(
            "li", font=(family, size), lmargin1=theme.px(14), lmargin2=theme.px(28),
            spacing1=theme.px(2), spacing3=theme.px(2), spacing2=theme.px(2),
        )
        self.text.tag_configure(
            "step", font=(family, size), lmargin1=theme.px(14), lmargin2=theme.px(34),
            spacing1=theme.px(2), spacing3=theme.px(2), spacing2=theme.px(2),
        )
        self.text.tag_configure(
            "term", font=(family, size, "bold"), foreground=p["text"],
            lmargin1=theme.px(14), lmargin2=theme.px(14), spacing1=theme.px(6),
        )
        self.text.tag_configure(
            "desc", font=(family, size), foreground=p["muted"],
            lmargin1=theme.px(30), lmargin2=theme.px(30), spacing3=theme.px(3),
            spacing2=theme.px(2),
        )
        self.text.tag_configure(
            "code",
            font=(theme.MONO_FAMILY, size),
            background=p["raised"],
            lmargin1=theme.px(16), lmargin2=theme.px(16), rmargin=theme.px(16),
            spacing1=theme.px(8), spacing3=theme.px(8), spacing2=theme.px(2),
        )
        self.text.tag_configure(
            "tip",
            font=(family, size),
            background=p["accent_soft"],
            foreground=p["text"],
            lmargin1=theme.px(14), lmargin2=theme.px(14), rmargin=theme.px(14),
            spacing1=theme.px(8), spacing3=theme.px(8), spacing2=theme.px(3),
        )
        self.text.tag_configure(
            "warn",
            font=(family, size),
            background="#f6ecea",
            foreground=p["text"],
            lmargin1=theme.px(14), lmargin2=theme.px(14), rmargin=theme.px(14),
            spacing1=theme.px(8), spacing3=theme.px(8), spacing2=theme.px(3),
        )
        # 문장 안의 **굵게**
        self.text.tag_configure("b", font=(family, size, "bold"))
        self.text.tag_configure("bi", font=(family, size, "bold"),
                                foreground=p["accent"])
        self.text.tag_configure("hit", background=p["select"])

    def _emit(self, text: str, tag: str) -> None:
        """**굵게** 표시를 풀어서 넣는다.

        전체 문법을 흉내 낼 생각은 없다. 강조 하나면 읽는 데 충분하고, 그 이상은
        글을 쓰는 사람이 문장을 나누는 편이 낫다.
        """
        pieces = text.split("**")
        for index, piece in enumerate(pieces):
            if not piece:
                continue
            if index % 2:
                self.text.insert("end", piece, (tag, "b"))
            else:
                self.text.insert("end", piece, tag)
        self.text.insert("end", "\n")

    def _render(self) -> None:
        for title, blocks in DOC:
            mark = f"sec{len(self._marks)}"
            self.text.mark_set(mark, "end-1c")
            self.text.mark_gravity(mark, "left")
            self._marks[title] = mark
            node = self.toc.insert("", "end", iid=title, text=title, open=False)

            self._emit(title, "h1")
            number = 0
            for kind, body in blocks:
                if kind == "h":
                    # 표식은 반드시 **글을 넣기 전에** 찍는다. 넣고 나서 뒤로
                    # 세어 오면 줄 한복판을 가리키게 되어, 목차를 눌렀을 때
                    # 제목이 잘린 채로 화면 맨 위에 걸린다.
                    sub = f"{title}\x00{body}"
                    submark = f"sec{len(self._marks)}"
                    self.text.mark_set(submark, "end-1c")
                    self.text.mark_gravity(submark, "left")
                    self._marks[sub] = submark
                    self._emit(str(body), "h2")
                    self.toc.insert(node, "end", iid=sub, text=f"  {body}")
                    number = 0
                elif kind == "p":
                    # 문단이 끼어들면 거기서 목록이 끊긴 것으로 본다. 한 절 안에
                    # "이럴 때는 1,2,3 / 저럴 때는 1,2,3"처럼 갈리는 경우가 많은데,
                    # 번호가 이어지면 앞의 것에 딸린 줄로 읽힌다.
                    number = 0
                    self._emit(str(body), "p")
                elif kind == "li":
                    self._emit(f"· {body}", "li")
                elif kind == "step":
                    number += 1
                    self._emit(f"{number}. {body}", "step")
                elif kind == "kv":
                    for term, desc in body:  # type: ignore[misc]
                        self._emit(term, "term")
                        self._emit(desc, "desc")
                elif kind == "code":
                    self.text.insert("end", str(body) + "\n", "code")
                elif kind == "tip":
                    # 맑은 고딕에 없는 글자(💡 등)를 쓰면 네모로 깨진다.
                    # KS 기호 범위 안에서 고른다.
                    self._emit(f"※ {body}", "tip")
                elif kind == "warn":
                    self._emit(f"⚠ {body}", "warn")
                elif kind == "hr":
                    self.text.insert("end", "\n")
            self.text.insert("end", "\n")

    # ------------------------------------------------------------------
    def _on_toc(self, _event: object = None) -> None:
        selection = self.toc.selection()
        if not selection:
            return
        mark = self._marks.get(selection[0])
        if mark is None:
            return
        # 절을 고르면 그 안의 소제목을 펼쳐 준다. 무엇이 들어 있는지 보여야
        # 다음에 어디를 누를지 알 수 있다.
        self.toc.item(selection[0], open=True)
        self.text.see(mark)
        # see()는 화면 안에만 넣어 준다. 고른 절이 맨 위에 오게 한 번 더 맞춘다.
        self.text.update_idletasks()
        self.text.yview(mark)

    def _find_next(self) -> None:
        query = self.query.get().strip()
        if not query:
            self.found_var.set("")
            self.text.tag_remove("hit", "1.0", "end")
            return

        if query != self._last_query:
            self._last_query = query
            self._hits = []
            self._hit_at = 0
            self.text.tag_remove("hit", "1.0", "end")
            start = "1.0"
            while True:
                found = self.text.search(query, start, stopindex="end", nocase=True)
                if not found:
                    break
                end = f"{found}+{len(query)}c"
                self.text.tag_add("hit", found, end)
                self._hits.append(found)
                start = end

        if not self._hits:
            self.found_var.set("찾지 못했습니다")
            return
        where = self._hits[self._hit_at % len(self._hits)]
        self.found_var.set(f"{self._hit_at % len(self._hits) + 1} / {len(self._hits)}")
        self._hit_at += 1
        self.text.see(where)
        self.text.update_idletasks()
        self.text.yview(f"{where} - 3 lines")

    # ------------------------------------------------------------------
    def sash_value(self) -> int:
        if not self._sash_placed:
            return 0
        try:
            return int(self.split.sashpos(0))
        except tk.TclError:
            return 0

    def reset_sash(self) -> None:
        self._sash_placed = False
        self._place_sash()
