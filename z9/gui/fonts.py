"""글꼴 — 프로그램에 딸린 글꼴을 **설치하지 않고** 쓴다.

프로그램 폴더의 fonts/ 아래 .ttf · .otf 를 켤 때마다 윈도우에 **이 프로그램만 쓰는
글꼴**로 올린다(AddFontResourceEx + FR_PRIVATE). 윈도우 글꼴 폴더에 설치하지 않으므로
관리자 권한도 필요 없고, 프로그램을 끄면 흔적 없이 사라진다. 다른 프로그램에는 안 보인다.

## 글꼴 이름은 파일에서 읽는다

같은 글꼴도 윈도우가 부르는 이름이 한글일 때와 영어일 때가 있다(예: "G마켓 산스" /
"Gmarket Sans"). 이름을 여기 적어 두면 윈도우 언어가 바뀌는 날 조용히 틀린다. 그래서
글꼴 파일의 이름표('name' 표)에서 후보 이름을 모두 읽고, 그중 **Tk가 실제로 알아보는
이름**을 쓴다. fonts/ 에 새 글꼴 폴더를 넣기만 하면 목록에 저절로 뜬다.

폴더 하나가 글꼴 하나다. 폴더 안에서 이름순으로 **맨 앞 파일이 대표**(보통 굵기)이고,
나머지(굵게)는 함께 올려 두어 굵은 글씨에 쓰이게 한다.
"""

from __future__ import annotations

import ctypes
import struct
from pathlib import Path

from .. import storage

# 사용자가 글꼴을 더 넣는 곳(exe 옆 fonts/)과, exe 안에 묶어 온 글꼴이 풀리는 곳.
# 개발 중에는 둘이 같은 폴더다.
FONT_DIR = storage.PROJECT_DIR / "fonts"
FONT_DIRS = tuple(dict.fromkeys((FONT_DIR, storage.BUNDLE_DIR / "fonts")))
FR_PRIVATE = 0x10
SYSTEM_DEFAULT = "Malgun Gothic"
SYSTEM_LABEL = "맑은 고딕 (윈도우 기본)"

# 올린 파일 → 이름표에서 읽은 후보 이름들.
_LOADED: dict[Path, list[str]] = {}


def family_names(path: str | Path) -> list[str]:
    """글꼴 파일의 이름표에서 글꼴 이름 후보들을 읽는다. 못 읽으면 []."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    if len(data) < 12 or data[:4] == b"ttcf":
        return []
    try:
        (tables,) = struct.unpack(">H", data[4:6])
        offset = None
        for i in range(tables):
            tag, _sum, start, _length = struct.unpack(
                ">4sIII", data[12 + 16 * i:28 + 16 * i])
            if tag == b"name":
                offset = start
                break
        if offset is None:
            return []
        _fmt, count, strings = struct.unpack(">HHH", data[offset:offset + 6])
        found: list[tuple[int, str]] = []
        for j in range(count):
            base = offset + 6 + 12 * j
            platform, _enc, _lang, name_id, length, where = struct.unpack(
                ">HHHHHH", data[base:base + 12])
            # 1 = 글꼴 이름(윈도우가 쓰는 것), 16 = 굵기를 뺀 대표 이름
            if name_id not in (1, 16):
                continue
            raw = data[offset + strings + where:offset + strings + where + length]
            try:
                text = (raw.decode("utf-16-be") if platform in (0, 3)
                        else raw.decode("latin-1"))
            except UnicodeDecodeError:
                continue
            found.append((0 if name_id == 1 else 1, text.strip()))
    except struct.error:
        return []
    names: list[str] = []
    for _rank, text in sorted(found, key=lambda item: item[0]):
        if text and text not in names:
            names.append(text)
    return names


def load_bundled() -> int:
    """fonts/ 아래 글꼴을 이 프로그램 전용으로 올린다. 새로 올린 파일 수.

    exe 옆 fonts/ 와 exe 안에 묶어 온 fonts/ 를 둘 다 본다. 같은 글꼴이 양쪽에
    있으면 목록에는 한 번만 뜬다 (choices가 이름으로 거른다).
    """
    try:
        gdi = ctypes.windll.gdi32
    except (AttributeError, OSError):
        return 0
    files = []
    for folder in FONT_DIRS:
        if folder.is_dir():
            files.extend(sorted(folder.rglob("*")))
    count = 0
    for path in files:
        if path.suffix.lower() not in (".ttf", ".otf") or path in _LOADED:
            continue
        try:
            added = gdi.AddFontResourceExW(str(path), FR_PRIVATE, None)
        except OSError:
            added = 0
        if added:
            _LOADED[path] = family_names(path)
            count += 1
    return count


def choices(root) -> list[tuple[str, str]]:
    """고를 수 있는 글꼴들 [(보여 줄 이름, 글꼴 이름)]. 맨 앞은 윈도우 기본."""
    from tkinter import font as tkfont

    try:
        available = set(tkfont.families(root))
    except Exception:  # noqa: BLE001 — 창이 막 닫혔을 수 있다
        available = set()
    out = [(SYSTEM_LABEL, SYSTEM_DEFAULT)]
    seen = {SYSTEM_DEFAULT}
    done_folders: set[Path] = set()
    for path, names in sorted(_LOADED.items()):
        if path.parent in done_folders:
            continue  # 폴더마다 대표 파일 하나만
        family = next((name for name in names if name in available), None)
        if family is None or family in seen:
            continue
        done_folders.add(path.parent)
        seen.add(family)
        out.append((f"{family}  ({path.parent.name})", family))
    return out


def resolve(root, family: str) -> str | None:
    """저장해 둔 글꼴 이름을 지금 쓸 수 있는 이름으로. 못 찾으면 None, 비었으면 "".

    윈도우 표시 언어가 바뀌면 같은 글꼴이 "G마켓 산스" ↔ "Gmarket Sans"로 이름을
    바꿔 단다. 저장한 이름이 목록에 없어도, 그 이름을 가진 **딸린 글꼴 파일의 다른
    이름**이 목록에 있으면 그것을 쓴다.
    """
    if not family:
        return ""
    from tkinter import font as tkfont

    try:
        available = set(tkfont.families(root))
    except Exception:  # noqa: BLE001
        return None
    if family in available:
        return family
    for names in _LOADED.values():
        if family in names:
            other = next((name for name in names if name in available), None)
            if other:
                return other
    return None


def usable(root, family: str) -> bool:
    """그 글꼴을 지금 쓸 수 있나. 비었으면 윈도우 기본이라 늘 된다."""
    return resolve(root, family) is not None
