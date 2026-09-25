"""스스로 점검 — exe가 제대로 묶였는지 창을 띄우지 않고 확인한다.

    Z9매크로.exe --selftest 결과.json

exe로 묶으면 개발 중에는 멀쩡하던 것이 빠지는 일이 흔하다 (안 딸려 온 모듈, 못 찾는
글꼴, 비어 버린 설정). 그런데 이 exe는 관리자 권한을 요구하고 전역 훅까지 설치하므로,
빌드할 때마다 직접 켜 보기가 번거롭다. 그래서 훅도 창도 없이 **켜질 때 거치는 길만**
그대로 밟아 보고, 무엇이 됐는지 JSON 파일로 남긴다.

창을 안 띄우는 빌드(--windowed)라 print는 보이지 않는다 — 그래서 파일로 쓴다.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path


def run(report_path: str) -> int:
    out: dict = {"ok": False, "steps": []}

    def step(name: str) -> None:
        out["steps"].append(name)

    try:
        from . import storage

        out["frozen"] = bool(getattr(sys, "frozen", False))
        out["project_dir"] = str(storage.PROJECT_DIR)
        out["bundle_dir"] = str(storage.BUNDLE_DIR)
        out["seeded"] = storage.seed_from_bundle()
        step("처음 설정 풀기")

        from .gui import fonts, theme

        out["fonts_loaded"] = fonts.load_bundled()
        step("글꼴 올리기")

        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        out["tk"] = str(root.tk.call("info", "patchlevel"))
        step("Tk 창")

        profile = storage.load()
        settings = profile.settings
        out["profile"] = {
            "exists": storage.DEFAULT_PROFILE.exists(),
            "macros": len(profile.macros),
            "rules": len(profile.rules),
            "scenarios": len(profile.scenarios),
            "fishing_ready": profile.fishing.ready,
            "window_pattern": settings.window_pattern,
        }
        step("설정 읽기")

        theme.use(settings.ui_theme, settings.ui_colors)
        theme.apply(root, settings.ui_scale)
        out["font_choices"] = [label for label, _family in fonts.choices(root)]
        step("테마 · 글꼴 목록")

        library = storage.DEFAULT_LIBRARY
        out["library_files"] = (sum(1 for p in library.rglob("*") if p.is_file())
                                if library.exists() else 0)

        # 화면 전체와 기능 모듈을 불러 본다. 빠진 모듈이 있으면 여기서 터진다.
        from . import digits, engine, fishing, fishtask, sound, tasks  # noqa: F401
        from .gui import app  # noqa: F401  — 모든 탭을 함께 불러온다

        step("모듈 불러오기")
        eng = engine.Engine()
        out["engine_library_root"] = str(eng.library_root)
        step("엔진 만들기 (훅은 안 켬)")

        root.destroy()
        out["ok"] = True
    except Exception:  # noqa: BLE001 — 무엇이든 파일에 남겨야 한다
        out["error"] = traceback.format_exc()
    try:
        Path(report_path).write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    except OSError:
        return 2
    return 0 if out["ok"] else 1
