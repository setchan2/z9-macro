"""낚시 인식 검사 — 돌리기 전에 눈으로 확인하는 창.

설정을 마쳤다고 해서 잘 잡힌다는 보장은 없다. 색 하나가 배경과 비슷하거나
띠가 몇 픽셀 어긋나면, 낚시를 시작해도 **아무 일도 안 일어나고** 왜 그런지
알 길이 없다. 로그에 "못 찾음"이 흘러가도 그때는 이미 늦다.

그래서 실제로 돌리기 전에 **지금 화면을 계속 읽어 보여 주는** 창을 둔다.
막대와 물고기가 좌우로 오가는 것이 숫자로 움직이는지, 체력이 비율로 나오는지,
찌와 낚는 모션이 뜰 때 반응하는지 — 여기서 다 보고 나서 시작하면 된다.

**여기서는 아무것도 누르지 않는다.** 보기만 한다. 그래야 설정이 틀린 채로
엉뚱한 데를 수십 번 클릭하는 일이 없다.

## "겹쳤는데 왜 안 눌렀나"를 짚는다

인식이 멀쩡해 보여도 미니게임에서 클릭이 한 번도 안 나간 적이 있다. 막대가
물고기를 덮으면 물고기 가장자리가 막대 옆으로 물러나, 겹친 폭이 내내 0px 이하로
재졌기 때문이다. 숫자만 보여 주는 창으로는 그걸 못 짚었다.

그래서 이 창은 **실제 판과 똑같은 판정 함수**로 "이 장면이면 누르나, 안 누르면
왜"를 보여 주고, [겹침 진단]은 실제 판과 같은 속도로 몇 초를 몰아 읽어 겹친
구간마다 눌렀을지를 센다. 한 번도 안 누를 구간이 있으면 그 장면을 멈춰 보여 준다.
"""

from __future__ import annotations

import bisect
import time
import tkinter as tk
from tkinter import ttk

from .. import fishing, sound
from ..fishtask import BLIND_LIMIT, HIDE_PX, LiveBoard, spot_count
from ..model import FishingSetup
from . import theme
from .fishpick import MARKS, to_photo

# 다시 읽는 간격(ms). 캡처가 6ms이므로 10Hz면 부담이 거의 없다. 더 빨리 볼
# 이유도 없다 — 사람이 보고 판단하는 창이다.
TICK_MS = 100

# [움직임 재기]가 몰아 읽는 시간(초)과, 겹치는 횟수를 세어 볼 앞날(초).
MEASURE_S = 2.0
CROSS_WINDOW_S = 10.0

# [겹침 진단]이 몰아 읽는 시간(초). 겹침이 1~2초에 한 번이니 몇 번은 보게 된다.
DIAG_S = 6.0

# 클릭 소리가 났을 때, 그 소리를 낸 클릭을 찾아 되짚는 시간(초).
# 소리는 클릭보다 늦게 나고 게임도 조금 늦게 판정한다.
SOUND_LOOKBACK_S = 0.35

SOUND_NAMES = {"hit": "맞음", "miss": "빗나감"}


class FishCheck(tk.Toplevel):
    def __init__(self, parent, engine, setup: FishingSetup) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setup = setup
        self._photo = None
        self._job = None
        self._zoom = 1
        self.ticks = 0
        self.overlaps = 0
        self.seen = {"bar": [None, None], "fish": [None, None]}
        # 폭은 여러 장을 봐야 제대로 잡힌다. 판 하나를 이어 쓴다.
        self._kept = None
        # [겹침 진단]이 멈춰 둔 장면 (그림, 읽은 것, 설명). 있으면 실시간 대신 이것을 그린다.
        self._pinned = None
        self._ear: sound.Ear | None = None
        self._ear_error = ""
        self.line_var = tk.StringVar(value="")
        self.press_var = tk.StringVar(value="")
        self.range_var = tk.StringVar(value="")
        self.spot_var = tk.StringVar(value="")
        self.sound_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="아직 안 쟀습니다 — [움직임 재기]를 "
                                            "누르세요.")
        self.diag_var = tk.StringVar(
            value="미니게임에서 클릭이 안 나가면 [겹침 진단]을 누르세요 — 겹친 "
                  "구간마다 실제 판이 눌렀을지와, 안 눌렀다면 왜인지를 셉니다.")
        self.verdict_var = tk.StringVar(value="")

        self.title("낚시 인식 검사 — 보기만 합니다")
        self.transient(parent)

        outer = ttk.Frame(self, padding=theme.pad(10))
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        ttk.Label(
            outer, style="Faint.TLabel", justify="left", wraplength=theme.px(820),
            text=("미니게임을 띄워 두고 이 창을 보세요. 막대와 물고기의 숫자가 "
                  "좌우로 오가고, 체력이 %로 나오면 제대로 잡힌 것입니다. "
                  "여기서는 클릭하지 않습니다 — 직접 눌러 보면 클릭 소리로 "
                  "게임 판정과 맞춰 봅니다."),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        wrap = ttk.Frame(outer)
        wrap.grid(row=1, column=0, sticky="nsew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(wrap, background="#101010", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        hbar = ttk.Scrollbar(wrap, orient="horizontal", command=self.canvas.xview)
        hbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=hbar.set)

        rows = (
            (self.line_var, "Heading.TLabel"),
            (self.press_var, "TLabel"),
            (self.range_var, "TLabel"),
            (self.spot_var, "TLabel"),
            (self.sound_var, "TLabel"),
            (self.model_var, "TLabel"),
            (self.diag_var, "TLabel"),
            (self.verdict_var, "Faint.TLabel"),
        )
        for row, (var, style) in enumerate(rows, start=2):
            ttk.Label(outer, textvariable=var, style=style, justify="left",
                      wraplength=theme.px(820)).grid(
                row=row, column=0, sticky="w", pady=(6 if row == 2 else 2, 0))

        foot = ttk.Frame(outer)
        foot.grid(row=2 + len(rows), column=0, sticky="e", pady=(10, 0))
        ttk.Button(foot, text="겹침 진단", style="Accent.TButton",
                   command=self._diagnose).pack(side="left", padx=(0, 6))
        ttk.Button(foot, text="움직임 재기", command=self._measure).pack(
            side="left", padx=(0, 6))
        self.pin_btn = ttk.Button(foot, text="멈춘 장면 풀기",
                                  style="Small.TButton", command=self._unpin)
        self.pin_btn.pack(side="left", padx=(0, 6))
        self.pin_btn.state(["disabled"])
        ttk.Button(foot, text="관찰값 지우기", style="Small.TButton",
                   command=self._reset).pack(side="left", padx=(0, 6))
        ttk.Button(foot, text="닫기", command=self.close).pack(side="left")

        self.protocol("WM_DELETE_WINDOW", self.close)
        self.geometry(theme.scale_geometry("900x680", parent))
        self._open_ear()
        self._tick()

    # ------------------------------------------------------------------
    def _reset(self) -> None:
        self.ticks = self.overlaps = 0
        self.seen = {"bar": [None, None], "fish": [None, None]}
        self._kept = None
        self._unpin()

    def _unpin(self) -> None:
        self._pinned = None
        self.pin_btn.state(["disabled"])

    def close(self) -> None:
        self.destroy()

    def destroy(self) -> None:
        # 부모가 창을 부숴도 여기로 온다. 귀를 안 거두면 소리 장치를 계속 붙잡는다.
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
        if self._ear is not None:
            self._ear.close()
            self._ear = None
        super().destroy()

    def _board(self):
        """읽기 전용 판. 창과 정지 신호가 없어도 되는 껍데기 맥락을 쓴다.

        한 번 만든 것을 이어 쓴다 — 폭은 여러 장을 봐야 제대로 잡히는데,
        볼 때마다 새로 만들면 매번 처음부터 재게 된다.
        """
        window = self.engine.window()
        if window is None:
            return None
        got = getattr(self, "_kept", None)
        if got is not None and got.rect == self.setup.board_rect(window):
            return got

        board = LiveBoard.reader(self.setup, window)
        self._kept = board
        return board

    def _share(self) -> float:
        """실제 판이 쓰는 배수. 배우기를 껐으면 1.0(닿기만 하면 누름)이다."""
        if not self.setup.learn_hit:
            return 1.0
        return fishing.Ratio().load(self.setup.ratio_stats).best

    def _tick(self) -> None:
        # 다음 차례를 잡기 전에 이미 잡아 둔 것을 반드시 취소한다. 안 그러면
        # _tick을 밖에서 한 번 더 부를 때마다 타이머 사슬이 하나씩 늘어나고,
        # 늘어난 사슬은 어디서도 못 멈춘다 (검사에서 초당 50번씩 읽혔다).
        if self._job is not None:
            self.after_cancel(self._job)
        self._job = self.after(TICK_MS, self._tick)
        self.sound_var.set(self._sound_text())
        if self._pinned is not None:
            return  # 진단이 멈춰 둔 장면을 보는 중이다
        board = self._board()
        if board is None or board.rect is None:
            self.line_var.set("게임 창이나 판 영역이 없습니다.")
            return
        frame = board.snapshot()
        if frame is None:
            self.line_var.set("판을 찍지 못했습니다.")
            return

        got = board.look(frame)
        self.ticks += 1
        share = self._share()
        press, why = self._judge(got, board, share)
        if press:
            self.overlaps += 1
        for role, value in (("bar", got.bar), ("fish", got.fish)):
            if value is None:
                continue
            slot = self.seen[role]
            slot[0] = value if slot[0] is None else min(slot[0], value)
            slot[1] = value if slot[1] is None else max(slot[1], value)

        self._draw(frame, got)
        self.line_var.set(got.describe(board.hit_px))
        self.press_var.set(self._press_text(press, why, share))

        def span(role):
            lo, hi = self.seen[role]
            if lo is None:
                return "아직 못 봄"
            return f"{lo:.0f} ~ {hi:.0f} (폭 {hi - lo:.0f}px)"

        self.range_var.set(
            f"지금까지 본 범위 — 막대 {span('bar')} · 물고기 {span('fish')}   "
            f"· 읽은 횟수 {self.ticks} · 누를 장면 {self.overlaps}")

        self.spot_var.set(self._extras_text() + "   ·   " + self._hit_text(board))
        self.verdict_var.set(self._verdict(got))

    # -- 누를지 --------------------------------------------------------
    def _judge(self, got, board, share: float) -> tuple[bool | None, str]:
        """실제 판이 **이 한 장**을 보고 누를지와 그 이유. 모르면 None.

        판정은 [fishing.press_decision]을 그대로 부른다. 여기서 따로 셈하면 검사와
        실제가 어긋나고, 그러면 검사가 아무것도 못 짚는다.
        """
        if got.bar is None and got.fish is None:
            return (False, "막대·물고기를 둘 다 못 찾음 — 미니게임이 떠 있는지, "
                           "색·허용차·영역을 보세요")
        if got.bar is None or got.fish is None:
            who = "막대" if got.bar is None else "물고기"
            return (None, f"{who}를 못 찾음 — 겹쳐서 가려진 것이면 실제 판은 "
                          f"직전 {fishing.HIDDEN_S:g}초 안에 닿은 것을 봤을 때만 "
                          f"이어 누릅니다")
        if got.touch is None:
            near = board.hit_px * share
            press = got.gap <= near
            return (press, f"폭이 오염돼 가장자리를 안 씀 → 가운데 거리 "
                           f"{got.gap:.0f}px {'≤' if press else '>'} {near:.0f}px")
        bar_w, fish_w = board._width["bar"], board._width["fish"]
        press, need = fishing.press_decision(got.touch, bar_w, fish_w, share)
        if press:
            text = f"겹친 폭 {got.touch:.0f}px ≥ 필요 {need:.0f}px"
            if got.filled and got.raw_touch is not None and got.raw_touch < need:
                text += (f" — {got.filled}: 메우지 않았다면 {got.raw_touch:.0f}px라 "
                         f"못 눌렀을 장면")
            return (True, text)
        if got.touch >= -HIDE_PX:
            why = (f"안 메운 까닭: {got.hint}" if got.hint
                   else f"가려진 부분을 못 메웠거나 배수({share:.1f})가 좁습니다")
            return (False, f"붙어 있는데 겹친 폭 {got.touch:.0f}px < 필요 "
                           f"{need:.0f}px — {why}")
        return (False, f"{-got.touch:.0f}px 떨어짐")

    @staticmethod
    def _press_text(press, why: str, share: float) -> str:
        mark = {True: "● 누름", False: "○ 안 누름", None: "? 모름"}[press]
        return f"실제 판이라면 → {mark} — {why}   (배수 {share:.1f} 기준)"

    # -- 소리 ----------------------------------------------------------
    def _click_cues(self) -> dict:
        s = self.setup
        return {name: (c.shape, c.near, c.floor, c.hits)
                for name, c in (("hit", s.hit_sound), ("miss", s.miss_sound))
                if c.ready}

    def _open_ear(self) -> None:
        """클릭 소리를 배워 뒀으면 듣기 시작한다. 못 들어도 검사는 된다."""
        if not self._click_cues():
            return
        ear = sound.Ear(sound.game_pid(self.engine.window()))
        try:
            ear.open()
        except sound.SoundError as exc:
            self._ear_error = str(exc)
            return
        self._ear = ear

    def _sound_text(self) -> str:
        if not self._click_cues():
            return ("클릭 소리 안 배움 — 낚시 탭의 [6-1 맞음]·[6-2 빗나감]을 배워 "
                    "두면, 게임이 클릭을 받는지 소리로 확인할 수 있습니다")
        if self._ear is None and not self._ear_error:
            self._open_ear()  # 창을 연 뒤에 배웠다
        if self._ear is None:
            return f"⚠ 클릭 소리를 못 듣습니다 — {self._ear_error or '귀를 못 열었음'}"
        now = time.perf_counter()
        frames = self._ear.recent(now - 3.0)
        level = max((f[1] for f in frames), default=0.0)
        got = {"hit": 0, "miss": 0}
        for _when, label, _score in sound.events(frames, self._click_cues()):
            got[label] += 1
        return (f"클릭 소리 (최근 3초) — 맞음 {got['hit']}번 · 빗나감 "
                f"{got['miss']}번 · 소리 크기 {level:.3f}   (직접 눌러 보세요)")

    # ------------------------------------------------------------------
    def _extras_text(self) -> str:
        """성공 알림 — 색으로 본다."""
        setup = self.setup
        window = self.engine.window()
        parts = []
        if not setup.notice.ready:
            parts.append("성공 알림 안 정함 (낚은 수를 세지 않습니다)")
        else:
            count = spot_count(setup.notice, window)
            mark = "● 떴음" if count >= setup.notice.min_px else "○ 안 뜸"
            parts.append(f"성공 알림 {mark} ({count}/{setup.notice.min_px}칸)")
        popup = setup.stack_popup
        if popup.ready:
            count = spot_count(popup, window)
            mark = "● 떴음 → Esc" if count >= popup.min_px else "○ 안 뜸"
            parts.append(f"버프 중첩 알림 {mark} ({count}/{popup.min_px}칸)")
        elif setup.buff_mode:
            parts.append("버프 중첩 알림 안 정함")
        parts.append(f"연타할 자리 {setup.tap_w}×{setup.tap_h}"
                     if setup.tap_w > 0 else "연타할 자리 안 정함")
        return "   ·   ".join(parts)

    def _hit_text(self, board) -> str:
        """지금 잰 폭과 거기서 나온 겹침 거리."""
        bar_w = board._width["bar"]
        fish_w = board._width["fish"]
        if bar_w <= 0 or fish_w <= 0:
            return "폭을 아직 못 쟀습니다"
        how = (f"(배운 배수 {self._share():.1f})" if self.setup.learn_hit
               else "(비율 %g)" % self.setup.hit_ratio
               if self.setup.hit_mode == "auto" else "(직접 정한 값)")
        return (f"온전한 폭 — 막대 {bar_w:.0f}px · 물고기 {fish_w:.0f}px "
                f"→ 겹쳤다고 볼 거리 {board.hit_px:.0f}px {how}")

    # ------------------------------------------------------------------
    def _diagnose(self) -> None:
        """실제 판과 같은 속도로 몰아 읽으며 **겹친 구간마다 눌렀을지** 센다.

        10Hz로 보는 창에서는 겹침(몇십~몇백 ms)을 거의 못 본다. 그래서 실제 판처럼
        쉬지 않고 읽고, 한 장 한 장을 실제 판정 함수에 넣어 본다.

            붙은 구간   두 물체가 붙어 있던(겹친 폭 ≥ -6px) 이어진 장들
            누를 구간   그중 한 장이라도 누름 판정이 난 구간

        붙은 구간인데 한 번도 안 누를 판정이면 그게 "겹쳤는데 클릭이 안 나간" 순간이다.
        그 이유를 모아서 알려 주고, 첫 장면을 멈춰 보여 준다.
        """
        board = self._board()
        if board is None or board.rect is None:
            self.diag_var.set("게임 창이나 판 영역이 없습니다.")
            return
        self._unpin()
        self.diag_var.set(f"{DIAG_S:g}초 동안 실제 판과 같은 속도로 읽는 중… "
                          "(미니게임을 띄워 두세요)")
        self.update_idletasks()

        share = self._share()
        count = {"frames": 0, "both": 0, "no_bar": 0, "no_fish": 0, "none": 0,
                 "press": 0, "filled": 0, "health_zero": 0}
        runs: list[dict] = []  # 붙은 구간마다 {장, 누름, 예전누름, 이유}
        run = None
        gap_frames = 0  # 붙은 구간 안에서 하나가 안 보인 채 이어진 장 수
        timeline_t: list[float] = []
        timeline_press: list[bool] = []
        pin = None
        dark = worst_dark = 0  # 미니게임 근거가 안 보인 채 이어진 장 수
        saw_health = False
        wide_before = sum(board._wide.values())

        started = time.perf_counter()
        while time.perf_counter() - started < DIAG_S:
            frame = board.snapshot()
            if frame is None:
                break
            when = time.perf_counter()
            got = board.look(frame)
            count["frames"] += 1

            dark = 0 if board.signals(got) else dark + 1
            worst_dark = max(worst_dark, dark)
            if got.health > 0:
                saw_health = True
            elif saw_health:
                count["health_zero"] += 1

            press, why = self._judge(got, board, share)
            timeline_t.append(when)
            timeline_press.append(bool(press))
            if press:
                count["press"] += 1

            if got.bar is None or got.fish is None:
                key = ("none" if got.bar is None and got.fish is None
                       else "no_bar" if got.bar is None else "no_fish")
                count[key] += 1
                # 붙어 가다가 하나가 사라졌으면 가려진 것이다. 구간을 이어 준다.
                if run is not None and gap_frames < 60:
                    gap_frames += 1
                    run["frames"] += 1
                    label = ("막대 안 보임(가려짐?)" if got.bar is None
                             else "물고기 안 보임(가려짐?)")
                    run["why"][label] = run["why"].get(label, 0) + 1
                else:
                    run = None
                continue

            count["both"] += 1
            if got.filled:
                count["filled"] += 1
            if got.touch is not None:
                contact = got.touch >= -HIDE_PX
                old = fishing.press_decision(
                    got.raw_touch, board._width["bar"], board._width["fish"],
                    share)[0]
            else:
                contact = bool(press)
                old = bool(press)
            if not contact:
                run = None
                continue
            if run is None:
                run = {"frames": 0, "press": 0, "old": 0, "why": {},
                       "reached": False}
                runs.append(run)
            gap_frames = 0
            run["frames"] += 1
            # **정말 겹쳤던 구간인가.** 6px 안까지 다가왔다가 돌아선 것까지 "안 누른
            # 구간"으로 세면 멀쩡한 판에도 ⚠가 뜬다. 가장자리는 가림에 속으므로
            # 가운데 거리와 온전한 폭으로 본다.
            reach = (board._width["bar"] + board._width["fish"]) / 2.0
            if got.gap is not None and reach > 0 and got.gap <= reach:
                run["reached"] = True
            run["press"] += 1 if press else 0
            run["old"] += 1 if old else 0
            if not press:
                label = "붙었는데 문턱 미달"
                run["why"][label] = run["why"].get(label, 0) + 1
                # 구간마다 **가장 깊이 물린** 안 누른 장을 들고 있는다. 다가오는 첫
                # 장(몇 px 떨어짐)을 보여 주면 정작 겹친 모습이 안 보인다.
                if "pin" not in run or got.touch is None or (
                        run["pin"][1].touch is not None
                        and got.touch > run["pin"][1].touch):
                    run["pin"] = (frame, got, why)
        took = max(0.001, time.perf_counter() - started)

        frames = max(1, count["frames"])

        def pct(key):
            return f"{count[key] * 100 // frames}%"

        lines = [f"겹침 진단 — {took:.1f}초에 {count['frames']}장 (초당 "
                 f"{count['frames'] / took:.0f}장) · 배수 {share:.1f} 기준",
                 f"  둘 다 보임 {pct('both')} · 막대 못 찾음 {pct('no_bar')} · "
                 f"물고기 못 찾음 {pct('no_fish')} · 둘 다 못 찾음 {pct('none')}"]
        if not runs:
            lines.append("  ⚠ 한 번도 붙지 않았습니다 — 미니게임이 떠 있었는지, "
                         "막대·물고기를 제대로 찾는지 보세요")
        else:
            pressed = [r for r in runs if r["press"]]
            old = [r for r in runs if r["old"]]
            lines.append(
                f"  붙은 구간 {len(runs)}번 → 실제 판이 누르는 구간 {len(pressed)}번 "
                f"· 구간마다 누를 장 수 "
                + ", ".join(str(r["press"]) for r in runs[:15]))
            if count["filled"]:
                lines.append(
                    f"  가려진 부분을 메운 장 {count['filled']}장 — 메우지 않았다면"
                    f"(예전 방식) 누르는 구간은 {len(old)}번이었습니다")
            dead = [r for r in runs if not r["press"] and r["reached"]]
            # 멈춰 보여 줄 장면은 **한 번도 안 누를 구간**에서만 고른다. 누른
            # 구간의 다가오는 장면을 보여 주면 멀쩡한 것을 문제처럼 보이게 한다.
            pin = next((r["pin"] for r in dead if "pin" in r), None)
            if dead:
                why: dict[str, int] = {}
                for r in dead:
                    for key, n in r["why"].items():
                        why[key] = why.get(key, 0) + n
                top = sorted(why.items(), key=lambda kv: -kv[1])[:3]
                lines.append(
                    f"  ⚠ 겹쳤는데 한 번도 안 누를 구간 {len(dead)}번 — 이유: "
                    + " · ".join(f"{k} {n}장" for k, n in top))
            if count["no_bar"] or count["no_fish"]:
                lines.append(
                    "  (한쪽이 안 보인 장은 누름으로 안 셌습니다 — 실제 판은 그동안 "
                    "직전 기억과 움직임 모델로 누를 수 있어 조금 더 누릅니다)")
        if count["health_zero"]:
            lines.append(
                f"  ⚠ 체력이 0%로 읽힌 장 {count['health_zero']}장 — 실제 판은 이것을 "
                "'다 깎았다'로 보고 곧바로 판을 끝냅니다(그 뒤로 안 누름). 체력 "
                "게이지 색·영역을 보세요")
        if worst_dark >= BLIND_LIMIT:
            lines.append(
                f"  ⚠ 미니게임 근거가 {worst_dark}장 이어서 안 보였습니다 — 실제 판은 "
                f"{BLIND_LIMIT}장이면 창이 닫힌 것으로 보고 끝냅니다")
        wide = sum(board._wide.values()) - wide_before
        if wide:
            lines.append(f"  ⚠ 폭이 트랙 절반을 넘게 잡힌 장 {wide}장 — 색이 배경에 "
                         "걸립니다. 허용차를 줄이거나 색을 다시 고르세요")
        lines.extend(self._sound_report(started, time.perf_counter(),
                                        timeline_t, timeline_press))
        self.diag_var.set("\n".join(lines))

        if pin is not None:
            frame, got, why = pin
            self._pinned = pin
            self.pin_btn.state(["!disabled"])
            self._draw(frame, got)
            self.line_var.set("📌 멈춘 장면 (붙었는데 안 누를 장) — " + got.describe(
                board.hit_px))
            self.press_var.set(self._press_text(False, why, share))

    def _sound_report(self, started, ended, times, presses) -> list[str]:
        """진단하는 동안 난 클릭 소리를 **그 순간 우리 판정**과 맞춰 본다.

        사람이 직접 눌렀을 때 게임은 소리로 답한다. 맞음 소리가 났는데 우리가 안
        겹쳤다고 봤다면 인식이 좁은 것이고, 빗나감 소리가 났는데 우리가 겹쳤다고
        봤다면 넓은 것이다. 게임 판정과 바로 견줄 수 있는 유일한 길이다.
        """
        cues = self._click_cues()
        if not cues or self._ear is None:
            return []
        # 마지막 클릭의 소리가 들어올 틈을 준다. 안 기다리면 여유를 둔 뜻이 없다.
        left = ended + SOUND_LOOKBACK_S - time.perf_counter()
        if left > 0:
            time.sleep(left)
        frames = [f for f in self._ear.recent(started)
                  if f[0] <= ended + SOUND_LOOKBACK_S]
        heard = sound.events(frames, cues)
        if not heard:
            return ["  클릭 소리 0번 — 진단하는 동안 직접 눌러 보면 게임 판정과 "
                    "우리 판정을 맞춰 봅니다"]
        tally = {name: [0, 0] for name in SOUND_NAMES}  # [우리도 누름, 우리는 안 누름]
        for when, label, _score in heard:
            lo = bisect.bisect_left(times, when - SOUND_LOOKBACK_S)
            hi = bisect.bisect_right(times, when)
            agreed = any(presses[lo:hi])
            tally[label][0 if agreed else 1] += 1
        out = []
        hit_yes, hit_no = tally["hit"]
        miss_yes, miss_no = tally["miss"]
        if hit_yes or hit_no:
            out.append(f"  맞음 소리 {hit_yes + hit_no}번 — 그 순간 우리 판정: 누름 "
                       f"{hit_yes} · 안 누름 {hit_no}")
            if hit_no:
                out.append("    ⚠ 게임은 겹쳤다는데 우리는 안 겹쳤다고 본 적이 "
                           "있습니다 — 인식이 좁습니다")
        if miss_yes or miss_no:
            out.append(f"  빗나감 소리 {miss_yes + miss_no}번 — 그 순간 우리 판정: "
                       f"누름 {miss_yes} · 안 누름 {miss_no}")
            if miss_yes:
                out.append("    ⚠ 게임은 빗나갔다는데 우리는 겹쳤다고 본 적이 "
                           "있습니다 — 인식이 넓습니다")
        return out

    # ------------------------------------------------------------------
    def _measure(self) -> None:
        """빠르게 몰아 읽어 **움직임 모델**을 세우고 그 값을 보여 준다.

        10Hz로 보는 이 창에서 "겹친 순간 0회"가 나오는 것은 정상이다. 실제로
        겹치는 시간은 몇십 ms뿐이라 0.1초마다 들여다봐서는 거의 못 본다.
        **본 횟수가 아니라 속도와 주기를 재야** 얼마나 자주 겹치는지 알 수 있다.
        """
        board = self._board()
        if board is None or board.rect is None:
            self.model_var.set("게임 창이나 판 영역이 없습니다.")
            return
        bar, fish = [], []
        shots = 0
        fresh = 0        # 앞 장과 **다른** 그림이었던 횟수
        prev = None
        started = time.perf_counter()
        while time.perf_counter() - started < MEASURE_S:
            frame = board.snapshot()
            if frame is None:
                break
            shots += 1
            if prev is not None and frame.buf != prev:
                fresh += 1
            prev = frame.buf
            got = board.look(frame)
            when = time.perf_counter()
            if got.bar is not None:
                bar.append((when, got.bar))
            if got.fish is not None:
                fish.append((when, got.fish))
        reads = max(len(bar), len(fish))
        if reads < 8:
            self.model_var.set(
                f"{MEASURE_S:g}초 동안 {reads}번밖에 못 읽었습니다. "
                "색과 영역을 먼저 맞춰 주세요.")
            return

        took = max(0.001, time.perf_counter() - started)
        rate = reads / took
        shot_rate = shots / took
        fresh_rate = fresh / took
        lines = [f"{MEASURE_S:g}초에 {reads}번 읽음 (초당 {rate:.0f}장)"]
        # **게임이 실제로 몇 장을 그리는가.** 우리가 읽는 속도가 아니라 이쪽이
        # 인식의 한계를 정한다.
        if shots:
            same = 100 * (1 - fresh / max(1, shots - 1))
            lines.append(
                f"→ 화면을 초당 {shot_rate:.0f}장 찍었고 그중 새 그림은 "
                f"초당 {fresh_rate:.0f}장 (같은 그림 {same:.0f}%)")
            if same >= 30:
                lines.append(
                    "   게임이 우리보다 느리게 그립니다 — 더 빨리 읽어도 "
                    "얻을 것이 없습니다. 같은 그림을 두 번 보게 될 뿐입니다.")
            else:
                lines.append(
                    "   화면이 우리만큼 빨리 바뀝니다 — 판 영역을 좁히면 더 "
                    "많이 읽을 수 있습니다.")
        models = {}
        for name, samples, key in (("막대", bar, "bar"), ("물고기", fish, "fish")):
            lo = min(x for _t, x in samples) if samples else 0
            hi = max(x for _t, x in samples) if samples else 0
            motion = fishing.fit_motion(samples, lo, hi) if len(samples) >= 8 else None
            models[key] = motion
            if motion is None:
                lines.append(f"{name}: 모델을 못 세움")
                continue
            # 왕복 주기는 **한 바퀴를 다 봐야** 맞는다. 2초 안에 한쪽 끝만
            # 봤다면 폭이 작게 잡히고 주기도 그만큼 짧게 나온다. 속도는 그래도
            # 맞으므로, 주기만 조심하라고 적어 둔다.
            track = max(1, self.setup.track_x1 - self.setup.track_x0)
            partial = (hi - lo) < track * 0.6
            note = " (한쪽만 봤습니다 — 주기는 더 지켜봐야 합니다)" if partial else ""
            lines.append(
                f"{name}: {motion.speed * 1000:.0f}px/초 · 왕복 "
                f"{motion.cycle_ms / 1000:.2f}초 · {lo:.0f}~{hi:.0f}px · "
                f"어긋남 {motion.residual:.1f}px{note}")
        got_bar, got_fish = models.get("bar"), models.get("fish")
        if got_bar and got_fish:
            crossings = self._count_crossings(got_bar, got_fish)
            lines.append(
                f"→ 계산상 {CROSS_WINDOW_S:g}초에 {crossings}번 겹칩니다 "
                f"(약 {CROSS_WINDOW_S / max(1, crossings):.1f}초에 한 번)")

            # **여기가 사람이 가장 궁금해하는 대목이다.** 겹쳐 있는 시간이
            # 몇 ms인지, 그 사이에 몇 번이나 보고 누를 수 있는지.
            hit = board.hit_px
            rel = abs(got_bar.speed) + abs(got_fish.speed)  # 최악(마주 올 때)
            if hit > 0 and rel > 0.0001:
                window_ms = 2.0 * hit / rel
                cycle_ms = 1000.0 / rate
                chances = window_ms / cycle_ms
                lines.append(
                    f"→ 마주 올 때 겹쳐 있는 시간 {window_ms:.0f}ms · "
                    f"한 장 읽는 데 {cycle_ms:.0f}ms "
                    f"→ 그 사이 {chances:.1f}번 보고 누를 수 있습니다")
                if chances < 2.0:
                    lines.append(
                        "⚠ 두 번도 못 누릅니다. 물체가 너무 빠르거나 겹침 거리가 "
                        "좁습니다 — [겹침 거리]의 비율을 1.0으로 두고, 판 영역을 "
                        "더 좁게 잡아 읽기를 빠르게 해 보세요.")
                elif chances < 4.0:
                    lines.append("(넉넉하지는 않습니다. 판 영역을 좁히면 "
                                 "읽기가 빨라집니다.)")
        self.model_var.set("\n".join(lines))

    def _count_crossings(self, bar, fish) -> int:
        """앞으로 얼마 동안 몇 번 겹치는지 세어 본다."""
        now = bar.at
        end = now + CROSS_WINDOW_S
        count = 0
        at = now
        for _ in range(400):
            shot = fishing.next_crossing(bar, fish, at, self.setup.hit_px,
                                         horizon_ms=(end - at) * 1000.0)
            if shot is None or shot.when > end:
                break
            count += 1
            at = shot.when + 0.02
        return count

    def _verdict(self, got) -> str:
        """지금 이대로 돌리면 될지 한 줄로."""
        bad = []
        if got.bar is None:
            bad.append("막대를 못 찾습니다 — 색이나 허용차, 트랙 영역을 보세요")
        if got.fish is None:
            bad.append("물고기를 못 찾습니다 — 흰 몸통을 찍었는지 확인하세요")
        if got.health <= 0:
            bad.append("체력이 0%로 읽힙니다 — 게이지 색과 영역을 보세요 (판 도중 "
                       "0%로 읽히면 실제 판은 다 깎은 줄 알고 곧바로 끝냅니다)")
        lo, hi = self.seen["bar"]
        if lo is not None and self.ticks > 30 and (hi - lo) < 5:
            bad.append("막대가 움직이지 않습니다 — 미니게임이 떠 있는지 보세요")
        if bad:
            return "⚠ " + " / ".join(bad)
        return ("인식은 됩니다. 클릭이 안 나가면 [겹침 진단]으로 겹친 구간마다 "
                "눌렀을지 보세요 (이 창은 0.1초마다 보므로 겹친 순간을 거의 "
                "못 봅니다).")

    def _draw(self, frame, got) -> None:
        zoom = max(1, min(3, theme.px(560) // max(1, frame.w)))
        self._zoom = zoom
        self._photo = to_photo(frame)
        if zoom > 1:
            self._photo = self._photo.zoom(zoom, zoom)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self.canvas.configure(scrollregion=(0, 0, frame.w * zoom, frame.h * zoom))

        s = self.setup
        z = zoom
        for box, color in ((s.track_box(), MARKS["bar"]),
                           (s.health_box(), MARKS["health"]),
                           (s.time_box(), MARKS["time"])):
            x0, x1, y0, y1 = box
            if x1 > x0 and y1 > y0:
                self.canvas.create_rectangle(x0 * z, y0 * z, x1 * z, y1 * z,
                                             outline=color, width=1)
        ty0, ty1 = s.track_y0, s.track_y1
        for role, value in (("bar", got.bar), ("fish", got.fish)):
            if value is None:
                continue
            self.canvas.create_line(value * z, (ty0 - 8) * z, value * z,
                                    (ty1 + 8) * z, fill=MARKS[role], width=3)
        # 판정에 쓴 **가장자리**를 가로줄로 긋는다. 막대는 트랙 위, 물고기는 아래.
        # 가려진 부분을 메웠으면 그 사실도 적는다 — 겹친 폭이 어디서 나왔는지
        # 눈으로 보여야 "왜 안 눌렀나"를 짚을 수 있다.
        for role, lo, hi, y in (("bar", got.bar_lo, got.bar_hi, ty0 - 4),
                                ("fish", got.fish_lo, got.fish_hi, ty1 + 4)):
            if lo is None or hi is None:
                continue
            self.canvas.create_line(lo * z, y * z, hi * z, y * z,
                                    fill=MARKS[role], width=3)
        if got.filled:
            self.canvas.create_text(
                (s.track_x0 + 4) * z, (ty1 + 10) * z, anchor="nw",
                fill="#ffffff", text=got.filled + " → 메움")
        # 체력이 어디까지 남았는지 세로선으로 표시한다.
        if got.health > 0 and s.health_x1 > s.health_x0:
            edge = s.health_x0 + got.health * (s.health_x1 - s.health_x0)
            self.canvas.create_line(edge * z, s.health_y0 * z, edge * z,
                                    s.health_y1 * z, fill="#ffffff", width=2)
