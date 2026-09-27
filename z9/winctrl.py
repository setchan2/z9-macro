"""남의 창 **속**을 들여다보고 누른다 — 단추·입력칸·목록.

좌표로만 누르면 창이 조금만 달라져도 엉뚱한 데가 눌린다. 특히 **목록**이
그렇다. 치트엔진의 프로세스 목록은 지금 떠 있는 프로그램만큼 줄이 생기므로,
게임 줄이 몇 번째인지가 매번 다르다. 고정 좌표로는 절대 맞출 수 없다.

윈도의 평범한 컨트롤(Button · Edit · ListBox · SysListView32)은 **글씨를 물어볼
수 있다.** 그래서 여기서는

    · 단추는 적힌 글씨로 찾고 (Enable Speedhack · Apply)
    · 목록은 줄마다 글씨를 읽어 원하는 줄을 찾은 뒤, 그 줄의 자리를 눌러

좌표를 안 쓴다. 치트엔진도 Lazarus 로 만든 프로그램이라 속은 평범한 윈도
컨트롤이어서 이것이 통한다 (확인함: Button 'Enable Speedhack' · Button 'Apply' ·
Edit '1.0').

## 남의 프로세스에서 글씨를 읽는 법

목록에 "몇 번째 줄 글씨를 달라"고 물으면, 그 글씨를 **부르는 쪽이 준 주소**에
적어 준다. 그런데 그 주소는 목록을 가진 프로그램 안에서만 뜻이 있다. 그래서
상대 프로그램 안에 자리를 하나 빌리고(VirtualAllocEx), 거기에 적게 한 뒤,
그 자리를 읽어 온다(ReadProcessMemory).

상대가 관리자 권한이면 이쪽도 관리자 권한이어야 한다. 이 프로그램은 관리자
권한으로 돌므로 괜찮다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 창 · 컨트롤
SMTO_ABORTIFHUNG = 0x0002
SEND_TIMEOUT_MS = 1500

# 목록(ListBox)
LB_GETCOUNT = 0x018B
LB_GETTEXT = 0x0189
LB_GETTEXTLEN = 0x018A
LB_GETITEMRECT = 0x0198
LB_SETTOPINDEX = 0x0197
LB_GETTOPINDEX = 0x018E
LB_GETITEMHEIGHT = 0x01A1

# 목록(SysListView32)
LVM_GETITEMCOUNT = 0x1004
LVM_GETITEMTEXTW = 0x1073
LVM_ENSUREVISIBLE = 0x1013
LVM_GETITEMRECT = 0x100E
LVIR_BOUNDS = 0

# 상대 프로세스 열기
PROCESS_VM_OPERATION = 0x0008
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT = 0x1000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04


@dataclass
class Ctrl:
    """창 속의 컨트롤 하나."""

    hwnd: int
    cls: str
    text: str
    left: int
    top: int
    width: int
    height: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def describe(self) -> str:
        return (f"{self.cls} {self.text!r} ({self.left},{self.top}) "
                f"{self.width}x{self.height}")


class LVITEMW(ctypes.Structure):
    _fields_ = [("mask", wintypes.UINT), ("iItem", ctypes.c_int),
                ("iSubItem", ctypes.c_int), ("state", wintypes.UINT),
                ("stateMask", wintypes.UINT), ("pszText", ctypes.c_void_p),
                ("cchTextMax", ctypes.c_int), ("iImage", ctypes.c_int),
                ("lParam", ctypes.c_void_p), ("iIndent", ctypes.c_int),
                ("iGroupId", ctypes.c_int), ("cColumns", wintypes.UINT),
                ("puColumns", ctypes.c_void_p), ("piColFmt", ctypes.c_void_p),
                ("iGroup", ctypes.c_int)]


def _text_of(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 2)
    user32.GetWindowTextW(hwnd, buf, length + 2)
    return buf.value


def _class_of(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _rect_of(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (rect.left, rect.top, rect.right - rect.left,
            rect.bottom - rect.top)


def size_of(hwnd: int) -> tuple[int, int, int, int]:
    """그 창의 (왼쪽, 위, 너비, 높이). 크기 0짜리 껍데기 창을 가릴 때 쓴다."""
    return _rect_of(hwnd)


def exe_of(hwnd: int) -> str:
    """그 창을 띄운 프로그램의 파일 이름(소문자). 못 알아내면 빈 글자.

    창 종류(class)로는 브라우저를 가릴 수 없다 — VS Code 같은 프로그램도 속이
    크로뮴이라 같은 종류로 잡힌다. 실제로 그 바람에 **편집기에 적힌 글씨를
    홈페이지 단추로 알고 눌렀다.** 프로그램 이름으로 가리면 그럴 일이 없다.
    """
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                  pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(520)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf,
                                                   ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(handle)


def send(hwnd: int, msg: int, wparam=0, lparam=0) -> int:
    """답을 기다리되 **영원히 기다리지는 않는다.**

    멈춰 있는 창에 그냥 물어보면 이쪽까지 같이 멈춘다. 매크로가 통째로 굳는
    것보다는 "못 읽었다"가 낫다.
    """
    out = ctypes.c_size_t(0)
    ok = user32.SendMessageTimeoutW(
        wintypes.HWND(hwnd), wintypes.UINT(msg), wintypes.WPARAM(wparam),
        ctypes.c_void_p(lparam), wintypes.UINT(SMTO_ABORTIFHUNG),
        wintypes.UINT(SEND_TIMEOUT_MS), ctypes.byref(out))
    return int(out.value) if ok else -1


def windows(title_part: str) -> list[tuple[int, str]]:
    """제목에 그 글자가 들어가는 **보이고 크기가 있는** 창들. 큰 것부터.

    크기 0짜리를 거르는 것이 중요하다. 치트엔진은 제목이 그냥 'Cheat Engine'인
    **보이지 않는 껍데기 창**을 하나 더 들고 있어서, 제목만 보고 고르면 그쪽을
    잡는다. 거기에 대고 누르면 아무 일도 일어나지 않는다.
    """
    needle = title_part.strip().lower()
    found: list[tuple[int, str, int]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = _text_of(hwnd)
        if not title or (needle and needle not in title.lower()):
            return True
        _x, _y, width, height = _rect_of(hwnd)
        if width <= 1 or height <= 1:
            return True
        found.append((hwnd, title, width * height))
        return True

    user32.EnumWindows(each, 0)
    found.sort(key=lambda row: -row[2])
    return [(hwnd, title) for hwnd, title, _area in found]


def best_window(title_part: str) -> int:
    """그 제목을 가진 창 중 가장 큰 것. 없으면 0."""
    got = windows(title_part)
    return got[0][0] if got else 0


def children(hwnd: int) -> list[Ctrl]:
    """그 창 속의 컨트롤 전부 (보이는 것만)."""
    out: list[Ctrl] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(kid, _lparam):
        if user32.IsWindowVisible(kid):
            left, top, width, height = _rect_of(kid)
            out.append(Ctrl(kid, _class_of(kid), _text_of(kid), left, top,
                            width, height))
        return True

    user32.EnumChildWindows(hwnd, each, 0)
    return out


def find_ctrl(hwnd: int, cls: str = "", text: str = "",
              exact: bool = True) -> Ctrl | None:
    """글씨(와 종류)로 컨트롤 하나를 찾는다."""
    needle = text.strip().lower()
    for ctrl in children(hwnd):
        if cls and cls.lower() not in ctrl.cls.lower():
            continue
        if needle:
            got = ctrl.text.strip().lower()
            if (got != needle) if exact else (needle not in got):
                continue
        return ctrl
    return None


def list_ctrl(hwnd: int) -> tuple[Ctrl | None, str]:
    """그 창에서 **줄 목록**을 가진 컨트롤과 그 종류("lb"|"lv")."""
    for ctrl in children(hwnd):
        if send(ctrl.hwnd, LB_GETCOUNT) > 0:
            return (ctrl, "lb")
    for ctrl in children(hwnd):
        if "syslistview" in ctrl.cls.lower():
            if send(ctrl.hwnd, LVM_GETITEMCOUNT) > 0:
                return (ctrl, "lv")
    return (None, "")


class Remote:
    """상대 프로세스 안에 빌린 자리. with 로 쓴다."""

    def __init__(self, hwnd: int, size: int = 4096) -> None:
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self.size = size
        self.handle = kernel32.OpenProcess(
            PROCESS_VM_OPERATION | PROCESS_VM_READ | PROCESS_VM_WRITE
            | PROCESS_QUERY_INFORMATION, False, pid.value)
        self.addr = 0
        if self.handle:
            kernel32.VirtualAllocEx.restype = ctypes.c_void_p
            self.addr = kernel32.VirtualAllocEx(
                self.handle, None, ctypes.c_size_t(size), MEM_COMMIT,
                PAGE_READWRITE) or 0

    @property
    def ok(self) -> bool:
        return bool(self.handle and self.addr)

    def read(self, size: int) -> bytes:
        buf = ctypes.create_string_buffer(size)
        done = ctypes.c_size_t(0)
        kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(self.addr),
                                   buf, ctypes.c_size_t(size),
                                   ctypes.byref(done))
        return buf.raw[:done.value]

    def write(self, data: bytes) -> bool:
        done = ctypes.c_size_t(0)
        return bool(kernel32.WriteProcessMemory(
            self.handle, ctypes.c_void_p(self.addr), data,
            ctypes.c_size_t(len(data)), ctypes.byref(done)))

    def close(self) -> None:
        if self.handle:
            if self.addr:
                kernel32.VirtualFreeEx(self.handle, ctypes.c_void_p(self.addr),
                                       0, MEM_RELEASE)
            kernel32.CloseHandle(self.handle)
        self.handle = self.addr = 0

    def __enter__(self) -> "Remote":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def items(ctrl: Ctrl, kind: str, limit: int = 4000) -> list[str]:
    """목록의 줄 글씨 전부. 못 읽으면 빈 목록.

    **LISTBOX 는 남의 메모리를 빌리면 안 된다.** 윈도가 평범한 컨트롤의 글씨
    요청(LB_GETTEXT 따위)은 프로세스 사이를 알아서 옮겨 주기 때문이다. 빌린
    자리를 주면 도리어 **빈 값**만 온다 — 여기서 한 번 데었다. SysListView32 는
    comctl32 라 옮겨 주지 않으므로 그때만 빌린다.
    """
    count = send(ctrl.hwnd, LB_GETCOUNT if kind == "lb" else LVM_GETITEMCOUNT)
    if count <= 0:
        return []
    count = min(count, limit)
    out: list[str] = []
    if kind == "lb":
        for index in range(count):
            length = send(ctrl.hwnd, LB_GETTEXTLEN, index)
            if length <= 0:
                out.append("")
                continue
            buf = ctypes.create_unicode_buffer(length + 2)
            user32.SendMessageW(wintypes.HWND(ctrl.hwnd), LB_GETTEXT,
                                wintypes.WPARAM(index), ctypes.byref(buf))
            out.append(buf.value)
        return out
    with Remote(ctrl.hwnd) as remote:
        if not remote.ok:
            return []
        for index in range(count):
            item = LVITEMW()
            item.iItem = index
            item.iSubItem = 0
            # 글씨는 빌린 자리의 뒤쪽 절반에 적게 한다.
            item.pszText = ctypes.c_void_p(remote.addr + 512)
            item.cchTextMax = 512
            remote.write(bytes(item))
            send(ctrl.hwnd, LVM_GETITEMTEXTW, index, remote.addr)
            raw = remote.read(remote.size)[512:]
            out.append(raw.decode("utf-16-le", "ignore").split("\x00", 1)[0])
    return out


def row_name(line: str) -> str:
    """목록 한 줄에서 **프로그램 이름만** 뽑는다.

    치트엔진은 "00003DB8-Z9★ 온라인" 처럼 앞에 프로세스 번호를 붙인다. 번호는
    켤 때마다 달라지므로 떼어 내고 견준다.
    """
    text = line.strip()
    head, sep, tail = text.partition("-")
    if sep and head and all(c in "0123456789abcdefABCDEF" for c in head):
        return tail.strip()
    return text


def find_row(lines: list[str], name: str) -> int:
    """그 이름과 **똑같은** 줄의 번호. 없으면 -1.

    똑같은 것만 고르는 것이 중요하다. 'Z9★ 온라인'으로 찾는데 앞부분만 맞으면
    되게 해 두면 **이 매크로 프로그램 창('Z9★ 온라인 매크로')**이 먼저 걸린다.
    그걸 고르면 치트엔진이 엉뚱한 프로그램에 붙는다.
    """
    want = name.strip().lower()
    if not want:
        return -1
    for index, line in enumerate(lines):
        if row_name(line).lower() == want:
            return index
    return -1


def row_point(ctrl: Ctrl, kind: str, index: int) -> tuple[int, int] | None:
    """그 줄을 화면에 보이게 하고, 누를 자리(화면 좌표)를 돌려준다.

    LISTBOX 는 **줄 높이로 셈한다.** 자리를 묻는 요청(LB_GETITEMRECT)은 프로세스
    사이를 안 옮겨 주기 때문이다. 그 줄이 맨 위에 오도록 밀어 올린 뒤, 실제로
    몇 번째에 놓였는지 다시 물어 셈한다 — 끝자락 줄은 더 못 밀려 올라가므로
    밀어 올린 값을 그대로 믿으면 엉뚱한 줄을 누른다.
    """
    if kind == "lb":
        send(ctrl.hwnd, LB_SETTOPINDEX, index)
        top = send(ctrl.hwnd, LB_GETTOPINDEX)
        height = send(ctrl.hwnd, LB_GETITEMHEIGHT, 0)
        if top < 0 or height <= 0:
            return None
        point = wintypes.POINT(min(60, max(10, ctrl.width // 3)),
                               (index - top) * height + height // 2)
        if not (0 <= point.y <= ctrl.height):
            return None
        user32.ClientToScreen(wintypes.HWND(ctrl.hwnd), ctypes.byref(point))
        return (point.x, point.y)
    send(ctrl.hwnd, LVM_ENSUREVISIBLE, index, 0)
    with Remote(ctrl.hwnd, 64) as remote:
        if not remote.ok:
            return None
        remote.write(bytes(wintypes.RECT(LVIR_BOUNDS, 0, 0, 0)))
        send(ctrl.hwnd, LVM_GETITEMRECT, index, remote.addr)
        raw = remote.read(ctypes.sizeof(wintypes.RECT))
    if len(raw) < ctypes.sizeof(wintypes.RECT):
        return None
    rect = wintypes.RECT.from_buffer_copy(raw)
    point = wintypes.POINT((rect.left + rect.right) // 2,
                           (rect.top + rect.bottom) // 2)
    if point.x <= 0 and point.y <= 0:
        return None
    user32.ClientToScreen(wintypes.HWND(ctrl.hwnd), ctypes.byref(point))
    return (point.x, point.y)


def find_row_point(window_hwnd: int, name: str) -> tuple[tuple[int, int] | None, str]:
    """그 창의 목록에서 이름이 같은 줄을 찾아 **누를 자리**를 돌려준다.

    (자리, 설명)을 돌려준다. 못 찾으면 자리가 None이고 설명에 까닭이 적힌다.
    """
    ctrl, kind = list_ctrl(window_hwnd)
    if ctrl is None:
        return (None, "목록을 못 찾았습니다")
    lines = items(ctrl, kind)
    if not lines:
        return (None, "목록의 글씨를 못 읽었습니다")
    index = find_row(lines, name)
    if index < 0:
        near = [row_name(x) for x in lines if name.strip()[:4].lower()
                in row_name(x).lower()][:4]
        return (None, f"'{name}' 줄이 목록에 없습니다 (줄 {len(lines)}개"
                      + (f" · 비슷한 것: {', '.join(near)}" if near else "") + ")")
    point = row_point(ctrl, kind, index)
    if point is None:
        return (None, f"'{name}' 줄({index + 1}번째)의 자리를 못 쟀습니다")
    return (point, f"'{name}' 줄({len(lines)}개 중 {index + 1}번째)")


__all__ = ["Ctrl", "windows", "best_window", "size_of", "exe_of", "children", "find_ctrl",
           "list_ctrl", "items", "find_row", "row_name", "row_point",
           "find_row_point", "send"]
