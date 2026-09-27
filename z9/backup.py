"""전체 백업 — **지금 이 컴퓨터의 설정을 통째로** 파일 하나에 담는다.

## 무엇을 담는가

    profile.json   설정 전부 — 매크로 · 시나리오 · 조건 · 이동 · 예약 ·
                   낚시 · 벌목 · 제작(버프 주기 · 채널 자리 · 치트엔진 자리)
    library/       보관함 — 감지 아이콘 그림 · 숫자 글꼴 · 보관해 둔 매크로
    data/ui/       꾸미기 이미지 (있으면)

**설정 파일 하나만 옮기면 안 된다.** 조건은 감지 아이콘 그림을 파일 이름으로
가리키고, 피로도는 익힌 숫자 글꼴을 쓴다. 그림과 글꼴이 없으면 조건이 조용히
안 서고, 그러면 "왜 저쪽 컴퓨터에서는 안 되지"가 된다. 그래서 함께 담는다.

## 되돌릴 때

먼저 **지금 것을 자동으로 한 벌 백업해 둔 다음** 덮어쓴다. 복원은 되돌릴 수
없는 일이라, 잘못 눌렀을 때 돌아올 자리가 있어야 한다.

## 왜 zip 인가

파이썬이 기본으로 다룰 수 있고, 다른 컴퓨터에서 압축을 풀어 눈으로 확인할
수도 있다. 확장자만 .z9backup 으로 두어 실수로 지우지 않게 한다.
"""

from __future__ import annotations

import json
import shutil
import socket
import zipfile
from datetime import datetime
from pathlib import Path

SUFFIX = ".z9backup"
FOLDER = "백업"
META = "meta.json"
# 한 폴더에 이만큼까지만 둔다. 넘으면 오래된 것부터 지운다.
KEEP = 40


def folder_of(data_dir: Path) -> Path:
    """백업을 모아 두는 폴더 (data/백업)."""
    return Path(data_dir) / FOLDER


def stamp(when: datetime | None = None) -> str:
    return (when or datetime.now()).strftime("%Y%m%d-%H%M%S")


def _add_tree(zf: zipfile.ZipFile, root: Path, prefix: str) -> int:
    """폴더 하나를 통째로 담는다. 담은 파일 수."""
    if not root.is_dir():
        return 0
    count = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            zf.write(path, f"{prefix}/{path.relative_to(root).as_posix()}")
            count += 1
    return count


def counts_of(profile_path: Path) -> dict:
    """설정 파일에 무엇이 몇 개 들었는지 (백업 목록에 보여 줄 것)."""
    try:
        data = json.loads(Path(profile_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    craft = data.get("craft") or {}
    return {
        "매크로": len(data.get("macros") or []),
        "시나리오": len(data.get("scenarios") or []),
        "조건": len(data.get("rules") or []),
        "이동": len(data.get("moves") or []),
        "예약": len(data.get("schedules") or []),
        "채널자리": sum(1 for s in (craft.get("channel_spots") or [])
                        if (s or {}).get("x", -1) >= 0),
        "버프": sum(1 for b in (craft.get("buffs") or []) if (b or {}).get("on")),
    }


def make(profile_path: Path, library_root: Path, data_dir: Path,
         note: str = "", where: Path | None = None) -> Path:
    """지금 설정을 백업 파일 하나로 만든다. 만든 파일 경로."""
    profile_path = Path(profile_path)
    data_dir = Path(data_dir)
    target_dir = Path(where) if where else folder_of(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    # **이미 있는 이름은 절대 쓰지 않는다.** 시각은 초 단위라 같은 초에 두 번
    # 만들면 이름이 겹치는데, 그러면 먼저 있던 백업을 덮어쓴다. 복원할 때
    # 직전 자동 백업이 **지금 읽고 있는 그 파일**을 덮어써 깨진 적이 있다.
    path = target_dir / f"백업-{stamp()}{SUFFIX}"
    serial = 1
    while path.exists():
        serial += 1
        path = target_dir / f"백업-{stamp()}-{serial}{SUFFIX}"

    meta = {
        "made_at": datetime.now().isoformat(timespec="seconds"),
        "computer": socket.gethostname(),
        "note": note,
        "library_from": str(library_root),
        "counts": counts_of(profile_path),
        "version": 1,
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        if profile_path.is_file():
            zf.write(profile_path, "profile.json")
        meta["library_files"] = _add_tree(zf, Path(library_root), "library")
        meta["ui_files"] = _add_tree(zf, data_dir / "ui", "ui")
        zf.writestr(META, json.dumps(meta, ensure_ascii=False, indent=2))
    prune(target_dir)
    return path


def prune(folder: Path, keep: int = KEEP) -> list[Path]:
    """오래된 백업부터 지운다. 지운 것들."""
    rows = sorted(Path(folder).glob(f"*{SUFFIX}"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    gone = []
    for path in rows[keep:]:
        try:
            path.unlink()
            gone.append(path)
        except OSError:
            pass
    return gone


def describe(path: Path) -> dict:
    """백업 하나의 속을 들여다본다 (목록에 보여 줄 것)."""
    path = Path(path)
    out = {"path": path, "name": path.name, "size": 0, "made_at": "",
           "computer": "", "counts": {}, "library_files": 0, "ok": False}
    try:
        out["size"] = path.stat().st_size
    except OSError:
        return out
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            out["ok"] = "profile.json" in names
            if META in names:
                meta = json.loads(zf.read(META).decode("utf-8"))
                out.update({k: meta.get(k, out[k])
                            for k in ("made_at", "computer", "counts",
                                      "library_files")})
            if not out["made_at"]:
                out["made_at"] = datetime.fromtimestamp(
                    path.stat().st_mtime).isoformat(timespec="seconds")
    except (OSError, zipfile.BadZipFile, ValueError):
        return out
    return out


def restore(path: Path, profile_path: Path, library_root: Path,
            data_dir: Path) -> dict:
    """백업을 되돌린다. 무엇을 했는지 돌려준다.

    **먼저 지금 것을 한 벌 백업한다.** 그래야 잘못 눌러도 돌아올 수 있다.
    보관함과 꾸미기 이미지는 **덮어쓰되 남의 파일은 안 지운다** — 백업에 없던
    파일까지 치우면 저쪽 컴퓨터의 다른 것들이 날아간다.
    """
    path = Path(path)
    profile_path = Path(profile_path)
    library_root = Path(library_root)
    data_dir = Path(data_dir)
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if "profile.json" not in names:
            raise ValueError("설정 파일이 없는 백업입니다.")
        safety = make(profile_path, library_root, data_dir,
                      note=f"복원 직전 자동 백업 ({path.name})")

        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_bytes(zf.read("profile.json"))

        wrote_lib = wrote_ui = 0
        for name in names:
            if name.startswith("library/") and not name.endswith("/"):
                out = library_root / name[len("library/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(zf.read(name))
                wrote_lib += 1
            elif name.startswith("ui/") and not name.endswith("/"):
                out = data_dir / "ui" / name[len("ui/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(zf.read(name))
                wrote_ui += 1
    return {"safety": safety, "library_files": wrote_lib, "ui_files": wrote_ui,
            "from": path}


def bring_in(source: Path, data_dir: Path) -> Path:
    """다른 컴퓨터에서 가져온 백업 파일을 백업 폴더로 들여놓는다."""
    source = Path(source)
    target_dir = folder_of(Path(data_dir))
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if target.exists() or source.suffix.lower() != SUFFIX:
        target = target_dir / f"가져옴-{stamp()}{SUFFIX}"
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
    return target


def listing(data_dir: Path) -> list[dict]:
    """백업 목록. 최근 것부터."""
    folder = folder_of(Path(data_dir))
    if not folder.is_dir():
        return []
    rows = [describe(p) for p in folder.glob(f"*{SUFFIX}")]
    rows.sort(key=lambda row: row["made_at"], reverse=True)
    return rows


__all__ = ["make", "restore", "listing", "describe", "bring_in", "folder_of",
           "counts_of", "prune", "SUFFIX"]
