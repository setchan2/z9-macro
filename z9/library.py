"""매크로 라이브러리 — 사용자가 지정한 폴더에 항목을 개별 파일로 정리해 둔다.

작업 프로필(`data/profile.json`)은 "지금 켜져 있는 것들"이다. 핫키가 걸리고
실제로 실행되는 대상이라 하나의 파일로 관리하는 게 맞다.

반면 만들어 둔 매크로를 나중에 다시 꺼내 쓰려면 그걸로는 부족하다. 그래서
라이브러리를 따로 둔다.

    <라이브러리 폴더>/
        농사/
            기본 연타.z9m.json
            작물 감지.z9m.json
        목장/
            여물주기.z9m.json

  · 하위 폴더 = 카테고리
  · 파일 하나 = 항목 하나 (연타 / 매크로 / 경로 / 조건)

항목마다 파일을 나눠 두면 탐색기에서 옮기고 복사하고 백업하기가 쉽고, 하나가
깨져도 나머지가 멀쩡하다.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from .model import (
    Macro,
    PathMacro,
    PixelRule,
    Profile,
    RepeatTask,
    Scenario,
    ScheduledTask,
)
from .model import BuffItem

SUFFIX = ".z9m.json"
FORMAT_VERSION = 1

# 보관함에 **올리는** 종류. 보관함은 "지금 가진 매크로 · 시나리오"와 똑같이 맞춘다.
UPLOAD_TYPES = ("macro", "scenario")

# 보관함에서 치운 항목을 옮겨 두는 폴더 이름 (data 폴더 아래). 지우지 않고 옮긴다 —
# 잘못 치웠을 때 되살릴 길이 있어야 한다.
BACKUP_DIRNAME = "보관함_지운것"

# 종류 코드 ↔ 클래스 ↔ 프로필 안의 목록 이름
TYPES: dict[str, tuple[type, str, str]] = {
    "macro": (Macro, "macros", "녹화 매크로"),
    "repeat": (RepeatTask, "repeats", "연타"),
    "path": (PathMacro, "paths", "이동 경로"),
    "rule": (PixelRule, "rules", "감지 조건"),
    "scenario": (Scenario, "scenarios", "시나리오"),
    "schedule": (ScheduledTask, "schedules", "시간 예약"),
    "buff": (BuffItem, "buffs", "버프"),
}

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class LibraryError(RuntimeError):
    pass


def safe_name(name: str) -> str:
    """Windows 파일명으로 쓸 수 있게 다듬는다."""
    cleaned = _BAD_CHARS.sub("_", name).strip().strip(".")
    if not cleaned:
        cleaned = "이름없음"
    if cleaned.upper() in _RESERVED:
        cleaned = f"_{cleaned}"
    return cleaned[:100]


@dataclass
class LibraryEntry:
    path: Path
    category: str  # "" = 최상위
    name: str
    type_code: str

    @property
    def type_label(self) -> str:
        return TYPES[self.type_code][2] if self.type_code in TYPES else self.type_code

    @property
    def display(self) -> str:
        return f"{self.name}  ({self.type_label})"


def type_of(item) -> str:
    for code, (cls, _attr, _label) in TYPES.items():
        if isinstance(item, cls):
            return code
    raise LibraryError(f"라이브러리에 저장할 수 없는 종류입니다: {type(item).__name__}")


# --------------------------------------------------------------------------
class Library:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- 폴더 ----------------------------------------------------------
    def ensure(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def categories(self) -> list[str]:
        if not self.root.exists():
            return []
        found = sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
        return found

    def create_category(self, name: str) -> Path:
        folder = self.ensure() / safe_name(name)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _folder(self, category: str) -> Path:
        return self.ensure() / safe_name(category) if category else self.ensure()

    # -- 목록 ----------------------------------------------------------
    def entries(self) -> list[LibraryEntry]:
        """라이브러리 전체를 훑어 항목 목록을 만든다. 깨진 파일은 건너뛴다."""
        if not self.root.exists():
            return []

        out: list[LibraryEntry] = []
        for path in sorted(self.root.rglob(f"*{SUFFIX}")):
            try:
                rel = path.relative_to(self.root)
            except ValueError:
                continue
            if BACKUP_DIRNAME in rel.parts:
                continue  # 보관함 안에 백업이 생긴 경우라도 목록에는 안 띄운다
            category = str(rel.parent) if rel.parent != Path(".") else ""
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                type_code = str(data.get("type", ""))
                name = str(data.get("item", {}).get("name", path.name))
            except (OSError, json.JSONDecodeError, AttributeError):
                continue
            if type_code not in TYPES:
                continue
            out.append(
                LibraryEntry(path=path, category=category, name=name, type_code=type_code)
            )
        return out

    # -- 저장 / 불러오기 -------------------------------------------------
    def save(self, item, category: str = "", overwrite: bool = True,
             folder: Path | None = None) -> Path:
        """항목을 파일로 저장한다. folder를 주면 카테고리 대신 **그 폴더에 그대로** 둔다
        (하위 카테고리 폴더를 다시 다듬다가 구조가 바뀌는 일을 막는다)."""
        type_code = type_of(item)
        folder = Path(folder) if folder is not None else self._folder(category)
        folder.mkdir(parents=True, exist_ok=True)
        path = self._free_path(folder, item, type_code)

        if path.exists() and not overwrite:
            raise LibraryError(f"이미 있는 파일입니다: {path.name}")

        payload = {
            "z9": FORMAT_VERSION,
            "type": type_code,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "item": item.to_dict(),
        }
        # 저장 도중 죽어도 기존 파일이 날아가지 않게 임시 파일 경유
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(path)
        return path

    def _free_path(self, folder: Path, item, type_code: str) -> Path:
        """그 항목을 둘 파일 자리. **다른 항목이 든 파일은 절대 덮어쓰지 않는다.**

        파일 이름은 항목 이름을 다듬어 만드므로 서로 다른 이름이 같은 파일로 모일 수
        있다 — "a/b"와 "a_b", 윈도우가 대소문자를 안 가리는 "Farm"과 "farm", 탐색기에서
        파일 이름만 바꾼 것, 매크로와 같은 이름의 시나리오. 그 파일에 **같은 종류 · 같은
        이름**의 항목이 들어 있을 때만 덮어쓰고, 아니면 번호를 붙인 이름을 찾는다.
        읽을 수 없는 파일도 남의 것으로 보고 건드리지 않는다.
        """
        base = safe_name(item.name)[:90]
        label = TYPES[type_code][2]
        names = [base, f"{base} ({label})"] + [f"{base} ({label} {i})" for i in range(2, 100)]
        for name in names:
            path = folder / (safe_name(name) + SUFFIX)
            if not path.exists() or _item_in(path) == (type_code, item.name):
                return path
        raise LibraryError(f"'{item.name}'을(를) 저장할 파일 이름을 찾지 못했습니다.")

    def backup_copy(self, path: Path, backup: Path) -> Path:
        """항목 파일을 백업 폴더에 **복사**한다 (원본은 그대로)."""
        src = Path(path)
        try:
            rel = src.relative_to(self.root)
        except ValueError:
            rel = Path(src.name)
        dest = Path(backup) / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(f"{src.name[:-len(SUFFIX)]}-{time.time_ns()}{SUFFIX}")
            shutil.copy2(src, dest)
        except OSError as exc:
            raise LibraryError(f"백업하지 못했습니다: {exc}") from exc
        return dest

    def load(self, path: Path):
        """파일 하나 → (종류 코드, 항목 객체)."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LibraryError(f"파일을 읽지 못했습니다: {exc}") from exc

        type_code = str(data.get("type", ""))
        if type_code not in TYPES:
            raise LibraryError(f"알 수 없는 항목 종류입니다: {type_code!r}")
        cls = TYPES[type_code][0]
        raw = data.get("item")
        if not isinstance(raw, dict):
            raise LibraryError("항목 내용이 없습니다.")
        return (type_code, cls.from_dict(raw))

    def delete(self, path: Path) -> None:
        try:
            Path(path).unlink()
        except OSError as exc:
            raise LibraryError(f"삭제하지 못했습니다: {exc}") from exc

    def discard(self, path: Path, backup: Path) -> Path:
        """항목 파일을 보관함에서 치워 **백업 폴더로 옮긴다.** 옮긴 자리를 돌려준다.

        카테고리 폴더 구조를 그대로 살려 옮기므로, 되살릴 때 제자리에 다시 넣으면 된다.
        """
        src = Path(path)
        try:
            rel = src.relative_to(self.root)
        except ValueError:
            rel = Path(src.name)
        dest = Path(backup) / rel
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(f"{src.name[:-len(SUFFIX)]}-{time.time_ns()}{SUFFIX}")
            shutil.move(str(src), str(dest))
        except OSError as exc:
            raise LibraryError(f"치우지 못했습니다: {exc}") from exc
        return dest

    def rename(self, path: Path, new_name: str) -> Path:
        """파일 안의 항목 이름과 파일 이름을 함께 바꾼다."""
        type_code, item = self.load(path)
        item.name = new_name.strip() or item.name
        category = ""
        rel = Path(path).relative_to(self.root)
        if rel.parent != Path("."):
            category = str(rel.parent)
        new_path = self.save(item, category=category)
        if new_path != Path(path):
            try:
                Path(path).unlink()
            except OSError:
                pass
        return new_path


def _item_in(path: Path) -> tuple[str, str] | None:
    """항목 파일에 든 (종류 코드, 이름). 못 읽으면 None."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return (str(data.get("type", "")), str(data.get("item", {}).get("name", "")))
    except (OSError, ValueError, AttributeError):
        return None


def _norm(path) -> str:
    import os

    return os.path.normcase(os.path.abspath(str(path)))


# --------------------------------------------------------------------------
# 보관함 올리기 — 보관함을 "지금 가진 매크로 · 시나리오"와 똑같이 맞춘다
# --------------------------------------------------------------------------
@dataclass
class UploadReport:
    saved: list[str] = field(default_factory=list)  # 새로 올린 것
    replaced: list[str] = field(default_factory=list)  # 같은 이름이 있어 바꿔 올린 것
    removed: list[str] = field(default_factory=list)  # 지금 가진 것이 아니라 치운 것
    failed: list[str] = field(default_factory=list)
    backup: Path | None = None  # 치운 것 · 바꾸기 전 것을 옮겨 둔 곳

    def summary(self) -> str:
        parts = [f"올림 {len(self.saved) + len(self.replaced)}개"
                 + (f" (그중 같은 이름 바꿈 {len(self.replaced)}개)" if self.replaced else ""),
                 f"치움 {len(self.removed)}개"]
        if self.failed:
            parts.append(f"실패 {len(self.failed)}개")
        return " · ".join(parts)


def new_backup_dir() -> Path:
    from . import storage

    return storage.DATA_DIR / BACKUP_DIRNAME / time.strftime("%Y%m%d-%H%M%S")


def upload(lib: Library, items: list, keep: set[tuple[str, str]], category: str = "",
           backup: Path | None = None, dry_run: bool = False) -> UploadReport:
    """items를 보관함에 올리고, keep에 없는 항목 파일은 치운다.

    · **같은 종류 · 같은 이름**이 보관함에 있으면(어느 카테고리든) 그것을 치우고 새로
      저장한다. 그 항목이 있던 카테고리에 다시 넣어, 정리해 둔 폴더가 흐트러지지 않게 한다.
    · 올리고 나서 keep(지금 가진 매크로 · 시나리오)에 없는 항목 파일은 **종류를 가리지
      않고** 치운다 — 지난 매크로, 조건, 예약 파일 모두.
    · 항목 파일(.z9m.json)이 아닌 것은 건드리지 않는다. 감지 조건이 쓰는 아이콘 그림이
      보관함 폴더에 들어 있어서, 지우면 조건이 조용히 망가진다.
    · 치운 것은 지우지 않고 backup 폴더로 옮긴다.

    dry_run이면 아무것도 바꾸지 않고 무엇을 할지만 적어 돌려준다(확인 창에 쓴다).
    """
    report = UploadReport()
    backup = backup or new_backup_dir()
    entries = lib.entries()
    saved_paths: set[str] = set()
    uploaded: set[tuple[str, str]] = set()
    backed_up = False

    for item in items:
        code = type_of(item)
        label = f"{item.name} ({TYPES[code][2]})"
        same = [e for e in entries if e.type_code == code and e.name == item.name]
        uploaded.add((code, item.name))
        if dry_run:
            (report.replaced if same else report.saved).append(label)
            continue
        try:
            # **백업 → 저장 → 성공하면 나머지 정리** 순서다. 먼저 치우고 저장하다
            # 실패하면(원드라이브 · 백신이 파일을 잡고 있으면 흔하다) 보관함에서만
            # 사라진 채 남는다.
            for entry in same:
                lib.backup_copy(entry.path, backup)
                backed_up = True
            folder = Path(same[0].path).parent if same else None
            path = lib.save(item, category=category, folder=folder)
            saved_paths.add(_norm(path))
            for entry in same:
                if _norm(entry.path) != _norm(path) and Path(entry.path).exists():
                    Path(entry.path).unlink()  # 다른 카테고리의 같은 항목 — 이미 백업함
            (report.replaced if same else report.saved).append(label)
        except (LibraryError, OSError) as exc:
            report.failed.append(f"{label}: {exc}")

    for entry in (entries if dry_run else lib.entries()):
        if (entry.type_code, entry.name) in keep:
            continue
        if dry_run:
            if (entry.type_code, entry.name) not in uploaded:
                report.removed.append(f"{entry.name} ({entry.type_label})")
            continue
        if _norm(entry.path) in saved_paths:
            continue
        try:
            lib.discard(entry.path, backup)
            backed_up = True
            report.removed.append(f"{entry.name} ({entry.type_label})")
        except (LibraryError, OSError) as exc:
            report.failed.append(f"{entry.name}: {exc}")

    if not dry_run and backed_up:
        report.backup = backup
    return report


# --------------------------------------------------------------------------
# 프로필과 주고받기
# --------------------------------------------------------------------------
def profile_list(profile: Profile, type_code: str) -> list:
    return getattr(profile, TYPES[type_code][1])


def unique_name(base: str, existing: list[str]) -> str:
    if base not in existing:
        return base
    i = 2
    while f"{base} ({i})" in existing:
        i += 1
    return f"{base} ({i})"


def import_into(profile: Profile, type_code: str, item) -> str:
    """라이브러리 항목을 작업 프로필에 추가한다.

    이름이 겹치면 덮어쓰지 않고 새 이름을 붙인다. 실행 중인 항목을 몰래 바꿔
    버리면 사용자가 이유를 알 수 없기 때문이다.
    """
    target = profile_list(profile, type_code)
    item.name = unique_name(item.name, [i.name for i in target])
    # 핫키는 가져오지 않는다. 기존 항목과 충돌하면 둘 다 오작동한다.
    if hasattr(item, "hotkey"):
        item.hotkey = ""
    target.append(item)
    return item.name


def collect_profile_items(profile: Profile) -> list[tuple[str, object]]:
    """(종류 코드, 항목) 목록 — 저장 대상 고르기 UI에 쓴다."""
    out: list[tuple[str, object]] = []
    for code in TYPES:
        for item in profile_list(profile, code):
            out.append((code, item))
    return out
