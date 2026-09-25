"""버프 아이템 사용.

두 가지 방식을 지원한다.

**퀵슬롯** — 5 6 7 8 9 0 - = 같은 자리에 올려 둔 아이템. 키 한 번이면 끝이라
간단하고 확실하다. 쓸 수 있으면 이쪽이 낫다.

**인벤토리** — 퀵슬롯이 모자라거나 슬롯에 올릴 수 없는 아이템. `I`로 인벤토리를
열고, 저장해 둔 아이콘 그림을 화면에서 찾아 클릭한 뒤 다시 닫는다. 아이템 자리가
고정이 아니라 좌표로는 잡을 수 없어서 그림으로 찾는다.

남은 시간을 아는 방법도 두 가지다.

**시간** — 쓴 시각 + 지속시간으로 계산한다. 지속시간이 고정이면 이게 가장 확실하고
버프 아이콘이 가려져 있어도 동작한다.

**화면** — 버프바에서 그 효과의 아이콘을 찾는다. 없으면 끝난 것이다. 지속시간이
들쭉날쭉하거나, 다른 데서 이미 걸어 둔 버프까지 함께 챙길 때 쓴다.

버프바는 앞엣것이 끝나면 뒤엣것이 앞으로 당겨지므로 아이콘 자리가 고정이 아니다.
그래서 좌표를 보지 않고 영역 안에서 그림을 찾는다 (icons 모듈).
"""

from __future__ import annotations

import time
from pathlib import Path

from . import icons as icons_mod
from . import imagematch, sender
from .arbiter import ARBITER
from .imagematch import Template
from .keys import vk_of
from .model import BuffItem
from .player import Aborted, RunContext
from .png import PngError, read_rgb

# 아이콘 그림을 두는 폴더 이름 (보관함 폴더 아래).
ICON_DIRNAME = "버프아이콘"


def icon_dir(library_root: Path) -> Path:
    return Path(library_root) / ICON_DIRNAME


def icon_path(library_root: Path, filename: str) -> Path:
    return icon_dir(library_root) / filename


class TemplateCache:
    """아이콘 PNG를 한 번만 읽어 두고 재사용한다.

    사이클마다 파일을 다시 읽으면 디스크를 계속 두드리게 된다. 파일이 바뀌면
    수정 시각으로 알아채고 다시 읽는다.
    """

    def __init__(self) -> None:
        self._cache: dict[Path, tuple[float, Template]] = {}

    def get(self, path: Path) -> Template | None:
        path = Path(path)
        try:
            stamp = path.stat().st_mtime
        except OSError:
            self._cache.pop(path, None)
            return None

        cached = self._cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]

        try:
            width, height, rgb = read_rgb(path)
        except (PngError, OSError):
            return None
        template = Template(width, height, rgb)
        self._cache[path] = (stamp, template)
        return template

    def clear(self) -> None:
        self._cache.clear()


TEMPLATES = TemplateCache()


# --------------------------------------------------------------------------
def use_buff(
    buff: BuffItem, ctx: RunContext, library_root: Path
) -> tuple[bool, str]:
    """버프를 한 번 쓴다. (성공 여부, 설명).

    성공하면 부른 쪽에서 last_used를 갱신해야 한다. 실패한 걸 썼다고 기록해 두면
    지속시간 내내 다시 시도하지 않게 되어 버프가 끊긴다.
    """
    if buff.use_kind == "quickslot":
        return _use_quickslot(buff, ctx)
    return _use_inventory(buff, ctx, library_root)


def _use_quickslot(buff: BuffItem, ctx: RunContext) -> tuple[bool, str]:
    vk = vk_of(buff.key)
    if vk is None:
        return (False, f"알 수 없는 키 '{buff.key}'")
    with ARBITER.dispatch():
        ctx.key_down(vk)
        ctx.sleep(0.04)
        ctx.key_up(vk)
    return (True, f"퀵슬롯 [{buff.key}]")


def _search_area(buff: BuffItem, ctx: RunContext) -> tuple[int, int, int, int] | None:
    """찾을 화면 영역 (절대좌표). 지정이 없으면 게임 창 전체."""
    if ctx.window is None:
        return None
    cw, ch = ctx.window.client_size()
    if buff.search_w > 0 and buff.search_h > 0:
        x, y = ctx.window.client_to_screen(buff.search_x, buff.search_y)
        return (x, y, buff.search_w, buff.search_h)
    origin_x, origin_y = ctx.window.client_to_screen(0, 0)
    return (origin_x, origin_y, cw, ch)


def _use_inventory(
    buff: BuffItem, ctx: RunContext, library_root: Path
) -> tuple[bool, str]:
    if not buff.icon:
        return (False, "아이콘 그림이 지정되지 않았습니다")

    template = TEMPLATES.get(icon_path(library_root, buff.icon))
    if template is None:
        return (False, f"아이콘 그림을 읽지 못했습니다 ({buff.icon})")

    area = _search_area(buff, ctx)
    if area is None:
        return (False, "게임 창을 찾지 못했습니다")

    open_vk = vk_of(buff.open_key)
    close_vk = vk_of(buff.close_key)
    if open_vk is None:
        return (False, f"인벤토리 여는 키가 잘못되었습니다 '{buff.open_key}'")

    opened = False
    try:
        with ARBITER.dispatch():
            ctx.key_down(open_vk)
            ctx.sleep(0.04)
            ctx.key_up(open_vk)
        opened = True
        ctx.sleep(max(buff.open_wait_ms, 0) / 1000.0)

        area_x, area_y, area_w, area_h = area
        match = imagematch.find(
            template, area_x, area_y, area_w, area_h, tolerance=buff.tolerance
        )
        if match is None:
            return (False, "인벤토리에서 아이콘을 찾지 못했습니다")

        # 아이콘 한가운데를 누른다. 모서리를 누르면 옆 칸이 눌릴 수 있다.
        cx = match.x + template.width // 2
        cy = match.y + template.height // 2
        with ARBITER.dispatch():
            sender.mouse_move(cx, cy)
            ctx.sleep(0.03)
            ctx.button_down(buff.click_button)
            ctx.sleep(0.04)
            ctx.button_up(buff.click_button)
        ctx.sleep(0.15)
        return (True, f"인벤토리 ({cx}, {cy}) 일치도 {match.score:.1f}")
    finally:
        # 인벤토리를 열어 놨으면 실패했더라도 반드시 닫는다. 열린 채로 두면
        # 뒤이어 돌 매크로가 전부 어긋난다.
        if opened and close_vk is not None:
            try:
                with ARBITER.dispatch():
                    ctx.key_down(close_vk)
                    ctx.sleep(0.04)
                    ctx.key_up(close_vk)
                ctx.sleep(0.15)
            except Aborted:
                raise
            except OSError:
                pass


# --------------------------------------------------------------------------
# 남았는가 / 끝났는가
# --------------------------------------------------------------------------
class WatchState:
    """화면 감지가 '없음'을 몇 번 연속으로 봤는지 세어 둔다.

    한 번 안 보였다고 바로 다시 쓰면, 다른 창이 잠깐 겹치거나 화면이 한 프레임
    깜빡였을 때 멀쩡한 버프를 덧씌우게 된다. 연속으로 안 보여야 진짜로 본다.
    """

    def __init__(self) -> None:
        self._misses: dict[str, int] = {}

    def saw(self, name: str) -> None:
        self._misses.pop(name, None)

    def missed(self, name: str) -> int:
        count = self._misses.get(name, 0) + 1
        self._misses[name] = count
        return count

    def clear(self) -> None:
        self._misses.clear()


def check_active(
    buff: BuffItem, ctx: RunContext, library_root: Path
) -> tuple[bool, str]:
    """버프가 지금 걸려 있는가. (걸려 있음, 설명).

    detect_kind가 icon일 때만 화면을 본다. timer면 시각 계산으로 답한다.
    """
    if buff.detect_kind != "icon":
        remaining = buff.remaining(time.time())
        return (remaining > 0, f"남은 시간 {remaining / 60:.1f}분")

    report = icons_mod.look(buff.watch, library_root, ctx.window)
    if report.error:
        return (True, f"확인 실패 — {report.error}")
    return (report.found, report.describe())


def _icon_expired(
    buff: BuffItem, ctx: RunContext, library_root: Path, state: WatchState | None
) -> tuple[bool, str]:
    """화면 감지로 '끝났다'를 판정한다. (끝남, 설명)."""
    report = icons_mod.look(buff.watch, library_root, ctx.window)
    if report.error:
        # 못 본 것과 없는 것은 다르다. 확인에 실패했으면 손대지 않는다 —
        # 창이 잠깐 가려졌다고 버프를 덧씌우면 아이템만 날아간다.
        return (False, f"확인 실패 — {report.error}")

    if report.found:
        if state is not None:
            state.saw(buff.name)
        return (False, f"아이콘 있음 (일치도 {report.score:.0f})")

    needed = max(1, buff.watch_confirm)
    misses = state.missed(buff.name) if state is not None else needed
    if misses < needed:
        return (False, f"아이콘 안 보임 {misses}/{needed}회 — 좀 더 지켜봅니다")
    return (True, f"아이콘 없음 {misses}회 연속")


# --------------------------------------------------------------------------
def refresh_expired(
    names: list[str],
    find_buff,
    ctx: RunContext,
    library_root: Path,
    margin_s: int = 30,
    now: float | None = None,
    state: WatchState | None = None,
) -> tuple[int, int]:
    """만료된 버프만 골라 다시 쓴다. (사용한 개수, 실패한 개수)."""
    now = time.time() if now is None else now
    used = failed = 0

    for name in names:
        ctx.check()
        buff = find_buff(name)
        if buff is None:
            ctx.log(f"  버프 '{name}'을(를) 찾지 못했습니다.")
            failed += 1
            continue

        if buff.detect_kind == "icon":
            expired, why = _icon_expired(buff, ctx, library_root, state)
            if not expired:
                ctx.log(f"  버프 '{buff.name}' {why} — 건너뜀")
                continue
            ctx.log(f"  버프 '{buff.name}' {why} → 다시 사용")
        else:
            remaining = buff.remaining(now)
            if not buff.expired(now, margin_s):
                ctx.log(f"  버프 '{buff.name}' 아직 {remaining / 60:.1f}분 남음 — 건너뜀")
                continue

        ok, detail = use_buff(buff, ctx, library_root)
        if ok:
            buff.last_used = time.time()
            used += 1
            if state is not None:
                # 방금 썼으니 세어 두었던 '안 보임' 횟수는 리셋한다. 아이콘이
                # 뜨기까지 한 박자 걸리는데 그동안 다시 쓰면 두 번 쓰게 된다.
                state.saw(buff.name)
            ctx.log(f"  버프 '{buff.name}' 사용 — {detail} ({buff.duration_min}분)")
        else:
            failed += 1
            ctx.log(f"  버프 '{buff.name}' 사용 실패 — {detail}")

    return (used, failed)
