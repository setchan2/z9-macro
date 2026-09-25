"""빌드 준비 — exe 안에 담을 **처음 설정**을 build\\seed 에 모은다.

[빌드.bat]이 PyInstaller 를 부르기 전에 이것을 돌린다. exe 파일 하나만 옮겨 와도
만들어 둔 것을 그대로 쓰게 하려는 것이다. exe 는 처음 켜질 때 이것을 자기 옆에
**없을 때만** 풀어 놓는다 (z9/storage.py 의 seed_from_bundle).

모으는 것

    data/profile.json   매크로 · 조건 · 시나리오 · 낚시 설정 전부
    data/ui/            꾸미기에서 고른 배경 이미지 · 창 아이콘 (있으면)
    library/            [설정]에서 정한 라이브러리 폴더 + 프로젝트 library/ 를 합친 것

라이브러리를 **합치는** 까닭 — 라이브러리 폴더를 바탕화면 등 다른 곳으로 정해 두면
감지 아이콘은 그쪽에, 예전에 익힌 숫자 글꼴은 프로젝트 library/ 에 나뉘어 남는다.
exe 를 다른 컴퓨터로 옮기면 그 절대 경로는 없으므로, 둘을 합쳐 담아 둔다.
글꼴(fonts/)은 여기서 안 옮긴다 — [빌드.bat]이 그대로 exe 에 담는다.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEED = ROOT / "build" / "seed"


def count_files(folder: Path) -> int:
    return sum(1 for p in folder.rglob("*") if p.is_file()) if folder.is_dir() else 0


def main() -> int:
    if SEED.exists():
        shutil.rmtree(SEED)
    (SEED / "data").mkdir(parents=True)

    # exe 로 쓰는 동안 고친 설정은 exe 옆(release\data)에 쌓인다. 프로젝트 쪽과
    # 둘 중 **더 최근에 저장된 것**을 담는다 — 안 그러면 exe 에서 고친 시나리오 ·
    # 매크로 · 낚시 설정이 옛것으로 되돌아간 exe 가 나온다.
    candidates = [ROOT / "data" / "profile.json",
                  ROOT / "release" / "data" / "profile.json"]
    candidates = [p for p in candidates if p.is_file()]
    profile = (max(candidates, key=lambda p: p.stat().st_mtime) if candidates
               else ROOT / "data" / "profile.json")
    libraries: list[Path] = []
    if profile.is_file():
        shutil.copy2(profile, SEED / "data" / "profile.json")
        try:
            settings = json.loads(profile.read_text(encoding="utf-8")).get("settings", {})
            configured = str(settings.get("library_dir") or "").strip()
        except (OSError, ValueError):
            configured = ""
        if configured and Path(configured).is_dir():
            libraries.append(Path(configured))
        print(f" 설정 파일      {profile.relative_to(ROOT)} ({profile.stat().st_size // 1024}KB)")
    else:
        print(" 설정 파일      없음 — exe 는 빈 설정으로 시작합니다")

    ui = profile.parent / "ui"
    if ui.is_dir():
        shutil.copytree(ui, SEED / "data" / "ui")
        print(f" 꾸미기 이미지  data/ui ({count_files(ui)}개)")

    # 나중 것이 위에 덮인다. 프로젝트 library/ 를 마지막에 두어, 같은 이름이면
    # 프로젝트 쪽(숫자 글꼴을 익힌 곳)이 남게 한다.
    libraries.append(ROOT / "release" / "library")
    libraries.append(ROOT / "library")
    target = SEED / "library"
    target.mkdir()
    for folder in libraries:
        if folder.is_dir():
            shutil.copytree(folder, target, dirs_exist_ok=True)
            print(f" 라이브러리     {folder} ({count_files(folder)}개)")
    print(f" → 합친 라이브러리 {count_files(target)}개")

    fonts = ROOT / "fonts"
    if not fonts.is_dir():
        print(" [경고] fonts 폴더가 없습니다 — 글꼴 없이 묶입니다")
    else:
        print(f" 글꼴           fonts ({count_files(fonts)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
