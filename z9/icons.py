"""화면 감지용 아이콘 그림 보관과 판정.

버프 아이콘처럼 **자리가 밀리는** 표시는 좌표로 잡을 수 없다. 버프 하나가 끝나면
뒤에 있던 것들이 앞으로 당겨지므로, 어제 3번 자리였던 아이콘이 오늘은 1번 자리에
있다. 그래서 "이 자리 색이 무엇인가"가 아니라 "이 그림이 이 영역 안 어딘가에
있는가"를 물어야 한다.

여기에 한 가지가 더 겹친다. 아이콘 위에 **남은 시간 숫자가 겹쳐 그려진다.**
그 칸은 1분마다 다른 그림이 되므로 비교에 넣으면 절대 맞지 않는다. 그래서 숫자가
덮는 사각형을 마스크로 빼 두고 나머지 그림만으로 판정한다.

  마스크 없이 비교      → 못 찾음
  숫자 칸 마스크        → 찾음
  마스크 + 밝기 보정    → 반투명하게 어두워져도 찾음

(위 셋은 실제로 재 본 결과다. 마스크가 없으면 아무리 허용 오차를 키워도 오탐만
늘고 인식률은 오르지 않는다.)
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from . import imagematch, pixel
from .imagematch import Match, Template
from .png import PngError, read_rgb, write_rgb

# 그림을 두는 폴더 이름 (보관함 폴더 아래).
ICON_DIRNAME = "감지아이콘"

# 파일 이름에 쓸 수 없는 글자.
_BAD_CHARS = re.compile(r'[\\/:*?"<>|]')


def icon_dir(library_root: Path) -> Path:
    return Path(library_root) / ICON_DIRNAME


def icon_path(library_root: Path, filename: str) -> Path:
    return icon_dir(library_root) / filename


def list_icons(library_root: Path) -> list[str]:
    folder = icon_dir(library_root)
    try:
        return sorted(p.name for p in folder.glob("*.png"))
    except OSError:
        return []


def safe_filename(name: str) -> str:
    """사람이 붙인 이름을 파일 이름으로 쓸 수 있게 다듬는다."""
    cleaned = _BAD_CHARS.sub("_", name).strip().strip(".")
    return (cleaned or "아이콘") + ".png"


def save_template(library_root: Path, filename: str, template: Template) -> Path:
    """잘라낸 그림을 PNG로 저장한다. 마스크는 그림에 담지 않는다.

    마스크는 "어디를 볼지"라는 판정 설정이지 그림 자체가 아니다. 그림에 섞어
    두면 같은 아이콘을 다른 조건에서 다르게 마스크해 쓸 수 없다.
    """
    folder = icon_dir(library_root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    write_rgb(path, template.width, template.height, template.data)
    return path


class TemplateCache:
    """PNG를 한 번만 읽어 두고 재사용한다.

    감시는 초마다 도는데 그때마다 파일을 다시 읽으면 디스크를 계속 두드리게 된다.
    파일이 바뀌면 수정 시각으로 알아채고 다시 읽는다.

    마스크를 씌운 결과도 함께 캐시한다. 마스크를 씌우는 일 자체는 픽셀 수만큼
    도는 작업이라, 판정할 때마다 새로 만들면 그게 비교보다 비싸질 수 있다.
    """

    def __init__(self) -> None:
        self._raw: dict[Path, tuple[float, Template]] = {}
        self._masked: dict[tuple, Template] = {}

    def raw(self, path: Path) -> Template | None:
        path = Path(path)
        try:
            stamp = path.stat().st_mtime
        except OSError:
            self._raw.pop(path, None)
            return None

        cached = self._raw.get(path)
        if cached and cached[0] == stamp:
            return cached[1]

        try:
            width, height, rgb = read_rgb(path)
        except (PngError, OSError):
            return None
        template = Template(width, height, rgb)
        self._raw[path] = (stamp, template)
        # 그림이 바뀌었으면 그 그림으로 만든 마스크본도 모두 버린다.
        self._masked = {k: v for k, v in self._masked.items() if k[0] != path}
        return template

    def masked(self, path: Path, rects: tuple) -> Template | None:
        path = Path(path)
        key = (path, rects)
        cached = self._masked.get(key)
        if cached is not None:
            return cached
        base = self.raw(path)
        if base is None:
            return None
        template = base.with_masked_rects(rects) if rects else base
        self._masked[key] = template
        return template

    def clear(self) -> None:
        self._raw.clear()
        self._masked.clear()


TEMPLATES = TemplateCache()


# --------------------------------------------------------------------------
# 판정
# --------------------------------------------------------------------------
class Report:
    """한 번 본 결과. 로그와 튜닝 화면이 같은 것을 쓴다."""

    __slots__ = ("found", "score", "matches", "error", "elapsed_ms")

    def __init__(
        self,
        found: bool,
        score: float | None,
        matches: list[Match],
        error: str = "",
        elapsed_ms: float = 0.0,
    ) -> None:
        self.found = found
        self.score = score  # 가장 잘 맞은 점수 (작을수록 같음). None = 못 잼
        self.matches = matches
        self.error = error
        self.elapsed_ms = elapsed_ms

    def describe(self) -> str:
        if self.error:
            return self.error
        if not self.matches:
            return f"없음 (일치도 {self.score:.0f} 초과, {self.elapsed_ms:.0f}ms)"
        spots = " ".join(f"({m.x},{m.y}) {m.score:.0f}" for m in self.matches)
        return f"{len(self.matches)}개 발견 {spots} ({self.elapsed_ms:.0f}ms)"


def rects_of(masks) -> tuple:
    """마스크 목록을 캐시 키로 쓸 수 있는 튜플로."""
    return tuple((m.x, m.y, m.w, m.h) for m in masks if m.w > 0 and m.h > 0)


def template_for(watch, library_root):
    """감시 설정이 실제로 쓰는 (마스크 씌운) 그림. 없으면 None."""
    return TEMPLATES.masked(
        icon_path(library_root, watch.icon), rects_of(watch.masks)
    )


_rects = rects_of  # 예전 이름


def look(
    watch,
    library_root: Path,
    window,
    max_hits: int = 1,
    measure_tolerance: int | None = None,
) -> Report:
    """감시 설정 하나를 지금 화면에서 확인한다.

    watch는 model.IconWatch. measure_tolerance를 주면 그 허용치로 찾는다 —
    튜닝 화면에서 "지금 점수가 몇인지"를 재려고 일부러 넉넉히 잡을 때 쓴다.
    """
    if not watch.icon:
        return Report(False, None, [], "그림이 지정되지 않았습니다")
    if window is None:
        return Report(False, None, [], "게임 창을 찾지 못했습니다")

    template = TEMPLATES.masked(icon_path(library_root, watch.icon), _rects(watch.masks))
    if template is None:
        return Report(False, None, [], f"그림을 읽지 못했습니다 ({watch.icon})")
    if template.used_count == 0:
        return Report(False, None, [], "마스크가 그림을 전부 가렸습니다")

    area = watch.area(window)
    if area is None:
        return Report(False, None, [], "찾을 영역이 잘못되었습니다")
    ax, ay, aw, ah = area
    if template.width > aw or template.height > ah:
        return Report(
            False, None, [],
            f"찾을 영역({aw}x{ah})이 그림({template.width}x{template.height})보다 작습니다",
        )

    tolerance = watch.tolerance if measure_tolerance is None else measure_tolerance
    started = time.perf_counter()
    try:
        frame = pixel.capture_region(ax, ay, aw, ah)
    except pixel.CaptureError as exc:
        return Report(False, None, [], str(exc))
    matches = imagematch.find_all_in_frame(
        template, frame, tolerance=tolerance, level=watch.level, limit=max(1, max_hits)
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    score = matches[0].score if matches else float(tolerance)
    return Report(bool(matches), score, matches, elapsed_ms=elapsed)


def present(watch, library_root: Path, window) -> tuple[bool, Report]:
    """그림이 화면에 있는지. (있음, 자세한 결과)."""
    report = look(watch, library_root, window)
    return (report.found, report)
