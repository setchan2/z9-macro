"""목장 매크로 — 시나리오를 한 바퀴 돌 때마다 피로도를 본다.

    ⓪ 처음 한 번   게임(지구별) 창을 앞으로 세운다
    ① 버프         재사용 대기가 끝난 것만 쓴다 — [Esc] → 버프 키 → [Esc]
    ② 그룹 한 바퀴  옮겨 온 시나리오([Verson 1.0] 투목)의 그룹을 차례대로 한 번
    ③ 피로도       가득(또는 기준값 이상)이면 정해 둔 매크로를 한 번 돌린다
    ④ N바퀴마다    (켜 두었으면) 정해 둔 매크로를 한 번 돌린다
    → 다시 ①  ([정지]를 누를 때까지)

## 왜 시나리오를 복사해 오는가

사용자가 시나리오 편집기에서 직접 짜 둔 흐름을 그대로 쓰되, 그 뒤에 피로도
확인을 끼우려면 시나리오가 "한 바퀴 끝났다"를 알려 줘야 한다. 시나리오 재생기는
무한 반복을 스스로 돌아서 그 틈이 없다. 그래서 그룹을 목장 설정으로 옮겨 오고,
단계 하나하나는 시나리오와 **같은 함수(_run_step)** 로 돌린다 — 대기 · 휠 칸 수 ·
반복 횟수가 시나리오에서 돌 때와 똑같다.

## 버프 앞뒤의 [Esc]

떠 있는 창이 있으면 버프 키를 그 창이 먹는다. 그래서 누르기 직전에 닫고, 쓰고
난 뒤 버프가 띄운 창이 남지 않게 한 번 더 닫는다. 사이는 짧게(기본 0.1초) 둔다.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace

from .arbiter import ARBITER
from .keys import vk_of
from .model import RanchSetup, ScenarioGroup
from .player import STEP_MARKS, Aborted, RunContext, _run_macro_step, _run_step

# 조건 설명에서 "31057 / 542000"의 앞 값을 뽑는다 (낚시와 같은 모양).
_FATIGUE_NOW = re.compile(r"(\d+)\s*/\s*\d+")


def note(ctx: RunContext, what: str, why: str = "") -> None:
    board = getattr(ctx, "board", None)
    if board is not None:
        board.sent(f"{what} — {why}" if why else what, "목장")


def tap(name: str, ctx: RunContext, why: str = "") -> bool:
    """키 하나를 톡 누른다. 모르는 키면 False."""
    vk = vk_of(name)
    if vk is None:
        return False
    with ARBITER.dispatch():
        ctx.key_down(vk)
        ctx.sleep(0.04)
        ctx.key_up(vk)
    note(ctx, f"키 [{name}]", why)
    return True


def say(ctx: RunContext, step: str, detail: str) -> None:
    board = getattr(ctx, "board", None)
    if board is not None:
        board.set(단계=f"{step} — {detail}")
    ctx.log(f"{step} · {detail}")


# --------------------------------------------------------------------------
# ⓪ 게임 창
# --------------------------------------------------------------------------
def activate_game(ctx: RunContext) -> bool:
    """게임(지구별) 창을 앞으로 세운다. 섰으면 True.

    엔진도 시작할 때 한 번 앞으로 가져오지만, 창 입력 방식(배경 입력)에서는
    건너뛴다. 목장은 **늘** 세운 뒤에 시작한다.
    """
    from .craft import bring_front, find

    game = find(ctx.settings.window_pattern)
    if game is None:
        ctx.log(f"  ⚠ 게임 창('{ctx.settings.window_pattern}')을 못 찾았습니다.")
        return False
    if not bring_front(game, ctx, "게임"):
        return False
    ctx.window = game
    ctx.sleep(0.3)   # 앞으로 선 뒤 입력을 받을 때까지 잠깐
    ctx.log(f"  게임 창 '{game.title}'을(를) 앞으로 세웠습니다.")
    return True


# --------------------------------------------------------------------------
# ① 버프
# --------------------------------------------------------------------------
def use_buffs(setup: RanchSetup, ctx: RunContext, save=None) -> str:
    """재사용 대기가 끝난 버프만 쓴다. 무슨 일이 있었는지 한 줄로.

    버프마다  [Esc] → (짧게) → 버프 키 → (짧게) → [Esc].
    쓴 시각이 아니라 **다음에 쓸 시각**을 적어 두므로 껐다 켜도 이어진다.
    """
    now = time.time()
    rows = [b for b in setup.buffs if b.ready]
    if not rows:
        return "버프 안 씀"
    used = []
    for buff in rows:
        ctx.check()
        if buff.left_s(now) > 0:
            continue
        label = buff.name or f"{buff.key}번"
        if used:
            ctx.sleep(setup.buff_gap_s)
        tap("Esc", ctx, f"버프 '{label}' 쓰기 전")
        ctx.sleep(setup.esc_gap_s)
        if not tap(buff.key, ctx, f"버프 '{label}'"):
            ctx.log(f"  ⚠ 버프 '{label}' 키 '{buff.key}'를 모릅니다.")
            continue
        ctx.sleep(setup.esc_gap_s)
        tap("Esc", ctx, f"버프 '{label}' 쓴 뒤")
        buff.used(time.time())
        used.append(f"[{buff.key}] {label}")
    if used and save is not None:
        save()   # 다음에 쓸 시각을 바로 남긴다

    now = time.time()
    plan = " · ".join(f"[{b.key}] {b.name} {b.describe(now)}" for b in rows)
    board = getattr(ctx, "board", None)
    if board is not None:
        board.set(버프=plan)
    return (" · ".join(used) if used else "이번엔 쓸 것 없음") + f" ({plan})"


# --------------------------------------------------------------------------
# ② 그룹 한 바퀴
# --------------------------------------------------------------------------
def lookups_for(setup: RanchSetup, finders: dict) -> dict:
    """시나리오 단계를 돌릴 때 쓰는 조회 함수 묶음 (player.play_scenario와 같은 모양)."""
    none = lambda _n: None  # noqa: E731
    return {
        "macro": finders.get("macro") or none,
        "repeat": finders.get("repeat") or none,
        "path": finders.get("path") or none,
        "schedule": finders.get("schedule") or none,
        "scenario": finders.get("scenario") or none,
        "rule": finders.get("rule") or none,
        "buff": finders.get("buff"),
        "library_root": finders.get("library_root"),
        "scenario_name": setup.source,
        "schedule_since": time.time(),
        "schedule_state": {},
    }


def run_group(group: ScenarioGroup, ctx: RunContext, lookups: dict,
              round_no: int) -> bool:
    """그룹 하나를 **정한 반복 횟수만큼** 돈다. 끝까지 돌았으면 True.

    반복이 무한(0)이면 한 번으로 끊는다 — 그래야 바퀴가 끝나고 피로도를 본다.
    """
    cycles = group.repeat if group.repeat > 0 else 1
    total = len(group.steps)
    for cycle in range(1, cycles + 1):
        for number, step in enumerate(group.steps, start=1):
            ctx.check()
            label = (f"[{round_no}바퀴 · {group.name}"
                     + (f" {cycle}/{cycles}회" if cycles > 1 else "")
                     + f"] {number}/{total}")
            board = getattr(ctx, "board", None)
            if board is not None:
                board.set(단계=f"② {group.name} {number}/{total} "
                               f"{STEP_MARKS.get(step.kind, '·')} {step.label}")
            if not _run_step(step, ctx, label, lookups):
                return False
            delay = step.effective_delay(group.interval_ms)
            if delay > 0:
                ctx.sleep(delay / 1000.0)
    return True


# --------------------------------------------------------------------------
# ③ 피로도
# --------------------------------------------------------------------------
def fatigue_goal(setup: RanchSetup) -> str:
    over = float(setup.fatigue_over or 0.0)
    return f"{over:g} 이상" if over > 0 else "가득"


def fatigue_rule(setup: RanchSetup, rule):
    """기준값이 있으면 조건의 숫자 보기를 '앞 값이 ○○ 이상'으로 바꿔 본다.

    읽을 자리 · 글꼴 · 밝기는 조건에 적힌 그대로 쓴다 (낚시와 같다).
    """
    over = float(setup.fatigue_over or 0.0)
    if over <= 0 or not rule.numbers:
        return rule
    numbers = [replace(w, target="current", compare="at_least", value=over)
               for w in rule.numbers]
    return replace(rule, numbers=numbers)


def check_fatigue(setup: RanchSetup, ctx: RunContext, find_rule, find_macro,
                  save=None) -> str:
    """피로도가 찼으면 정해 둔 매크로를 **한 번** 돌린다. 한 줄로 결과를 돌려준다.

    조건이나 매크로를 못 찾아도 목장은 멈추지 않는다 — 경고만 남기고 넘어간다.
    """
    if not setup.fatigue_on:
        return "피로도 안 봄"
    rule = find_rule(setup.fatigue_rule) if setup.fatigue_rule else None
    if rule is None:
        return (f"⚠ 피로도 조건 '{setup.fatigue_rule or '안 정함'}'을(를) "
                "찾지 못해 건너뜁니다")
    from .tasks import evaluate_rule  # 순환 참조를 피해 여기서 가져온다

    goal = fatigue_goal(setup)
    note(ctx, "피로도 확인", f"조건 '{rule.name}' · {goal}이면 매크로")
    full, detail = evaluate_rule(fatigue_rule(setup, rule), ctx)
    board = getattr(ctx, "board", None)
    if board is not None:
        found = _FATIGUE_NOW.search(detail or "")
        board.set(피로도=(found.group(0) if found else detail)[:60])
    if not full:
        return f"아직 {goal} 아님 [{detail}]"
    macro = setup.fatigue_macro
    if not macro or find_macro(macro) is None:
        return (f"⚠ 피로도 {goal} [{detail}] — 돌릴 매크로 "
                f"'{macro or '안 정함'}'을(를) 찾지 못했습니다")
    ctx.log(f"  [피로도 {goal}] [{detail}] → 매크로 '{macro}' 한 번 실행 후 "
            "목장을 이어 갑니다")
    if not _run_macro_step(macro, ctx, find_macro, "  피로도 매크로"):
        raise Aborted()
    setup.fatigue_runs += 1
    if save is not None:
        save()
    return f"{goal} [{detail}] → '{macro}' 실행함 ({setup.fatigue_runs}번째)"


# --------------------------------------------------------------------------
# 한 바퀴씩
# --------------------------------------------------------------------------
def run_ranch(setup: RanchSetup, ctx: RunContext, finders: dict,
              rounds: int = 0, save=None) -> None:
    """[정지]를 누를 때까지 돈다. rounds를 주면 그만큼만 (시험용)."""
    problems = setup.problems()
    if problems:
        ctx.log("목장: 아직 못 정한 것이 있습니다 —")
        for line in problems:
            ctx.log(f"  · {line}")
        return
    groups = setup.ordered_groups
    lookups = lookups_for(setup, finders)
    find_rule, find_macro = lookups["rule"], lookups["macro"]
    board = getattr(ctx, "board", None)

    say(ctx, "⓪ 시작", "게임(지구별) 창을 앞으로 세웁니다")
    if not activate_game(ctx):
        ctx.log("목장: 게임 창을 앞으로 세우지 못해 시작하지 않습니다.")
        return
    steps = sum(len(g.steps) for g in groups)
    ctx.log(f"목장 시작 — '{setup.source}' 그룹 {len(groups)}개 · 단계 {steps}개"
            f" → 바퀴마다 피로도 확인"
            + (f" ({rounds}바퀴만)" if rounds else " ([정지]까지)"))

    done = 0
    while True:
        ctx.check()
        if rounds and done >= rounds:
            ctx.log(f"목장 끝 — {done}바퀴 돌았습니다.")
            return
        done += 1
        setup.rounds += 1
        if board is not None:
            board.set(목장바퀴=f"{done}바퀴째 (여태 {setup.rounds}번 · "
                              f"피로도 매크로 {setup.fatigue_runs}번)")

        say(ctx, "① 버프", "재사용 대기가 끝난 것만 씁니다")
        ctx.log(f"  {use_buffs(setup, ctx, save)}")

        for group in groups:
            say(ctx, "② 목장", f"{done}바퀴째 — [{group.name}]")
            if not run_group(group, ctx, lookups, done):
                raise Aborted()

        say(ctx, "③ 피로도", f"{done}바퀴째 끝 — 확인합니다")
        ctx.log(f"  피로도: {check_fatigue(setup, ctx, find_rule, find_macro, save)}")

        # ④ N바퀴마다 매크로 한 번 → 그다음 바퀴(시나리오)로
        if setup.every_on and done % setup.every_n == 0:
            say(ctx, "④ 정기 매크로",
                f"{done}바퀴째 — {setup.every_n}바퀴마다 '{setup.every_macro}'")
            run_every(setup, ctx, find_macro, save)


def run_every(setup: RanchSetup, ctx: RunContext, find_macro, save=None) -> None:
    """N바퀴마다 돌리는 매크로를 한 번. 못 찾으면 경고만 하고 이어 간다."""
    macro = setup.every_macro
    if not macro or find_macro(macro) is None:
        ctx.log(f"  ⚠ {setup.every_n}바퀴마다 돌릴 매크로 '{macro or '안 정함'}'을(를) "
                "찾지 못해 건너뜁니다")
        return
    if not _run_macro_step(macro, ctx, find_macro, "  정기 매크로"):
        raise Aborted()
    setup.every_runs += 1
    if save is not None:
        save()


__all__ = ["run_ranch", "use_buffs", "check_fatigue", "activate_game",
           "run_every"]
