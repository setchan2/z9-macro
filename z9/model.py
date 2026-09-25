"""프로필 데이터 모델 (JSON 직렬화 가능)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .achievements import Plan as AchievementPlan

RGB = tuple[int, int, int]

# 실행 중 게임 창이 뒤로 밀렸을 때의 처리
FOCUS_STOP = "stop"
FOCUS_REFOCUS = "refocus"
FOCUS_IGNORE = "ignore"
FOCUS_POLICIES = (FOCUS_STOP, FOCUS_REFOCUS, FOCUS_IGNORE)

# 설정 형식의 판 번호. 예전에 잘못 저장된 값을 한 번만 바로잡을 때 쓴다.
SETTINGS_VERSION = 2

# 입력 전달 방법
INPUT_SEND = "send"  # SendInput — 맨 앞 창으로
INPUT_POST = "post"  # PostMessage — 지정한 창으로 (배경 입력)
INPUT_MODES = (INPUT_SEND, INPUT_POST)


def _coerce(cls, data: dict[str, Any]):
    """dict에서 dataclass로. 모르는 키는 버리고 없는 키는 기본값을 쓴다."""
    fields = {f for f in cls.__dataclass_fields__}
    return cls(**{k: v for k, v in data.items() if k in fields})


# --------------------------------------------------------------------------
# 1. 녹화 매크로
# --------------------------------------------------------------------------
@dataclass
class Macro:
    """녹화된 키/마우스 이벤트 시퀀스.

    events 원소 형식:
      {"t": 초, "kind": "key",   "vk": int, "down": bool}
      {"t": 초, "kind": "button","button": "left", "down": bool, "cx": int, "cy": int}
      {"t": 초, "kind": "move",  "cx": int, "cy": int}
      {"t": 초, "kind": "wheel", "wheel": int, "cx": int, "cy": int}
    cx/cy는 녹화 당시 게임 창 클라이언트 기준 상대좌표.
    """

    name: str = "새 매크로"
    events: list[dict[str, Any]] = field(default_factory=list)
    client_w: int = 0
    client_h: int = 0
    absolute: bool = False  # True면 cx/cy가 화면 절대좌표
    repeat: int = 1  # 0 = 무한
    speed: float = 1.0
    interval_ms: int = 0  # 반복 사이 대기
    hotkey: str = ""
    scale_to_window: bool = True
    # 긴 대기 중에 녹화해 둔 짧은 이동을 끼워 넣을지. 켜도 매번 넣지는 않는다.
    use_moves: bool = False

    @property
    def duration(self) -> float:
        """첫 이벤트부터 마지막으로 할 일이 끝나는 순간까지의 길이(초).

        대기 이벤트가 쉬는 시간은 보통 뒤따르는 이벤트의 시각에 이미 들어가
        있다. 하지만 맨 끝에 놓인 대기는 밀어줄 뒤가 없어서, 시각만 보면
        그 몫이 통째로 사라진다. 그래서 대기는 t가 아니라 t+쉬는 시간으로 잰다.
        """
        end = 0.0
        for event in self.events:
            done = event.get("t", 0.0)
            if event.get("kind") == "wait":
                done += max(event.get("duration_ms", 0), 0) / 1000.0
            end = max(end, done)
        return end

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Macro":
        return _coerce(cls, data)


@dataclass
class Movement:
    """대기 중에 끼워 넣는 짧은 방향키 이동.

    매크로와 달리 마우스도 스킬도 담지 않는다. 대기 시간에 나가는 것이므로
    캐릭터가 조금 걸어 다니는 것 이상을 하면 매크로의 흐름이 깨진다.
    """

    name: str = "움직임"
    events: list[dict[str, Any]] = field(default_factory=list)
    enabled: bool = True

    @property
    def duration(self) -> float:
        return max((e.get("t", 0.0) for e in self.events), default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Movement":
        return _coerce(cls, data)


# --------------------------------------------------------------------------
# 2. 단일 키 반복 (연타 / 홀드)
# --------------------------------------------------------------------------
@dataclass
class RepeatTask:
    name: str = "새 연타"
    key: str = "Z"
    mode: str = "tap"  # "tap" = 연타, "hold" = 계속 누르고 있기
    interval_ms: int = 100  # tap 모드: 누름 시작 간격
    hold_ms: int = 30  # tap 모드: 한 번 누르고 있는 시간
    jitter_ms: int = 0  # 간격에 ±무작위 편차 (게임 입력 큐가 밀릴 때 완화용)
    hotkey: str = ""  # 토글 핫키
    duration_s: int = 0  # 0 = 무제한, >0이면 그 초 후 자동 정지

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RepeatTask":
        return _coerce(cls, data)


# --------------------------------------------------------------------------
# 3. 이동 경로 매크로
# --------------------------------------------------------------------------
@dataclass
class PathStep:
    kind: str = "key"  # key | click | move | wait
    key: str = "Right"
    duration_ms: int = 300  # key: 누르고 있는 시간 / wait: 대기 시간
    x: int = 0  # click/move: 클라이언트 상대좌표
    y: int = 0
    button: str = "left"

    def label(self) -> str:
        if self.kind == "key":
            return f"키 [{self.key}] {self.duration_ms}ms 누름"
        if self.kind == "click":
            return f"클릭 {self.button} ({self.x}, {self.y})"
        if self.kind == "move":
            return f"커서 이동 ({self.x}, {self.y})"
        return f"대기 {self.duration_ms}ms"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PathStep":
        return _coerce(cls, data)


@dataclass
class PathMacro:
    name: str = "새 경로"
    steps: list[PathStep] = field(default_factory=list)
    repeat: int = 1  # 0 = 무한
    interval_ms: int = 200
    hotkey: str = ""
    client_w: int = 0
    client_h: int = 0
    scale_to_window: bool = True

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [s.to_dict() for s in self.steps]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PathMacro":
        obj = _coerce(cls, {k: v for k, v in data.items() if k != "steps"})
        obj.steps = [PathStep.from_dict(s) for s in data.get("steps", [])]
        return obj


# --------------------------------------------------------------------------
# 시나리오 — 만들어 둔 매크로를 순서대로 엮는다
# --------------------------------------------------------------------------
USE_GROUP_DELAY = -1
USE_MACRO_WHEEL = -1
USE_ITEM_REPEAT = -1

# 단계를 언제 끝낼지 정하는 방식
LIMIT_ITEM = "item"    # 항목 자체 설정을 따른다
LIMIT_COUNT = "count"  # 정해진 횟수만큼 반복
LIMIT_TIME = "time"    # 정해진 시간 동안 반복
LIMIT_MODES = (LIMIT_ITEM, LIMIT_COUNT, LIMIT_TIME)


STEP_KINDS = ("macro", "repeat", "path", "wait", "schedule", "fishing")


@dataclass
class ScenarioStep:
    """시나리오의 한 단계.

    처음에는 매크로만 넣을 수 있었지만, 연타나 이동 경로도 흐름의 일부라 같은
    자리에서 다뤄야 한다. kind로 무엇을 돌릴지 정하고 target이 그 이름이다.
    """

    kind: str = "macro"  # macro | repeat | path | wait | schedule | fishing
    target: str = ""  # 매크로 · 연타 · 경로 · 예약 이름 (wait·fishing이면 비어 있음)
    # -1이면 그룹의 '단계 간 대기'를 따른다. 0 이상이면 이 단계만 그 값을 쓴다.
    # 대부분의 단계는 같은 간격이면 충분하고, 특정 매크로 뒤에만 길게 쉬어야 하는
    # 경우가 있어서 예외를 둘 수 있게 했다.
    delay_ms: int = USE_GROUP_DELAY
    # -1이면 매크로에 기록된 휠 횟수를 그대로 쓴다. 0 이상이면 그 매크로 안의 휠
    # 이벤트를 전부 이 횟수로 바꿔 실행한다. 같은 매크로를 "세 칸 내리기"와
    # "열 칸 내리기"로 나눠 쓰려고 복제할 필요가 없다.
    wheel_count: int = USE_MACRO_WHEEL
    wait_ms: int = 1000  # 대기 단계에서 쉴 시간
    # 이 단계를 언제 끝낼지. 항목 설정 / 몇 회 / 몇 초 중 하나.
    # 같은 매크로를 자리마다 다르게 쓰려고 복제할 필요가 없게 하려는 것이라,
    # 여기서 정한 값은 원본 항목을 건드리지 않는다.
    limit_mode: str = LIMIT_ITEM
    repeat_count: int = 1  # count 모드에서 쓸 횟수
    limit_seconds: float = 10.0  # time 모드에서 쓸 시간 (0.1초 단위)

    def effective_delay(self, group_delay: int) -> int:
        return group_delay if self.delay_ms < 0 else self.delay_ms

    @property
    def custom_delay(self) -> bool:
        return self.delay_ms >= 0

    @property
    def custom_wheel(self) -> bool:
        return self.wheel_count >= 0

    @property
    def custom_repeat(self) -> bool:
        return self.limit_mode == LIMIT_COUNT

    @property
    def timed(self) -> bool:
        return self.limit_mode == LIMIT_TIME

    def effective_repeat(self, item_repeat: int) -> int:
        """횟수 모드에서 몇 번 돌릴지. 무한(0)은 시나리오 안에서 1회로 끊는다."""
        if self.limit_mode == LIMIT_COUNT:
            return max(int(self.repeat_count), 1)
        return item_repeat if item_repeat > 0 else 1

    def effective_seconds(self, item_seconds: float = 0.0) -> float:
        """시간 모드에서 몇 초 돌릴지."""
        if self.limit_mode == LIMIT_TIME:
            return max(round(float(self.limit_seconds), 1), 0.1)
        return item_seconds

    @property
    def label(self) -> str:
        if self.kind == "wait":
            return f"대기 {self.wait_ms}ms"
        if self.kind == "schedule":
            return f"예약 확인 · {self.target}" if self.target else "예약 확인"
        if self.kind == "fishing":
            if self.limit_mode == LIMIT_TIME:
                return f"낚시 {self.limit_seconds:g}초"
            if self.limit_mode == LIMIT_COUNT:
                return f"낚시 {self.repeat_count}판"
            return "낚시"
        return self.target or "(비어 있음)"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioStep":
        obj = _coerce(cls, data)
        # 단계 종류가 생기기 전에는 매크로 이름만 'macro' 키로 들어 있었다.
        if not obj.target and data.get("macro"):
            obj.kind = "macro"
            obj.target = str(data["macro"])
        if obj.kind not in STEP_KINDS:
            obj.kind = "macro"

        # 한계 방식이 생기기 전 형식:
        #   repeat_count -1  = 항목 설정 / 1 이상 = 그 횟수
        #   run_seconds  0   = 항목 설정 / 1 이상 = 그 초 (연타 전용)
        if "limit_mode" not in data:
            old_count = int(data.get("repeat_count", -1))
            old_seconds = float(data.get("run_seconds", 0) or 0)
            if old_count >= 1:
                obj.limit_mode = LIMIT_COUNT
                obj.repeat_count = old_count
            elif old_seconds > 0:
                obj.limit_mode = LIMIT_TIME
                obj.limit_seconds = old_seconds
            else:
                obj.limit_mode = LIMIT_ITEM
                obj.repeat_count = 1
        if obj.limit_mode not in LIMIT_MODES:
            obj.limit_mode = LIMIT_ITEM
        return obj


# 그룹 종류.
GROUP_NORMAL = "normal"  # 차례가 되면 순서대로 돈다
GROUP_CONDITIONAL = "conditional"  # 순서에서 빠지고, 조건이 걸릴 때만 끼어든다
GROUP_KINDS = (GROUP_NORMAL, GROUP_CONDITIONAL)

# 조건부 그룹의 발동 조건을 언제 확인할지.
TRIGGER_CYCLE = "cycle"  # 사이클 경계마다 (싸다)
TRIGGER_STEP = "step"  # 단계 사이마다 (빠르지만 확인 비용이 든다)
TRIGGER_WHENS = (TRIGGER_CYCLE, TRIGGER_STEP)


@dataclass
class GroupCondition:
    """그룹이 한 사이클 돌고 난 뒤 확인하는 조건.

    조건 자체는 [조건부 실행] 탭의 감지 조건(PixelRule)을 이름으로 참조한다.
    픽셀 감지 로직을 두 벌 만들 이유가 없고, 한 곳에서 좌표를 고치면 이쪽에도
    그대로 반영된다.

    action이 goto와 group으로 나뉘는 것이 중요하다.
      goto  — 그 그룹으로 **옮겨 간다.** 돌아오지 않는다. 흐름 자체가 바뀐다.
      group — 그 그룹을 **한 번 돌고 원래 자리로 돌아온다.** 끼어들기다.
    """

    rule: str = ""  # 감지 조건 이름
    # run = 매크로 실행 / click = 찾은 그림 누르기 / group = 그룹 1회 실행 후
    # 복귀 / goto = 그룹으로 이동 / stop = 중지
    action: str = "run"
    target: str = ""  # run이면 매크로 이름, group·goto면 그룹 이름
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroupCondition":
        return _coerce(cls, data)


@dataclass
class ScenarioGroup:
    """매크로 몇 개를 묶어 반복하는 단위.

    종류가 둘이다.

    **일반 그룹** — 시나리오가 돌 때 차례대로 실행된다. 예전부터 있던 그것이다.

    **조건부 그룹** — 순서에서 빠진다. 대신 시나리오가 도는 **내내** 발동 조건을
    지켜보다가, 걸리면 하던 일을 잠깐 멈추고 이 그룹을 한 번 돌린 뒤 원래 자리로
    돌아온다. "체력이 낮아지면 물약 먹기", "가방이 차면 팔러 가기"처럼 언제 필요할지
    모르는 일을 흐름에 억지로 끼워 넣지 않고 따로 둘 수 있다.
    """

    name: str = "새 그룹"
    steps: list[ScenarioStep] = field(default_factory=list)
    repeat: int = 1  # 0 = 무한 (조건으로만 빠져나감)
    interval_ms: int = 300  # 단계 사이 대기
    conditions: list[GroupCondition] = field(default_factory=list)
    # 이 그룹이 한 사이클 돌 때마다 확인할 버프 이름들. 만료된 것만 다시 쓴다.
    buffs: list[str] = field(default_factory=list)
    buff_margin_s: int = 30  # 만료 몇 초 전에 미리 갱신할지
    # -- 조건부 그룹 -------------------------------------------------------
    kind: str = GROUP_NORMAL
    trigger: str = ""  # 발동 조건 (감지 조건 이름)
    trigger_when: str = TRIGGER_CYCLE  # 언제 확인할지
    # 한 번 발동한 뒤 이만큼은 다시 보지 않는다. 조건이 걸린 채로 남아 있을 때
    # 쉴 새 없이 되풀이하는 것을 막는다. 0이면 제한 없음.
    trigger_cooldown_s: int = 0

    @property
    def conditional(self) -> bool:
        return self.kind == GROUP_CONDITIONAL

    def interrupt_cycles(self) -> int:
        """끼어들었을 때 몇 사이클 돌지.

        무한(0)은 여기서 1회로 끊는다. 끼어든 그룹이 안 끝나면 시나리오가 통째로
        그 안에 갇힌다 — 되돌아올 수 없는 끼어들기는 끼어들기가 아니다.
        """
        return self.repeat if self.repeat > 0 else 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["steps"] = [s.to_dict() for s in self.steps]
        data["conditions"] = [c.to_dict() for c in self.conditions]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScenarioGroup":
        obj = _coerce(
            cls, {k: v for k, v in data.items() if k not in ("steps", "conditions")}
        )
        obj.steps = [ScenarioStep.from_dict(s) for s in data.get("steps", [])]
        obj.conditions = [
            GroupCondition.from_dict(c) for c in data.get("conditions", [])
        ]
        if obj.kind not in GROUP_KINDS:
            obj.kind = GROUP_NORMAL
        if obj.trigger_when not in TRIGGER_WHENS:
            obj.trigger_when = TRIGGER_CYCLE
        obj.trigger_cooldown_s = max(0, obj.trigger_cooldown_s)
        return obj


@dataclass
class Scenario:
    name: str = "새 시나리오"
    groups: list[ScenarioGroup] = field(default_factory=list)
    repeat: int = 1  # 0 = 무한
    interval_ms: int = 300  # 그룹 사이 대기
    hotkey: str = ""

    @property
    def step_count(self) -> int:
        return sum(len(g.steps) for g in self.groups)

    @property
    def ordered_groups(self) -> list["ScenarioGroup"]:
        """차례대로 도는 그룹만. 조건부 그룹은 빠진다."""
        return [g for g in self.groups if not g.conditional]

    @property
    def watch_groups(self) -> list["ScenarioGroup"]:
        """발동 조건이 걸린 조건부 그룹만."""
        return [g for g in self.groups if g.conditional and g.trigger]

    def find_group(self, name: str) -> "ScenarioGroup | None":
        for group in self.groups:
            if group.name == name:
                return group
        return None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["groups"] = [g.to_dict() for g in self.groups]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scenario":
        obj = _coerce(cls, {k: v for k, v in data.items() if k != "groups"})
        obj.groups = [ScenarioGroup.from_dict(g) for g in data.get("groups", [])]

        # 그룹이 생기기 전에 저장된 시나리오는 단계가 평평하게 들어 있다.
        # 통째로 그룹 하나에 담아 그대로 쓸 수 있게 한다.
        if not obj.groups and data.get("steps"):
            obj.groups = [
                ScenarioGroup(
                    name="그룹 1",
                    steps=[ScenarioStep.from_dict(s) for s in data["steps"]],
                    interval_ms=int(data.get("interval_ms", 300)),
                )
            ]
        return obj


# --------------------------------------------------------------------------
# 4. 조건부 실행 (픽셀 감지)
# --------------------------------------------------------------------------
@dataclass
class PixelPoint:
    x: int = 0  # 클라이언트 상대좌표
    y: int = 0
    r: int = 0
    g: int = 0
    b: int = 0

    @property
    def color(self) -> RGB:
        return (self.r, self.g, self.b)

    def set_color(self, rgb: RGB) -> None:
        self.r, self.g, self.b = rgb

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PixelPoint":
        return _coerce(cls, data)


@dataclass
class MaskRect:
    """그림에서 비교하지 않을 사각형 (그림 왼쪽 위 기준)."""

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MaskRect":
        return _coerce(cls, data)


@dataclass
class IconWatch:
    """영역 안 어딘가에 있는 **그림**을 찾아 있음/없음을 본다.

    버프 아이콘처럼 자리가 밀리는 표시를 잡기 위한 것이다. 앞의 버프가 끝나면
    뒤엣것이 앞으로 당겨지므로 좌표가 고정이 아니고, 그래서 좌표+색으로는
    원리적으로 잡을 수 없다.

    masks는 **비교에서 뺄 칸**이다. 아이콘 위에 남은 시간 숫자가 겹쳐 그려지면
    그 칸은 1분마다 다른 그림이 되므로, 빼 두지 않으면 절대 맞지 않는다.
    """

    name: str = "새 그림"
    icon: str = ""  # PNG 파일 이름 (감지아이콘 폴더 기준)
    # 찾을 영역 (창 기준). 폭·높이가 0이면 창 전체 — 느리므로 꼭 좁혀 쓸 것.
    area_x: int = 0
    area_y: int = 0
    area_w: int = 0
    area_h: int = 0
    tolerance: int = 22  # 채널당 평균 허용 차이. 작을수록 깐깐하다
    expect: str = "present"  # present = 있어야 성립 / absent = 없어야 성립
    level: bool = True  # 반투명하게 밝기가 밀린 것도 같은 그림으로 볼지
    masks: list[MaskRect] = field(default_factory=list)

    def area(self, window) -> tuple[int, int, int, int] | None:
        """찾을 영역을 화면 절대좌표로. 지정이 없으면 창 전체."""
        if window is None:
            return None
        if self.area_w > 0 and self.area_h > 0:
            x, y = window.client_to_screen(self.area_x, self.area_y)
            return (x, y, self.area_w, self.area_h)
        cw, ch = window.client_size()
        x, y = window.client_to_screen(0, 0)
        return (x, y, cw, ch)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["masks"] = [m.to_dict() for m in self.masks]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IconWatch":
        obj = _coerce(cls, {k: v for k, v in data.items() if k != "masks"})
        obj.masks = [MaskRect.from_dict(m) for m in data.get("masks", [])]
        if obj.expect not in ("present", "absent"):
            obj.expect = "present"
        return obj


# 숫자를 무엇과 견줄지.
NUM_AT_MAX = "at_max"  # 앞 값이 뒤 값에 닿았을 때 (피로도 가득)
NUM_CURRENT = "current"  # 앞 값 자체
NUM_MAX = "max"  # 뒤 값 자체
NUM_PERCENT = "percent"  # 앞 값 / 뒤 값 × 100
NUM_LEFT = "left"  # 뒤 값 - 앞 값 (남은 양)
NUM_TARGETS = (NUM_AT_MAX, NUM_CURRENT, NUM_MAX, NUM_PERCENT, NUM_LEFT)

NUM_AT_LEAST = "at_least"  # 이상
NUM_AT_MOST = "at_most"  # 이하
NUM_COMPARES = (NUM_AT_LEAST, NUM_AT_MOST)


@dataclass
class NumberWatch:
    """화면에 적힌 **숫자**를 읽어 견준다.

    피로도처럼 숫자 자체가 조건인 것들이 있다. "피로도: 10502 / 540000"에서 앞의
    값이 뒤의 값에 닿으면 더 얻을 게 없으니 다른 일을 해야 한다. 색이나 그림으로는
    이걸 알 수 없다 — 숫자를 실제로 읽어야 한다.

    최대값이 달라질 수 있으므로 **뒤 값도 같이 읽어서** 견준다. 어딘가에 540000을
    적어 두면 그 숫자가 바뀌는 날 조용히 틀린다.

    툴팁처럼 커서를 올려야 뜨는 것은 hover 자리를 정해 두면 읽기 직전에 커서를
    올렸다가 원래 자리로 돌려놓는다.
    """

    name: str = "새 숫자"
    # -- 어디를 읽나 -------------------------------------------------------
    # 커서를 올려야 뜨는 경우 그 자리 (창 기준). 둘 다 음수면 올리지 않는다.
    hover_x: int = -1
    hover_y: int = -1
    hover_wait_ms: int = 400  # 커서를 올리고 툴팁이 뜰 때까지 기다릴 시간
    # 숫자가 적힌 영역 (창 기준).
    area_x: int = 0
    area_y: int = 0
    area_w: int = 0
    area_h: int = 0
    # -- 어떻게 읽나 -------------------------------------------------------
    font: str = ""  # 익혀 둔 글꼴 이름 (숫자글꼴 폴더 아래)
    dark_text: bool = True  # 밝은 배경에 어두운 글자인가
    threshold: int = 128  # 글자와 배경을 가르는 밝기
    # -- 무엇과 견주나 -----------------------------------------------------
    target: str = NUM_AT_MAX
    compare: str = NUM_AT_LEAST
    value: float = 100.0  # target이 at_max면 쓰지 않는다

    def area(self, window) -> tuple[int, int, int, int] | None:
        if window is None or self.area_w <= 0 or self.area_h <= 0:
            return None
        x, y = window.client_to_screen(self.area_x, self.area_y)
        return (x, y, self.area_w, self.area_h)

    @property
    def hovers(self) -> bool:
        return self.hover_x >= 0 and self.hover_y >= 0

    def describe(self) -> str:
        """사람이 읽는 한 줄. 화면과 로그가 같은 말을 쓰게 한다."""
        if self.target == NUM_AT_MAX:
            return "앞 값이 뒤 값에 닿으면"
        names = {
            NUM_CURRENT: "앞 값",
            NUM_MAX: "뒤 값",
            NUM_PERCENT: "비율(%)",
            NUM_LEFT: "남은 양(뒤 - 앞)",
        }
        how = "이상" if self.compare == NUM_AT_LEAST else "이하"
        return f"{names.get(self.target, self.target)}이 {self.value:g} {how}이면"

    def judge(self, current: int, maximum: int) -> tuple[bool, str]:
        """읽은 두 값으로 성립 여부를 낸다. (성립, 설명)."""
        if self.target == NUM_AT_MAX:
            hit = maximum > 0 and current >= maximum
            return (hit, f"{current}/{maximum}")

        if self.target == NUM_CURRENT:
            actual = float(current)
        elif self.target == NUM_MAX:
            actual = float(maximum)
        elif self.target == NUM_LEFT:
            actual = float(maximum - current)
        else:  # percent
            if maximum <= 0:
                return (False, f"{current}/{maximum} — 뒤 값이 0이라 비율을 낼 수 없습니다")
            actual = current * 100.0 / maximum

        hit = actual >= self.value if self.compare == NUM_AT_LEAST else actual <= self.value
        how = "≥" if self.compare == NUM_AT_LEAST else "≤"
        return (hit, f"{current}/{maximum} → {actual:g} {how} {self.value:g}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NumberWatch":
        obj = _coerce(cls, data)
        if obj.target not in NUM_TARGETS:
            obj.target = NUM_AT_MAX
        if obj.compare not in NUM_COMPARES:
            obj.compare = NUM_AT_LEAST
        obj.threshold = max(0, min(255, obj.threshold))
        obj.hover_wait_ms = max(0, obj.hover_wait_ms)
        return obj


@dataclass
class PixelRule:
    """점 색과 그림을 함께 보고, 조건이 성립하면 동작을 실행한다.

    한 점만 보면 게임의 애니메이션/파티클 한 프레임에 오탐이 난다. 2~4점을
    AND로 묶으면 오탐이 급격히 줄어든다.

    셋을 쓰임에 따라 골라 쓴다.
      점(points)   — 자리가 고정된 것 (체력바 색, 창이 열렸는지)
      그림(icons)  — 자리가 밀리는 것 (버프 아이콘)
      숫자(numbers) — 값 자체가 조건인 것 (피로도 10502 / 540000)
    셋을 섞어 쓸 수 있고, match_mode가 셋 모두에 함께 걸린다.
    """

    name: str = "새 조건"
    points: list[PixelPoint] = field(default_factory=list)
    icons: list[IconWatch] = field(default_factory=list)
    numbers: list[NumberWatch] = field(default_factory=list)
    tolerance: int = 12
    match_mode: str = "all"  # all = 전부 성립 / any = 하나라도 성립
    condition: str = "match"  # match = 성립할 때 / differ = 어긋났을 때
    # key = 키 입력 / click = 찾은 그림 누르기 / macro · path = 그것을 실행
    action_kind: str = "key"
    action_key: str = "Z"
    action_target: str = ""  # macro/path 이름
    check_ms: int = 300
    cooldown_ms: int = 1500
    edge_only: bool = True  # 조건이 거짓→참으로 바뀔 때만 실행
    # 이만큼 연속으로 성립해야 진짜로 본다. 화면이 한 프레임 깜빡이거나 아이콘이
    # 다시 그려지는 순간에 잘못 발동하는 것을 막는다. 1이면 예전과 같다.
    confirm_count: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["points"] = [p.to_dict() for p in self.points]
        data["icons"] = [i.to_dict() for i in self.icons]
        data["numbers"] = [n.to_dict() for n in self.numbers]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PixelRule":
        skip = {"points", "icons", "numbers"}
        obj = _coerce(cls, {k: v for k, v in data.items() if k not in skip})
        obj.points = [PixelPoint.from_dict(p) for p in data.get("points", [])]
        obj.icons = [IconWatch.from_dict(i) for i in data.get("icons", [])]
        obj.numbers = [NumberWatch.from_dict(n) for n in data.get("numbers", [])]
        obj.confirm_count = max(1, obj.confirm_count)
        return obj


# --------------------------------------------------------------------------
# 버프 아이템
# --------------------------------------------------------------------------
# 지속시간이 정해져 있는 아이템들. 새 버프를 만들 때 기본값으로 쓴다.
KNOWN_BUFFS: list[tuple[str, int]] = [
    ("직업별 왕관", 15),
    ("갈비탕", 30),
    ("경카", 60),
    ("점검사", 360),
]


@dataclass
class BuffItem:
    """주기적으로 다시 써야 하는 버프 아이템.

    남은 시간을 아는 방법이 두 가지다.

    **시간(timer)** — 쓴 시각 + 지속시간으로 계산한다. 지속시간이 고정인 아이템은
    이쪽이 가장 확실하고, 버프 아이콘이 가려져 있어도 동작한다.

    **화면(icon)** — 버프바에서 그 효과의 아이콘을 찾아 본다. 아이콘이 사라지면
    끝난 것이다. 지속시간이 들쭉날쭉하거나(중첩·감소 효과), 다른 데서 이미 걸어
    둔 버프까지 함께 챙겨야 할 때 쓴다. 대신 버프바가 가려지면 못 본다.
    """

    name: str = "새 버프"
    duration_min: int = 15  # 지속시간(분)
    # 남은 시간을 무엇으로 아는가. timer = 쓴 시각 기준 / icon = 버프바를 본다
    detect_kind: str = "timer"
    # detect_kind가 icon일 때 버프바에서 찾을 그림.
    watch: IconWatch = field(default_factory=IconWatch)
    # 아이콘이 이만큼 연속으로 안 보여야 진짜 끝난 것으로 본다. 화면이 한 프레임
    # 깜빡이거나 다른 창이 잠깐 겹쳤을 때 헛되이 다시 쓰는 것을 막는다.
    watch_confirm: int = 2
    use_kind: str = "quickslot"  # quickslot = 퀵슬롯 키 / inventory = 인벤토리 아이콘
    key: str = "5"  # quickslot일 때 누를 키
    # -- inventory 방식 --------------------------------------------------
    icon: str = ""  # 아이콘 PNG 파일 이름 (버프 폴더 기준)
    open_key: str = "I"  # 인벤토리 여는 키
    close_key: str = "I"  # 닫는 키 (같은 키로 토글하는 게임이 많다)
    open_wait_ms: int = 500  # 인벤토리가 열릴 때까지 기다릴 시간
    click_button: str = "right"  # 아이템을 쓰는 클릭 (보통 우클릭)
    tolerance: int = 30  # 아이콘 일치 허용 오차
    search_x: int = 0  # 찾을 영역 (창 기준). 폭·높이가 0이면 화면 전체
    search_y: int = 0
    search_w: int = 0
    search_h: int = 0
    # -- 런타임 상태 ------------------------------------------------------
    last_used: float = 0.0  # time.time() 기준. 앱을 껐다 켜도 남아 있어야 한다

    def remaining(self, now: float) -> float:
        """남은 시간(초). 0 이하면 다시 써야 한다."""
        if self.last_used <= 0:
            return 0.0
        return max(0.0, self.last_used + self.duration_min * 60 - now)

    def expired(self, now: float, margin_s: int = 0) -> bool:
        """margin_s는 미리 갱신할 여유. 30초를 주면 만료 30초 전에 다시 쓴다."""
        return self.remaining(now) <= margin_s

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["watch"] = self.watch.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuffItem":
        obj = _coerce(cls, {k: v for k, v in data.items() if k != "watch"})
        obj.watch = IconWatch.from_dict(data.get("watch", {}))
        if obj.detect_kind not in ("timer", "icon"):
            obj.detect_kind = "timer"
        obj.watch_confirm = max(1, obj.watch_confirm)
        return obj


# --------------------------------------------------------------------------
# 시간 예약 실행
# --------------------------------------------------------------------------
@dataclass
class ScheduledTask:
    """정해진 시각에 한 번 실행한다.

    돌아가는 매크로 한복판에 끼어들면 입력이 뒤섞이므로, 실제 실행은 **입력이 비는
    순간**을 기다렸다가 한다. 그 순간을 제한 시간 안에 못 찾으면 이번 회차는
    건너뛴다 — 억지로 끼어드는 것보다 한 번 거르는 편이 낫다.
    """

    name: str = "새 예약"
    mode: str = "hourly"  # hourly = 매시 N분 / interval = N분마다
    minute: int = 0  # hourly일 때 몇 분 (0 = 정각)
    every_minutes: int = 30  # interval일 때 주기
    action_kind: str = "macro"  # macro | path | scenario
    action_target: str = ""
    gap_wait_s: int = 60  # 입력이 빌 때까지 최대 몇 초 기다릴지
    quiet_ms: int = 150  # 이만큼 조용해야 '비었다'고 본다
    hotkey: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduledTask":
        return _coerce(cls, data)


# --------------------------------------------------------------------------
# 낚시
# --------------------------------------------------------------------------
@dataclass
class ColorSpot:
    """창 안 어느 사각형에서 **어떤 색이 몇 픽셀 이상 보이는가**.

    찌가 떴는지, 물고기를 낚는 모션이 나왔는지처럼 "지금 저게 화면에 있나"만
    알면 되는 것들에 쓴다. 그림 맞추기(IconWatch)보다 훨씬 싸다 — 색 한 가지만
    세면 되므로 한 판에 0.1ms 남짓이다.

    min_px가 핵심이다. 한 픽셀만 맞아도 있다고 하면 배경의 비슷한 색에 늘
    속는다. "이만큼은 보여야 진짜"라는 문턱을 사람이 정하게 한다.
    """

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    color: str = ""
    tol: int = 30
    min_px: int = 40

    @property
    def ready(self) -> bool:
        return self.w > 0 and self.h > 0 and bool(self.color)

    def rect(self, window) -> tuple[int, int, int, int] | None:
        """화면 절대좌표로."""
        if window is None or not self.ready:
            return None
        sx, sy = window.client_to_screen(self.x, self.y)
        return (sx, sy, self.w, self.h)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColorSpot":
        obj = _coerce(cls, data)
        obj.tol = max(1, min(150, int(obj.tol)))
        obj.min_px = max(1, int(obj.min_px))
        return obj


@dataclass
class MotionSpot:
    """창 안 어느 사각형이 **흔들리고 있는가**.

    색으로는 낚시중과 낚은 상태를 못 가른다 — 자세만 달라지고 색은 거의 같아서,
    한때 넣었다가 못 쓰고 뺐다. 하지만 **낚았을 때는 낚싯대 끝에 물고기가 매달려
    쉬지 않고 흔들린다.** 낚시중에는 그 자리가 거의 그대로다. 그러니 색이 아니라
    **바뀌는 것**을 보면 둘이 확실히 갈린다.

    물고기 종류가 여러 가지라 색도 모양도 매번 다른데, 흔들림은 종류를 안 가린다.
    그래서 빨간 글씨(ColorSpot)보다 오히려 든든한 근거다.

    **흔들림은 미세하다.** 물고기가 화면을 가로지르는 것이 아니라 매달려서 조금씩
    까딱거린다. 그래서 찍는 간격(gap_s)이 중요하다 — 너무 촘촘히 찍으면 그 사이
    움직인 폭이 작아 안 잡히고, 너무 뜸하면 흔들림이 한 바퀴 돌아 제자리에 와
    있다. 0.1초쯤이 알맞다.

    ## 문턱을 사람이 맞히게 했더니 못 맞혔다

    처음에는 "한 장에 몇 칸 넘게 바뀌면 움직임"이라는 **절대 문턱**을 사람이 재서
    넣게 했다. 그게 안 됐다. 자리마다, 물고기마다, 배경마다 값이 딴판이라 한 번
    재서 넣은 값이 다음 판에 안 맞는다. 그러면 아무리 흔들려도 그냥 못 알아본다.

    지금은 **바탕을 스스로 잰다.** 그 자리를 늘 지켜보고 있으므로, 낚시중일 때
    얼마나 잠잠한지는 저절로 알게 된다. 그 잠잠함(바탕)의 몇 배로 튀면 움직임이다.

        바탕      최근 오래도록 본 점수 중 아래쪽 (조용할 때가 어느 만큼인지)
        문턱      바탕 × rise. 자리를 옮겨도, 물고기가 달라도 저절로 따라간다
        되풀이    span_s 안에 문턱을 넘은 장이 repeats개는 나와야 한다

    마지막 겹이 핵심이다. **대롱대롱은 한 번이 아니라 되풀이다.** 창이 하나 뜨거나
    다른 캐릭터가 지나가는 것은 한 번 튀고 마는데, 매달린 물고기는 보는 내내
    까딱거린다. 되풀이를 세면 그 둘이 갈린다.
    """

    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    # 밝기가 이만큼 안쪽으로 달라진 것은 같은 것으로 본다. 화면이 조금씩
    # 어른거리는 것(그림자·반투명 연출)에 속지 않으려는 여유다. 흔들림이 미세한
    # 만큼 너무 크게 두면 그 미세함까지 함께 지워진다.
    tol: int = 16
    # 문턱을 스스로 잡을지. 끄면 min_px를 그대로 쓴다(예전 방식).
    auto: bool = True
    # 바탕의 몇 배로 튀어야 움직임으로 볼지 (auto일 때).
    rise: float = 3.0
    # span_s 안에 문턱 넘은 장이 이만큼은 나와야 "되풀이해 움직인다"고 본다.
    repeats: int = 4
    span_s: float = 1.2
    min_px: int = 25  # auto를 끈 경우의 절대 문턱
    hits: int = 3  # (옛 설정) 지금은 repeats를 쓴다
    window: int = 6  # (옛 설정)
    # 두 장 사이 간격(초). 이 사이에 움직인 만큼이 그대로 점수가 되므로, 미세한
    # 흔들림일수록 촘촘히 찍는 것이 오히려 불리하다.
    gap_s: float = 0.1
    # 한 번 "낚았다"고 센 뒤 이만큼은 다시 안 센다(초).
    cooldown_s: float = 4.0

    @property
    def ready(self) -> bool:
        return self.w > 0 and self.h > 0 and self.min_px > 0

    def rect(self, window) -> tuple[int, int, int, int] | None:
        """화면 절대좌표로."""
        if window is None or self.w <= 0 or self.h <= 0:
            return None
        sx, sy = window.client_to_screen(self.x, self.y)
        return (sx, sy, self.w, self.h)

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    @property
    def need_frames(self) -> int:
        """되풀이를 가리려면 몇 장이나 봐야 하나."""
        return max(self.repeats, int(self.span_s / max(0.02, self.gap_s)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotionSpot":
        obj = _coerce(cls, data)
        obj.tol = max(1, min(150, int(obj.tol)))
        obj.window = max(2, min(30, int(obj.window)))
        obj.hits = max(1, min(obj.window, int(obj.hits)))
        obj.rise = max(1.2, min(20.0, float(obj.rise)))
        obj.repeats = max(2, min(30, int(obj.repeats)))
        obj.span_s = max(0.2, min(10.0, float(obj.span_s)))
        obj.gap_s = max(0.02, min(1.0, float(obj.gap_s)))
        obj.cooldown_s = max(0.5, min(30.0, float(obj.cooldown_s)))
        # 넘을 수 없는 문턱은 "아무리 흔들려도 못 알아본다"는 뜻이다. 시간표시
        # 문턱에서 똑같이 데었으므로 여기서도 칸 수 안으로 접어 둔다.
        room = obj.area
        obj.min_px = max(1, int(obj.min_px))
        if room and obj.min_px > room // 2:
            obj.min_px = max(4, room // 4)
        return obj


@dataclass
class SoundCue:
    """낚시 성공 **효과음**.

    화면으로 낚음을 가리는 것이 번번이 어긋났다. 빨간 글씨는 다른 것에 가리거나
    뜨는 자리가 밀리면 못 보고, 낚싯대 흔들림은 너무 미세해서 문턱을 잡기 어려웠다.
    그런데 성공하면 **효과음이 울린다.** 소리는 가려지지도 밀리지도 미세하지도
    않다 — 게임 창이 뒤에 있어도, 다른 창이 위를 덮어도 똑같이 들린다.

    **소리 크기가 아니라 결로 가린다.** 크기만 보면 배경 음악이나 딴 효과음에
    그대로 속는다. 어느 높이의 소리가 얼마나 섞여 있는지(열두 대역의 세기)를 재서
    미리 배워 둔 것과 견준다. 결은 길이 1로 맞춰 두므로 **볼륨을 바꿔도 그대로
    알아본다.**

    문턱이 세 겹이다.

        floor  이보다 작은 소리는 아예 안 본다 (고요의 결은 잡음의 결이다)
        near   배운 결과 이만큼 닮아야 그 소리로 본다
        hits   그렇게 닮은 조각이 몇 개는 나와야 한다

    마지막 것이 중요하다. 효과음은 여러 조각(한 조각 0.04초)에 걸쳐 울리므로,
    한 조각만 닮아도 됐다고 하면 지나가는 소리에 속는다.
    """

    # 배운 결. 열두 개가 아니면 안 배운 것으로 친다.
    shape: list[float] = field(default_factory=list)
    near: float = 0.88  # 이만큼 닮으면 그 소리
    floor: float = 0.03  # 이보다 작으면 안 본다
    hits: int = 2  # 닮은 조각이 몇 개는 나와야
    cooldown_s: float = 4.0  # 한 번 세고 나서 다시 안 셀 시간
    learned_level: float = 0.0  # 배울 때 얼마나 컸는지 (참고용)

    @property
    def ready(self) -> bool:
        return len(self.shape) == 12 and any(self.shape)

    def describe(self) -> str:
        if not self.ready:
            return "안 배움"
        hz = (180, 260, 370, 520, 740, 1040,
              1460, 2050, 2880, 4050, 5000, 5700)
        top = sorted(range(12), key=lambda i: -self.shape[i])[:3]
        parts = [f"{hz[i]}Hz" for i in top if self.shape[i] > 0.05]
        return "가장 센 높이 " + " · ".join(parts or ["?"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SoundCue":
        obj = _coerce(cls, {k: v for k, v in data.items() if k != "shape"})
        raw = data.get("shape") or []
        try:
            shape = [float(v) for v in raw]
        except (TypeError, ValueError):
            shape = []
        obj.shape = shape if len(shape) == 12 else []
        obj.near = max(0.3, min(0.999, float(obj.near)))
        obj.floor = max(0.0, min(0.9, float(obj.floor)))
        obj.hits = max(1, min(30, int(obj.hits)))
        obj.cooldown_s = max(0.5, min(30.0, float(obj.cooldown_s)))
        return obj


@dataclass
class FishingSetup:
    """낚시 미니게임 설정.

    **미니게임 창은 늘 같은 자리에 뜬다.** 그래서 판의 위치와 그 안에서 무엇을
    어디서 볼지 한 번 정해 두면 매번 찾을 필요가 없다. 매 판마다 찾는다면 화면을
    통째로 훑어야 하고, 그건 6ms짜리 캡처를 몇 배로 늘린다.

    좌표는 두 기준이 섞여 있다.

      board_*  : **게임 창** 기준 — 미니게임 판이 창 안 어디에 뜨는가
      track_*  : **판** 기준 — 판 안 어느 자리를 볼 것인가
      click_*  : **게임 창** 기준 — 어디를 눌러도 되는가
      tap_*    : **게임 창** 기준 — 낚시중에 되풀이해 누를 자리 (머리 위)
      notice   : **게임 창** 기준 — 낚시 성공 알림이 뜨는 자리 (왼쪽 위)

    **한 줄이 아니라 띠(band)로 본다.** 처음에는 y 한 줄만 훑었는데, 그러면
    사람이 그 한 줄을 정확히 짚어야 하고 물고기처럼 속이 빈 그림은 줄 하나에
    아무것도 안 걸리는 일이 생긴다. 몇 줄을 함께 보면 훨씬 잘 잡히고, 열 줄을
    더 봐도 1ms가 안 든다 (캡처 6ms에 비하면 없는 셈이다).

    클릭은 판 밖 아무 데나 해도 되므로 사각형으로 받아 **그 안에서 무작위로**
    고른다. 늘 같은 한 점을 누르면 사람이 아닌 티가 나고, 하필 그 자리에 다른
    UI가 겹치면 통째로 망가진다.
    """

    # -- 미니게임 판 (창 기준) --------------------------------------------
    board_x: int = 0
    board_y: int = 0
    board_w: int = 0
    board_h: int = 0

    # -- 트랙: 막대와 물고기가 **오가는 사각형** (판 기준) -----------------
    #
    # 이것은 물체가 지금 있는 자리가 아니라 **왔다 갔다 하는 범위**다. 둘 다
    # 이 안에서 좌우로 움직이므로 가로 범위는 둘이 함께 쓴다.
    track_x0: int = 0
    track_x1: int = 0
    track_y0: int = 0
    track_y1: int = 0

    # 세로 범위는 **따로** 갖는다. 막대는 트랙 높이를 꽉 채우고 물고기는 가운데
    # 조금만 차지하는 식으로 생김새가 다르다. 하나로 묶어 두었더니 나중에 잡은
    # 쪽이 앞엣것을 덮어써서, 막대를 잡으면 물고기 설정이 사라졌다.
    # 0이면 트랙 전체 높이를 쓴다.
    bar_y0: int = 0
    bar_y1: int = 0
    fish_y0: int = 0
    fish_y1: int = 0

    bar_color: str = ""  # 노란 막대 #rrggbb
    bar_tol: int = 30
    fish_color: str = ""  # 물고기 #rrggbb
    fish_tol: int = 30
    # 색이 이만큼은 보여야 "찾았다"고 한다. 한두 픽셀이면 배경에 속은 것이다.
    track_min_px: int = 8

    # -- 물고기 체력 게이지 (판 기준). 자리가 고정이다 ---------------------
    health_x0: int = 0
    health_x1: int = 0
    health_y0: int = 0
    health_y1: int = 0
    health_color: str = ""  # 남아 있는 부분의 색 #rrggbb
    health_tol: int = 30
    # 창이 갑자기 닫혔을 때, 체력이 이 비율 아래였으면 깬 것으로 본다.
    # 마지막 한 방과 창이 닫히는 사이에 화면을 못 읽고 지나갈 수 있다.
    clear_ratio: float = 0.15

    # -- 남은 시간 (판 기준). 숫자를 읽지는 않고 **보이는지**만 본다 -------
    time_x0: int = 0
    time_x1: int = 0
    time_y0: int = 0
    time_y1: int = 0
    time_color: str = ""
    time_tol: int = 30
    time_min_px: int = 20

    # -- 클릭 범위 (창 기준). 이 사각형 안 아무 데나 --------------------
    click_x: int = 0
    click_y: int = 0
    click_w: int = 0
    click_h: int = 0
    click_button: str = "left"
    # 한 번 누를 때 버튼을 붙잡고 있는 시간(ms).
    #
    # 겹쳐 있는 동안에는 많이 누를수록 체력이 빨리 깎이는데, 오래 붙잡고 있으면
    # 그만큼 덜 누르게 된다. 12ms로 두었더니 90ms짜리 겹침에 일곱 번이 한계였다.
    # 너무 짧으면 게임이 클릭을 놓칠 수 있으니, 명중률을 보며 줄여 가면 된다.
    click_hold_ms: float = 4.0
    # 미니게임에서 **겹쳤을 때** 클릭하는 빠르기 배율. 1이면 지금 그대로,
    # 1.2면 1.2배, 2면 2배 빠르게 누른다(fishtask.LiveBoard.click_plan).
    overlap_speed: float = 1.0

    # -- 판정 -------------------------------------------------------------
    #
    # **물고기 크기는 미니게임마다 다르다.** 그래서 겹쳤다고 볼 거리를 고정값으로
    # 두면 어떤 판에서는 너무 좁고 어떤 판에서는 너무 넓다. 기본은 화면에서 잰
    # 두 물체의 폭에서 뽑아 쓴다.
    hit_mode: str = "auto"  # auto = 잰 폭에서 / manual = hit_px 그대로
    # 가장자리가 맞닿는 거리의 몇 배까지 겹쳤다고 볼지.
    #
    # 1.0 = **닿기만 하면 겹친 것으로 본다.** 게임도 그렇게 판정한다.
    #
    # 처음에는 0.8로 두어 안전 여유를 뒀는데, 물체가 빠를 때 손해가 컸다. 겹쳐
    # 있는 시간이 그만큼 짧아지는데 그중 20%를 스스로 버리는 셈이기 때문이다.
    # 속도를 1~4배로 올려 가며 재 보니 (클리어율)
    #
    #     비율 0.8 → 100% · 85% · 47% · 29%
    #     비율 1.0 → 100% · 99% · 80% · 81%
    #
    # 그러면서 헛클릭은 모든 속도에서 0%였다. **눈으로 본 겹침만 누르기** 때문에
    # 판정선에 바짝 붙여도 헛클릭이 안 는다. 1.1로 넘기면 그때부터 는다.
    hit_ratio: float = 1.0
    hit_px: float = 10.0  # manual일 때, 또는 아직 폭을 못 쟀을 때

    limit_s: float = 30.0  # 한 판 제한 시간

    # -- 낚시 흐름 --------------------------------------------------------
    cast_key: str = "ctrl"  # 던지는 키
    bite_wait_s: float = 40.0  # 던지고 미니게임이 뜰 때까지 최대 대기
    rest_s: float = 1.5  # 한 판 끝나고 다시 던지기까지
    # -- 낚시중에 되풀이해 누를 자리 (창 기준). 캐릭터 머리 위 -------------
    #
    # 찌를 알아보고 그때만 누르려 했지만, 찌는 작고 잠깐 떠서 놓치기 일쑤였다.
    # **보이든 안 보이든 그 자리를 계속 두드리는 편**이 훨씬 잘 걸린다 —
    # 헛클릭은 아무 해가 없고, 미니게임이 뜨면 그때 멈추면 된다.
    tap_x: int = 0
    tap_y: int = 0
    tap_w: int = 0
    tap_h: int = 0
    # 누르는 간격(초). 이 사이에서 무작위로 고른다 — 딱 떨어지는 간격으로
    # 두드리면 사람이 아닌 티가 난다.
    tap_min_s: float = 0.1
    tap_max_s: float = 0.3
    # 두드리기만 이만큼 이어지면 다시 던진다(초). 0이면 안 끊는다.
    #
    # 낚음을 알아보는 세 근거가 다 어긋나면 이미 낚아 놓고도 계속 두드리게 된다.
    # 그 상태는 **아무 일도 안 일어나므로 스스로 빠져나올 길이 없고**, 예전에는
    # 입질 대기(기본 40초)가 다 지나야 풀렸다. 그 40초가 고스란히 낭비였다.
    #
    # 미니게임이 떠 있는 동안은 이 시간을 세지 않는다 — 판을 푸는 중이지
    # 두드리는 중이 아니다.
    tap_limit_s: float = 5.0

    # -- 버프 -------------------------------------------------------------
    #
    # 낚시에 걸어 두는 버프가 둘이고, 유지 시간이 서로 다르다. 처음 한 번 걸고,
    # 만료될 때마다 다시 걸어야 한다.
    #
    #     처음      [1] → [7] →(1초)→ [8] → [0]×23
    #     다시 걸 때 [1] → [만료된 버프키] → [0]×N → [6] → [ctrl]
    #
    # **만료되자마자 걸지 않는다.** 낚시 도중에 끼어들면 그 판이 날아가므로,
    # 다음에 한 마리 낚을 때까지 기다렸다가 그 틈에 건다.
    #
    # 0키 횟수가 버프마다 다른 것은 그 버프가 쓰는 물건 자리가 다르기 때문이다.
    # 처음에 23번인 것은 두 몫(4 + 19)을 한 번에 하기 때문이다.
    buff_mode: bool = False
    # 버프를 걸기 전에 게임 창 한복판을 한 번 누를지.
    #
    # 키를 보내려면 게임 창이 입력을 받고 있어야 한다. 다른 창을 만지다 시작하면
    # 첫 키 몇 개가 그냥 흘러가고, 그러면 버프가 안 걸린 채로 낚시가 돈다.
    buff_center_click: bool = True
    buff_pre_key: str = "1"  # 버프를 걸기 전에 먼저 누르는 키
    buff_zero_key: str = "0"
    buff_rod_key: str = "6"  # 낚싯대를 다시 든다
    buff_open_zeros: int = 23  # 처음 걸 때
    buff_open_gap_s: float = 1.0  # 버프와 버프 사이
    buff_zero_gap_s: float = 0.1  # 0키를 누르는 간격
    # 유지 시간은 **초**로 둔다. 분으로만 두면 "15분 기준으로 초 단위 조절"을
    # 할 수 없다 — 게임마다 몇 초씩 다르고, 그 몇 초가 쌓이면 버프가 끊긴다.
    buff_a_key: str = "7"
    buff_a_sec: float = 180.0  # 3분
    buff_a_zeros: int = 4
    buff_b_key: str = "8"
    buff_b_sec: float = 600.0  # 10분
    buff_b_zeros: int = 19
    buff_c_key: str = "9"
    buff_c_sec: float = 900.0  # 15분
    buff_c_zeros: int = 0
    # 버프 **중첩 알림** (창 기준). "지금 적용 중인 낚시꾼의 왕관 효과를 …로 바꿀게요.
    # 사용하시겠어요?" — 아직 켜져 있는 버프를 또 쓰면 뜨는 창이다. 이 창이 떠 있으면
    # 뒤따르는 키가 전부 막혀 낚시가 멈춘다. 그래서 뜨면 닫는 키를 **한 번** 누른다.
    #
    # 무조건 누르지 않고 **보일 때만** 누른다. 아무 창도 없을 때 [Esc]를 누르면
    # 게임 메뉴가 열려 오히려 입력이 막힐 수 있다.
    stack_popup: ColorSpot = field(default_factory=lambda: ColorSpot(min_px=40))
    stack_close_key: str = "Esc"
    # 버프 키를 누른 뒤 알림이 뜨는지 지켜볼 시간(초). 창은 조금 늦게 뜬다.
    stack_wait_s: float = 0.5

    # -- 피로도 확인 -------------------------------------------------------
    #
    # 피로도가 가득 차면 낚아도 얻는 것이 없다. **낚음 N마리마다** 피로도 조건([조건]
    # 탭에서 만든 것 — 숫자 읽기 "앞 값이 뒤 값에 닿으면")을 확인하고, 찼으면 정해
    # 둔 매크로를 **한 번** 돌린 뒤 다시 던진다.
    #
    # 조건을 여기 따로 만들지 않고 [조건] 탭의 것을 이름으로 가져다 쓴다. 숫자 글꼴,
    # 커서 올릴 자리, 읽을 영역을 이미 거기서 맞추고 시험해 볼 수 있기 때문이다.
    fatigue_mode: bool = False
    fatigue_every: int = 10  # 낚음 몇 마리마다 확인할지
    fatigue_rule: str = ""  # [조건] 탭의 조건 이름
    fatigue_macro: str = ""  # 다 찼을 때 한 번 돌릴 매크로 이름
    # 0보다 크면 **가득 차기를 기다리지 않고** 앞 값이 이 수를 넘는 순간 매크로를
    # 돌린다. 게임에서 피로도를 일부러 꽉 채워 보기는 어려워 시험이 안 된다.
    fatigue_over: float = 0.0

    # -- 낚시가 멎었을 때 되살리기 -----------------------------------------
    # 이만큼 동안 한 마리도 못 낚으면 **낚시중이 아니게 된 것**으로 본다. 손에
    # 낚싯대가 아닌 것을 들었거나, 초대·거래 같은 신청 창이 떠서 키가 안 먹는
    # 경우다. [Esc]를 몇 번 눌러 창을 닫고, 낚싯대를 다시 들고, 다시 던진다.
    dry_s: float = 30.0  # 0이면 안 함
    dry_esc_times: int = 5
    dry_rod_key: str = "6"  # 비우면 안 누름

    # -- 얼음낚시 ---------------------------------------------------------
    #
    # 낚시터가 두 군데다. 일반 낚시터는 던져 놓고 기다리면 되지만, **얼음낚시터는
    # 땅이 다시 언다.** 얼면 낚시가 안 되므로 때맞춰 다시 파야 하는데, 파는 동안은
    # 낚시가 끊기므로 파고 나서 다시 던져야 한다.
    #
    # 손놀림은 이렇다.
    #
    #     [5] 삽을 든다
    #     [ctrl] 내리친다 × 몇 번   ← 한 번으로는 안 뚫린다
    #     [6] 낚싯대로 바꾼다
    #     [ctrl] 던진다             ← 여기서부터 다시 낚시
    #
    # **처음 뚫는 자리는 한 번 더 내리쳐야 한다.** 이미 뚫었던 자리는 얼어붙은
    # 것만 깨면 되므로 덜 친다.
    ice_mode: bool = False
    ice_every_s: float = 300.0  # 몇 초마다 팔지 (1초 눈금)
    ice_dig_key: str = "5"  # 삽
    ice_hit_key: str = "ctrl"  # 내리치는 키
    ice_hits: int = 2  # 이미 뚫었던 자리
    ice_first_hits: int = 3  # 처음 뚫는 자리
    ice_back_key: str = "6"  # 낚싯대
    # 한 번 내리칠 때 키를 붙잡고 있는 시간(초). 이 사이에서 무작위.
    ice_hold_min_s: float = 0.1
    ice_hold_max_s: float = 3.0
    # 내리침과 내리침 사이(초). 이 사이에서 무작위.
    ice_press_min_s: float = 1.0
    ice_press_max_s: float = 2.0
    ice_gap_s: float = 0.35  # 도구를 바꾸고 나서 쉬는 시간

    # -- 낚시 성공 알림 (창 기준). 왼쪽 위에 뜨는 빨간 글씨 ------------------
    #
    # "○○ 떡밥 1개가 차감됐어요." 떡밥 종류가 많아 글자는 매번 다르지만
    # **색은 늘 같다.** 그래서 여기서는 글자를 읽지 않고 그 색이 몇 칸 보이는지만
    # 센다. 이 글씨가 뜨면 = 경험치를 얻었고 = 한 마리 낚았고 = 다시 던질 때다.
    notice: ColorSpot = field(default_factory=lambda: ColorSpot(min_px=30))
    # 한 번 세고 나서 이만큼은 다시 안 센다(초). 글씨가 몇 초 떠 있기 때문이다.
    notice_cooldown_s: float = 3.0
    # 알림을 보면 이 키를 눌러 다시 낚시로 돌아간다. 비우면 던지는 키를 쓴다.
    resume_key: str = ""

    # -- 낚은 자세 (창 기준). 낚싯대에 매달린 물고기가 흔들리는 자리 --------
    #
    # 빨간 글씨만으로는 놓치는 판이 있었다. 글씨가 다른 것에 가리거나, 색이
    # 조금 달라지거나, 뜨는 자리가 밀리면 그대로 못 본다. 그러면 이미 낚았는데도
    # 계속 머리 위만 두드리고 있게 된다.
    #
    # 흔들림은 그런 것에 안 걸린다. 낚았으면 물고기가 매달려 흔들리고, 안 낚았으면
    # 안 흔들린다. 둘 중 **하나만 서도 낚은 것으로 본다.**
    catch_motion: MotionSpot = field(default_factory=MotionSpot)

    # -- 낚시 성공 효과음 --------------------------------------------------
    #
    # 셋 중 **가장 든든한 근거**다. 화면에 기대지 않으므로 창이 가려도, 자리가
    # 밀려도, 물고기가 하필 멈춰도 상관없다.
    catch_sound: SoundCue = field(default_factory=SoundCue)

    # -- 클릭 소리 (미니게임 도중) -----------------------------------------
    #
    # 겹쳤을 때 누르면 나는 소리(맞음)와 안 겹쳤을 때 누르면 나는 소리(빗나감)가
    # 따로 있다. 둘 중 **어느 쪽이든 들렸다면 게임이 클릭을 받은 것**이다.
    #
    # 화면만 보고는 "우리가 클릭을 안 보냈다"와 "보냈는데 게임이 안 받았다"를
    # 가를 수 없다. 체력이 안 준 것은 둘 다 똑같기 때문이다. 소리는 그 둘을 가른다 —
    # 보낸 클릭은 수십 번인데 소리가 한 번도 안 났다면 입력이 막힌 것이다.
    # 클릭 소리는 짧다(한 조각 0.04초 남짓). 조각 두 개를 요구하면 못 셀 수 있다.
    hit_sound: SoundCue = field(default_factory=lambda: SoundCue(hits=1))
    miss_sound: SoundCue = field(default_factory=lambda: SoundCue(hits=1))

    # -- 스스로 배운 것 (판을 넘겨 이어 간다) ------------------------------
    lead_ms: float = 0.0
    lead_stats: dict[str, list[int]] = field(default_factory=dict)
    # 겹쳤다고 볼 거리를 잰 폭의 몇 배로 잡을지 — 눌러 보고 배운다.
    #
    # 잰 그림 폭대로(1.0) 잡으면 게임이 맞다고 치는 자리보다 훨씬 넓을 수 있고,
    # 넓은 만큼이 고스란히 빗나감이 되어 깎아 둔 체력을 도로 채워 준다.
    learn_hit: bool = True
    # 돌아가는 동안 있었던 일을 파일로 남길지. 무엇이 낚음 주기를 줄이는지
    # 나중에 견줘 보려면 재 둔 것이 있어야 한다.
    keep_log: bool = True
    ratio_stats: dict[str, list[int]] = field(default_factory=dict)
    rounds: int = 0
    clears: int = 0
    caught: int = 0

    # -- 쓸 수 있는 상태인가 ----------------------------------------------
    def problems(self) -> list[str]:
        """아직 못 정한 것들. 비어 있으면 돌릴 수 있다."""
        missing = []
        if self.board_w <= 0 or self.board_h <= 0:
            missing.append("미니게임 판 영역")
        if self.track_x1 <= self.track_x0 or self.track_y1 <= self.track_y0:
            missing.append("움직이는 범위")
        if not self.bar_color:
            missing.append("막대 색")
        if not self.fish_color:
            missing.append("물고기 색")
        if not self.health_color or self.health_x1 <= self.health_x0:
            missing.append("체력 게이지")
        if self.click_w <= 0 or self.click_h <= 0:
            missing.append("클릭 범위")
        return missing

    @property
    def can_tell_caught(self) -> bool:
        """낚았는지 알아볼 길이 하나라도 있는가."""
        return (self.notice.ready or self.catch_motion.ready
                or self.catch_sound.ready)

    @property
    def ready(self) -> bool:
        return not self.problems()

    def extras(self) -> list[str]:
        """없어도 돌아가지만 있으면 좋은 것들 중 아직 안 정한 것."""
        out = []
        if not self.time_color:
            out.append("남은 시간")
        if self.tap_w <= 0 or self.tap_h <= 0:
            out.append("연타할 자리")
        if not self.notice.ready:
            out.append("성공 알림")
        if not self.catch_motion.ready:
            out.append("낚은 자세 (흔들림)")
        if not self.catch_sound.ready:
            out.append("성공 효과음")
        return out

    def buffs(self) -> list[tuple[str, str, float, int]]:
        """걸어야 할 버프들. (이름, 키, 유지 초, 0키 횟수)

        키를 비운 것은 안 쓴다. 그래서 셋 중 둘만 쓰거나 하나만 쓸 수도 있다.
        """
        out = []
        for name, key, span, zeros in (
            ("A", self.buff_a_key, self.buff_a_sec, self.buff_a_zeros),
            ("B", self.buff_b_key, self.buff_b_sec, self.buff_b_zeros),
            ("C", self.buff_c_key, self.buff_c_sec, self.buff_c_zeros),
        ):
            if key:
                out.append((name, key, max(1.0, float(span)), int(zeros)))
        return out

    @property
    def buff_ready(self) -> bool:
        return self.buff_mode and bool(self.buffs()) and bool(self.buff_pre_key)

    def buff_story(self) -> str:
        """무엇을 어떤 차례로 하는지 한 줄로."""
        first = " → ".join(
            [f"[{self.buff_pre_key}]"]
            + [f"[{k}]" for _n, k, _s, _z in self.buffs()]
            + [f"[{self.buff_zero_key}]×{self.buff_open_zeros}"])
        again = " / ".join(
            f"[{k}]→[{self.buff_zero_key}]×{z} ({s:g}초)"
            for _n, k, s, z in self.buffs())
        return f"처음 {first}  ·  다시 걸 때 [{self.buff_pre_key}]→{again}"

    def ice_hold(self, rng=None) -> float:
        """한 번 내리칠 때 붙잡고 있을 시간."""
        import random

        return (rng or random).uniform(self.ice_hold_min_s,
                                       self.ice_hold_max_s)

    def ice_press_gap(self, rng=None) -> float:
        """내리침과 내리침 사이."""
        import random

        return (rng or random).uniform(self.ice_press_min_s,
                                       self.ice_press_max_s)

    def ice_hit_count(self, first: bool) -> int:
        """몇 번 내리쳐야 뚫리나."""
        return self.ice_first_hits if first else self.ice_hits

    def ice_story(self, first: bool = False) -> str:
        """무엇을 어떤 차례로 하는지 한 줄로."""
        n = self.ice_hit_count(first)
        return (f"[{self.ice_dig_key}] → [{self.ice_hit_key}]×{n} → "
                f"[{self.ice_back_key}] → [{self.back_key}]")

    @property
    def ice_ready(self) -> bool:
        return (self.ice_mode and self.ice_every_s > 0
                and bool(self.ice_dig_key) and bool(self.ice_hit_key))

    @property
    def back_key(self) -> str:
        """낚은 자세에서 다시 낚시로 돌아갈 때 누를 키."""
        return self.resume_key or self.cast_key

    # -- 좌표 --------------------------------------------------------------
    def board_rect(self, window) -> tuple[int, int, int, int] | None:
        """판을 화면 절대좌표로."""
        if window is None or self.board_w <= 0 or self.board_h <= 0:
            return None
        x, y = window.client_to_screen(self.board_x, self.board_y)
        return (x, y, self.board_w, self.board_h)

    def track_box(self) -> tuple[int, int, int, int]:
        """막대와 물고기가 오가는 사각형."""
        return (self.track_x0, self.track_x1, self.track_y0, self.track_y1)

    def _moving_box(self, y0: int, y1: int) -> tuple[int, int, int, int]:
        """가로는 트랙 전체, 세로는 그 물체 몫. 안 정했으면 트랙 높이 그대로.

        가로를 물체가 지금 서 있는 자리로 좁히면 **반대편으로 간 순간 놓친다.**
        움직이는 것을 찾을 때는 늘 오가는 범위 전체를 봐야 한다.
        """
        if y1 <= y0:
            y0, y1 = self.track_y0, self.track_y1
        return (self.track_x0, self.track_x1, y0, y1)

    def bar_box(self) -> tuple[int, int, int, int]:
        return self._moving_box(self.bar_y0, self.bar_y1)

    def fish_box(self) -> tuple[int, int, int, int]:
        return self._moving_box(self.fish_y0, self.fish_y1)

    def health_box(self) -> tuple[int, int, int, int]:
        return (self.health_x0, self.health_x1, self.health_y0, self.health_y1)

    def time_box(self) -> tuple[int, int, int, int]:
        return (self.time_x0, self.time_x1, self.time_y0, self.time_y1)

    @property
    def health_span(self) -> int:
        """체력 게이지의 **전체** 길이. 남은 길이를 이걸로 나눠 비율을 낸다."""
        return max(1, self.health_x1 - self.health_x0)

    def tap_point(self, window, rng=None) -> tuple[int, int] | None:
        """연타할 자리 안에서 무작위로 고른 (창 기준, 화면 절대) 좌표."""
        if window is None or self.tap_w <= 0 or self.tap_h <= 0:
            return None
        import random

        pick = rng or random
        cx = self.tap_x + pick.randrange(self.tap_w)
        cy = self.tap_y + pick.randrange(self.tap_h)
        return ((cx, cy), window.client_to_screen(cx, cy))

    def tap_gap(self, rng=None) -> float:
        """다음 연타까지 쉴 시간(초)."""
        import random

        lo, hi = sorted((max(0.02, self.tap_min_s), max(0.02, self.tap_max_s)))
        return (rng or random).uniform(lo, hi)

    def click_point(self, window, rng=None) -> tuple[int, int] | None:
        """클릭 범위 안에서 무작위로 고른 화면 절대좌표."""
        if window is None or self.click_w <= 0 or self.click_h <= 0:
            return None
        import random

        pick = rng or random
        cx = self.click_x + pick.randrange(self.click_w)
        cy = self.click_y + pick.randrange(self.click_h)
        return window.client_to_screen(cx, cy)

    @property
    def clear_rate(self) -> float:
        return self.clears / self.rounds if self.rounds else 0.0

    @property
    def catch_rate(self) -> float:
        return self.caught / self.rounds if self.rounds else 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notice"] = self.notice.to_dict()
        data["stack_popup"] = self.stack_popup.to_dict()
        data["catch_motion"] = self.catch_motion.to_dict()
        data["catch_sound"] = self.catch_sound.to_dict()
        data["hit_sound"] = self.hit_sound.to_dict()
        data["miss_sound"] = self.miss_sound.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FishingSetup":
        skip = {"lead_stats", "ratio_stats", "bobber", "catch", "pose",
                "notice", "catch_motion", "catch_sound", "hit_sound",
                "miss_sound", "stack_popup"}
        obj = _coerce(cls, {k: v for k, v in data.items() if k not in skip})
        stats = data.get("lead_stats") or {}
        # JSON은 키가 문자열이라 그대로 두고, 쓰는 쪽에서 float로 읽는다.
        obj.lead_stats = {
            str(k): [int(v[0]), int(v[1])]
            for k, v in stats.items()
            if isinstance(v, (list, tuple)) and len(v) == 2
        }
        got = data.get("ratio_stats") or {}
        # 배수 성적은 [깎은 체력, 쓴 ms, 써 본 횟수] 세 칸이다. 예전에는 두 칸짜리만
        # 받아서, 저장해 둔 배수 성적이 **다시 켤 때마다 통째로 버려졌다.**
        obj.ratio_stats = {
            str(k): [int(x) for x in v]
            for k, v in got.items()
            if isinstance(v, (list, tuple)) and len(v) in (2, 3)
        }
        obj.notice = ColorSpot.from_dict(data.get("notice", {}))
        if obj.notice.min_px <= 1:
            obj.notice.min_px = 30
        obj.stack_popup = ColorSpot.from_dict(data.get("stack_popup") or {"min_px": 40})
        obj.stack_close_key = (obj.stack_close_key or "Esc").strip() or "Esc"
        obj.stack_wait_s = max(0.1, min(3.0, float(obj.stack_wait_s)))
        obj.fatigue_every = max(1, min(1000, int(obj.fatigue_every)))
        obj.fatigue_rule = str(obj.fatigue_rule or "").strip()
        obj.fatigue_macro = str(obj.fatigue_macro or "").strip()
        obj.fatigue_over = max(0.0, float(obj.fatigue_over or 0.0))
        obj.dry_s = max(0.0, min(600.0, float(obj.dry_s or 0.0)))
        obj.dry_esc_times = max(0, min(20, int(obj.dry_esc_times or 0)))
        obj.dry_rod_key = str(obj.dry_rod_key or "").strip()
        obj.catch_motion = MotionSpot.from_dict(data.get("catch_motion", {}))
        obj.catch_sound = SoundCue.from_dict(data.get("catch_sound", {}))
        obj.hit_sound = SoundCue.from_dict(data.get("hit_sound") or {"hits": 1})
        obj.miss_sound = SoundCue.from_dict(data.get("miss_sound") or {"hits": 1})
        # 찌를 알아보던 시절의 자리는 그대로 연타할 자리로 물려받는다.
        # 어차피 캐릭터 머리 위, 같은 곳이다.
        old = data.get("bobber", {}) or {}
        if obj.tap_w <= 0 and old.get("area_w"):
            obj.tap_x = int(old.get("area_x", 0) or 0)
            obj.tap_y = int(old.get("area_y", 0) or 0)
            obj.tap_w = int(old.get("area_w", 0) or 0)
            obj.tap_h = int(old.get("area_h", 0) or 0)
        elif obj.tap_w <= 0 and old.get("w"):
            obj.tap_x = int(old.get("x", 0) or 0)
            obj.tap_y = int(old.get("y", 0) or 0)
            obj.tap_w = int(old.get("w", 0) or 0)
            obj.tap_h = int(old.get("h", 0) or 0)

        # 예전에는 y 한 줄만 봤다. 그 줄을 띠의 시작으로 삼고 몇 줄 넓혀 둔다 —
        # 한 줄짜리 띠로 옮기면 예전만큼도 안 잡히는 자리가 생긴다.
        if obj.track_y1 <= obj.track_y0 and "track_row" in data:
            row = int(data.get("track_row") or 0)
            obj.track_y0, obj.track_y1 = max(0, row - 4), row + 5
        if obj.health_y1 <= obj.health_y0 and "health_row" in data:
            row = int(data.get("health_row") or 0)
            obj.health_y0, obj.health_y1 = max(0, row - 2), row + 3
        # 색 허용차가 하나였던 시절의 값을 세 갈래로 나눠 준다.
        if "color_tol" in data and "bar_tol" not in data:
            shared = max(1, min(150, int(data.get("color_tol") or 30)))
            obj.bar_tol = obj.fish_tol = obj.health_tol = obj.time_tol = shared

        if obj.click_button not in ("left", "right"):
            obj.click_button = "left"
        obj.tap_min_s = max(0.02, min(5.0, float(obj.tap_min_s)))
        obj.tap_max_s = max(obj.tap_min_s, min(5.0, float(obj.tap_max_s)))
        # 0은 "안 끊음"이므로 그대로 둔다. 그 밖에는 0.1초 눈금으로 맞춘다.
        limit = max(0.0, min(600.0, float(obj.tap_limit_s)))
        obj.tap_limit_s = round(limit, 1)
        # 땅 파는 주기는 1초 눈금. 0이면 안 판다.
        every = max(0.0, min(36000.0, float(obj.ice_every_s)))
        obj.ice_every_s = float(round(every))
        obj.ice_gap_s = max(0.05, min(3.0, float(obj.ice_gap_s)))
        obj.buff_open_zeros = max(0, min(200, int(obj.buff_open_zeros)))
        obj.buff_a_zeros = max(0, min(200, int(obj.buff_a_zeros)))
        obj.buff_b_zeros = max(0, min(200, int(obj.buff_b_zeros)))
        obj.buff_c_zeros = max(0, min(200, int(obj.buff_c_zeros)))
        # 유지 시간은 1초 눈금. 옛 프로필은 분으로 적혀 있으니 옮겨 준다.
        for slot, old_min in (("a", 3.0), ("b", 10.0), ("c", 15.0)):
            legacy = data.get(f"buff_{slot}_min")
            if legacy is not None and f"buff_{slot}_sec" not in data:
                setattr(obj, f"buff_{slot}_sec", float(legacy) * 60.0)
            span = getattr(obj, f"buff_{slot}_sec")
            setattr(obj, f"buff_{slot}_sec",
                    float(round(max(1.0, min(36000.0, float(span))))))
        obj.buff_open_gap_s = max(0.05, min(10.0, float(obj.buff_open_gap_s)))
        obj.buff_zero_gap_s = max(0.02, min(3.0, float(obj.buff_zero_gap_s)))
        obj.ice_hits = max(1, min(20, int(obj.ice_hits)))
        obj.ice_first_hits = max(1, min(20, int(obj.ice_first_hits)))
        obj.ice_hold_min_s = max(0.02, min(10.0, float(obj.ice_hold_min_s)))
        obj.ice_hold_max_s = max(obj.ice_hold_min_s,
                                 min(10.0, float(obj.ice_hold_max_s)))
        obj.ice_press_min_s = max(0.02, min(10.0, float(obj.ice_press_min_s)))
        obj.ice_press_max_s = max(obj.ice_press_min_s,
                                  min(10.0, float(obj.ice_press_max_s)))
        # 예전에는 키 차례를 글로 적었다. 그 설정이 있으면 삽과 낚싯대만 물려받는다.
        old_keys = data.get("ice_keys")
        if isinstance(old_keys, str) and old_keys.strip():
            parts = [t.strip() for t in old_keys.split(",") if t.strip()]
            if len(parts) >= 3:
                obj.ice_dig_key = parts[0]
                obj.ice_back_key = parts[-2]
        obj.notice_cooldown_s = max(0.5, min(30.0, float(obj.notice_cooldown_s)))
        # 세로 범위가 트랙 밖으로 나가 있으면 뜻이 없다. 트랙 안으로 접어 둔다.
        for lo, hi in (("bar_y0", "bar_y1"), ("fish_y0", "fish_y1")):
            y0, y1 = getattr(obj, lo), getattr(obj, hi)
            if y1 > y0 and obj.track_y1 > obj.track_y0:
                setattr(obj, lo, max(y0, obj.track_y0))
                setattr(obj, hi, min(y1, obj.track_y1))
                if getattr(obj, hi) <= getattr(obj, lo):
                    setattr(obj, lo, 0)
                    setattr(obj, hi, 0)
        for name in ("bar_tol", "fish_tol", "health_tol", "time_tol"):
            setattr(obj, name, max(1, min(150, int(getattr(obj, name)))))
        obj.track_min_px = max(1, int(obj.track_min_px))
        # 문턱은 그 영역이 가진 칸 수를 넘을 수 없다. 넘으면 **아무리 잘 보여도
        # 못 봤다고 하게 되고**, 미니게임이 영원히 인식되지 않는다. 실제로
        # 4006(영역은 3344칸)이 저장돼 있어서 낚시가 두드리기만 하고 있었다.
        obj.time_min_px = max(1, int(obj.time_min_px))
        room = max(0, obj.time_x1 - obj.time_x0) * max(0, obj.time_y1 - obj.time_y0)
        if room and obj.time_min_px > room // 2:
            obj.time_min_px = max(4, room // 4)
        if obj.hit_mode not in ("auto", "manual"):
            obj.hit_mode = "auto"
        obj.hit_ratio = max(0.1, min(2.0, float(obj.hit_ratio)))
        obj.hit_px = max(1.0, min(200.0, float(obj.hit_px)))
        obj.click_hold_ms = max(0.0, min(60.0, float(obj.click_hold_ms)))
        # 3배를 넘으면 누름이 바닥(8ms)에 닿아 더 빨라지지 않는다 — 칸도 거기까지만.
        obj.overlap_speed = max(0.5, min(3.0, float(obj.overlap_speed or 1.0)))
        obj.limit_s = max(3.0, min(180.0, float(obj.limit_s)))
        obj.clear_ratio = max(0.0, min(0.5, float(obj.clear_ratio)))
        return obj


@dataclass
class LumberSetup:
    """벌목 설정 — **걷는 시간**으로 자리를 셈한다.

    나무 26그루가 같은 간격으로 서 있으므로, 자리에서 자리까지 걷는 시간만 알면
    된다. 그 시간은 [가르치기]로 배운다(z9/lumber.py).
    """

    walk_key: str = "Left"   # 훑어 가는 쪽 (포탈에서 반대쪽으로)
    home_key: str = "Right"  # 끝까지 갔다가 되돌아오는 쪽
    chop_key: str = "Ctrl"

    teaching: bool = True    # 켜면 [벌목 시작]이 '가르치기'로 돈다

    try_s: float = 1.6       # 눌러 보고 데미지를 기다리는 시간
    quiet_s: float = 1.3     # 데미지가 이만큼 안 뜨면 다 벤 것
    chop_max_s: float = 15.0  # 한 자리에 이보다 오래 붙들지 않는다
    after_s: float = 1.2     # 다 베고 떨어진 것을 기다리는 시간

    # 가르치며 배운 것 — 손댈 일 없다.
    first_s: float = 0.0     # 시작(포탈) → 첫 자리까지 걷는 시간
    gap_s: float = 0.0       # 자리 사이 간격(가운뎃값)
    gaps: list[float] = field(default_factory=list)  # 자리마다의 간격 그대로
    spots_n: int = 0         # 배운 자리 수
    damage_px: int = 0       # 이만큼 바뀌면 데미지로 본다 (0이면 기본값)
    chopped: int = 0

    @property
    def taught(self) -> bool:
        return bool(self.gaps or self.gap_s)

    def problems(self) -> list[str]:
        from .keys import vk_of

        missing = []
        for label, key in (("걷는 키", self.walk_key), ("되돌아가는 키", self.home_key),
                           ("벌목 키", self.chop_key)):
            if vk_of(key) is None:
                missing.append(f"{label} '{key}'을(를) 모름")
        return missing

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LumberSetup":
        data = data if isinstance(data, dict) else {}
        obj = cls()
        # 예전 설정(영역·색·미니맵·이름표)이 남아 있어도 조용히 버린다.
        for key, value in data.items():
            if key not in cls.__dataclass_fields__ or key == "gaps":
                continue
            default = getattr(obj, key)
            try:
                if isinstance(default, bool):
                    setattr(obj, key, bool(value))
                elif isinstance(default, int):
                    setattr(obj, key, int(value))
                elif isinstance(default, float):
                    setattr(obj, key, float(value))
                elif isinstance(default, str):
                    setattr(obj, key, str(value))
            except (TypeError, ValueError):
                continue
        try:
            obj.gaps = [max(0.0, min(120.0, float(v)))
                        for v in (data.get("gaps") or [])][:200]
        except (TypeError, ValueError):
            obj.gaps = []
        obj.try_s = max(0.4, min(10.0, obj.try_s))
        obj.quiet_s = max(0.3, min(10.0, obj.quiet_s))
        obj.chop_max_s = max(2.0, min(60.0, obj.chop_max_s))
        obj.after_s = max(0.0, min(10.0, obj.after_s))
        obj.first_s = max(0.0, min(120.0, obj.first_s))
        obj.gap_s = max(0.0, min(120.0, obj.gap_s))
        obj.spots_n = max(0, min(200, obj.spots_n))
        obj.damage_px = max(0, min(20000, obj.damage_px))
        obj.chopped = max(0, obj.chopped)
        return obj





# --------------------------------------------------------------------------
# 설정 + 프로필
# --------------------------------------------------------------------------
@dataclass
class Settings:
    window_pattern: str = "Z9★ 온라인"
    activate_before_run: bool = True  # 실행 전 게임 창을 앞으로
    require_foreground: bool = True  # (구버전 호환) focus_policy로 대체됨
    # 실행 중에 게임 창이 앞에서 밀려났을 때 무엇을 할지.
    #   stop    — 중단한다 (예전 동작)
    #   refocus — 창을 다시 앞으로 가져오고 이어서 한다 (기본)
    #   ignore  — 그냥 계속 보낸다. SendInput은 맨 앞 창으로 가므로 다른 창에
    #             입력이 새어 들어간다. 배경 입력을 켰을 때만 안전하다.
    focus_policy: str = FOCUS_REFOCUS
    # 입력을 어떤 방법으로 보낼지.
    #   send — SendInput. 확실하지만 게임이 반드시 맨 앞에 있어야 한다.
    #   post — 창 메시지(PostMessage). 창이 뒤에 있거나 최소화돼 있어도 되고
    #          사용자는 마우스·키보드를 따로 쓸 수 있다. 다만 게임이 이 방식을
    #          받아들이지 않으면 아무 일도 일어나지 않는다. 반드시 시험할 것.
    input_mode: str = INPUT_SEND
    settings_version: int = SETTINGS_VERSION
    panic_hotkey: str = "F12"  # 전부 정지
    record_hotkey: str = "F9"  # 녹화 시작/정지
    observe_hotkey: str = "F10"  # 관찰 시작/정지
    record_mouse_move: bool = True
    move_sample_ms: int = 20  # 마우스 이동 최소 기록 간격
    use_scancode: bool = True
    release_keys_on_stop: bool = True  # 정지 시 눌린 키 강제 해제
    # 시나리오가 몇 사이클 돌 때마다 입력 상태를 설정해 둔 대로 되돌릴지.
    # 0이면 끈다. 오래 돌릴수록 조금씩 어긋나는 것들을 여기서 바로잡는다.
    resync_cycles: int = 1
    # 켜면 이벤트 하나하나를 로그에 남긴다. 흐름을 따져 볼 때는 유용하지만
    # 촘촘한 매크로에서는 초당 수십 줄이 쌓이므로 기본은 꺼 둔다.
    # (평소 진행 상황은 [실행 상태] 창에서 보는 편이 낫다.)
    verbose_log: bool = False
    # -- 대기 중 움직임 -------------------------------------------------
    # 이만큼 긴 대기에만 끼워 넣는다. 짧은 틈에 밀어 넣으면 뒤 이벤트와 겹친다.
    move_min_gap_s: float = 5.0
    # 대기가 시작하고 이만큼은 그대로 둔다.
    move_lead_s: float = 1.5
    # 이동이 끝나고 다음 이벤트까지 남겨 둘 여유.
    move_tail_s: float = 0.5
    # 조건을 만족했을 때 실제로 넣을 확률(%). 100이면 늘 넣는다.
    move_chance: int = 60
    # 매크로 라이브러리 폴더. 비우면 프로젝트 안의 library/ 를 쓴다.
    library_dir: str = ""
    # -- 화면 -----------------------------------------------------------
    # 글꼴 크기 · 목록 행 높이 · 여백에 한꺼번에 걸리는 배율.
    # 1920x1080 이상에서 9pt 기본값이 작게 느껴질 때 키운다.
    ui_scale: float = 1.0
    # -- 꾸미기 ---------------------------------------------------------
    ui_theme: str = "기본"  # 기본 · 화이트 · 다크 · 모던 · 심플 · 따뜻한
    # 테마 위에 직접 바꾼 색 {역할: "#rrggbb"}. 역할은 bg · surface · raised ·
    # text · accent · danger 여섯 가지.
    ui_colors: dict[str, str] = field(default_factory=dict)
    ui_background: str = ""  # 배경 그림 (data/ui 에 복사해 둔 것)
    ui_bg_margin: int = 16  # 배경 그림이 보일 창 테두리(px)
    ui_icon: str = ""  # 창 아이콘 그림
    ui_font: str = ""  # 기본 글꼴 이름. 비우면 맑은 고딕 (fonts/ 폴더 글꼴도 고를 수 있다)
    # 마지막으로 쓰던 창 크기·위치("WxH+X+Y"). 비면 화면 크기에 맞춰 새로 잡는다.
    window_geometry: str = ""
    # 분할선 자리(px). 0이면 기본값을 쓴다.
    sash_main: int = 0  # 탭 영역 / 로그 사이 (위에서부터)
    sash_list: int = 0  # 왼쪽 항목 목록 / 오른쪽 편집 폼 사이 (왼쪽에서부터)
    sash_events: int = 0  # 이벤트 목록 / 편집 도구 사이 (위에서부터)
    # 관찰 모드
    observe_step: int = 4  # 화면을 몇 픽셀 간격으로 솎아 저장할지
    observe_interval_ms: int = 50
    # 1366x768 창을 4픽셀 격자로 50ms마다 담으면 초당 약 4MB 쌓인다.
    # 농사·목장은 한 사이클이 몇 초라 45초면 10회 이상 관찰된다.
    observe_seconds: int = 45

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        obj = _coerce(cls, data)
        # focus_policy가 생기기 전에는 require_foreground 하나로 껐다 켰다 했다.
        # 그때 켜 두었던 뜻은 "다른 창에 입력이 새지 않게 하라"였지 "멈춰라"가
        # 아니다. 그 목적은 창을 다시 앞으로 가져오는 쪽이 더 잘 이룬다 —
        # 입력도 안 새고 하던 일도 안 끊긴다. 그래서 refocus로 옮긴다.
        if "focus_policy" not in data:
            obj.focus_policy = FOCUS_REFOCUS if obj.require_foreground else FOCUS_IGNORE
        # 판 2 이전에는 위 이행이 require_foreground=True 를 전부 stop 으로
        # 옮겼다. 그 값은 사용자가 고른 것이 아니라 이행이 만든 것이므로,
        # 딱 한 번 바로잡는다. 그 뒤에 직접 stop 을 고르면 그대로 남는다.
        if int(data.get("settings_version", 0) or 0) < 2:
            if obj.focus_policy == FOCUS_STOP:
                obj.focus_policy = FOCUS_REFOCUS
        obj.settings_version = SETTINGS_VERSION
        if obj.focus_policy not in FOCUS_POLICIES:
            obj.focus_policy = FOCUS_REFOCUS
        if obj.input_mode not in INPUT_MODES:
            obj.input_mode = INPUT_SEND
        # 손으로 고친 설정 파일에서 말도 안 되는 배율이 들어오면 창을 못 쓰게 된다.
        try:
            obj.ui_scale = max(0.9, min(2.0, float(obj.ui_scale)))
        except (TypeError, ValueError):
            obj.ui_scale = 1.0
        # 손으로 고친 파일에서 이상한 색이 들어오면 버린다. 테마 이름 확인은 화면
        # 쪽(theme.build_palette)이 한다 — 모르는 이름이면 기본을 쓴다.
        roles = ("bg", "surface", "raised", "text", "accent", "danger")
        colors = obj.ui_colors if isinstance(obj.ui_colors, dict) else {}
        obj.ui_colors = {
            k: str(v).lower() for k, v in colors.items()
            if k in roles and isinstance(v, str) and len(v) == 7 and v[0] == "#"
            and all(c in "0123456789abcdefABCDEF" for c in v[1:])
        }
        obj.ui_theme = str(obj.ui_theme or "기본")
        obj.ui_background = str(obj.ui_background or "")
        obj.ui_icon = str(obj.ui_icon or "")
        obj.ui_font = str(obj.ui_font or "").strip()
        try:
            obj.ui_bg_margin = max(0, min(120, int(obj.ui_bg_margin)))
        except (TypeError, ValueError):
            obj.ui_bg_margin = 16
        for field_name in ("sash_main", "sash_list", "sash_events"):
            try:
                setattr(obj, field_name, max(0, int(getattr(obj, field_name))))
            except (TypeError, ValueError):
                setattr(obj, field_name, 0)
        return obj


@dataclass
class Profile:
    settings: Settings = field(default_factory=Settings)
    macros: list[Macro] = field(default_factory=list)
    repeats: list[RepeatTask] = field(default_factory=list)
    paths: list[PathMacro] = field(default_factory=list)
    rules: list[PixelRule] = field(default_factory=list)
    scenarios: list[Scenario] = field(default_factory=list)
    schedules: list[ScheduledTask] = field(default_factory=list)
    moves: list[Movement] = field(default_factory=list)
    buffs: list[BuffItem] = field(default_factory=list)
    # 업적 자동화 계획. 손댄 것만 들어간다 (achievements.ensure_plan 참고).
    achievements: list[AchievementPlan] = field(default_factory=list)
    # 낚시는 미니게임이 하나뿐이라 설정도 하나면 된다.
    fishing: FishingSetup = field(default_factory=FishingSetup)
    # 벌목도 맵마다 따로 둘 까닭이 없어 하나다.
    lumber: LumberSetup = field(default_factory=LumberSetup)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "settings": self.settings.to_dict(),
            "achievements": [a.to_dict() for a in self.achievements],
            "fishing": self.fishing.to_dict(),
            "lumber": self.lumber.to_dict(),
            "macros": [m.to_dict() for m in self.macros],
            "repeats": [r.to_dict() for r in self.repeats],
            "paths": [p.to_dict() for p in self.paths],
            "rules": [r.to_dict() for r in self.rules],
            "scenarios": [s.to_dict() for s in self.scenarios],
            "schedules": [s.to_dict() for s in self.schedules],
            "moves": [m.to_dict() for m in self.moves],
            "buffs": [b.to_dict() for b in self.buffs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return cls(
            settings=Settings.from_dict(data.get("settings", {})),
            macros=[Macro.from_dict(m) for m in data.get("macros", [])],
            repeats=[RepeatTask.from_dict(r) for r in data.get("repeats", [])],
            paths=[PathMacro.from_dict(p) for p in data.get("paths", [])],
            rules=[PixelRule.from_dict(r) for r in data.get("rules", [])],
            scenarios=[Scenario.from_dict(s) for s in data.get("scenarios", [])],
            schedules=[
                ScheduledTask.from_dict(s) for s in data.get("schedules", [])
            ],
            buffs=[BuffItem.from_dict(b) for b in data.get("buffs", [])],
            moves=[Movement.from_dict(m) for m in data.get("moves", [])],
            achievements=[
                AchievementPlan.from_dict(a) for a in data.get("achievements", [])
            ],
            fishing=FishingSetup.from_dict(data.get("fishing", {})),
            lumber=LumberSetup.from_dict(data.get("lumber") or {}),
        )
