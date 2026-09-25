"""탭 0 — 생활 콘텐츠 프리셋 (사냥/채광/벌목/농사/낚시/목장)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from .. import presets
from ..engine import Engine
from . import theme

DESCRIPTIONS = {
    "사냥": "좌우 순찰 + 공격 연타 + 체력 조건 회복. 세 가지를 따로 켜고 끕니다.",
    "채광": "채광 키를 주기적으로 반복. 광맥이 사라지면 다음 지점으로 이동.",
    "벌목": "벌목 키를 주기적으로 반복. 나무가 사라지면 다음 지점으로 이동.",
    "농사": "심기/수확 키 반복 + 밭 사이 이동 경로.",
    "낚시": "입질을 픽셀로 감지해 낚아챕니다. 시간 기반보다 훨씬 정확합니다.",
    "목장": "동물 상호작용 키를 쿨타임에 맞춰 반복.",
}


class PresetTab(ttk.Frame):
    def __init__(
        self, parent: tk.Misc, engine: Engine, on_applied: Callable[[], None]
    ) -> None:
        super().__init__(parent, padding=14)
        self.engine = engine
        self.on_applied = on_applied

        ttk.Label(
            self,
            text="생활 콘텐츠 프리셋",
            style="Title.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            self,
            text=(
                "콘텐츠별 뼈대(연타 · 이동 경로 · 감지 조건)를 한 번에 만듭니다.\n"
                "만든 뒤 각 탭에서 실제 단축키와 감지 좌표를 채워 넣으세요."
            ),
            style="Muted.TLabel",
            justify="left",
        ).pack(anchor="w", pady=(4, 14))

        grid = ttk.Frame(self)
        grid.pack(fill="x")
        for index, activity in enumerate(presets.ACTIVITIES):
            self._card(grid, activity, index)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        guide = ttk.LabelFrame(self, text="다음에 할 일", padding=10)
        guide.pack(fill="both", expand=True, pady=(16, 0))

        self.notes = tk.Text(
            guide, height=10, wrap="word", state="disabled"
        )
        theme.style_text(self.notes)
        self.notes.pack(side="left", fill="both", expand=True)
        bar = ttk.Scrollbar(guide, orient="vertical", command=self.notes.yview)
        bar.pack(side="left", fill="y")
        self.notes.configure(yscrollcommand=bar.set)

        self._write_notes(
            "위에서 콘텐츠를 고르면 여기에 설정해야 할 항목이 순서대로 표시됩니다."
        )

    def _card(self, parent: ttk.Frame, activity: str, index: int) -> None:
        box = ttk.LabelFrame(parent, text=f"  {activity}  ", padding=10)
        box.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
        ttk.Label(
            box, text=DESCRIPTIONS[activity], wraplength=380, justify="left", style="Muted.TLabel"
        ).pack(anchor="w")
        ttk.Button(
            box,
            text=f"{activity} 프리셋 만들기",
            command=lambda a=activity: self._apply(a),
        ).pack(anchor="w", pady=(8, 0))

    def _apply(self, activity: str) -> None:
        spec, added = presets.apply_to(self.engine.profile, activity)
        self.engine.rebind_hotkeys()
        self.on_applied()

        lines = [f"■ {spec.summary}", ""]
        if added:
            lines.append("만들어진 항목:")
            lines += [f"   · {name}" for name in added]
            self.engine.log(f"{activity} 프리셋 생성 — 항목 {len(added)}개.")
        else:
            lines.append("이미 만들어져 있습니다. 기존 항목을 그대로 씁니다.")
        lines += ["", "설정할 것:"]
        lines += [f"   {i}. {note}" for i, note in enumerate(spec.notes, start=1)]
        lines += [
            "",
            "감지 점은 [조건부 실행] 탭에서 '🎯 점 추가 (화면 클릭)'로 찍습니다.",
            "핫키는 각 항목 폼의 [지정] 버튼으로 걸어두면 게임 중에 켜고 끌 수 있습니다.",
        ]
        self._write_notes("\n".join(lines))

    def _write_notes(self, text: str) -> None:
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", text)
        self.notes.configure(state="disabled")
