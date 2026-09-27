"""브라우저 화면의 **글씨로** 단추를 찾는다 (윈도 UI 자동화).

홈페이지의 [GAME START]를 좌표로 누르면 창을 옮기거나, 스크롤이 달라지거나,
브라우저 확대가 바뀌면 그대로 어긋난다. 그런데 브라우저는 **지금 띄운 쪽의
내용을 이름으로** 바깥에 알려 준다 — 화면 낭독기가 웹을 읽을 수 있는 것이
그 덕이다. 그 길로 'GAME START'라는 이름을 가진 것을 찾아 그 자리를 얻는다.

찾은 뒤에는 **진짜 마우스로 그 자리를 누른다.** 자동화로 "눌러라"라고 시키는
길(Invoke)도 있지만, 게임 홈페이지 단추처럼 자바스크립트가 마우스를 직접 보는
것은 그 방식으로 안 먹는 일이 있다. 자리만 얻고 누르는 것은 사람이 하는 것과
같으므로 늘 통한다.

못 찾으면 조용히 실패한다(None). 부르는 쪽은 찍어 둔 자리로 넘어가면 된다 —
이 길이 막혔다고 매크로가 서면 안 된다.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

ole32 = ctypes.windll.ole32
oleaut32 = ctypes.windll.oleaut32

COINIT_APARTMENTTHREADED = 0x2
CLSCTX_INPROC_SERVER = 0x1

TREESCOPE_DESCENDANTS = 4
UIA_NAME_PROPERTY = 30005
UIA_BOUNDING_RECT_PROPERTY = 30001
UIA_CONTROLTYPE_PROPERTY = 30003
UIA_IS_OFFSCREEN_PROPERTY = 30022

# 눌러도 되는 것들. 홈페이지 단추는 이 셋 중 하나로 잡힌다.
#   50000 Button · 50005 Hyperlink · 50006 Image
# 그냥 글씨(50020 Text)까지 받아 주면 **아무 데나** 걸린다 — 실제로 편집기에
# 열어 둔 소스 코드의 'GAME START' 글씨를 단추로 알고 눌렀다.
CLICKABLE = (50000, 50005, 50006)

VT_BSTR = 8
VT_BOOL = 11
VT_R8_ARRAY = 0x2005  # VT_ARRAY | VT_R8

# IUIAutomation 의 함수 자리. (앞의 셋은 어느 COM 객체나 같다)
AUTO_ELEMENT_FROM_HANDLE = 6
AUTO_CREATE_TRUE_CONDITION = 21
# IUIAutomationElement
ELEM_FIND_ALL = 6
ELEM_GET_PROPERTY = 10
# IUIAutomationElementArray
ARRAY_GET_LENGTH = 3
ARRAY_GET_ELEMENT = 4


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str) -> None:
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(self))


class VARIANT(ctypes.Structure):
    """COM 이 값을 돌려줄 때 쓰는 그릇. 여기서는 글씨와 네모만 꺼낸다."""

    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("val", ctypes.c_longlong), ("pad", ctypes.c_longlong)]


CLSID_CUIAutomation = "{FF48DBA4-60EF-4201-AA87-54103EEF594E}"
IID_IUIAutomation = "{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}"


def _call(ptr, index: int, *args, types=()):
    """COM 객체의 index 번째 함수를 부른다."""
    table = ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *types)
    return proto(table[index])(ptr, *args)


def _release(ptr) -> None:
    if ptr:
        _call(ptr, 2)


def _text_of(variant: VARIANT) -> str:
    if variant.vt != VT_BSTR or not variant.val:
        return ""
    text = ctypes.cast(ctypes.c_void_p(variant.val), ctypes.c_wchar_p).value or ""
    oleaut32.SysFreeString(ctypes.c_void_p(variant.val))
    return text


def _rect_of(variant: VARIANT) -> tuple[float, float, float, float] | None:
    """(왼쪽, 위, 너비, 높이). UI 자동화는 이 네 값을 준다."""
    if variant.vt != VT_R8_ARRAY or not variant.val:
        return None
    array = ctypes.c_void_p(variant.val)
    data = ctypes.c_void_p()
    if oleaut32.SafeArrayAccessData(array, ctypes.byref(data)) != 0:
        return None
    try:
        values = ctypes.cast(data, ctypes.POINTER(ctypes.c_double * 4))[0]
        got = (float(values[0]), float(values[1]), float(values[2]),
               float(values[3]))
    finally:
        oleaut32.SafeArrayUnaccessData(array)
        oleaut32.SafeArrayDestroy(array)
    return got


def _plain(text: str) -> str:
    """견주기 좋게 다듬는다 — 사이 빈칸과 대소문자는 무시."""
    return "".join(text.split()).lower()


def find_named(hwnd: int, names: list[str], limit: int = 4000,
               kinds: tuple[int, ...] = CLICKABLE
               ) -> tuple[tuple[int, int] | None, str]:
    """그 창 안에서 이름이 맞는 것의 **한복판(화면 좌표)**을 찾는다.

    (자리, 설명)을 돌려준다. 못 찾으면 자리가 None이고 설명에 까닭이 적힌다.
    names 는 여러 개를 줄 수 있다 — 'GAME START' · '게임시작'처럼 홈페이지가
    바뀌어도 걸리도록.
    """
    wanted = [_plain(n) for n in names if n.strip()]
    if not wanted:
        return (None, "찾을 이름이 없습니다")
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    auto = ctypes.c_void_p()
    hr = ole32.CoCreateInstance(ctypes.byref(GUID(CLSID_CUIAutomation)), None,
                                CLSCTX_INPROC_SERVER,
                                ctypes.byref(GUID(IID_IUIAutomation)),
                                ctypes.byref(auto))
    if hr != 0 or not auto:
        return (None, "UI 자동화를 못 열었습니다")
    root = ctypes.c_void_p()
    cond = ctypes.c_void_p()
    array = ctypes.c_void_p()
    try:
        if _call(auto, AUTO_ELEMENT_FROM_HANDLE, wintypes.HWND(hwnd),
                 ctypes.byref(root), types=(wintypes.HWND,
                                            ctypes.POINTER(ctypes.c_void_p))):
            return (None, "그 창을 UI 자동화로 못 잡았습니다")
        if _call(auto, AUTO_CREATE_TRUE_CONDITION, ctypes.byref(cond),
                 types=(ctypes.POINTER(ctypes.c_void_p),)):
            return (None, "조건을 못 만들었습니다")
        if _call(root, ELEM_FIND_ALL, ctypes.c_int(TREESCOPE_DESCENDANTS),
                 cond, ctypes.byref(array),
                 types=(ctypes.c_int, ctypes.c_void_p,
                        ctypes.POINTER(ctypes.c_void_p))):
            return (None, "창 안을 못 읽었습니다")
        count = ctypes.c_int(0)
        _call(array, ARRAY_GET_LENGTH, ctypes.byref(count),
              types=(ctypes.POINTER(ctypes.c_int),))
        seen = 0
        # 이름이 맞는 것이 여럿일 수 있다. 홈페이지에서는 [게임 다운로드]까지
        # 감싼 넓은 띠와, [GAME START] 동그라미가 **둘 다** '게임 시작'이라는
        # 이름으로 잡혔다. 넓은 쪽 한복판은 단추 밖이므로 **가장 작은 것**을
        # 고른다 — 이름이 똑같은 것이 있으면 그쪽을 먼저 본다.
        hits: list[tuple[int, float, tuple[int, int], str]] = []
        for index in range(min(count.value, limit)):
            item = ctypes.c_void_p()
            if _call(array, ARRAY_GET_ELEMENT, ctypes.c_int(index),
                     ctypes.byref(item),
                     types=(ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))):
                continue
            try:
                name = VARIANT()
                _call(item, ELEM_GET_PROPERTY, ctypes.c_int(UIA_NAME_PROPERTY),
                      ctypes.byref(name),
                      types=(ctypes.c_int, ctypes.POINTER(VARIANT)))
                text = _plain(_text_of(name))
                if not text:
                    continue
                seen += 1
                if not any(w == text or w in text for w in wanted):
                    continue
                kind = VARIANT()
                _call(item, ELEM_GET_PROPERTY,
                      ctypes.c_int(UIA_CONTROLTYPE_PROPERTY),
                      ctypes.byref(kind),
                      types=(ctypes.c_int, ctypes.POINTER(VARIANT)))
                if kinds and int(kind.val) not in kinds:
                    continue   # 글씨나 칸 따위 — 누를 것이 아니다
                box = VARIANT()
                _call(item, ELEM_GET_PROPERTY,
                      ctypes.c_int(UIA_BOUNDING_RECT_PROPERTY),
                      ctypes.byref(box),
                      types=(ctypes.c_int, ctypes.POINTER(VARIANT)))
                rect = _rect_of(box)
                if rect is None or rect[2] <= 1 or rect[3] <= 1:
                    continue  # 화면에 안 그려진 것 (숨었거나 스크롤 밖)
                point = (int(rect[0] + rect[2] / 2), int(rect[1] + rect[3] / 2))
                hits.append((0 if text in wanted else 1, rect[2] * rect[3],
                             point, f"{rect[2]:.0f}×{rect[3]:.0f}"))
            finally:
                _release(item)
        if hits:
            hits.sort(key=lambda row: (row[0], row[1]))
            _rank, _area, point, size = hits[0]
            return (point, f"'{names[0]}'을(를) 이름으로 찾았습니다 ({size}"
                           + (f" · 후보 {len(hits)}개 중 가장 작은 것)"
                              if len(hits) > 1 else ")"))
        return (None, f"이름이 맞는 것이 없습니다 (글씨 있는 것 {seen}개 중)")
    except OSError as exc:
        return (None, f"UI 자동화에서 문제가 났습니다: {exc!r}")
    finally:
        _release(array)
        _release(cond)
        _release(root)
        _release(auto)


def find_named_anywhere(names: list[str], skip_titles: list[str] = (),
                        limit_windows: int = 12
                        ) -> tuple[tuple[int, int] | None, str, int]:
    """열려 있는 창들을 돌며 그 이름을 가진 것을 찾는다.

    **창 제목을 몰라도 된다.** 브라우저 제목은 지금 보고 있는 탭에 따라 바뀌므로
    제목으로 찾으면 탭을 옮겨 둔 사이에 못 찾는다. 이름이 잡히는 것은 화면에
    실제로 그려진 것뿐이라, 다른 탭에 있는 단추가 잘못 걸릴 일도 없다.
    """
    from . import window as win_mod

    skip = [t.strip().lower() for t in skip_titles if t]
    tried = 0
    last = "창을 못 찾았습니다"
    for info in win_mod.list_windows(""):
        title = info.title.strip().lower()
        if any(s and s in title for s in skip):
            continue
        tried += 1
        if tried > limit_windows:
            break
        point, why = find_named(info.hwnd, names)
        if point is not None:
            return (point, f"{why} — '{info.title}' 창", info.hwnd)
        last = why
    return (None, f"연 창 {tried}개에서 못 찾았습니다 ({last})", 0)


__all__ = ["find_named", "find_named_anywhere"]
