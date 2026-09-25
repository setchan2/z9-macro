"""가상 키코드(VK) 이름 매핑과 핫키 문자열 파싱."""

from __future__ import annotations

VK_BY_NAME: dict[str, int] = {
    # 마우스 버튼 (핫키로 쓸 수 있게 포함)
    "MouseLeft": 0x01,
    "MouseRight": 0x02,
    "MouseMiddle": 0x04,
    "MouseX1": 0x05,
    "MouseX2": 0x06,
    # 제어
    "Backspace": 0x08,
    "Tab": 0x09,
    "Clear": 0x0C,
    "Enter": 0x0D,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "Esc": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "Left": 0x25,
    "Up": 0x26,
    "Right": 0x27,
    "Down": 0x28,
    "PrintScreen": 0x2C,
    "Insert": 0x2D,
    "Delete": 0x2E,
    # 수정자 (일반/좌우 구분)
    "Shift": 0x10,
    "Ctrl": 0x11,
    "Alt": 0x12,
    "LShift": 0xA0,
    "RShift": 0xA1,
    "LCtrl": 0xA2,
    "RCtrl": 0xA3,
    "LAlt": 0xA4,
    "RAlt": 0xA5,
    "LWin": 0x5B,
    "RWin": 0x5C,
    "Apps": 0x5D,
    # 넘패드
    "Num0": 0x60,
    "Num1": 0x61,
    "Num2": 0x62,
    "Num3": 0x63,
    "Num4": 0x64,
    "Num5": 0x65,
    "Num6": 0x66,
    "Num7": 0x67,
    "Num8": 0x68,
    "Num9": 0x69,
    "NumMul": 0x6A,
    "NumAdd": 0x6B,
    "NumSub": 0x6D,
    "NumDot": 0x6E,
    "NumDiv": 0x6F,
    "NumLock": 0x90,
    "ScrollLock": 0x91,
    # 기호
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}

for _i in range(10):
    VK_BY_NAME[str(_i)] = 0x30 + _i
for _i in range(26):
    VK_BY_NAME[chr(ord("A") + _i)] = 0x41 + _i
for _i in range(1, 25):
    VK_BY_NAME[f"F{_i}"] = 0x70 + _i - 1

NAME_BY_VK: dict[int, str] = {}
for _name, _vk in VK_BY_NAME.items():
    # 좌우 구분 키가 일반 키를 덮어쓰지 않도록 먼저 등록된 이름을 유지
    NAME_BY_VK.setdefault(_vk, _name)

# 확장 키: SendInput에 스캔코드로 보낼 때 KEYEVENTF_EXTENDEDKEY가 필요하다.
EXTENDED_VKS = {
    0x21,  # PageUp
    0x22,  # PageDown
    0x23,  # End
    0x24,  # Home
    0x25,  # Left
    0x26,  # Up
    0x27,  # Right
    0x28,  # Down
    0x2C,  # PrintScreen
    0x2D,  # Insert
    0x2E,  # Delete
    0x5B,  # LWin
    0x5C,  # RWin
    0x5D,  # Apps
    0x6F,  # NumDiv
    0x90,  # NumLock
    0xA3,  # RCtrl
    0xA5,  # RAlt
}

MODIFIER_VKS = {0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C}

MOUSE_VKS = {0x01, 0x02, 0x04, 0x05, 0x06}

# GUI 콤보박스에 노출할 순서 있는 키 목록
KEY_CHOICES: list[str] = (
    [chr(ord("A") + i) for i in range(26)]
    + [str(i) for i in range(10)]
    + [f"F{i}" for i in range(1, 13)]
    + [
        "Space",
        "Enter",
        "Esc",
        "Tab",
        "Backspace",
        "Delete",
        "Insert",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Up",
        "Down",
        "Left",
        "Right",
        "Shift",
        "Ctrl",
        "Alt",
        "LShift",
        "LCtrl",
        "LAlt",
    ]
    + [f"Num{i}" for i in range(10)]
    + ["NumAdd", "NumSub", "NumMul", "NumDiv", "NumDot"]
    + [";", "=", ",", "-", ".", "/", "`", "[", "]", "\\", "'"]
)


def vk_of(name: str) -> int | None:
    """키 이름 → VK 코드. 대소문자 구분 없이 찾는다."""
    if not name:
        return None
    if name in VK_BY_NAME:
        return VK_BY_NAME[name]
    lowered = name.strip().lower()
    for key, vk in VK_BY_NAME.items():
        if key.lower() == lowered:
            return vk
    return None


def name_of(vk: int) -> str:
    return NAME_BY_VK.get(vk, f"VK_{vk:02X}")


def is_mouse_vk(vk: int) -> bool:
    return vk in MOUSE_VKS


# --------------------------------------------------------------------------
# 핫키 문자열: "Ctrl+Shift+F1"
# --------------------------------------------------------------------------
_MOD_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "win": "Win",
}
MOD_ORDER = ("Ctrl", "Shift", "Alt", "Win")


def parse_hotkey(text: str) -> tuple[frozenset[str], int] | None:
    """'Ctrl+Shift+F1' → (frozenset{'Ctrl','Shift'}, vk). 실패 시 None."""
    if not text or not text.strip():
        return None
    parts = [p.strip() for p in text.split("+") if p.strip()]
    if not parts:
        return None
    mods: set[str] = set()
    main: str | None = None
    for part in parts:
        alias = _MOD_ALIASES.get(part.lower())
        if alias is not None:
            mods.add(alias)
        else:
            main = part
    if main is None:
        # "Ctrl" 단독처럼 수정자만 있는 경우 → 마지막 수정자를 본 키로 취급
        main = parts[-1]
        alias = _MOD_ALIASES.get(main.lower())
        if alias is not None:
            mods.discard(alias)
    vk = vk_of(main)
    if vk is None:
        return None
    return frozenset(mods), vk


def format_hotkey(mods: frozenset[str] | set[str], vk: int) -> str:
    ordered = [m for m in MOD_ORDER if m in mods]
    return "+".join([*ordered, name_of(vk)])
