"""채광 — 화면을 한 번 누르고 [Ctrl]을 꾹 누른 채 피로도가 찰 때까지 둔다.

    ⓪ 시작       게임 창을 앞으로 → 화면 한복판 클릭 → (대기가 끝난 버프) → [Ctrl] 누름
    ⋯ 누른 채로  피로도를 정한 간격(기본 1분)마다 확인 — [Ctrl]은 떼지 않는다
                 버프 재사용 대기가 끝나면 [Ctrl] 떼고 → [Esc] → 버프 키 → [Esc]
                 → 다시 [Ctrl] 누름
    끝           피로도가 가득(또는 기준값 이상)이면 [Ctrl]을 떼고 멈춘다

버프와 피로도 읽기는 목장과 같은 함수를 쓴다 (z9/ranch.py).
"""

from __future__ import annotations

import re
import time

from .keys import vk_of
from .model import MineSetup
from .player import RunContext
from .ranch import activate_game, fatigue_goal, fatigue_rule, note, say, use_buffs

# 버프 · 피로도 차례가 됐는지 들여다보는 간격(초).
POLL_S = 0.5
_FATIGUE_NOW = re.compile(r"(\d+)\s*/\s*\d+")


class Ctrl:
    """[Ctrl]을 누르고 떼는 것. 눌려 있는지 기억해 두었다가 끝날 때 꼭 뗀다."""

    def __init__(self, ctx: RunContext) -> None:
        self.ctx = ctx
        self.vk = vk_of("Ctrl")
        self.held = False

    def down(self, why: str) -> None:
        if self.held or self.vk is None:
            return
        self.ctx.key_down(self.vk)
        self.held = True
        note(self.ctx, "키 [Ctrl] 누름", why)

    def up(self, why: str) -> None:
        if not self.held or self.vk is None:
            return
        self.ctx.key_up(self.vk)
        self.held = False
        note(self.ctx, "키 [Ctrl] 뗌", why)


def buffs_due(setup: MineSetup, now: float) -> bool:
    return any(b.ready and b.left_s(now) <= 0 for b in setup.buffs)


def full_now(setup: MineSetup, ctx: RunContext, find_rule) -> tuple[bool, str]:
    """피로도가 찼는가. (찼나, 설명). 조건을 못 찾으면 (False, 경고)."""
    from .tasks import evaluate_rule  # 순환 참조를 피해 여기서 가져온다

    rule = find_rule(setup.fatigue_rule) if setup.fatigue_rule else None
    if rule is None:
        return False, f"⚠ 피로도 조건 '{setup.fatigue_rule or '안 정함'}'을(를) 못 찾음"
    note(ctx, "피로도 확인", f"조건 '{rule.name}' · {fatigue_goal(setup)}이면 끝")
    full, detail = evaluate_rule(fatigue_rule(setup, rule), ctx)
    board = getattr(ctx, "board", None)
    if board is not None:
        found = _FATIGUE_NOW.search(detail or "")
        board.set(피로도=(found.group(0) if found else detail)[:60])
    return full, detail


def run_mine(setup: MineSetup, ctx: RunContext, find_rule, save=None) -> None:
    """피로도가 찰 때까지 캔다. [정지]를 누르면 그때 멈춘다."""
    from .craft import click_game_center

    problems = setup.problems()
    if problems:
        ctx.log("채광: 아직 못 정한 것이 있습니다 —")
        for line in problems:
            ctx.log(f"  · {line}")
        return
    board = getattr(ctx, "board", None)
    goal = fatigue_goal(setup)

    say(ctx, "⓪ 시작", "게임 창을 앞으로 세우고 화면을 누릅니다")
    if not activate_game(ctx):
        ctx.log("채광: 게임 창을 앞으로 세우지 못해 시작하지 않습니다.")
        return
    click_game_center(ctx)
    ctx.sleep(0.3)

    ctrl = Ctrl(ctx)
    if ctrl.vk is None:
        ctx.log("채광: [Ctrl] 키를 모릅니다.")
        return
    started = time.perf_counter()
    last = started
    checks = 0
    try:
        if buffs_due(setup, time.time()):
            say(ctx, "버프", "시작 전에 씁니다")
            ctx.log(f"  {use_buffs(setup, ctx, save)}")
        ctrl.down("채광 시작")
        ctx.log(f"채광 시작 — [Ctrl]을 누른 채 {setup.check_s:g}초마다 피로도 확인, "
                f"{goal}이면 끝")
        next_check = time.perf_counter()   # 첫 확인은 바로 (이미 찼을 수도 있다)
        while True:
            ctx.check()
            now = time.perf_counter()
            setup.mined_s += now - last
            last = now

            if buffs_due(setup, time.time()):
                say(ctx, "버프", "[Ctrl] 떼고 씁니다")
                ctrl.up("버프 쓰기 전")
                ctx.sleep(0.1)
                ctx.log(f"  {use_buffs(setup, ctx, save)}")
                ctx.sleep(0.1)
                ctrl.down("버프 쓴 뒤 다시 채광")

            if now >= next_check:
                checks += 1
                say(ctx, "채광", f"피로도 확인 ({checks}번째) — [Ctrl]은 누른 채")
                full, detail = full_now(setup, ctx, find_rule)
                ctx.log(f"  피로도 ({checks}번째): "
                        + (f"{goal} [{detail}]" if full else f"아직 [{detail}]"))
                if full:
                    break
                next_check = time.perf_counter() + setup.check_s

            if board is not None:
                spent = int(time.perf_counter() - started)
                left = max(0, int(next_check - time.perf_counter()))
                board.set(채광=f"{spent // 60}분 {spent % 60}초째 · 다음 확인 "
                               f"{left}초 뒤")
            ctx.sleep(POLL_S)
    finally:
        ctrl.up("채광 끝")
        if save is not None:
            save()
    spent = int(time.perf_counter() - started)
    ctx.log(f"채광 끝 — 피로도 {goal}. {spent // 60}분 {spent % 60}초 캤습니다.")


__all__ = ["run_mine"]
