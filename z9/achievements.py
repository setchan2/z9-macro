"""업적 — 무엇이 있는지, 무엇을 자동으로 깰지, 단계가 어떻게 늘어나는지.

게임의 업적은 **단계식**이다. 한 단계를 깨면 RP를 주고 다음 단계로 올라가는데,
올라갈수록 필요한 수도 RP도 늘어난다.

    10  [일간] 몬스터 사냥 (1/5)   보상: 물약 1개   (0 / 70)
    ~~  ~~~~~~~~~~~~~~~~~ ~~~~~                    ~~~~~~~
    RP        제목        단계                     진행/필요

여기서 **숫자가 두 종류**라는 것이 이 파일의 전부다.

* 공식 가이드 표에 적힌 숫자는 **그 단계에서 더 해야 하는 양**이다.
  농작물 수확이면 35 / 55 / 90 / 140 / 230.
* 게임 화면의 (0 / 70)은 **누적**이다. 위 값을 더해 가면 35 / 90 / 180 / 320 / 550.

그래서 농작물 수확은 **550을 채우면 다섯 단계가 전부 깨진다.** 35를 채우고 다시
55를 채우는 식이 아니다. 이 구분을 놓치면 필요한 것보다 몇 배씩 더 돌리게 된다.

    이 단계만 올리는 데 필요한 양 = 가이드 표의 그 단계 숫자 (steps)
    전부 깨는 데 필요한 양        = 그 숫자를 모두 더한 값 (cumulative[-1])

카탈로그는 공식 가이드(GUIDE_URL)의 표를 그대로 옮긴 것이라 다섯 단계 값을
처음부터 전부 안다. 그래도 **단계 기록**은 남겨 둔다. 게임은 패치로 바뀌고,
그때 붙박이 값이 조용히 틀리는 것보다 "화면에서 본 값이 우선"이 낫기 때문이다.

가이드에 없고 화면에서만 본 업적(기간 한정 이벤트)은 source=SRC_SEEN으로
따로 표시해 둔다. 사라져도 놀라지 않도록.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

# 카탈로그의 출처. 값이 이상하면 여기부터 다시 본다.
GUIDE_URL = "https://www.z9star.co.kr/guide/info/68/"
GUIDE_CHECKED = "2026-09-05"

# 업적이 초기화되는 시각(시).
#
# 공식 가이드는 "매일 0시"라고 적어 두었지만, 실제 화면의 '남은 시간'을 역산하면
# 04:00이다 — 21:52에 6시간 8분이 남아 있었다. 피로도 초기화와도 같은 시각이다.
# 본 것을 믿되, 가이드 표기도 남겨 둔다. 게임이 바뀌면 이 값만 고치면 된다.
RESET_HOUR = 4
GUIDE_RESET_HOUR = 0
# 주간은 월요일, 월간은 1일에 넘어간다 (가이드 표기 그대로).
WEEK_RESET_WEEKDAY = 0  # 0 = 월요일
MONTH_RESET_DAY = 1

DAILY = "daily"
WEEKLY = "weekly"
MONTHLY = "monthly"
SPECIAL = "special"

PERIOD_LABELS = {
    DAILY: "일일업적",
    WEEKLY: "주간업적",
    MONTHLY: "월간업적",
    SPECIAL: "특별업적",
}
PERIOD_RESETS = {
    DAILY: "매일 초기화",
    WEEKLY: "매주 월요일 초기화",
    MONTHLY: "매월 1일 초기화",
    SPECIAL: "기간 제한 없음 (수시로 바뀜)",
}
PERIODS = (DAILY, WEEKLY, MONTHLY, SPECIAL)

# 자동화 가능성. 화면에 이유를 그대로 보여 주려고 값에 설명을 붙여 둔다.
AUTO_YES = "yes"  # 매크로로 깰 수 있다
AUTO_LOGIN = "login"  # 접속만 하면 저절로 깨진다 — 매크로 대상이 아니다
AUTO_CASH = "cash"  # 현금 결제가 필요하다 — 자동화 대상이 아니다
AUTO_DERIVED = "derived"  # 다른 업적을 깨면 저절로 오른다

# 출처. 가이드에 없는 줄은 기간 한정일 가능성이 높다.
SRC_GUIDE = "guide"  # 공식 가이드 표에 있다
SRC_SEEN = "seen"  # 가이드엔 없고 화면에서만 봤다 (이벤트로 추정)


@dataclass(frozen=True)
class Spec:
    """카탈로그 한 줄 — 공식 가이드 표를 그대로 옮긴 것.

    steps / rps / rewards는 길이가 같고, i번째가 (i+1)단계다.
    steps는 **그 단계에서 더 해야 하는 양**이지 누적이 아니다. 누적이 필요하면
    cumulative를 쓴다.
    """

    title: str
    steps: tuple[int, ...]
    rps: tuple[int, ...]
    rewards: tuple[str, ...]
    how: str = "{n}"  # 가이드의 '달성 방법'. {n}에 그 단계 숫자가 들어간다
    auto: str = AUTO_YES
    note: str = ""
    source: str = SRC_GUIDE

    # -- 단계 --------------------------------------------------------------
    @property
    def stages(self) -> int:
        return len(self.steps)

    @property
    def staged(self) -> bool:
        return self.stages > 1

    @property
    def cumulative(self) -> tuple[int, ...]:
        """단계별 **누적** 필요 수. 게임 화면의 (진행/필요)와 같은 숫자다."""
        total = 0
        out = []
        for step in self.steps:
            total += step
            out.append(total)
        return tuple(out)

    def _index(self, stage: int) -> int:
        return min(max(1, stage), self.stages) - 1

    def need(self, stage: int) -> int:
        """그 단계 하나를 올리는 데 **더** 해야 하는 양."""
        return self.steps[self._index(stage)]

    def upto(self, stage: int) -> int:
        """그 단계까지의 누적 필요 수."""
        return self.cumulative[self._index(stage)]

    def rp_at(self, stage: int) -> int:
        return self.rps[self._index(stage)]

    def reward_at(self, stage: int) -> str:
        return self.rewards[self._index(stage)]

    def how_at(self, stage: int) -> str:
        """그 단계의 '달성 방법' 문구."""
        try:
            return self.how.format(n=self.need(stage))
        except (KeyError, IndexError, ValueError):
            return self.how

    # -- 첫 단계 지름길 (화면에서 가장 자주 쓴다) ---------------------------
    @property
    def rp(self) -> int:
        return self.rps[0]

    @property
    def reward(self) -> str:
        return self.rewards[0]

    @property
    def target(self) -> int:
        """1단계 누적 필요 수."""
        return self.cumulative[0]

    @property
    def total(self) -> int:
        """마지막 단계까지의 누적 필요 수 — 전부 깨는 데 필요한 양."""
        return self.cumulative[-1]

    @property
    def total_rp(self) -> int:
        """전부 깨면 받는 RP."""
        return sum(self.rps)

    def points(self) -> list[tuple[int, int, int]]:
        """카탈로그가 아는 (단계, RP, **누적** 필요) 전부."""
        return [
            (i + 1, self.rps[i], self.cumulative[i]) for i in range(self.stages)
        ]

    def table(self) -> list[str]:
        """사람이 읽을 단계표. '1단계 · RP 10 · 35개(누적 35) · 랜덤씨 x1'."""
        out = []
        for stage, rp, upto in self.points():
            need = self.need(stage)
            amount = f"{need:,}" if need == upto else f"{need:,}(누적 {upto:,})"
            out.append(f"{stage}단계 · RP {rp} · {amount} · {self.reward_at(stage)}")
        return out


def _spec(
    title: str,
    how: str,
    rows: tuple[tuple[int, int, str], ...],
    auto: str = AUTO_YES,
    note: str = "",
    source: str = SRC_GUIDE,
) -> Spec:
    """가이드 표의 한 업적을 그대로 받아 적는다. rows는 (필요 수, RP, 보상)."""
    return Spec(
        title=title,
        steps=tuple(int(r[0]) for r in rows),
        rps=tuple(int(r[1]) for r in rows),
        rewards=tuple(str(r[2]) for r in rows),
        how=how,
        auto=auto,
        note=note,
        source=source,
    )


# --------------------------------------------------------------------------
# 카탈로그 — 공식 가이드(GUIDE_URL)의 표를 그대로
#
# rows의 숫자는 가이드에 적힌 그대로, 즉 **그 단계에서 더 해야 하는 양**이다.
# 누적은 Spec.cumulative가 계산한다.
# --------------------------------------------------------------------------
CATALOG: dict[str, tuple[Spec, ...]] = {
    DAILY: (
        _spec("몬스터 사냥", "몬스터 {n}마리 처치", (
            (70, 10, "물약 x1"),
            (110, 15, "물약 x2"),
            (170, 20, "물약 x3"),
            (290, 25, "물약 x4"),
            (450, 30, "물약 x5"),
        )),
        _spec("농작물 수확", "농작물 {n}개 수확", (
            (35, 10, "랜덤씨 x1"),
            (55, 15, "랜덤씨 x2"),
            (90, 20, "랜덤씨 x3"),
            (140, 25, "랜덤씨 x4"),
            (230, 30, "랜덤씨 x5"),
        )),
        _spec("나무 벌목", "나무 {n}그루 벌목", (
            (20, 10, "돈나무씨 x1"),
            (30, 15, "돈나무씨 x2"),
            (50, 20, "돈나무씨 x3"),
            (80, 25, "돈나무씨 x4"),
            (120, 30, "돈나무씨 x5"),
        )),
        _spec("광맥 채굴", "광맥 {n}개 채광", (
            (10, 10, "용왕의 비약 x1"),
            (15, 15, "용왕의 비약 x1"),
            (25, 20, "용왕의 비약 x1"),
            (40, 25, "용왕의 비약 x1"),
            (60, 30, "용왕의 비약 x1"),
        )),
        _spec("낚시 성공", "물고기 {n}마리 낚시", (
            (30, 10, "낚시왕의 최고급 떡밥 x1"),
            (45, 15, "낚시왕의 최고급 떡밥 x1"),
            (65, 20, "낚시왕의 최고급 떡밥 x1"),
            (100, 25, "낚시왕의 최고급 떡밥 x1"),
            (160, 30, "낚시왕의 최고급 떡밥 x1"),
        )),
        _spec("동물 성장완료", "동물 {n}마리 성장 완료", (
            (12, 10, "사육사의 목줄 x1"),
            (18, 15, "사육사의 목줄 x1"),
            (30, 20, "사육사의 목줄 x2"),
            (40, 25, "사육사의 목줄 x2"),
            (50, 30, "사육사의 목줄 x3"),
        )),
        _spec("요리 생산", "요리 {n}개 완성", (
            (35, 10, "맛있는 냄새 x1"),
            (55, 15, "맛있는 냄새 x1"),
            (90, 20, "맛있는 냄새 x1"),
            (140, 25, "맛있는 냄새 x1"),
            (230, 30, "맛있는 냄새 x1"),
        )),
        _spec("대전 완료", "대전 {n}번 완료", ((3, 10, "지구박_블루 x1"),)),
        _spec("OX퀴즈 문제 풀기", "OX퀴즈 {n}개 풀기", (
            (10, 15, "지구박_블루 x1"),
            (10, 15, "지구박_블루 x1"),
            (10, 15, "지구박_블루 x1"),
        )),
        _spec("수영대회 참가", "수영대회 참가", (
            (1, 10, "지구박_블루 x1"),
            (1, 10, "지구박_블루 x1"),
            (1, 10, "지구박_블루 x1"),
        )),
        _spec("자동차 경주 참가", "자동차 경주대회 참가", (
            (1, 10, "오일 x1"),
            (1, 10, "오일 x1"),
            (1, 10, "오일 x1"),
        )),
        _spec("출석하기", "게임에 접속하기", ((1, 20, "지구박_블랙 x1"),),
              AUTO_LOGIN, "접속만 하면 저절로 깨집니다. 자동화 목록에서 뺐습니다."),
        _spec("우주 대전 참가", "우주 대전 참가", (
            (1, 15, "크립톤 x1"),
            (1, 15, "크립톤 x1"),
            (1, 15, "크립톤 x1"),
        )),
        _spec("외계인 침공 방어 참가", "외계인 침공 방어 참가", (
            (1, 15, "크립톤 x1"),
            (1, 15, "크립톤 x1"),
            (1, 15, "크립톤 x1"),
        )),
        _spec("마이홈 성장", "마이홈 {n}회 성장", ((10, 10, "지구박_블루 x1"),)),
        _spec("조이캡슐 상점 이용", "조이캡슐상점 {n}회 이용",
              ((10, 10, "지구박_블루 x1"),)),
        _spec("지구텔 숙박", "지구텔 이용", ((1, 5, "지구박_블루 x1"),)),
        _spec("길드포인트 구매", "길드포인트 {n}회 구매", ((10, 10, "하얀 봉투 x1"),)),
        _spec("누적 캐시아이템 구매금액", "캐시 아이템 {n:,}스타 구매",
              ((1000, 100, "호텔 숙박권(특실) x1"),),
              AUTO_CASH, "현금 결제가 필요합니다. 자동화 대상이 아닙니다."),
        _spec("오목 플레이", "오목 {n}회 플레이", ((5, 0, "오목 보상 상자 x1"),)),
        _spec("마네킹을 통해 캐시상점 방문", "패션샵 마네킹을 통해 캐시상점 방문",
              ((1, 0, "도깨비 묘약 x5"),)),
        # 아래는 가이드에 없다. 화면에서 본 것이라 이벤트로 추정한다.
        _spec("패션 배틀 참가", "패션 배틀 참가", ((1, 25, "엔틱 실버 단추 x1"),),
              note="공식 가이드에 없는 업적입니다 (이벤트로 추정).",
              source=SRC_SEEN),
    ),
    WEEKLY: (
        _spec("일간 누적 RP", "일간 누적 {n:,}RP 달성", ((1000, 20, "전기톱 (3일)"),),
              AUTO_DERIVED, "일일업적을 채우면 저절로 오릅니다."),
        _spec("OX퀴즈 정답", "OX퀴즈 {n}개 정답", ((70, 15, "황금 호루라기 (3일)"),)),
        _spec("수영대회 우승", "수영 대회 우승", ((1, 10, "골드 클로버 x1"),)),
        _spec("자동차경주 우승", "자동차 경주 대회 우승", ((1, 10, "골드 클로버 x1"),)),
        _spec("보스 레이드에서 생존", "보스 처치 이벤트 {n}회 승리",
              ((7, 15, "스프링클러 (3일)"),)),
        _spec("우주 대전 승리", "우주 대전 {n}회 승리", ((7, 10, "트랙터 (3일)"),)),
        _spec("외계인 침공 방어 성공", "외계인 침공 방어 {n}회 성공",
              ((7, 10, "파워 드릴 (3일)"),)),
        _spec("누적 캐시아이템 구매금액", "캐시 아이템 {n:,}스타 구매",
              ((10000, 30, "찬란한 행운의 돌 x1"),),
              AUTO_CASH, "현금 결제가 필요합니다."),
        _spec("출석하기(이벤트)", "출석 {n}회 완료",
              ((6, 0, "점검과 함께 사라지다 x2"),),
              AUTO_LOGIN, "접속만 하면 저절로 깨집니다."),
        _spec("패션 배틀 300점 이상 획득", "패션 배틀 {n}회 300점 이상",
              ((3, 15, "트랙터 (3일)"),),
              note="공식 가이드에 없는 업적입니다 (이벤트로 추정).",
              source=SRC_SEEN),
    ),
    MONTHLY: (
        _spec("주간 누적 RP", "주간 누적 {n}RP 달성", ((350, 20, "슈퍼 드릴 (7일)"),),
              AUTO_DERIVED, "주간업적을 채우면 저절로 오릅니다."),
        _spec("OX퀴즈 정답", "OX퀴즈 {n}개 정답", ((300, 15, "슈퍼 전기톱 (7일)"),)),
        _spec("수영대회 우승", "수영 대회 {n}회 우승", ((5, 10, "슈퍼 트랙터 (7일)"),)),
        _spec("자동차경주 우승", "자동차 경주 대회 {n}회 우승",
              ((5, 10, "김탁규씨의 요리 냄비 (7일)"),)),
        _spec("보스 레이드에서 생존", "보스 처치 이벤트 {n}회 승리",
              ((30, 15, "슈퍼 스프링클러 (7일)"),)),
        _spec("우주 대전 승리", "우주 대전 {n}회 승리", ((30, 10, "슈퍼 호루라기 (7일)"),)),
        _spec("외계인 침공 방어 성공", "외계인 침공 방어 {n}회 성공",
              ((30, 10, "슈퍼 낚싯대 (7일)"),)),
        _spec("누적 캐시아이템 구매금액", "캐시 아이템 {n:,}스타 구매",
              ((50000, 30, "순간이동의 날개 (7일)"),),
              AUTO_CASH, "현금 결제가 필요합니다."),
        _spec("출석하기(이벤트)", "출석 {n}회 완료",
              ((24, 0, "전체 경험치 UP부스터 (7일)"),),
              AUTO_LOGIN, "접속만 하면 저절로 깨집니다."),
        _spec("패션 배틀 400점 이상 획득", "패션 배틀 {n}회 400점 이상",
              ((3, 15, "슈퍼 트랙터 (7일)"),),
              note="공식 가이드에 없는 업적입니다 (이벤트로 추정).",
              source=SRC_SEEN),
    ),
    # 가이드: "특별업적은 기간 제한이 없으며, 수시로 삭제 및 변경됩니다.
    #          반복하여 진행할 수 있는 특별업적은 보상 획득시 초기화됩니다."
    # 표가 없으므로 화면에서 본 것만 적어 둔다. 없어져 있어도 정상이다.
    SPECIAL: (
        _spec("[반복] 주간업적 RP90 보상획득 4회", "주간업적 RP 90 보상 {n}회 획득",
              ((4, 0, "엔틱 블랙 단추 x1"),),
              AUTO_DERIVED, "주간업적을 RP 90까지 채우면 저절로 오릅니다.",
              source=SRC_SEEN),
        _spec("[반복] 일일업적 RP200 보상획득 10회", "일일업적 RP 200 보상 {n}회 획득",
              ((10, 0, "복고의상상자 무료쿠폰(1회) x1"),),
              AUTO_DERIVED, "일일업적을 RP 200까지 채우면 저절로 오릅니다.",
              source=SRC_SEEN),
        _spec("[이벤트] 패션 배틀 응원", "패션 배틀 응원", ((1, 0, "패션 배틀 참가권 x2"),),
              source=SRC_SEEN),
    ),
}

# 예전 이름 → 지금 이름. 가이드와 표기가 달랐던 것들이라, 저장해 둔 계획이
# 이름을 못 찾고 사라지지 않도록 옮겨 준다. 키는 (기간, 옛 이름).
TITLE_FIXES: dict[tuple[str, str], str] = {
    (DAILY, "0X퀴즈 문제 풀기"): "OX퀴즈 문제 풀기",
    (WEEKLY, "0X퀴즈 정답"): "OX퀴즈 정답",
    (MONTHLY, "0X퀴즈 정답"): "OX퀴즈 정답",
    (WEEKLY, "외계인 침공 방어 참가"): "외계인 침공 방어 성공",
    (MONTHLY, "외계인 침공 방어 참가"): "외계인 침공 방어 성공",
}


def fix_title(period: str, title: str) -> str:
    return TITLE_FIXES.get((period, title), title)


# RP 이정표 — 이만큼 모으면 따로 보상을 준다 (화면 위쪽 막대). 가이드 표 그대로.
MILESTONES: dict[str, tuple[tuple[int, str], ...]] = {
    DAILY: (
        (100, "100 에코 포인트"),
        (150, "호텔 숙박권(특실) x1"),
        (200, "혹시크린 x1"),
    ),
    WEEKLY: (
        (45, "출석 의상 교환권(7일) x5"),
        (90, "레시피 보관상자 x5"),
    ),
    MONTHLY: (
        (45, "3,000 에코 포인트"),
        (90, "캐시의상무료쿠폰 x1"),
    ),
}

# 막대의 끝 = 마지막 이정표. 그 위로 더 모아도 보상은 없다.
RP_GOAL = {period: rows[-1][0] for period, rows in MILESTONES.items()}


def total_rp(period: str) -> int:
    """그 기간의 업적을 전부 깨면 얻는 RP 합계."""
    return sum(spec.total_rp for spec in CATALOG.get(period, ()))


def next_milestone(period: str, rp: int) -> tuple[int, str] | None:
    """지금 RP 다음에 오는 이정표."""
    for need, reward in MILESTONES.get(period, ()):
        if rp < need:
            return (need, reward)
    return None


def spec_for(period: str, title: str) -> Spec | None:
    title = fix_title(period, title)
    for spec in CATALOG.get(period, ()):
        if spec.title == title:
            return spec
    return None


# --------------------------------------------------------------------------
# 업적 하루 — 새벽 4시에 넘어간다
# --------------------------------------------------------------------------
def _now(now: float | None = None) -> datetime:
    return datetime.fromtimestamp(now if now is not None else time.time())


def _shifted(now: float | None = None) -> datetime:
    """초기화 시각을 자정으로 옮긴 시계. 날짜 계산을 이 위에서 한다."""
    return _now(now) - timedelta(hours=RESET_HOUR)


def game_day(now: float | None = None) -> str:
    """지금이 속한 '업적 하루'. 새벽 4시 전이면 아직 어제다.

    자정으로 끊으면 새벽 1시에 돌린 매크로가 다음 날 몫으로 세어져, 정작 4시에
    초기화된 뒤에는 아무것도 안 하게 된다.
    """
    return _shifted(now).strftime("%Y-%m-%d")


def game_week(now: float | None = None) -> str:
    """지금이 속한 '업적 주'. 월요일 초기화 기준의 ISO 주 표기."""
    stamp = _shifted(now)
    year, week, _weekday = stamp.isocalendar()
    return f"{year}-W{week:02d}"


def game_month(now: float | None = None) -> str:
    """지금이 속한 '업적 달'. 1일 초기화 기준."""
    return _shifted(now).strftime("%Y-%m")


def period_key(period: str, now: float | None = None) -> str:
    """그 기간의 '지금 회차' 이름. 같은 회차에 두 번 돌리지 않으려고 쓴다."""
    if period == WEEKLY:
        return game_week(now)
    if period == MONTHLY:
        return game_month(now)
    if period == SPECIAL:
        return ""  # 초기화가 없다
    return game_day(now)


def seconds_to_reset(now: float | None = None) -> float:
    """다음 일일 초기화까지 남은 초."""
    return period_seconds_to_reset(DAILY, now)


def period_seconds_to_reset(period: str, now: float | None = None) -> float:
    """그 기간의 다음 초기화까지 남은 초. 특별업적은 초기화가 없어 0."""
    if period == SPECIAL:
        return 0.0
    stamp = _now(now)
    target = stamp.replace(hour=RESET_HOUR, minute=0, second=0, microsecond=0)

    if period == WEEKLY:
        ahead = (WEEK_RESET_WEEKDAY - target.weekday()) % 7
        target += timedelta(days=ahead)
        if stamp >= target:
            target += timedelta(days=7)
    elif period == MONTHLY:
        if target.day != MONTH_RESET_DAY or stamp >= target:
            # 다음 달 1일로 넘긴다.
            head = target.replace(day=1)
            target = (head + timedelta(days=32)).replace(day=MONTH_RESET_DAY)
    else:
        if stamp >= target:
            target += timedelta(days=1)
    return max(0.0, (target - stamp).total_seconds())


def describe_remaining(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    if days:
        return f"{days}일 {hours}시간"
    return f"{hours}시간 {rest // 60}분"


# --------------------------------------------------------------------------
# 단계 기록
# --------------------------------------------------------------------------
@dataclass
class StageRecord:
    """실제로 화면에서 본 한 단계의 값."""

    stage: int = 1
    rp: int = 0
    target: int = 0
    day: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageRecord":
        return cls(
            stage=int(data.get("stage", 1) or 1),
            rp=int(data.get("rp", 0) or 0),
            target=int(data.get("target", 0) or 0),
            day=str(data.get("day", "")),
        )


def _guess_next(values: list[tuple[int, int]]) -> int | None:
    """(단계, 값) 기록에서 다음 단계 값을 어림한다. 못 하면 None.

    두 가지만 본다 — **차이가 일정한가**(등차), **비가 일정한가**(등비). 게임의
    단계 수치는 거의 이 둘 중 하나이고, 아니라면 어림짐작을 내놓기보다 모른다고
    하는 편이 낫다. 틀린 숫자를 확신에 차서 보여 주면 그걸 믿고 계획을 세운다.
    """
    if len(values) < 2:
        return None
    values = sorted(values)
    stages = [s for s, _v in values]
    if stages != list(range(stages[0], stages[0] + len(stages))):
        return None  # 중간이 비면 규칙을 못 본다
    nums = [v for _s, v in values]
    if any(n <= 0 for n in nums):
        return None

    diffs = {nums[i + 1] - nums[i] for i in range(len(nums) - 1)}
    if len(diffs) == 1:
        return nums[-1] + diffs.pop()

    ratios = {round(nums[i + 1] / nums[i], 3) for i in range(len(nums) - 1)}
    if len(ratios) == 1:
        ratio = ratios.pop()
        if ratio > 1:
            return int(round(nums[-1] * ratio))
    return None


# --------------------------------------------------------------------------
# 자동화 계획
# --------------------------------------------------------------------------
RUN_KINDS = ("macro", "scenario", "path", "repeat")
RUN_LABELS = {
    "macro": "매크로",
    "scenario": "시나리오",
    "path": "이동 경로",
    "repeat": "연타",
}

LIMIT_COUNT = "count"  # 몇 번 돌린다
LIMIT_TIME = "time"  # 몇 분 동안 돌린다
# 아래 둘은 '한 번 돌면 1 오른다'고 볼 때의 이야기다. 필요 수가 누적이므로
# 전부 깨려면 마지막 단계 누적값 하나면 되고, 한 단계만 올리려면 그 단계
# 누적값에서 앞 단계 누적값을 뺀 만큼이면 된다.
LIMIT_ALL = "all"  # 마지막 단계까지 전부 깨는 데 필요한 만큼
LIMIT_STAGE = "stage"  # 지금 단계 하나만 올리는 데 필요한 만큼
LIMIT_TARGET = LIMIT_ALL  # 예전 이름
LIMIT_LABELS = {
    LIMIT_ALL: "전부 깨는 데 필요한 만큼",
    LIMIT_STAGE: "지금 단계만 올릴 만큼",
    LIMIT_COUNT: "정한 횟수만큼",
    LIMIT_TIME: "정한 시간 동안",
}


@dataclass
class Plan:
    """업적 하나를 어떻게 자동으로 깰지. 프로필에 저장된다."""

    period: str = DAILY
    title: str = ""
    enabled: bool = False
    kind: str = "macro"
    target_name: str = ""  # 돌릴 매크로 · 시나리오 · 경로 · 연타 이름
    limit_mode: str = LIMIT_ALL
    repeat_count: int = 1
    minutes: float = 5.0
    note: str = ""
    # 오늘 몇 단계까지 올렸는지 사람이 적어 두는 칸 (화면에서 본 값).
    stage: int = 1
    stages: list[StageRecord] = field(default_factory=list)
    # 마지막으로 끝낸 업적 하루. 같은 날 두 번 돌리지 않기 위해서다.
    done_day: str = ""

    # -- 기록 -----------------------------------------------------------
    def record(self, stage: int, rp: int, target: int, day: str = "") -> None:
        """한 단계의 값을 적는다. 같은 단계가 있으면 새 값으로 바꾼다."""
        day = day or game_day()
        for existing in self.stages:
            if existing.stage == stage:
                existing.rp, existing.target, existing.day = rp, target, day
                return
        self.stages.append(StageRecord(stage=stage, rp=rp, target=target, day=day))
        self.stages.sort(key=lambda s: s.stage)

    def known(self, stage: int) -> StageRecord | None:
        for record in self.stages:
            if record.stage == stage:
                return record
        return None

    def points(self, spec: Spec | None) -> dict[int, tuple[int, int, bool]]:
        """아는 단계들의 {단계: (RP, 누적 필요, 실측인가)}.

        적어 둔 값이 카탈로그를 이긴다. 카탈로그는 화면에서 한 번 본 것이고
        패치로 바뀔 수 있지만, 적어 둔 값은 사용자가 방금 본 것이다.
        """
        got: dict[int, tuple[int, int, bool]] = {}
        if spec is not None:
            for stage, rp, target in spec.points():
                if target > 0:
                    got[stage] = (rp, target, False)
        for record in self.stages:
            got[record.stage] = (record.rp, record.target, True)
        return got

    def effective(self, stage: int, spec: Spec | None) -> tuple[int, int, bool]:
        """그 단계의 (RP, **누적** 필요 수, 실측인가)."""
        return self.points(spec).get(stage, (0, 0, False))

    def increment(self, stage: int, spec: Spec | None) -> int | None:
        """그 단계 하나를 올리는 데 **더** 해야 하는 양.

        누적이므로 앞 단계 누적값을 빼야 한다. 1단계는 앞이 0이라 그대로다.
        앞 단계를 모르면 계산할 수 없으므로 None.
        """
        got = self.points(spec)
        _rp, target, _real = got.get(stage, (0, 0, False))
        if not target:
            return None
        if stage <= 1:
            return target
        previous = got.get(stage - 1)
        if previous is None or not previous[1]:
            return None
        return max(0, target - previous[1])

    def total_needed(self, spec: Spec | None) -> int | None:
        """전부 깨는 데 필요한 양 = 마지막 단계 누적값.

        누적이라서 이 숫자 하나면 된다. 중간 단계를 몰라도 상관없다 — 오히려
        이것이 자동화에 가장 중요한 값이다.
        """
        total = spec.stages if spec else 1
        _rp, target, _real = self.effective(total, spec)
        if target:
            return target
        rp, guess = self.predict(total, spec)
        return guess

    def predict(self, stage: int, spec: Spec | None = None) -> tuple[int | None, int | None]:
        """아직 못 본 단계의 (RP, 누적 필요)를 어림한다."""
        got = self.points(spec)
        if stage in got:
            rp, target, _real = got[stage]
            return (rp or None, target or None)
        rp = _guess_next([(s, v[0]) for s, v in sorted(got.items()) if v[0] > 0])
        target = _guess_next([(s, v[1]) for s, v in sorted(got.items())])
        # 어림은 바로 다음 단계에만 쓴다. 두 칸 넘게 앞을 내다보면 오차가 커진다.
        highest = max(got, default=0)
        if stage != highest + 1:
            return (None, None)
        return (rp, target)

    def missing_stages(self, spec: Spec | None) -> list[int]:
        """아직 값을 모르는 단계들."""
        total = spec.stages if spec else 1
        got = self.points(spec)
        return [s for s in range(1, total + 1) if s not in got]

    def planned_rp(self, spec: Spec | None) -> int:
        """오늘 이 업적으로 얻을 수 있는 RP.

        전부 깨기로 했으면 아는 단계의 RP를 모두 더한다 — 누적 필요 수를
        채우면 그 아래 단계도 함께 깨지기 때문이다.
        """
        if not self.enabled:
            return 0
        got = self.points(spec)
        if self.limit_mode == LIMIT_ALL:
            return sum(rp for rp, _t, _r in got.values())
        rp, _target, _real = self.effective(max(1, self.stage), spec)
        return rp

    def ready(self) -> bool:
        return bool(self.enabled and self.target_name)

    def done_today(self, now: float | None = None) -> bool:
        """이번 회차에 이미 돌렸는가.

        일일이면 오늘, 주간이면 이번 주, 월간이면 이번 달이다. 주간 계획을
        하루 지났다고 다시 돌리면 같은 업적을 일곱 번 돌리게 된다.
        """
        key = period_key(self.period, now)
        if not key:
            return False  # 특별업적은 초기화가 없어 '오늘 했음'이 없다
        return bool(self.done_day) and self.done_day == key

    def mark_done(self, now: float | None = None) -> None:
        self.done_day = period_key(self.period, now)

    # -- 저장 -----------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stages"] = [s.to_dict() for s in self.stages]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Plan":
        obj = cls(
            period=str(data.get("period", DAILY)),
            title=str(data.get("title", "")),
            enabled=bool(data.get("enabled", False)),
            kind=str(data.get("kind", "macro")),
            target_name=str(data.get("target_name", "")),
            limit_mode=str(data.get("limit_mode", LIMIT_ALL)),
            repeat_count=int(data.get("repeat_count", 1) or 1),
            minutes=float(data.get("minutes", 5.0) or 5.0),
            note=str(data.get("note", "")),
            stage=int(data.get("stage", 1) or 1),
            done_day=str(data.get("done_day", "")),
        )
        obj.stages = [StageRecord.from_dict(s) for s in data.get("stages", [])]
        obj.stages.sort(key=lambda s: s.stage)
        if obj.period not in PERIODS:
            obj.period = DAILY
        # 가이드와 표기가 달랐던 제목("0X퀴즈" 등)을 옮긴다. 안 옮기면 저장해 둔
        # 설정이 카탈로그에서 짝을 못 찾아 조용히 사라진다.
        obj.title = fix_title(obj.period, obj.title)
        if obj.kind not in RUN_KINDS:
            obj.kind = "macro"
        # "target"은 필요 수가 누적임을 알기 전에 쓰던 이름이다. 뜻이 같은
        # "전부 깨는 데 필요한 만큼"으로 옮긴다.
        if obj.limit_mode == "target":
            obj.limit_mode = LIMIT_ALL
        if obj.limit_mode not in LIMIT_LABELS:
            obj.limit_mode = LIMIT_ALL
        obj.stage = max(1, obj.stage)
        return obj


# --------------------------------------------------------------------------
# 프로필 안의 계획 다루기
# --------------------------------------------------------------------------
def find_plan(plans: list[Plan], period: str, title: str) -> Plan | None:
    for plan in plans:
        if plan.period == period and plan.title == title:
            return plan
    return None


def ensure_plan(plans: list[Plan], period: str, title: str) -> Plan:
    """계획이 없으면 만들어 붙인다.

    카탈로그의 모든 업적을 미리 만들어 두지 않는다. 손대지 않은 업적까지 전부
    저장 파일에 들어가면, 게임이 업적을 바꿨을 때 남은 찌꺼기를 구분할 수 없다.
    """
    plan = find_plan(plans, period, title)
    if plan is None:
        plan = Plan(period=period, title=title)
        plans.append(plan)
    return plan


def daily_queue(plans: list[Plan], now: float | None = None) -> list[Plan]:
    """오늘 아직 안 한, 실행할 수 있는 일일업적 계획을 카탈로그 순서대로."""
    order = {spec.title: i for i, spec in enumerate(CATALOG[DAILY])}
    ready = [
        plan
        for plan in plans
        if plan.period == DAILY and plan.ready() and not plan.done_today(now)
    ]
    ready.sort(key=lambda p: order.get(p.title, 999))
    return ready


def summarize(plans: list[Plan], period: str = DAILY) -> dict[str, Any]:
    """화면 위에 띄울 한 줄 요약."""
    specs = CATALOG.get(period, ())
    automatable = [s for s in specs if s.auto == AUTO_YES]
    picked = [p for p in plans if p.period == period and p.ready()]
    rp = sum(p.planned_rp(spec_for(period, p.title)) for p in picked)
    unknown = sum(
        len(p.missing_stages(spec_for(period, p.title)))
        for p in plans
        if p.period == period and p.enabled
    )
    return {
        "total": len(specs),
        "automatable": len(automatable),
        "picked": len(picked),
        "rp": rp,
        "goal": RP_GOAL.get(period, 0),
        "unknown": unknown,
    }
