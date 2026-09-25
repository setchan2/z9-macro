"""생활 콘텐츠별 프리셋.

사냥 / 채광 / 벌목 / 농사 / 낚시 / 목장은 반복 구조가 서로 다르다.

  · 채광·벌목·농사·목장 — "대상 앞에 서서 상호작용 키를 일정 주기로 반복"
    작업 1회 시간이 정해져 있어 **연타 주기**만 맞추면 된다.
  · 낚시 — "던지고 → 입질을 기다렸다가 → 낚아챈다"
    시간이 아니라 **화면 변화**에 반응해야 해서 조건부 실행이 필수다.
  · 사냥 — "이동하며 공격, 체력이 줄면 회복"
    이동 경로 + 공격 연타 + 체력 조건, 세 가지가 같이 돈다.

여기서 만드는 값은 어디까지나 뼈대다. 실제 단축키와 좌표는 게임 설정에 따라
다르므로 생성 후 각 탭에서 채워 넣어야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import PathMacro, PathStep, PixelRule, Profile, RepeatTask

ACTIVITIES = ("사냥", "채광", "벌목", "농사", "낚시", "목장")


@dataclass
class PresetSpec:
    activity: str
    summary: str
    repeat: RepeatTask | None = None
    path: PathMacro | None = None
    rules: list[PixelRule] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _repeat(activity: str, key: str, interval: int, hold: int = 40) -> RepeatTask:
    return RepeatTask(
        name=f"[{activity}] 반복",
        key=key,
        mode="tap",
        interval_ms=interval,
        hold_ms=hold,
        jitter_ms=0,
        duration_s=0,
    )


def _gather_preset(activity: str, interval: int, note: str) -> PresetSpec:
    """채광·벌목·농사·목장 공통 — 상호작용 키 주기 반복."""
    rule = PixelRule(
        name=f"[{activity}] 대상 소진 감지",
        tolerance=14,
        match_mode="all",
        condition="differ",
        action_kind="path",
        action_target=f"[{activity}] 다음 지점 이동",
        check_ms=400,
        cooldown_ms=3000,
        edge_only=True,
    )
    path = PathMacro(
        name=f"[{activity}] 다음 지점 이동",
        steps=[
            PathStep(kind="key", key="Right", duration_ms=700),
            PathStep(kind="wait", duration_ms=300),
        ],
        repeat=1,
        interval_ms=200,
    )
    return PresetSpec(
        activity=activity,
        summary=f"{activity}: 상호작용 키를 {interval}ms 주기로 반복",
        repeat=_repeat(activity, "Space", interval),
        path=path,
        rules=[rule],
        notes=[
            f"'[{activity}] 반복'의 키를 실제 {activity} 단축키로 바꾸세요.",
            f"주기 {interval}ms는 초안입니다. {note}",
            f"'[{activity}] 대상 소진 감지'에 감지 점을 찍어야 동작합니다 "
            "(대상이 사라지면 색이 바뀌는 지점).",
        ],
    )


def build(activity: str) -> PresetSpec:
    if activity == "사냥":
        return PresetSpec(
            activity="사냥",
            summary="사냥: 좌우 이동 + 공격 연타 + 체력 회복 조건",
            repeat=_repeat("사냥", "Z", 180, hold=35),
            path=PathMacro(
                name="[사냥] 순찰 경로",
                steps=[
                    PathStep(kind="key", key="Right", duration_ms=1200),
                    PathStep(kind="wait", duration_ms=400),
                    PathStep(kind="key", key="Left", duration_ms=1200),
                    PathStep(kind="wait", duration_ms=400),
                ],
                repeat=0,
                interval_ms=200,
            ),
            rules=[
                PixelRule(
                    name="[사냥] 체력 회복",
                    tolerance=20,
                    match_mode="any",
                    condition="differ",
                    action_kind="key",
                    action_key="1",
                    check_ms=250,
                    cooldown_ms=4000,
                    edge_only=True,
                ),
            ],
            notes=[
                "'[사냥] 반복'의 키를 공격 단축키로 바꾸세요.",
                "'[사냥] 체력 회복'의 감지 점을 체력바 위, 위험 수위에 해당하는 "
                "위치에 찍으세요. 체력이 그 아래로 내려가면 색이 바뀌어 발동합니다.",
                "회복 키는 기본 '1'입니다. 물약 슬롯에 맞게 바꾸세요.",
                "순찰 경로와 공격 연타는 각각 따로 켜고 끌 수 있습니다.",
            ],
        )

    if activity == "낚시":
        return PresetSpec(
            activity="낚시",
            summary="낚시: 던지기 반복 + 입질 감지 시 낚아채기",
            repeat=_repeat("낚시", "Space", 8000, hold=40),
            rules=[
                PixelRule(
                    name="[낚시] 입질 감지",
                    tolerance=25,
                    match_mode="any",
                    condition="differ",
                    action_kind="key",
                    action_key="Space",
                    check_ms=60,  # 입질은 순간이라 촘촘히 본다
                    cooldown_ms=2000,
                    edge_only=True,
                ),
            ],
            notes=[
                "낚시는 시간이 아니라 화면 변화로 판단해야 정확합니다.",
                "'[낚시] 입질 감지'의 감지 점을 찌 또는 입질 표시(느낌표 등)가 "
                "나타나는 자리에 찍으세요.",
                "확인 주기 60ms는 입질을 놓치지 않기 위한 값입니다. 너무 늘리면 "
                "반응이 늦어집니다.",
                "'[낚시] 반복'은 입질 감지가 잘 잡히면 꺼도 됩니다. 감지가 "
                "어려운 환경에서 시간 기반으로 돌릴 때만 쓰세요.",
            ],
        )

    if activity == "채광":
        return _gather_preset("채광", 1500, "한 번 캐는 데 걸리는 시간에 맞추세요.")
    if activity == "벌목":
        return _gather_preset("벌목", 1800, "나무 종류마다 벌목 시간이 다릅니다.")
    if activity == "농사":
        return _gather_preset("농사", 900, "심기/수확 모션 길이에 맞추세요.")
    if activity == "목장":
        return _gather_preset("목장", 1200, "동물 상호작용 쿨타임에 맞추세요.")

    raise ValueError(f"알 수 없는 콘텐츠: {activity}")


def apply_to(profile: Profile, activity: str) -> tuple[PresetSpec, list[str]]:
    """프로필에 프리셋을 추가한다. 이름이 겹치면 건너뛴다.

    반환값: (스펙, 실제로 추가된 항목 이름 목록)
    """
    spec = build(activity)
    added: list[str] = []

    if spec.repeat and not any(r.name == spec.repeat.name for r in profile.repeats):
        profile.repeats.append(spec.repeat)
        added.append(spec.repeat.name)

    if spec.path and not any(p.name == spec.path.name for p in profile.paths):
        profile.paths.append(spec.path)
        added.append(spec.path.name)

    for rule in spec.rules:
        if not any(r.name == rule.name for r in profile.rules):
            profile.rules.append(rule)
            added.append(rule.name)

    return spec, added
