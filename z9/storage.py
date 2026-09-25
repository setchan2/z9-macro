"""프로필 JSON 저장/불러오기."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from .model import Profile


def _project_dir() -> Path:
    """매크로와 설정을 둘 폴더의 기준점.

    exe로 묶으면 __file__ 은 PyInstaller 가 만든 **임시 해제 폴더**를 가리킨다.
    거기에 저장하면 프로그램을 끌 때 통째로 지워져서, 애써 만든 매크로가 매번
    사라진다. 묶인 상태에서는 exe 가 놓인 폴더를 기준으로 삼는다.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_DIR = _project_dir()
DATA_DIR = PROJECT_DIR / "data"
DEFAULT_PROFILE = DATA_DIR / "profile.json"
DEFAULT_LIBRARY = PROJECT_DIR / "library"


def _bundle_dir() -> Path:
    """exe 안에 **묶어 넣은** 파일이 풀리는 곳. 개발 중에는 프로젝트 폴더.

    PROJECT_DIR(사용자가 고치고 저장하는 곳)과 다르다. 여기는 켤 때마다 새로
    풀리고 끌 때 지워지는 읽기 전용 자리라, 글꼴처럼 **읽기만 하는 것**을 둔다.
    """
    base = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and base:
        return Path(base)
    return _project_dir()


BUNDLE_DIR = _bundle_dir()
# exe에 담아 온 **처음 설정** (빌드할 때의 profile.json · library).
SEED_DIR = BUNDLE_DIR / "seed"


def seed_from_bundle() -> list[str]:
    """exe에 담아 온 설정·라이브러리를 exe 옆에 **없을 때만** 풀어 놓는다.

    exe 파일 하나만 옮겨 와도 만들어 둔 매크로·조건·낚시 설정과 피로도 숫자
    글꼴(library)을 그대로 쓰게 하려는 것이다. **이미 있으면 절대 덮어쓰지 않는다**
    — exe 쪽에서 고쳐 쓴 설정이 빌드할 때의 옛 설정으로 되돌아가면 안 된다.

    무엇을 풀었는지 돌려준다. 개발 중(묶이지 않은 상태)에는 아무것도 안 한다.
    """
    if not getattr(sys, "frozen", False):
        return []
    done: list[str] = []
    try:
        profile = SEED_DIR / "data" / "profile.json"
        if profile.is_file() and not DEFAULT_PROFILE.exists():
            ensure_dir()
            shutil.copy2(profile, DEFAULT_PROFILE)
            done.append("설정(data/profile.json)")
        library = SEED_DIR / "library"
        if library.is_dir() and not DEFAULT_LIBRARY.exists():
            shutil.copytree(library, DEFAULT_LIBRARY)
            done.append("라이브러리(library)")
        ui = SEED_DIR / "data" / "ui"
        if ui.is_dir() and not (DATA_DIR / "ui").exists():
            shutil.copytree(ui, DATA_DIR / "ui")
            done.append("꾸미기 이미지(data/ui)")
    except OSError as exc:
        # 쓰기 금지 폴더(Program Files 등)에 둔 경우. 빈 설정으로라도 뜨게 한다.
        done.append(f"⚠ 처음 설정을 풀지 못했습니다: {exc}")
    return done


def ensure_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def load(path: Path | None = None) -> Profile:
    path = path or DEFAULT_PROFILE
    if not path.exists():
        return Profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # 깨진 파일은 지우지 않고 옆으로 치워둔다.
        broken = path.with_suffix(path.suffix + ".broken")
        try:
            shutil.copy2(path, broken)
        except OSError:
            pass
        return Profile()
    return Profile.from_dict(data)


def save(profile: Profile, path: Path | None = None) -> Path:
    path = path or DEFAULT_PROFILE
    ensure_dir()
    payload = json.dumps(profile.to_dict(), ensure_ascii=False, indent=2)
    # 저장 도중 죽어도 기존 파일이 날아가지 않도록 임시 파일 경유
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)
    return path
