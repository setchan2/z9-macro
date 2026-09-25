"""백그라운드 작업: 단일 키 반복, 픽셀 조건 감시."""

from __future__ import annotations

import copy
import random
import time
from pathlib import Path
from typing import Callable

from . import digits, icons, pixel, sender
from .arbiter import ARBITER
from .keys import vk_of
from .model import Macro, PathMacro, PixelRule, RepeatTask, ScheduledTask
from .player import Aborted, RunContext, play_macro, play_path, play_scenario


# --------------------------------------------------------------------------
# 단일 키 반복 (연타 / 홀드)
# --------------------------------------------------------------------------
def run_repeat(task: RepeatTask, ctx: RunContext) -> None:
    vk = vk_of(task.key)
    if vk is None:
        ctx.log(f"'{task.name}': 알 수 없는 키 '{task.key}'")
        return

    deadline = time.perf_counter() + task.duration_s if task.duration_s > 0 else None

    try:
        if task.mode == "hold":
            ctx.check()
            with ARBITER.dispatch():
                ctx.key_down(vk)
            ctx.log(f"'{task.name}': [{task.key}] 누르고 있는 중")
            if ctx.board is not None:
                ctx.board.set(연타=f"[{task.key}] 계속 누르고 있는 중")
                ctx.board.sent(f"[{task.key}] 누름", task.name)
            while True:
                ctx.check()
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                ctx.sleep(0.05)
        else:
            interval = max(task.interval_ms, 1) / 1000.0
            hold = max(task.hold_ms, 0) / 1000.0
            jitter = max(task.jitter_ms, 0) / 1000.0
            ctx.log(f"'{task.name}': [{task.key}] {task.interval_ms}ms 간격 연타 시작")
            # 절대 시각 기준으로 다음 입력 시점을 잡아 오차 누적을 막는다.
            next_at = time.perf_counter()
            taps = 0
            while True:
                ctx.check()
                if deadline is not None and time.perf_counter() >= deadline:
                    break
                with ARBITER.dispatch():
                    ctx.key_down(vk)
                    if hold > 0:
                        ctx.sleep(hold)
                    ctx.key_up(vk)
                taps += 1
                if ctx.board is not None:
                    # 한 타씩 흐름 목록에 쌓으면 그것만으로 가득 찬다. 횟수만 센다.
                    left = "" if deadline is None else                         f" · {max(deadline - time.perf_counter(), 0):.1f}초 남음"
                    ctx.board.set(연타=f"[{task.key}] {taps}회{left}")

                step = interval
                if jitter > 0:
                    step += random.uniform(-jitter, jitter)
                next_at += max(step, hold + 0.001)
                now = time.perf_counter()
                if next_at < now:
                    # 간격이 너무 짧아 밀렸다면 기준을 현재로 리셋
                    next_at = now
                else:
                    ctx.sleep_until(next_at)
        ctx.log(f"'{task.name}' 종료.")
    except Aborted as exc:
        ctx.log(f"'{task.name}' 중단됨. {exc.args[0] if exc.args else ''}".strip())
    finally:
        ctx.cleanup()


# --------------------------------------------------------------------------
# 픽셀 조건 감시
# --------------------------------------------------------------------------
MacroLookup = Callable[[str], Macro | None]
PathLookup = Callable[[str], PathMacro | None]


def evaluate_rule(
    rule: PixelRule,
    ctx: RunContext,
    library_root: Path | None = None,
    spots: list | None = None,
) -> tuple[bool, str]:
    """조건 성립 여부와 사람이 읽을 설명을 돌려준다.

    점(고정 좌표의 색)과 그림(영역 안 어딘가의 아이콘)을 함께 본다. match_mode가
    둘 모두에 걸리므로, '점 두 개가 맞고 그림도 있을 때'처럼 섞어 쓸 수 있다.

    spots를 주면 **찾은 그림의 한가운데 화면 좌표**를 거기 담는다. '찾은 그림
    누르기' 동작이 이 값을 쓴다 — 자리가 밀리는 것은 좌표를 미리 적어 둘 수
    없으므로, 찾은 그 자리를 그대로 눌러야 한다.
    """
    if not rule.points and not rule.icons and not rule.numbers:
        return (False, "볼 것이 하나도 없습니다 (점 · 그림 · 숫자)")
    if ctx.window is None:
        return (False, "게임 창을 찾지 못했습니다")

    hits: list[bool] = []
    parts: list[str] = []

    if rule.points:
        screen_points = [ctx.window.client_to_screen(p.x, p.y) for p in rule.points]
        try:
            actual = pixel.sample_points(screen_points)
        except pixel.CaptureError as exc:
            return (False, str(exc))
        for got, point in zip(actual, rule.points):
            hit = pixel.color_matches(got, point.color, rule.tolerance)
            hits.append(hit)
            parts.append(f"{'O' if hit else 'X'}{pixel.to_hex(got)}")

    if rule.icons:
        root = library_root if library_root is not None else ctx.library_root
        for watch in rule.icons:
            report = icons.look(watch, root, ctx.window)
            if spots is not None and report.matches:
                # 누를 자리는 그림의 한가운데다. 모서리를 누르면 옆 칸이 눌린다.
                template = icons.template_for(watch, root)
                half_w = template.width // 2 if template else 0
                half_h = template.height // 2 if template else 0
                spots.extend((m.x + half_w, m.y + half_h) for m in report.matches)
            # expect가 absent면 "없을 때" 성립이다. 버프가 끝난 것을 잡는 쓰임이
            # 바로 이것이라, 그림 조건의 절반은 이쪽으로 쓰인다.
            hit = report.found if watch.expect == "present" else not report.found
            hits.append(hit)
            label = watch.name or watch.icon or "그림"
            if report.error:
                parts.append(f"X{label}:{report.error}")
            else:
                mark = "O" if hit else "X"
                state = "있음" if report.found else "없음"
                parts.append(f"{mark}{label}:{state}({report.score:.0f})")

    if rule.numbers:
        root = library_root if library_root is not None else ctx.library_root
        for watch in rule.numbers:
            hit, detail = digits.evaluate(watch, root, ctx.window, ctx)
            hits.append(hit)
            label = watch.name or "숫자"
            parts.append(f"{'O' if hit else 'X'}{label}:{detail}")

    matched = all(hits) if rule.match_mode == "all" else any(hits)
    triggered = matched if rule.condition == "match" else not matched
    return (triggered, " ".join(parts))


def run_pixel_rule(
    rule: PixelRule,
    ctx: RunContext,
    find_macro: MacroLookup,
    find_path: PathLookup,
) -> None:
    check_interval = max(rule.check_ms, 30) / 1000.0
    cooldown = max(rule.cooldown_ms, 0) / 1000.0
    needed = max(1, rule.confirm_count)
    last_fire = 0.0
    was_true = False
    streak = 0

    parts = [f"{len(rule.points)}개 점"] if rule.points else []
    if rule.icons:
        parts.append(f"{len(rule.icons)}개 그림")
    if rule.numbers:
        parts.append(f"{len(rule.numbers)}개 숫자")
    if needed > 1:
        parts.append(f"{needed}회 연속 확인")
    ctx.log(f"'{rule.name}': 감시 시작 ({', '.join(parts)}, {rule.check_ms}ms 주기)")
    hovering = [n for n in rule.numbers if n.hovers]
    if hovering:
        ctx.log(
            f"  ⓘ 숫자 {len(hovering)}개는 커서를 올려서 읽습니다 — 읽을 때마다 "
            "커서가 잠깐 그 자리로 갔다가 돌아옵니다. 확인 주기를 넉넉히 두세요."
        )
    wide = [w for w in rule.icons if w.area_w <= 0 or w.area_h <= 0]
    if wide:
        ctx.log(
            f"  ⚠ 찾을 영역을 지정하지 않은 그림이 {len(wide)}개 있습니다 — "
            "창 전체를 뒤지므로 한 번에 몇 초씩 걸립니다. 영역을 좁혀 주세요."
        )
    warned_slow = False
    try:
        while True:
            ctx.check()
            started = time.perf_counter()
            spots: list = []
            raw, detail = evaluate_rule(rule, ctx, spots=spots)
            spent = time.perf_counter() - started
            if not warned_slow and spent > check_interval:
                warned_slow = True
                ctx.log(
                    f"  ⚠ 한 번 확인에 {spent * 1000:.0f}ms 걸립니다 "
                    f"(확인 주기 {rule.check_ms}ms). 주기를 늘리거나 찾을 영역을 "
                    "좁히세요 — 지금은 쉴 틈 없이 화면만 뒤집니다."
                )

            # 한 프레임 깜빡임에 속지 않도록, 같은 판정이 연속으로 나와야 믿는다.
            streak = streak + 1 if raw else 0
            triggered = streak >= needed

            should_fire = triggered and (not rule.edge_only or not was_true)
            was_true = triggered

            if should_fire and time.perf_counter() - last_fire >= cooldown:
                last_fire = time.perf_counter()
                ctx.log(f"'{rule.name}' 조건 성립 [{detail}] → 동작 실행")
                _fire(rule, ctx, find_macro, find_path, spots)

            ctx.sleep(check_interval)
    except Aborted as exc:
        ctx.log(f"'{rule.name}' 감시 중단. {exc.args[0] if exc.args else ''}".strip())
    finally:
        ctx.cleanup()


def click_spot(rule: PixelRule, ctx: RunContext, spots: list | None) -> bool:
    """그림을 찾은 자리를 그대로 누른다.

    업적 보상 상자처럼 **자리가 정해져 있지 않은 버튼**을 누르는 데 쓴다. 목록이
    스크롤되고 줄마다 상자가 있으니 좌표를 적어 둘 수가 없다. 찾은 곳을 눌러야
    한다.
    """
    if not spots:
        ctx.log(f"'{rule.name}': 누를 자리를 못 찾았습니다 (그림 조건이 있어야 합니다).")
        return False
    button = rule.action_key if rule.action_key in ("left", "right") else "left"
    x, y = spots[0]
    with ARBITER.dispatch():
        sender.mouse_move(x, y)
        ctx.sleep(0.05)
        ctx.button_down(button)
        ctx.sleep(0.05)
        ctx.button_up(button)
    ctx.sleep(0.15)
    ctx.log(f"'{rule.name}': 찾은 자리 ({x}, {y})를 눌렀습니다.")
    return True


def _fire(
    rule: PixelRule,
    ctx: RunContext,
    find_macro: MacroLookup,
    find_path: PathLookup,
    spots: list | None = None,
) -> None:
    if rule.action_kind == "click":
        click_spot(rule, ctx, spots)
        return

    if rule.action_kind == "key":
        vk = vk_of(rule.action_key)
        if vk is None:
            ctx.log(f"'{rule.name}': 알 수 없는 키 '{rule.action_key}'")
            return
        with ARBITER.dispatch():
            ctx.key_down(vk)
            ctx.sleep(0.03)
            ctx.key_up(vk)
        return

    if rule.action_kind == "macro":
        macro = find_macro(rule.action_target)
        if macro is None:
            ctx.log(f"'{rule.name}': 매크로 '{rule.action_target}'을 찾지 못했습니다.")
            return
        # 감시용 ctx의 stop_event를 공유해서 정지가 즉시 전파되게 한다.
        sub = ctx.spawn()
        play_macro(macro, sub)
        return

    if rule.action_kind == "path":
        path = find_path(rule.action_target)
        if path is None:
            ctx.log(f"'{rule.name}': 경로 '{rule.action_target}'을 찾지 못했습니다.")
            return
        sub = ctx.spawn()
        play_path(path, sub)


# --------------------------------------------------------------------------
# 시간 예약 실행
# --------------------------------------------------------------------------
def next_fire_time(task: ScheduledTask, now: float | None = None) -> float:
    """다음 실행 시각(time.time 기준). 지금이 정확히 그 시각이면 다음 회차로."""
    now = time.time() if now is None else now
    if task.mode == "interval":
        period = max(task.every_minutes, 1) * 60
        # 자정을 기준으로 딱 떨어지는 시각에 맞춘다. 켠 시점에 따라 어긋나면
        # "매 30분"이 매번 다른 분에 도는 것처럼 보인다.
        local = time.localtime(now)
        midnight = now - (local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec)
        elapsed = now - midnight
        return midnight + (int(elapsed // period) + 1) * period

    minute = min(max(task.minute, 0), 59)
    local = time.localtime(now)
    target = now - (local.tm_min * 60 + local.tm_sec) + minute * 60
    if target <= now:
        target += 3600
    return target


def prev_fire_time(task: ScheduledTask, now: float | None = None) -> float:
    """가장 최근에 지나간 실행 시각(time.time 기준). 지금이 딱 그 시각이면 지금.

    시나리오 안에 넣는 '예약 확인' 단계는 정각에 딱 맞춰 도달할 수 없다. 앞
    단계가 끝나야 확인하러 오기 때문이다. 그래서 "지금이 정각인가"가 아니라
    "지난번 확인 이후로 정각이 지나갔는가"를 묻는 데 이 값을 쓴다.
    """
    now = time.time() if now is None else now
    if task.mode == "interval":
        period = max(task.every_minutes, 1) * 60
        local = time.localtime(now)
        midnight = now - (local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec)
        return midnight + int((now - midnight) // period) * period

    minute = min(max(task.minute, 0), 59)
    local = time.localtime(now)
    target = now - (local.tm_min * 60 + local.tm_sec) + minute * 60
    if target > now:
        target -= 3600
    return target


def describe_schedule(task: ScheduledTask) -> str:
    if task.mode == "interval":
        return f"{max(task.every_minutes, 1)}분마다"
    return "매시 정각" if task.minute == 0 else f"매시 {task.minute}분"


ScenarioLookup = Callable[[str], object]


def run_schedule(
    task: ScheduledTask,
    ctx: RunContext,
    find_macro: MacroLookup,
    find_path: PathLookup,
    find_scenario: ScenarioLookup,
    find_rule: Callable[[str], PixelRule | None],
    find_buff=None,
    library_root=None,
    find_repeat=None,
    find_schedule=None,
) -> None:
    """정해진 시각마다, 입력이 비는 순간을 골라 한 번씩 실행한다."""
    ctx.log(f"'{task.name}': 예약 감시 시작 ({describe_schedule(task)})")
    try:
        while True:
            target = next_fire_time(task)
            remaining = target - time.time()
            ctx.log(
                f"'{task.name}': 다음 실행 "
                f"{time.strftime('%H:%M:%S', time.localtime(target))} "
                f"({remaining / 60:.1f}분 뒤)"
            )
            # 잘게 나눠 자야 정지 신호에 바로 반응한다.
            while True:
                ctx.check()
                left = target - time.time()
                if left <= 0:
                    break
                ctx.sleep(min(left, 0.5))

            fire_schedule(
                task, ctx, find_macro, find_path, find_scenario, find_rule,
                find_buff, library_root, find_repeat, find_schedule,
            )
    except Aborted as exc:
        ctx.log(f"'{task.name}' 예약 중단. {exc.args[0] if exc.args else ''}".strip())
    finally:
        ctx.cleanup()


def fire_schedule(
    task: ScheduledTask,
    ctx: RunContext,
    find_macro: MacroLookup,
    find_path: PathLookup,
    find_scenario: ScenarioLookup,
    find_rule: Callable[[str], PixelRule | None],
    find_buff=None,
    library_root=None,
    find_repeat=None,
    find_schedule=None,
) -> None:
    quiet = max(task.quiet_ms, 0) / 1000.0
    wait = max(task.gap_wait_s, 0)

    ctx.log(f"'{task.name}': 시각 도달 — 입력이 비는 순간을 기다립니다.")
    if not ARBITER.wait_for_gap(wait, quiet_s=quiet, stop_check=ctx.stop_event.is_set):
        ctx.check()  # 정지 때문이면 여기서 Aborted
        ctx.log(
            f"'{task.name}': {wait}초 안에 입력이 비지 않아 이번 회차를 건너뜁니다. "
            "(다른 매크로가 계속 입력 중이거나 키를 누르고 있습니다)"
        )
        return

    try:
        ctx.log(f"'{task.name}': 실행 — {task.action_kind} '{task.action_target}'")
        sub = ctx.spawn()

        if task.action_kind == "macro":
            macro = find_macro(task.action_target)
            if macro is None:
                ctx.log(f"'{task.name}': 매크로 '{task.action_target}'을 찾지 못했습니다.")
                return
            target = macro
            if macro.repeat == 0:
                target = copy.copy(macro)
                target.repeat = 1
                ctx.log("  ※ 무한 반복 매크로라 1회만 실행합니다.")
            play_macro(target, sub)
        elif task.action_kind == "path":
            path = find_path(task.action_target)
            if path is None:
                ctx.log(f"'{task.name}': 경로 '{task.action_target}'을 찾지 못했습니다.")
                return
            play_path(path, sub)
        elif task.action_kind == "scenario":
            scenario = find_scenario(task.action_target)
            if scenario is None:
                ctx.log(f"'{task.name}': 시나리오 '{task.action_target}'을 찾지 못했습니다.")
                return
            play_scenario(
                scenario, sub, find_macro, find_rule, find_buff, library_root,
                find_repeat, find_path, find_schedule, find_scenario,
            )
    finally:
        ARBITER.release_gap()


__all__ = [
    "run_repeat",
    "run_pixel_rule",
    "run_schedule",
    "evaluate_rule",
    "next_fire_time",
    "prev_fire_time",
    "fire_schedule",
    "describe_schedule",
    "sender",
]
