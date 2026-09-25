"""벌목 — **걷는 시간**으로 나무 자리를 셈해 오가며 벤다.

## 벌목장이 어떻게 생겼나 (사용자가 알려 준 것)

나무 26그루가 **같은 간격**으로 늘어서 있고, 맨 오른쪽에 포탈이 있다. 그래서 자리를
화면에서 알아볼 까닭이 없다 — 한 자리에서 다음 자리까지 **걷는 시간**만 알면 된다.

## 두 걸음으로 만든다

    ① 가르치기   프로그램이 창을 띄우고 방향키를 잡아 준다. 사람이 나무 자리마다
                 [Ctrl]을 누른다. 누른 순간이 곧 "여기가 자리"라는 뜻이므로
                 **누름과 누름 사이의 걸은 시간**을 적는다.
                 → 첫 자리까지 걸리는 시간 · 자리 사이 간격 · 자리 개수를 배운다.

    ② 벌목       배운 시간만큼 걷고 멈춰서 [Ctrl]을 잡는다. 자리 수만큼 되풀이하고,
                 끝나면 그만큼 되돌아가 다시 시작한다.

## 남이 서 있는 자리는 어떻게 아나

26자리 가운데 아무 데나 다른 사람이 서서 벌목하고 있다. 화면에서 남을 가려내기는
어렵지만, **벨 수 있는지 없는지는 눌러 보면 안다** — 도끼가 닿으면 데미지 숫자가
뜨고, 남이 이미 캐고 있거나 나무가 아직 안 자랐으면 안 뜬다. 그래서 자리마다 잠깐
눌러 보고, 데미지가 안 뜨면 곧장 다음 자리로 간다. 사람이 하는 것과 같은 판단이다.

가르칠 때 사람이 [Ctrl]을 누르면 그동안 방향키를 놓아 준다 — 그 자리에 서서 실제로
베어도 되고, 자리만 찍어 줘도 된다. 누르고 있던 시간은 걸은 시간에서 빠진다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

# 데미지 숫자 색 (베고 있는지 보는 용도) — 빨강이 세고 초록·파랑이 약한 칸
WARM_R, WARM_GB = 165, 215
DAMAGE_PX = 45
# 데미지를 살펴볼 네모 (캐릭터 기준 px). 숫자는 머리 위로 떠오르며 사라진다.
WATCH_SIDE, WATCH_UP, WATCH_DOWN = 320, 360, 50

# 가르칠 때 키를 살펴보는 간격(초). 촘촘해야 누른 때를 정확히 잡는다.
WATCH_S = 0.03
# 자리 사이 간격이 이만큼 흩어지면 알린다
SPREAD_WARN = 0.35
# 걸음 시간에서 이만큼 뺀다(초) — 키를 떼도 조금 미끄러지기 때문이다
COAST_S = 0.06

# 자리에 섰는데 데미지가 안 뜨면 조금씩 옮겨 가며 다시 눌러 본다(초, 누적).
# 사람이 눈으로 찍어 준 자리라 조금씩 어긋나기 마련이고, 26자리를 도는 동안
# 그 어긋남이 쌓이기도 한다. 한 걸음 더 갔다 오는 값이라 손해가 거의 없다.
NUDGES = (0.18, 0.18, -0.54, -0.18)


def _ge(limit: int) -> bytes:
    return bytes(0xFF if v >= limit else 0 for v in range(256))


def _le(limit: int) -> bytes:
    return bytes(0xFF if v <= limit else 0 for v in range(256))


# (파랑 표, 초록 표, 빨강 표)
_WARM = (_le(WARM_GB), _le(WARM_GB), _ge(WARM_R))


def row_mask(buf, width: int, y: int, x0: int, n: int, tb, tg, tr) -> bytes:
    """한 줄에서 (파랑·초록·빨강) 조건을 모두 채운 칸 = 0xFF.

    칸마다 파이썬으로 돌지 않는다 — 채널을 슬라이스로 뽑아 표로 바꾸고 정수 AND.
    낚시 판을 읽는 것과 같은 수법이라 넓은 화면도 한 장에 몇 ms면 된다.
    """
    base = (y * width + x0) * 4
    row = buf[base:base + n * 4]
    both = (int.from_bytes(row[0::4].translate(tb), "big")
            & int.from_bytes(row[1::4].translate(tg), "big")
            & int.from_bytes(row[2::4].translate(tr), "big"))
    return both.to_bytes(n, "big")


# --------------------------------------------------------------------------
# 데미지 보기 (베고 있나)
# --------------------------------------------------------------------------
def watch_box(char_x: float, char_y: float, frame=None) -> tuple[int, int, int, int]:
    """데미지를 살펴볼 네모. 화면 밖은 미리 잘라 둔다."""
    box = (int(char_x - WATCH_SIDE), int(char_y - WATCH_UP),
           int(char_x + WATCH_SIDE), int(char_y + WATCH_DOWN))
    if frame is None:
        return box
    x0, y0, x1, y1 = box
    return (max(0, min(frame.w, x0)), max(0, min(frame.h, y0)),
            max(0, min(frame.w, x1)), max(0, min(frame.h, y1)))


def warm_mask(frame, box) -> bytes:
    """네모 안에서 데미지 숫자 색(빨강이 센 칸)을 모은 자국."""
    x0, y0, x1, y1 = box
    n = x1 - x0
    if n <= 0 or y1 <= y0:
        return b""
    tb, tg, tr = _WARM
    return b"".join(row_mask(frame.buf, frame.w, y, x0, n, tb, tg, tr)
                    for y in range(y0, y1))


def warm_count(mask: bytes) -> int:
    return mask.count(0xFF)


def warm_change(before: bytes, after: bytes) -> int:
    """두 자국에서 달라진 칸 수. 가만있는 빨간 것(사과 따위)은 저절로 빠진다."""
    if not before or len(before) != len(after):
        return 0
    return (int.from_bytes(before, "big")
            ^ int.from_bytes(after, "big")).bit_count() // 8


# --------------------------------------------------------------------------
# 눈과 손
# --------------------------------------------------------------------------
class Eyes:
    """게임 창을 통째로 찍는다."""

    def __init__(self, window) -> None:
        self.window = window

    def look(self):
        from . import pixel

        window = self.window
        if window is None:
            return None
        try:
            width, height = window.client_size()
            if width <= 0 or height <= 0:
                return None
            x, y = window.client_to_screen(0, 0)
            return pixel.capture_region(x, y, width, height)
        except (pixel.CaptureError, OSError):
            return None


class Hands:
    """키를 누르고, 보낸 입력을 [실행 상태] 창과 로그에 남긴다."""

    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.held: set[str] = set()

    def now(self) -> float:
        return time.perf_counter()

    def sleep(self, seconds: float) -> None:
        self.ctx.sleep(max(0.0, seconds))

    def check(self) -> None:
        self.ctx.check()

    def _vk(self, name: str) -> int:
        from .keys import vk_of

        vk = vk_of(name)
        if vk is None:
            raise ValueError(f"키 이름 '{name}'을(를) 모르겠습니다")
        return vk

    def note(self, text: str, log: bool = False) -> None:
        board = getattr(self.ctx, "board", None)
        if board is not None:
            board.sent(text, "벌목")
        if log:
            self.ctx.log(f"  ↳ {text}")

    def press(self, name: str, why: str = "") -> None:
        if name in self.held:
            return
        self.ctx.key_down(self._vk(name))
        self.held.add(name)
        self.note(f"키 [{name}] 누름" + (f" — {why}" if why else ""), log=bool(why))

    def let_go(self, name: str, why: str = "") -> None:
        if name not in self.held:
            return
        self.ctx.key_up(self._vk(name))
        self.held.discard(name)
        self.note(f"키 [{name}] 뗌" + (f" — {why}" if why else ""), log=bool(why))

    def hold(self, name: str, seconds: float, why: str = "") -> None:
        self.press(name, why)
        self.sleep(seconds)
        self.let_go(name)

    def release_all(self) -> None:
        for name in list(self.held):
            try:
                self.let_go(name)
            except (ValueError, OSError):
                self.held.discard(name)


def key_down(vk: int) -> bool:
    """지금 그 키가 눌려 있나 — **사람이 누르는 것**을 보려고 쓴다."""
    try:
        from .win32 import user32

        return bool(user32.GetAsyncKeyState(vk) & 0x8000)
    except (ImportError, OSError):
        return False


# --------------------------------------------------------------------------
# ① 가르치기 — 누름과 누름 사이의 걸은 시간을 적는다
# --------------------------------------------------------------------------
def middle_of(values: list[float]) -> float:
    """가운뎃값. 없으면 0."""
    if not values:
        return 0.0
    order = sorted(values)
    return order[len(order) // 2]


def spread_of(values: list[float]) -> float:
    """가운뎃값에서 가장 많이 벗어난 정도(비율). 고르면 0에 가깝다."""
    middle = middle_of(values)
    if middle <= 0 or not values:
        return 0.0
    return max(abs(v - middle) for v in values) / middle


@dataclass
class Lesson:
    """가르치며 배운 것 (모두 초)."""

    first: float = 0.0                                # 시작 → 첫 자리
    gaps: list[float] = field(default_factory=list)   # 자리 → 다음 자리
    holds: list[float] = field(default_factory=list)  # 자리마다 누른 시간
    note: str = ""

    @property
    def count(self) -> int:
        if not self.first and not self.gaps:
            return 0
        return len(self.gaps) + 1

    @property
    def gap(self) -> float:
        return middle_of(self.gaps)

    def to_dict(self) -> dict:
        return {
            "첫자리까지": round(self.first, 2),
            "자리간격": [round(g, 2) for g in self.gaps],
            "간격가운뎃값": round(self.gap, 2),
            "자리수": self.count,
            "누른시간": [round(h, 2) for h in self.holds],
            "메모": self.note,
        }


class Teacher:
    """방향키를 잡아 주고, 사람이 [Ctrl]을 누른 **시간 간격**을 적는다."""

    def __init__(self, setup, hands: Hands, log=None, folder=None) -> None:
        self.setup = setup
        self.hands = hands
        self.log = log or (lambda text: None)
        self.folder = folder
        self.lesson = Lesson()
        self.marks: list[dict] = []

    def run(self, seconds: float = 0.0) -> Lesson:
        from .keys import vk_of

        setup = self.setup
        vk = vk_of(setup.chop_key)
        if vk is None:
            self.log(f"  '{setup.chop_key}' 키를 모르겠습니다")
            return self.lesson
        way = setup.walk_key

        self.log(f"  제가 [{way}]를 잡고 있겠습니다 — 포탈 앞에서 시작하세요.")
        self.log(f"  나무 자리에 닿을 때마다 [{setup.chop_key}]를 눌러 주세요. "
                 "누르는 동안은 걸음을 멈춥니다(그 자리에서 베셔도 됩니다).")
        self.log("  다 걸었으면 [정지]를 누르시면 됩니다.")

        started = self.hands.now()
        walked = 0.0        # 여태 **걸은** 시간 (누르고 있던 동안은 안 센다)
        last_mark = 0.0     # 지난 자리를 찍었을 때까지 걸은 시간
        holding = False
        press_at = 0.0
        leg_from = started  # 이번에 걷기 시작한 때
        self.hands.press(way, "걷기 (가르치는 중)")
        try:
            while True:
                self.hands.check()
                self.hands.sleep(WATCH_S)
                now = self.hands.now()
                if seconds and now - started >= seconds:
                    self.lesson.note = "정한 시간이 찼습니다"
                    break
                down = key_down(vk)
                if down and not holding:
                    holding = True
                    press_at = now
                    walked += now - leg_from
                    self.hands.let_go(way)
                    gap = walked - last_mark
                    last_mark = walked
                    if not self.lesson.first:
                        self.lesson.first = gap
                        self.log(f"  1번째 자리 — 시작에서 {gap:.2f}초")
                    else:
                        self.lesson.gaps.append(gap)
                        self.log(f"  {self.lesson.count}번째 자리 — "
                                 f"지난 자리에서 {gap:.2f}초")
                    self.marks.append({"번호": self.lesson.count,
                                       "걸은시간": round(walked, 2),
                                       "간격": round(gap, 2)})
                elif not down and holding:
                    holding = False
                    held = now - press_at
                    self.lesson.holds.append(held)
                    if self.marks:
                        self.marks[-1]["누른시간"] = round(held, 2)
                    leg_from = now
                    self.hands.press(way)
        finally:
            self.hands.release_all()
        self.finish()
        return self.lesson

    def finish(self) -> None:
        lesson = self.lesson
        self.log("─" * 30)
        if not lesson.count:
            self.log("  자리를 하나도 못 받았습니다 — "
                     f"[{self.setup.chop_key}]를 눌러 자리를 찍어 주세요")
            return
        self.log(f"  배운 자리 {lesson.count}곳 · 첫 자리까지 {lesson.first:.2f}초 · "
                 f"자리 사이 {lesson.gap:.2f}초")
        if lesson.gaps:
            spread = spread_of(lesson.gaps)
            self.log(f"  간격 {min(lesson.gaps):.2f}~{max(lesson.gaps):.2f}초"
                     + (f"  ⚠ 들쭉날쭉합니다(±{spread:.0%}) — 자리를 놓치셨을 수 "
                        "있습니다" if spread > SPREAD_WARN else "  (고르게 나왔습니다)"))
        if lesson.holds:
            self.log(f"  누른 시간 {min(lesson.holds):.1f}~{max(lesson.holds):.1f}초 "
                     f"(가운뎃값 {middle_of(lesson.holds):.1f}초)")
        self.save()

    def save(self) -> None:
        if self.folder is None:
            return
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            data = self.lesson.to_dict()
            data["자리들"] = self.marks
            (self.folder / "수업.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            self.log(f"  기록: {self.folder / '수업.json'}")
        except OSError as exc:
            self.log(f"  기록을 남기지 못했습니다: {exc}")


# --------------------------------------------------------------------------
# ② 자동 벌목 — 배운 시간만큼 걷고, 눌러 보고, 안 되면 다음 자리로
# --------------------------------------------------------------------------
class Cutter:
    """배운 간격대로 자리를 돌며 벤다."""

    def __init__(self, setup, eyes: Eyes, hands: Hands, log=None) -> None:
        self.setup = setup
        self.eyes = eyes
        self.hands = hands
        self.log = log or (lambda text: None)
        self.chopped = 0
        self.skipped = 0
        self.rounds = 0
        self.char = (0.0, 0.0)

    def legs(self) -> list[float]:
        """자리마다 걸을 시간. 가르친 그대로 쓰고, 모자라면 가운뎃값으로 채운다."""
        setup = self.setup
        gaps = [g for g in (setup.gaps or []) if g > 0.05]
        gap = middle_of(gaps) or setup.gap_s
        count = max(1, int(setup.spots_n or (len(gaps) + 1)))
        out = [setup.first_s or gap]
        for i in range(count - 1):
            out.append(gaps[i] if i < len(gaps) else gap)
        return out

    def ready(self) -> bool:
        frame = self.eyes.look()
        if frame is None:
            self.log("  게임 창을 못 찍었습니다 — 창이 열려 있는지 봐 주세요")
            return False
        self.char = (frame.w / 2.0, frame.h * 0.62)
        return True

    def chop(self) -> bool:
        """[Ctrl]을 잡고 데미지를 본다.

        데미지가 아예 안 뜨면 False — 남이 그 자리를 캐고 있거나, 나무가 아직 안
        자란 것이다. 그럴 때는 붙잡고 있지 말고 다음 자리로 가는 편이 낫다.
        """
        setup = self.setup
        frame = self.eyes.look()
        if frame is None:
            return False
        box = watch_box(*self.char, frame=frame)
        last = warm_mask(frame, box)
        floor = warm_count(last)
        mark = int(getattr(setup, "damage_px", 0) or DAMAGE_PX)
        self.hands.press(setup.chop_key, "나무 베기")
        started = self.hands.now()
        first = quiet = None
        hits = 0
        try:
            while True:
                self.hands.check()
                self.hands.sleep(0.12)
                now = self.hands.now()
                frame = self.eyes.look()
                if frame is None:
                    return False
                seen = warm_mask(frame, box)
                here = warm_count(seen)
                floor = min(floor, here)
                moved = max(warm_change(last, seen), here - floor)
                last = seen
                if moved >= mark:
                    hits += 1
                    quiet = None
                    if first is None:
                        first = now
                elif first is not None:
                    if quiet is None:
                        quiet = now
                    elif now - quiet >= setup.quiet_s:
                        break
                if first is None and now - started >= setup.try_s:
                    return False
                if now - started >= setup.chop_max_s:
                    break
        finally:
            self.hands.let_go(setup.chop_key)
        self.hands.sleep(setup.after_s)
        return hits > 0

    def try_here(self) -> tuple[bool, float]:
        """이 자리에서 눌러 보고, 안 되면 조금씩 옮겨 가며 다시. (벴나, 옮긴 시간)

        사람이 눈으로 찍어 준 자리라 조금 어긋날 수 있다. 다시 멀리서 걸어오는
        것보다 반 걸음씩 옮겨 보는 편이 훨씬 싸다.
        """
        if self.chop():
            return (True, 0.0)
        moved = 0.0
        for step in NUDGES:
            self.hands.check()
            if step >= 0:
                self.walk(step)
            else:
                self.walk(-step, back=True)
            moved += step
            if self.chop():
                return (True, moved)
        # 못 벴으면 제자리로 돌려놓는다 — 다음 자리 셈이 어긋나지 않게.
        if moved > 0:
            self.walk(moved, back=True)
        elif moved < 0:
            self.walk(-moved)
        return (False, 0.0)

    def walk(self, seconds: float, back: bool = False) -> None:
        """그만큼 걷는다. back이면 반대쪽으로."""
        setup = self.setup
        key = setup.home_key if back else setup.walk_key
        self.hands.hold(key, max(0.05, seconds - COAST_S))
        self.hands.sleep(0.08)

    def run(self, seconds: float = 0.0, count: int = 0) -> dict:
        legs = self.legs()
        if not self.ready():
            return self.report()
        self.log(f"  자리 {len(legs)}곳 · 첫 자리까지 {legs[0]:.2f}초 · "
                 f"자리 사이 {middle_of(legs[1:]) or legs[0]:.2f}초")
        started = self.hands.now()
        while True:
            self.hands.check()
            if seconds and self.hands.now() - started >= seconds:
                break
            if count and self.chopped >= count:
                break
            self.rounds += 1
            self.log(f"  {self.rounds}바퀴째 — {len(legs)}자리를 훑습니다")
            spent = 0.0
            for number, leg in enumerate(legs, start=1):
                self.hands.check()
                if count and self.chopped >= count:
                    break
                if seconds and self.hands.now() - started >= seconds:
                    break
                self.walk(leg)
                spent += leg
                done, moved = self.try_here()
                spent += moved
                if done:
                    self.chopped += 1
                    self.log(f"  {number}번째 자리 — 벴습니다 "
                             f"(모두 {self.chopped}그루)"
                             + (f" · {moved:+.2f}초 옮겨서" if moved else ""))
                else:
                    self.skipped += 1
                    self.log(f"  {number}번째 자리 — 데미지가 없어 건너뜁니다 "
                             "(남이 있거나 아직 안 자랐습니다)")
            self.go_home(spent)
        return self.report()

    def go_home(self, spent: float) -> None:
        """끝까지 갔으면 시작 자리로 되돌아간다."""
        if spent <= 0:
            return
        self.log(f"  끝까지 갔습니다 — {spent:.1f}초 되돌아갑니다")
        self.walk(spent, back=True)

    def report(self) -> dict:
        return {"chopped": self.chopped, "skipped": self.skipped,
                "rounds": self.rounds}


# --------------------------------------------------------------------------
def run_lumber(setup, ctx, seconds: float = 0.0, count: int = 0) -> dict:
    """[벌목 시작]이 부르는 곳. 가르치기와 벌목을 설정에 따라 갈라 준다."""
    from .player import Aborted

    problems = setup.problems()
    if problems:
        ctx.log("벌목 설정이 덜 됐습니다 — " + ", ".join(problems))
        return {"chopped": 0}

    window = ctx.window
    if window is not None:
        try:
            window.activate()   # 게임 창을 앞으로 (누르는 키가 게임에 들어가도록)
        except OSError:
            pass

    eyes, hands = Eyes(window), Hands(ctx)
    ctx.log("═" * 12 + " 벌목 " + "═" * 12)
    out: dict = {"chopped": 0}
    try:
        if setup.teaching or not (setup.gaps or setup.gap_s):
            from . import storage

            folder = storage.DATA_DIR / "벌목배움" / time.strftime("%Y%m%d-%H%M%S")
            teacher = Teacher(setup, hands, log=ctx.log, folder=folder)
            lesson = teacher.run(seconds)
            if lesson.count:
                setup.first_s = round(lesson.first, 2)
                setup.gaps = [round(g, 2) for g in lesson.gaps]
                setup.gap_s = round(lesson.gap, 2)
                setup.spots_n = lesson.count
                if lesson.holds:
                    setup.chop_max_s = max(
                        setup.chop_max_s, round(max(lesson.holds) + 3.0, 1))
                ctx.log(f"  자리 {lesson.count}곳을 기억했습니다 — [가르치기]를 끄고 "
                        "[벌목 시작]을 누르면 그대로 돕니다.")
            out = {"chopped": 0, "spots": lesson.count}
        else:
            cutter = Cutter(setup, eyes, hands, log=ctx.log)
            out = cutter.run(seconds, count)
            setup.chopped = int(getattr(setup, "chopped", 0)) + cutter.chopped
            ctx.log(f"벌목 끝 — {cutter.chopped}그루 · 건너뜀 {cutter.skipped}자리 "
                    f"· {cutter.rounds}바퀴")
    except Aborted:
        raise
    finally:
        hands.release_all()
    return out
