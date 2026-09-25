"""낚시 기록 — 무엇을 어떻게 했더니 얼마나 빨리 낚았는지 남긴다.

**고치려면 재야 한다.** 지금까지는 설정을 바꿔 보고 "좀 나아진 것 같다"로 판단했는데,
낚시는 한 판에 몇십 초씩 걸리고 운도 섞여서 몇 판 봐서는 알 수 없다. 그래서 돌아가는
동안 있었던 일을 그대로 적어 둔다.

가장 중요한 값은 **낚음 주기** — 한 마리 낚고 다음 마리 낚기까지 걸린 시간이다.
이것이 짧아지는 쪽이 곧 좋아진 것이다. 클리어율도 명중률도 결국 여기로 모인다.

한 줄에 한 가지 일(JSON Lines). 이렇게 두면

  · 돌아가는 도중에 죽어도 그때까지가 남는다 (한 줄씩 바로 내려쓴다)
  · 나중에 몇 줄이든 붙여 읽을 수 있다
  · 사람이 그냥 열어 봐도 읽힌다

파일은 세션마다 하나씩 새로 만든다. 설정을 바꿔 가며 돌린 것들을 뒤섞지 않으려는
것이다 — 무엇 때문에 좋아졌는지 가리려면 갈라 두어야 한다.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

# 한 번에 열어 둘 파일 이름의 생김새.
STAMP = "%Y%m%d-%H%M%S"


class FishLog:
    """한 세션의 기록. 쓰다가 무슨 일이 나도 낚시를 멈추지 않는다.

    **기록이 낚시를 방해하면 안 된다.** 디스크가 꽉 찼든 폴더가 없든, 여기서
    터져서 낚시가 멈추는 것이 훨씬 큰 손해다. 그래서 모든 쓰기를 감싸 두고,
    한 번 실패하면 조용히 그만둔다.
    """

    def __init__(self, folder: Path | str, name: str = "fishing") -> None:
        self.folder = Path(folder)
        self.path: Path | None = None
        self.dead = False
        self.started = time.perf_counter()
        self.last_catch: float | None = None
        self.rounds = 0
        self.catches = 0
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime(STAMP)
            self.path = self.folder / f"{name}-{stamp}.jsonl"
        except OSError:
            self.dead = True

    # -- 쓰기 --------------------------------------------------------------
    def write(self, kind: str, **fields) -> None:
        """한 가지 일을 한 줄로 남긴다."""
        if self.dead or self.path is None:
            return
        row = {
            "kind": kind,
            "at": datetime.now().isoformat(timespec="milliseconds"),
            "s": round(time.perf_counter() - self.started, 3),
        }
        row.update(fields)
        try:
            with self.path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        except (OSError, TypeError, ValueError):
            # 한 번 안 되면 그 뒤로는 안 쓴다. 매 판마다 실패를 되풀이할 까닭이 없다.
            self.dead = True

    def caught(self, reason: str, **fields) -> float | None:
        """한 마리 낚았다. **직전 낚음과의 간격**을 함께 남긴다.

        이 간격이 곧 낚음 주기다. 첫 마리는 견줄 것이 없으므로 None.
        """
        now = time.perf_counter()
        cycle = None if self.last_catch is None else round(
            now - self.last_catch, 2)
        self.last_catch = now
        self.catches += 1
        self.write("caught", reason=reason, cycle_s=cycle,
                   nth=self.catches, **fields)
        return cycle

    def round_done(self, result, **fields) -> None:
        """미니게임 한 판이 끝났다."""
        self.rounds += 1
        self.write(
            "round", nth=self.rounds, outcome=result.outcome,
            seconds=round(result.seconds, 2), shots=result.shots,
            clicks=result.clicks, hits=result.hits, misses=result.misses,
            hit_px=round(result.hit_px, 1), ratio=round(result.ratio, 2),
            lead_ms=round(result.lead_ms, 1), **fields)


# --------------------------------------------------------------------------
# 읽기 — 남긴 것을 사람이(그리고 내가) 읽을 수 있게
# --------------------------------------------------------------------------
def read(path: Path | str) -> list[dict]:
    """기록 한 파일을 줄줄이 읽는다. 깨진 줄은 건너뛴다."""
    out = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # 쓰다 만 줄. 마지막 한 줄에서 흔하다.
    return out


def sessions(folder: Path | str) -> list[Path]:
    """기록 파일들. 새것부터."""
    try:
        got = sorted(Path(folder).glob("*.jsonl"))
    except OSError:
        return []
    return list(reversed(got))


def _mid(values: list[float]) -> float:
    if not values:
        return 0.0
    got = sorted(values)
    n = len(got)
    return got[n // 2] if n % 2 else (got[n // 2 - 1] + got[n // 2]) / 2.0


def digest(rows: list[dict]) -> dict:
    """한 세션에서 뽑아 낼 것들. 핵심은 **낚음 주기**다."""
    head = next((r for r in rows if r["kind"] == "start"), {})
    cycles = [r["cycle_s"] for r in rows
              if r["kind"] == "caught" and r.get("cycle_s")]
    rounds = [r for r in rows if r["kind"] == "round"]
    clears = [r for r in rounds if r.get("outcome") == "clear"]
    catches = [r for r in rows if r["kind"] == "caught"]
    spans = [r["seconds"] for r in rounds if r.get("seconds")]
    last = rows[-1] if rows else {}
    return {
        "setup": head.get("setup", {}),
        "learned": head.get("learned", {}),
        "minutes": round(last.get("s", 0.0) / 60.0, 1),
        "catches": len(catches),
        "cycle_mid": round(_mid(cycles), 1),
        "cycle_min": round(min(cycles), 1) if cycles else 0.0,
        "cycle_n": len(cycles),
        "rounds": len(rounds),
        "clear_rate": round(len(clears) / len(rounds), 3) if rounds else 0.0,
        "round_mid": round(_mid(spans), 1),
        "clicks_mid": round(_mid([r.get("clicks", 0) for r in rounds]), 1),
        "ratio_end": rounds[-1].get("ratio") if rounds else None,
        "lead_end": rounds[-1].get("lead_ms") if rounds else None,
        "reasons": _tally(r.get("reason", "?") for r in catches),
        "nudges": sum(1 for r in rows if r["kind"] == "nudge"),
        "recasts": sum(1 for r in rows if r["kind"] == "recast"),
        "digs": sum(1 for r in rows if r["kind"] == "dig"),
    }


def _tally(items) -> dict:
    out: dict[str, int] = {}
    for item in items:
        out[item] = out.get(item, 0) + 1
    return out


def report(folder: Path | str, limit: int = 12) -> str:
    """세션들을 한 표로. 낚음 주기가 짧은 쪽이 좋은 것이다."""
    files = sessions(folder)[:limit]
    if not files:
        return "기록이 없습니다. 낚시를 한 번 돌리면 쌓입니다."
    lines = [
        f"{'언제':24} {'분':>5} {'낚음':>5} {'주기(중앙)':>10} {'가장짧게':>8} "
        f"{'판':>4} {'클리어':>7} {'판시간':>7} {'배수':>5} {'lead':>6}",
    ]
    best = None
    for path in files:
        got = digest(read(path))
        if not got["catches"] and not got["rounds"]:
            continue
        stamp = path.stem
        lines.append(
            f"{stamp:24} {got['minutes']:5.0f} {got['catches']:5} "
            f"{got['cycle_mid']:9.1f}초 {got['cycle_min']:7.1f}초 "
            f"{got['rounds']:4} {got['clear_rate'] * 100:6.0f}% "
            f"{got['round_mid']:6.1f}초 "
            f"{(got['ratio_end'] or 0):5.1f} {(got['lead_end'] or 0):+6.0f}")
        if got["cycle_n"] >= 3 and (best is None
                                    or got["cycle_mid"] < best[0]):
            best = (got["cycle_mid"], stamp, got)
    if best is not None:
        _mid_s, stamp, got = best
        lines.append("")
        lines.append(f"가장 짧은 주기: {stamp} — 중앙 {got['cycle_mid']}초 "
                     f"(낚음 {got['catches']}마리 · {got['cycle_n']}번 잼)")
        lines.append(f"  그때 설정: 배수 {got['ratio_end']} · "
                     f"lead {got['lead_end']}ms · "
                     f"판당 클릭 {got['clicks_mid']} · "
                     f"클리어 {got['clear_rate'] * 100:.0f}%")
        if got["reasons"]:
            lines.append("  낚음을 무엇으로 알았나: "
                         + " · ".join(f"{k} {v}번"
                                      for k, v in got["reasons"].items()))
        for name, count in (("두드리다 다시 던짐", got["nudges"]),
                            ("근거 없이 다시 던짐", got["recasts"]),
                            ("땅 파기", got["digs"])):
            if count:
                lines.append(f"  {name} {count}번")
    return "\n".join(lines)
