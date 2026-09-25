"""Z9★ 온라인 매크로 — 실행 진입점.

    python main.py
"""

from __future__ import annotations

import sys


def _check_platform() -> None:
    if sys.platform != "win32":
        raise SystemExit("이 프로그램은 Windows 전용입니다.")


def main() -> None:
    _check_platform()
    # 빌드한 exe가 제대로 묶였는지 창 없이 점검한다: Z9매크로.exe --selftest 결과.json
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        from z9.selftest import run as selftest

        raise SystemExit(selftest(sys.argv[2]))
    try:
        from z9.gui.app import main as run
    except ImportError as exc:  # tkinter 미설치 등
        raise SystemExit(f"필요한 모듈을 불러오지 못했습니다: {exc}") from exc
    run()


if __name__ == "__main__":
    main()
