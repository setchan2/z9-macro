"""창 꾸미기 — 배경 이미지와 창 아이콘.

외부 라이브러리(Pillow)를 안 쓰기로 한 프로그램이라, 이미지는 **Tk가 스스로 읽는
형식만** 받는다. Tk 8.6은 PNG · GIF를 읽고 **JPG는 못 읽는다.** 그래서 JPG를 고르면
조용히 깨지는 대신 "PNG로 저장해 주세요"라고 알려 준다.

## 배경은 창 가장자리에 보인다

tkinter의 판(목록 · 입력칸 · 탭)은 **반투명이 안 된다.** 판 뒤에 그림을 깔아 봐야
판에 가려 하나도 안 보인다. 그렇다고 판을 없애면 그림 위 글씨가 안 읽힌다.

그래서 그림을 창 맨 뒤에 깔고, 내용을 **테두리 여백만큼 안쪽으로** 들인다. 액자처럼
창 둘레로 그림이 보이고, 내용은 읽기 쉬운 불투명한 판 위에 남는다. 여백은 설정에서
0~120px로 고른다.

## 크기는 정수배로만 맞춘다

Pillow 없이 Tk가 할 수 있는 크기 조절은 **정수배 확대(zoom)와 정수분의 1 축소
(subsample)** 뿐이다. 그래서 창보다 2배 넘게 크면 1/2 · 1/3로 줄이고, 창의 절반보다
작으면 정수배로 키운다(흐려진다). 그 사이면 원래 크기 그대로 **가운데에 놓고 넘치는
부분은 잘린다.** 창보다 조금 큰 그림을 준비하는 것이 가장 깔끔하다.
"""

from __future__ import annotations

import math
import shutil
import tkinter as tk
from pathlib import Path

from .. import storage
from . import theme

# 고른 이미지를 복사해 둘 폴더 (data/ui). 원본을 옮기거나 지워도 계속 보이게 한다.
UI_DIR = "ui"

IMAGE_TYPES = [("PNG 이미지", "*.png"), ("GIF 이미지", "*.gif"),
               ("모든 파일", "*.*")]

# Tk가 못 읽는 흔한 형식. 열어 보기 전에 알아듣게 막는다.
UNREADABLE = (".jpg", ".jpeg", ".bmp", ".webp", ".ico", ".tif", ".tiff")

# 아이콘으로 넘길 크기들. 원본이 이 크기로 **딱 나뉘면** 줄인 것도 함께 넘긴다 —
# 제목 표시줄(16~24px)과 작업 표시줄(32~48px)이 각자 가까운 것을 골라 쓴다.
ICON_SIZES = (128, 64, 48, 32, 24, 16)

# 작은 그림을 키울 때 최대 배수. 넘으면 그만큼만 키우고 나머지는 바탕색으로 둔다.
MAX_ZOOM = 8

# 권장 크기 — 설정 화면 안내와 같은 값을 쓴다.
ICON_ADVICE = "정사각형 PNG · 256×256 권장 (투명 배경 가능)"
BACKGROUND_ADVICE = "PNG · 창보다 조금 크게 (1920×1200 권장)"


class ImageError(RuntimeError):
    """이미지를 쓸 수 없다. 사람이 읽을 말을 담는다."""


def load_photo(master: tk.Misc, path: str | Path) -> tk.PhotoImage:
    """이미지를 읽는다. 못 읽으면 ImageError."""
    src = Path(path)
    if not src.is_file():
        # exe를 다른 폴더로 옮기면 저장해 둔 절대 경로가 어긋난다. 복사해 둔 사본은
        # 늘 data/ui 에 같은 이름으로 있으므로 거기서 찾는다.
        moved = storage.DATA_DIR / UI_DIR / src.name
        if moved.is_file():
            src = moved
        else:
            raise ImageError(f"파일이 없습니다: {src}")
    if src.suffix.lower() in UNREADABLE:
        raise ImageError(
            f"{src.suffix} 파일은 읽을 수 없습니다 — PNG로 저장해서 골라 주세요. "
            "(그림판에서 열고 [다른 이름으로 저장] → PNG)")
    try:
        return tk.PhotoImage(master=master, file=str(src))
    except tk.TclError as exc:
        raise ImageError(
            f"이미지를 읽지 못했습니다 ({exc}) — PNG로 다시 저장해 보세요") from exc


def keep_copy(path: str | Path, name: str) -> Path:
    """고른 이미지를 data/ui/<name>.<확장자>로 복사하고 그 자리를 돌려준다."""
    src = Path(path)
    folder = storage.DATA_DIR / UI_DIR
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{name}{src.suffix.lower()}"
    # 확장자만 다른 옛 사본은 지운다. 남겨 두면 어느 것이 쓰이는지 헷갈린다.
    for old in folder.glob(f"{name}.*"):
        if old != dest:
            try:
                old.unlink()
            except OSError:
                pass
    if src.resolve() != dest.resolve():
        shutil.copyfile(src, dest)
    return dest


# --------------------------------------------------------------------------
# 창 아이콘
# --------------------------------------------------------------------------
def apply_icon(root: tk.Tk, path: str) -> str:
    """창 아이콘을 바꾼다. 무슨 일이 있었는지 한 줄로 (비었으면 "")."""
    if not path:
        return ""
    try:
        image = load_photo(root, path)
    except ImageError as exc:
        return f"창 아이콘: {exc}"
    width, height = image.width(), image.height()
    images = [image]
    for size in ICON_SIZES:
        if size < width and width % size == 0 and height % size == 0:
            images.append(image.subsample(width // size, height // size))
    try:
        # True = 앞으로 뜨는 모든 창(상태 창 · 설정 창)에도 같은 아이콘.
        root.iconphoto(True, *images)
    except tk.TclError as exc:
        return f"창 아이콘: 적용하지 못했습니다 ({exc})"
    # PhotoImage는 파이썬 쪽에서 붙들고 있지 않으면 사라진다.
    root._z9_icon_images = images  # type: ignore[attr-defined]
    note = "" if width == height else " — 정사각형이 아니라 찌그러져 보일 수 있습니다"
    return f"창 아이콘 적용 ({width}×{height}){note}"


# --------------------------------------------------------------------------
# 배경 이미지
# --------------------------------------------------------------------------
def fit(source: tk.PhotoImage, width: int, height: int) -> tk.PhotoImage:
    """창 크기에 맞춘 그림. 정수배로만 줄이고 키운다 (위 설명 참고)."""
    iw, ih = max(1, source.width()), max(1, source.height())
    shrink = min(iw // max(1, width), ih // max(1, height))
    if shrink >= 2:
        return source.subsample(shrink)
    if iw * 2 <= width or ih * 2 <= height:
        grow = max(math.ceil(width / iw), math.ceil(height / ih))
        # 1×200 같은 가느다란 그림은 수천 배가 되어 메모리를 통째로 먹는다.
        grow = min(grow, MAX_ZOOM)
        if grow >= 2:
            return source.zoom(grow)
    return source


class Backdrop:
    """창 맨 뒤에 깔리는 배경 그림.

    캔버스 하나를 창 전체에 **place**로 깔고 맨 아래로 내린다. 내용(pack)은 그 위에
    그대로 쌓이므로 기존 배치를 하나도 안 건드린다. 여백만 on_margin으로 부탁한다.
    """

    def __init__(self, root: tk.Tk, on_margin) -> None:
        self.root = root
        self.on_margin = on_margin
        self.path = ""
        self.source: tk.PhotoImage | None = None
        self.shown: tk.PhotoImage | None = None
        self._drawn = (0, 0)
        self._job = None
        self.canvas = tk.Canvas(root, highlightthickness=0, borderwidth=0,
                                background=theme.PALETTE["bg"])
        self.canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self._sink()
        root.bind("<Configure>", self._on_configure, add="+")

    def _sink(self) -> None:
        # tk.Canvas는 lower를 "그림 항목 내리기"로 덮어써 두었다. 위젯 자체를 내리려면
        # Misc의 것을 불러야 한다.
        tk.Misc.lower(self.canvas)

    @property
    def active(self) -> bool:
        return self.source is not None

    def show(self, path: str, margin: int) -> str:
        """그림을 바꾼다. 비우면 없앤다. 무슨 일이 있었는지 한 줄로."""
        self.path = path or ""
        self.canvas.delete("all")
        self.shown = None
        self._drawn = (0, 0)
        if not path:
            self.source = None
            self.on_margin(None)
            return ""
        try:
            self.source = load_photo(self.root, path)
        except ImageError as exc:
            self.source = None
            self.on_margin(None)
            return f"배경 이미지: {exc}"
        self.on_margin(max(0, int(margin)))
        self.root.update_idletasks()
        self._redraw()
        return (f"배경 이미지 적용 ({self.source.width()}×{self.source.height()}) · "
                f"테두리 {int(margin)}px")

    def set_margin(self, margin: int) -> None:
        if self.active:
            self.on_margin(max(0, int(margin)))

    def refresh_color(self) -> None:
        """테마를 바꿨다. 그림이 안 덮는 곳의 바탕색을 맞춘다."""
        self.canvas.configure(background=theme.PALETTE["bg"])

    def _on_configure(self, event) -> None:
        if event.widget is not self.root or self.source is None:
            return
        if self._job is not None:
            self.root.after_cancel(self._job)
        # 창을 끄는 동안 수십 번 불린다. 멈춘 뒤 한 번만 다시 그린다.
        self._job = self.root.after(120, self._redraw)

    def _redraw(self) -> None:
        self._job = None
        if self.source is None:
            return
        width = max(1, self.root.winfo_width())
        height = max(1, self.root.winfo_height())
        if (width, height) == self._drawn:
            return
        self._drawn = (width, height)
        self.shown = fit(self.source, width, height)
        self.canvas.delete("all")
        self.canvas.create_image(width // 2, height // 2, image=self.shown,
                                 anchor="center")
        self._sink()
