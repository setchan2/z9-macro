"""제작 매크로 — 치트엔진으로 속도를 올려 두고, 끊기면 다시 접속한다.

한 바퀴는 이렇다.

    ① 마이홈 개설·이동   (녹화해 둔 매크로)
    ② 치트엔진           Open Process → 게임 고르기 → Speedhack 켜고 배속 → Apply
    ③ 제작              띠링 소리가 들리는 동안은 그대로 둔다
    ④ 소리가 멎으면      게임 강제 종료 → 홈페이지 [게임 시작] → 로딩 → [Start]
                        → 채널 접속 매크로 → 다시 ①

## 왜 소리로 가리는가

배속이 크면 인터넷이 끊겨도 화면은 멀쩡해 보인다. 캐릭터도 서 있고 제작 창도
그대로다. 다만 **경험치가 안 들어온다.** 눈으로는 같은 화면이라 화면으로는 못
가린다. 그런데 제작이 한 번 될 때마다 띠링 소리가 난다 — 그 소리가 멎는 것이
곧 끊긴 것이다. 그래서 여기서는 화면을 안 보고 소리만 듣는다(낚시의 성공 효과음과
같은 틀: z9/sound.py).

## 왜 창마다 따로 찾는가

치트엔진 · 브라우저 · 게임은 서로 다른 창이다. 게임을 껐다 켜면 **게임 창은
손잡이(HWND)가 통째로 바뀐다.** 그래서 한 번 찾아 둔 창을 계속 쓰면 다시 접속한
뒤부터 아무 데도 안 눌린다. 누를 때마다 제목으로 다시 찾는다.

## 멈추지 않는다

목표가 무한 반복이므로, 창을 못 찾거나 매크로가 어긋나도 **끝내지 않고** 잠깐
쉬었다가 그 단계를 다시 한다. 끝내는 것은 [정지]를 눌렀을 때뿐이다.
"""

from __future__ import annotations

import ctypes
import os
import time

from . import sender, sound, uia, winctrl, window
from .player import Aborted, RunContext, _run_macro_step
from .model import ClickSpot, CraftSetup

# 창을 찾거나 소리를 들을 때 들여다보는 간격(초).
POLL_S = 0.2
# 클릭 하나에 눌러 두는 시간(ms). 치트엔진 같은 평범한 창에 넉넉한 값.
HOLD_MS = 40
# 창을 못 찾았을 때 한 번 더 찾아보기까지(초).
LOOK_S = 1.0
# 홈페이지를 찾을 프로그램들. **브라우저에서만 찾는다** — 편집기에 열어 둔
# 소스 코드의 'GAME START' 글씨를 단추로 알고 누른 적이 있다.
BROWSERS = ("msedge.exe", "chrome.exe", "whale.exe", "firefox.exe",
            "opera.exe", "brave.exe", "iexplore.exe", "vivaldi.exe")


def check(ctx: RunContext) -> None:
    """[정지]만 본다.

    ctx.check()는 **게임 창이 앞에 있는지**까지 따져서, 앞에 없으면 되찾을 때까지
    붙잡는다. 매크로 재생에는 옳지만 여기서는 안 된다 — 치트엔진과 브라우저를
    누르는 동안에는 게임이 앞에 없는 것이 당연하기 때문이다.
    """
    if ctx.stopped:
        raise Aborted()


def nap(ctx: RunContext, seconds: float) -> None:
    """그만큼 쉰다. [정지]를 누르면 즉시 빠져나온다.

    ctx.sleep(player)와 달리 **게임 창이 앞에 있는지 따지지 않는다.** 이 매크로는
    치트엔진과 브라우저도 만지므로, 그때마다 게임 창을 앞으로 끌어오면 안 된다.
    """
    deadline = time.perf_counter() + max(0.0, seconds)
    while True:
        if ctx.stopped:
            raise Aborted()
        left = deadline - time.perf_counter()
        if left <= 0:
            return
        time.sleep(min(POLL_S, left))


def find(title: str):
    """제목 조각으로 창 하나를 찾는다. 없으면 None.

    **크기가 0인 껍데기 창은 거른다.** 치트엔진은 제목이 그냥 'Cheat Engine'인
    보이지 않는 창을 하나 더 들고 있어서, 제목만 맞춰 고르면 그쪽을 잡는다.
    거기에 대고 누르면 아무 일도 안 일어난다(실제로 그랬다).

    **제목이 더 긴 창은 다른 창이다.** 'Z9★ 온라인'을 찾는데 크기만 보고 고르면
    이 매크로 프로그램 창('Z9★ 온라인 매크로')이 더 커서 그쪽이 잡힌다. 실제로
    그 바람에 게임 대신 매크로 창을 껐다. 그래서 순서를 둔다.

        ① 제목이 똑같은 창      ② 제목이 그것으로 시작하는 창 중 가장 짧은 것
        ③ 나머지 중 제목이 가장 짧은 것
    """
    if not title.strip():
        return None
    needle = title.strip().lower()
    # 자기 프로그램 창은 list_windows 가 알아서 뺀다. 크기 0짜리 껍데기는
    # 여기서 뺀다 — 치트엔진이 그런 창을 하나 들고 있다.
    rows = []
    for info in window.list_windows(title):
        _x, _y, width, height = winctrl.size_of(info.hwnd)
        if width <= 1 or height <= 1:
            continue
        got = info.title.strip().lower()
        rank = 0 if got == needle else (1 if got.startswith(needle) else 2)
        rows.append((rank, len(info.title), info))
    if not rows:
        return None
    rows.sort(key=lambda row: (row[0], row[1]))
    info = rows[0][2]
    return window.GameWindow(info.hwnd, info.title)


def on_screen(x: int, y: int) -> bool:
    """그 자리가 지금 화면 안인가.

    노트북처럼 화면이 작아지거나 보조 모니터를 떼면, 큰 화면에서 찍어 둔 자리가
    화면 **밖**이 된다. 밖을 누르면 윈도가 가장자리로 끌어다 눌러서 엉뚱한 것이
    눌린다 — 아무 일도 안 일어나는 것보다 나쁘다.
    """
    from .win32 import virtual_screen

    left, top, width, height = virtual_screen()
    return left <= x < left + width and top <= y < top + height


def click_at(x: int, y: int, ctx: RunContext, label: str,
             double: bool = False) -> bool:
    """화면의 그 자리를 누른다. 화면 밖이면 안 누르고 False."""
    check(ctx)
    if not on_screen(x, y):
        from .win32 import virtual_screen

        left, top, width, height = virtual_screen()
        ctx.log(f"  ⚠ '{label}' 자리 ({x}, {y})가 화면 밖입니다 "
                f"(화면 {left},{top} {width}×{height}) — 안 누릅니다. "
                "작은 화면으로 옮겼다면 그 자리를 다시 찍어 주세요.")
        return False
    sender.mouse_click(x, y, "left", hold_ms=HOLD_MS)
    if double:
        sender.precise_sleep(0.06)
        sender.mouse_click(x, y, "left", hold_ms=HOLD_MS)
    note(ctx, f"클릭 ({x}, {y})", label)
    return True


def ctrl_click(hwnd: int, ctx: RunContext, label: str, cls: str = "",
               text: str = "") -> bool:
    """창 속에서 **적힌 글씨로** 단추를 찾아 누른다. 못 찾으면 False.

    좌표로 누르면 창 크기나 자리가 달라질 때마다 어긋나는데, 단추는 글씨를
    물어볼 수 있으므로 찾아서 누르는 편이 훨씬 튼튼하다.
    """
    ctrl = winctrl.find_ctrl(hwnd, cls=cls, text=text)
    if ctrl is None:
        return False
    x, y = ctrl.center
    click_at(x, y, ctx, f"{label} (글씨로 찾음)")
    return True


def wait_for(title: str, ctx: RunContext, label: str, limit_s: float = 0.0):
    """그 창이 나타날 때까지 기다린다. limit_s가 0이면 [정지]까지 기다린다."""
    said = False
    deadline = (time.perf_counter() + limit_s) if limit_s > 0 else 0.0
    while True:
        got = find(title)
        if got is not None:
            return got
        if deadline and time.perf_counter() >= deadline:
            return None
        if not said:
            ctx.log(f"  {label} 창('{title}')을 기다립니다…")
            said = True
        nap(ctx, LOOK_S)


def click(spot: ClickSpot, ctx: RunContext, label: str, double: bool = False,
          gap_s: float = 0.0) -> bool:
    """정해 둔 자리를 누른다. 누를 데를 못 찾으면 False.

    창 기준으로 적어 둔 자리는 **누를 때마다 그 창을 다시 찾아** 화면 좌표로
    바꾼다. 창을 옮겨 두었어도 그대로 눌린다.
    """
    if not spot.ready:
        ctx.log(f"  ⚠ '{label}' 자리를 안 정했습니다 — [제작] 탭에서 찍어 주세요.")
        return False
    x, y = spot.x, spot.y
    if spot.where:
        win = find(spot.where)
        if win is None:
            ctx.log(f"  ⚠ '{label}'을(를) 누를 창('{spot.where}')이 없습니다.")
            return False
        bring_front(win, ctx, label)
        x, y = win.client_to_screen(spot.x, spot.y)
    if not click_at(x, y, ctx, label, double=double):
        return False
    if gap_s:
        nap(ctx, gap_s)
    return True


def note(ctx: RunContext, what: str, why: str) -> None:
    board = getattr(ctx, "board", None)
    if board is not None:
        board.sent(what, why)


def type_number(text: str, ctx: RunContext) -> None:
    """적혀 있던 것을 지우고 숫자를 넣는다 (Ctrl+A → 숫자)."""
    from .keys import vk_of

    ctrl, a = vk_of("Ctrl"), vk_of("A")
    if ctrl is not None and a is not None:
        sender.key_combo([ctrl, a], hold_ms=30)
        sender.precise_sleep(0.05)
    for ch in text.strip():
        vk = vk_of(ch)
        if vk is None:
            continue
        sender.key_tap(vk, hold_ms=30)
        sender.precise_sleep(0.03)
    note(ctx, f"입력 '{text}'", "배속")


def click_game_center(ctx: RunContext) -> bool:
    """게임 창을 앞으로 가져오고 한복판을 한 번 누른다.

    **소리는 창이 살아 있어야 난다.** 치트엔진을 만지는 동안 게임이 뒤로 밀리면
    소리가 안 나거나 줄어드는데, 그러면 제작이 도는데도 "끊겼다"고 보고 괜히
    다시 접속한다.
    """
    game = find(ctx.settings.window_pattern)
    if game is None:
        ctx.log("  ⚠ 게임 창을 못 찾아 한복판을 못 눌렀습니다.")
        return False
    game.activate(timeout=1.0)
    nap(ctx, 0.2)
    width, height = game.client_size()
    if width <= 0 or height <= 0:
        return False
    x, y = game.client_to_screen(width // 2, height // 2)
    click_at(x, y, ctx, "게임 창 한복판 (소리가 나게)")
    return True


def kill_game(ctx: RunContext) -> bool:
    """게임을 강제로 끈다. 껐으면(또는 이미 꺼져 있으면) True."""
    return kill_window(ctx.settings.window_pattern, ctx, "게임")


def kill_window(pattern: str, ctx: RunContext, label: str) -> bool:
    """그 제목을 가진 창의 프로그램을 강제로 끈다. 껐으면(또는 없으면) True.

    창을 닫으라고 부탁하지 않고 프로세스를 끊는다 — 종료 확인 창이 뜨면 거기서
    멈추기 때문이다.
    """
    win = find(pattern)
    if win is None:
        ctx.log(f"  {label} 창이 이미 없습니다.")
        return True
    pid = ctypes.c_ulong(0)
    ctypes.windll.user32.GetWindowThreadProcessId(win.hwnd, ctypes.byref(pid))
    if not pid.value:
        return False
    # **자기 자신은 절대 끄지 않는다.** 이 프로그램 창 제목도 게임 이름으로
    # 시작하므로(Z9★ 온라인 매크로), 창을 잘못 고르면 스스로를 껐다.
    if pid.value == os.getpid():
        ctx.log(f"  ⚠ '{win.title}'은(는) 이 매크로 프로그램입니다 — 안 끕니다.")
        return False
    PROCESS_TERMINATE = 0x0001
    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid.value)
    if not handle:
        ctx.log(f"  ⚠ {label}을(를) 끄지 못했습니다 (권한). 관리자 권한으로 "
                "실행했는지 보세요.")
        return False
    ok = bool(ctypes.windll.kernel32.TerminateProcess(handle, 0))
    ctypes.windll.kernel32.CloseHandle(handle)
    ctx.log(f"  {label} 창('{win.title}')을 껐습니다.")
    note(ctx, f"{label} 강제 종료 (pid {pid.value})", label)
    return ok


# --------------------------------------------------------------------------
# 치트엔진 창에서 자리 찾기
# --------------------------------------------------------------------------
def open_process_point(ce_hwnd: int) -> tuple[int, int] | None:
    """[Open Process] 단추의 한복판(화면 좌표).

    이 단추에는 글씨가 없다(컴퓨터 그림만 있다). 대신 **창 왼쪽 위 구석의 작은
    네모**라는 생김새가 뚜렷하다: 36×36쯤 되는 네모가 창 맨 앞자리에 있다.
    """
    kids = winctrl.children(ce_hwnd)
    if not kids:
        return None
    left = min(k.left for k in kids)
    top = min(k.top for k in kids)
    best = None
    for kid in kids:
        if not (24 <= kid.width <= 48 and 24 <= kid.height <= 48):
            continue
        if kid.left > left + 60 or kid.top > top + 60:
            continue
        far = (kid.left - left) + (kid.top - top)
        if best is None or far < best[0]:
            best = (far, kid)
    return best[1].center if best else None


def speed_field(ce_hwnd: int) -> tuple[int, int] | None:
    """배속을 적는 입력칸의 한복판(화면 좌표).

    입력칸이 여럿이라 아무거나 잡으면 안 된다. 스캔 값이나 주소 칸에 17000을
    적어 봐야 아무 일도 안 일어난다. **[Enable Speedhack] 체크칸 바로 아래에
    있는, 숫자가 적힌 작은 칸**이 그것이다 (기본값 '1.0').
    """
    check_box = winctrl.find_ctrl(ce_hwnd, cls="Button", text="Enable Speedhack")
    if check_box is None:
        return None
    best = None
    for kid in winctrl.children(ce_hwnd):
        if kid.cls.lower() != "edit" or kid.width > 120:
            continue
        try:
            float(kid.text.strip() or "x")
        except ValueError:
            continue
        gap_y = kid.top - check_box.top
        if not (-10 <= gap_y <= 70) or abs(kid.left - check_box.left) > 220:
            continue
        if best is None or gap_y < best[0]:
            best = (gap_y, kid)
    return best[1].center if best else None


# --------------------------------------------------------------------------
# 단계들
# --------------------------------------------------------------------------
def speedhack(setup: CraftSetup, ctx: RunContext) -> bool:
    """치트엔진에 게임을 붙이고 배속을 건다.

        Open Process → 목록에서 게임 → Enable Speedhack → 배속 → Apply

    게임을 껐다 켜면 프로세스가 새로 뜨므로 **매번 다시 붙인다.**
    """
    gap = setup.step_gap_s
    ce = find(setup.ce_title)
    if ce is None:
        ctx.log(f"  ⚠ 치트엔진 창('{setup.ce_title}')을 못 찾았습니다.")
        return False
    ce.activate(timeout=0.8)
    nap(ctx, gap)

    # Open Process — 왼쪽 위 네모 단추. 글씨가 없으니 생김새로 찾고,
    # 못 찾으면 찍어 둔 자리로 누른다.
    spot = open_process_point(ce.hwnd)
    if spot is not None:
        click_at(spot[0], spot[1], ctx, "Open Process (단추로 찾음)")
        nap(ctx, gap)
    elif not click(setup.open_process, ctx, "Open Process", gap_s=gap):
        return False

    # 프로세스 목록이 뜨기를 기다린다. 늦게 뜨면 다음 클릭이 허공에 나간다.
    plist = wait_for(setup.plist_title, ctx, "프로세스 목록", limit_s=8.0)
    if plist is None:
        ctx.log(f"  ⚠ 프로세스 목록('{setup.plist_title}')이 안 떴습니다.")
        return False

    # **목록에서 글씨로 찾는다.** 떠 있는 프로그램 수에 따라 줄이 밀리므로
    # 자리로는 못 맞춘다. 이름이 **똑같은** 줄만 고르므로 'Z9★ 온라인 매크로'
    # (이 프로그램 창)를 잘못 고르는 일도 없다.
    point, why = winctrl.find_row_point(plist.hwnd, setup.target_name)
    if point is not None:
        ctx.log(f"  목록에서 {why}을(를) 골랐습니다.")
        click_at(point[0], point[1], ctx, f"목록 {why}", double=setup.row_double)
        nap(ctx, gap)
    else:
        ctx.log(f"  ⚠ 목록에서 글씨로 못 찾았습니다 ({why}) — 찍어 둔 자리로 누릅니다.")
        if not click(setup.pick_row, ctx, f"목록에서 '{setup.target_name}'",
                     double=setup.row_double, gap_s=gap):
            return False

    # 목록 창이 닫히면 붙은 것이다.
    for _ in range(int(5.0 / LOOK_S)):
        if find(setup.plist_title) is None:
            break
        nap(ctx, LOOK_S)

    # 체크칸·Apply 는 적힌 글씨로 찾는다. 배속 칸은 그 둘 사이의 입력칸이다.
    if not ctrl_click(ce.hwnd, ctx, "Enable Speedhack", cls="Button",
                      text="Enable Speedhack"):
        if not click(setup.speed_check, ctx, "Enable Speedhack", gap_s=0):
            return False
    nap(ctx, gap)

    field = speed_field(ce.hwnd)
    if field is not None:
        click_at(field[0], field[1], ctx, "배속 칸 (컨트롤로 찾음)")
    elif not click(setup.speed_field, ctx, "배속 칸", gap_s=0):
        return False
    nap(ctx, 0.2)
    type_number(setup.speed_value, ctx)
    nap(ctx, 0.2)

    if not ctrl_click(ce.hwnd, ctx, "Apply", cls="Button", text="Apply"):
        if not click(setup.apply_btn, ctx, "Apply", gap_s=0):
            return False
    nap(ctx, gap)
    ctx.log(f"  치트엔진: '{setup.target_name}'에 {setup.speed_value}배 걸었습니다.")
    # 마지막으로 게임 창을 앞으로. 소리를 들으려면 창이 활성이어야 한다.
    # 여기서 어긋나도 배속은 이미 걸렸으므로 이 단계를 실패로 만들지 않는다.
    try:
        click_game_center(ctx)
    except Aborted:
        raise
    except Exception as exc:  # noqa: BLE001
        ctx.log(f"  ⚠ 게임 창 한복판을 못 눌렀습니다: {exc!r}")
    return True


def listen(setup: CraftSetup, ctx: RunContext) -> str:
    """제작 소리를 듣는다. 소리가 멎으면 "quiet"를 돌려준다.

    들리는 동안은 아무것도 하지 않는다 — 제작이 잘 돌고 있다는 뜻이다.
    """
    cue = setup.craft_sound
    if not cue.ready:
        ctx.log("  ⚠ 제작 소리를 안 배웠습니다 — [제작] 탭에서 배워 주세요.")
        return "no-sound"
    pid = sound.game_pid(find(ctx.settings.window_pattern))
    ear = sound.Ear(pid)
    try:
        ear.open()
    except Exception as exc:  # noqa: BLE001 — 소리 장치가 없을 수도 있다
        ctx.log(f"  ⚠ 소리를 못 듣습니다: {exc}")
        return "no-ear"
    board = getattr(ctx, "board", None)
    print_ = sound.SoundPrint(cue.shape)
    heard_at = time.perf_counter()
    heard_n = 0
    since = 0.0
    try:
        ctx.log(f"  제작 중 — 소리가 {setup.quiet_s:g}초 동안 없으면 끊긴 것으로 봅니다"
                f" (듣는 곳: {ear.source})")
        while True:
            check(ctx)
            now = time.perf_counter()
            frames = ear.recent(since)
            if frames:
                since = frames[-1][0]
                hit, _best = sound.match(frames, print_, cue.near, cue.floor,
                                         cue.hits)
                if hit:
                    heard_at = now
                    heard_n += 1
            quiet = now - heard_at
            if board is not None:
                board.set(제작=f"소리 {heard_n}번 들음 · 마지막에서 {quiet:.1f}초")
            if quiet >= setup.quiet_s:
                ctx.log(f"  소리가 {setup.quiet_s:g}초 동안 없습니다 "
                        f"(여태 {heard_n}번 들었습니다) → 다시 접속합니다.")
                return "quiet"
            nap(ctx, 0.05)
    finally:
        try:
            ear.close()
        except Exception:  # noqa: BLE001
            pass


def open_site(setup: CraftSetup, ctx: RunContext):
    """지구별 홈페이지를 연다. 열려서 창을 찾으면 그 창, 아니면 None.

    **탐색기(explorer)를 거쳐 연다.** 이 매크로는 관리자 권한으로 도는데, 그
    상태에서 브라우저를 바로 띄우면 이미 켜 둔(권한 없는) 브라우저와 따로 놀아
    로그인이 안 된 새 창이 뜬다. 탐색기에 맡기면 **쓰던 브라우저에 탭으로**
    열린다 — 로그인도 그대로다.
    """
    import subprocess

    url = setup.site_url.strip()
    if not url:
        return None
    ctx.log(f"  홈페이지를 엽니다: {url}")
    note(ctx, f"홈페이지 열기 {url}", "열어 둔 창이 없음")
    try:
        subprocess.Popen(["explorer.exe", url], shell=False,
                         creationflags=0x08000000)  # 검은 창 안 띄우기
    except OSError as exc:
        ctx.log(f"  ⚠ 홈페이지를 열지 못했습니다: {exc}")
        return None
    return wait_for(setup.site_title, ctx, "홈페이지",
                    limit_s=max(5.0, setup.site_wait_s))


CHANNEL_MARK = "craft_channel"


def channel_edit(setup: CraftSetup, ctx: RunContext):
    """채널 접속 매크로에서 **표시해 둔 클릭**의 자리를 이번 채널로 갈아 끼운다.

    돌려주는 것은 (이벤트 바꾸는 함수, 채널 번호). 표시된 클릭이 없거나 이번
    채널 자리를 안 찍었으면 아무것도 안 바꾼다 — 매크로는 녹화한 그대로 돈다.
    """
    number, spot = setup.channel_spot()
    if spot is None:
        return (None, number)

    def edit(events):
        marked = [e for e in events if e.get(CHANNEL_MARK)]
        if not marked:
            ctx.log("  ⚠ 채널 접속 매크로에 '제작 채널 이동' 클릭이 없습니다 — "
                    "[녹화 · 재생] 탭에서 그 클릭에 표시해 주세요.")
            return None
        ctx.log(f"  채널 {number}번 자리로 갈아 끼웁니다 "
                f"({spot.x}, {spot.y}) · 클릭 {len(marked)}개")
        return [({**e, "cx": spot.x, "cy": spot.y} if e.get(CHANNEL_MARK) else e)
                for e in events]

    return (edit, number)


def check_sizes(setup: CraftSetup, ctx: RunContext) -> None:
    """찍어 둔 자리가 지금 화면·창에서도 말이 되는지 본다.

    노트북처럼 화면이 작아지거나, 게임 창 크기를 바꾸거나, 다른 컴퓨터로 옮기면
    **찍어 둔 자리가 통째로 어긋난다.** 돌기 전에 한 번 짚어 주면, 엉뚱한 데를
    누르며 헤매는 대신 무엇을 다시 찍어야 하는지 바로 안다.
    """
    game = find(ctx.settings.window_pattern)
    if game is not None:
        width, height = game.client_size()
        ctx.log(f"  게임 창 안쪽 {width}×{height}")
        if setup.client_w and (width, height) != (setup.client_w, setup.client_h):
            ctx.log(f"  ⚠ 채널 자리를 찍을 때는 {setup.client_w}×{setup.client_h}"
                    "였습니다 — 창 크기가 달라졌으니 채널 자리가 어긋날 수 있습니다.")
    off = []
    for attr, label in (("start_btn", "클라이언트 [Start]"),
                        ("start_game", "홈페이지 [게임 시작]")):
        spot = getattr(setup, attr)
        if spot.ready and not spot.where and not on_screen(spot.x, spot.y):
            off.append(f"{label} ({spot.x}, {spot.y})")
    for i, spot in enumerate(setup.channel_spots):
        if spot.ready and not spot.where and not on_screen(spot.x, spot.y):
            off.append(f"{i + 1}채널 ({spot.x}, {spot.y})")
    if off:
        ctx.log("  ⚠ 화면 밖이라 못 누르는 자리: " + " · ".join(off)
                + " — [제작] 탭이나 [녹화 · 재생] 탭에서 다시 찍어 주세요.")


def press_esc(setup: CraftSetup, ctx: RunContext) -> None:
    """한 바퀴를 시작하며 [Esc]를 정한 횟수만큼 누른다.

    채널까지 들어오고 나면 무슨 창이 떠 있을지 모른다(공지 · 상점 · 안내).
    창이 하나라도 떠 있으면 **버프 키도 마이홈 매크로도 그 창이 먹는다.**
    그래서 아무것도 하기 전에 닫아 둔다.
    """
    from .keys import vk_of

    times = max(0, setup.esc_times)
    if not times:
        return
    vk = vk_of("Esc")
    if vk is None:
        return
    game = find(ctx.settings.window_pattern)
    if game is not None:
        bring_front(game, ctx, "게임")
    for i in range(times):
        check(ctx)
        if i:
            nap(ctx, setup.esc_gap_s)
        sender.key_tap(vk, hold_ms=40)
        note(ctx, "키 [Esc]", f"시작하며 창 닫기 {i + 1}/{times}")
    ctx.log(f"  [Esc] {times}번 (간격 {setup.esc_gap_s:g}초) — 떠 있는 창을 닫습니다.")


def use_buffs(setup: CraftSetup, ctx: RunContext, save=None) -> str:
    """주기가 된 버프만 쓴다. 무슨 일이 있었는지 한 줄로.

    **마이홈 매크로를 돌리기 직전에** 부른다. 한 바퀴가 시작될 때가 버프를 걸기
    가장 좋은 때다 — 제작 도중에 끼어들면 그 판을 건드리게 된다.

    쓴 시각이 아니라 **다음에 쓸 시각**을 설정에 적어 두므로, 프로그램을 껐다
    켜도 주기가 이어진다. 그래서 쓰고 나면 바로 저장한다(save).
    """
    from .keys import vk_of

    now = time.time()
    rows = [b for b in setup.buffs if b.ready]
    if not rows:
        return "버프 안 씀"
    used = []
    for buff in rows:
        check(ctx)
        if buff.left_s(now) > 0:
            continue
        vk = vk_of(buff.key)
        if vk is None:
            ctx.log(f"  ⚠ 버프 '{buff.name}' 키 '{buff.key}'를 모릅니다.")
            continue
        if used:
            nap(ctx, setup.buff_gap_s)   # 키 사이는 2초쯤 띄운다
        sender.key_tap(vk, hold_ms=40)
        note(ctx, f"키 [{buff.key}]", f"버프 {buff.name}")
        buff.used(time.time())
        used.append(f"[{buff.key}] {buff.name}")
    if used and save is not None:
        save()   # 다음에 쓸 시각을 바로 남긴다 (껐다 켜도 이어지게)

    now = time.time()
    plan = " · ".join(f"[{b.key}] {b.name} {b.describe(now)}" for b in rows)
    board = getattr(ctx, "board", None)
    if board is not None:
        board.set(버프=plan)
    if used:
        ctx.log(f"  버프 사용: {' → '.join(used)}")
    ctx.log(f"  버프 예정: {plan}")
    return (" · ".join(used) if used else "이번엔 쓸 것 없음") + f" ({plan})"


def bring_front(win, ctx: RunContext, label: str, tries: int = 3) -> bool:
    """그 창을 앞으로 가져온다. 앞에 섰으면 True.

    **가려진 창은 누를 수 없다.** 화면 좌표로 누르면 그 자리를 덮고 있는 창이
    대신 받기 때문이다. 그래서 누르기 전에 반드시 앞으로 세우고, 정말 앞에
    섰는지 확인한다.
    """
    for attempt in range(1, tries + 1):
        try:
            if win.is_foreground():
                return True
            win.activate(timeout=1.0)
        except Exception:  # noqa: BLE001 — 창이 사라졌을 수도 있다
            return False
        nap(ctx, 0.3)
        try:
            if win.is_foreground():
                return True
        except Exception:  # noqa: BLE001
            return False
    ctx.log(f"  ⚠ {label} 창을 앞으로 가져오지 못했습니다 "
            f"({tries}번 해 봤습니다).")
    return False


def scroll_top(win, ctx: RunContext, times: int = 10) -> None:
    """페이지를 맨 위로 올린다.

    [GAME START]는 페이지 맨 위에 있다. 조금이라도 내려가 있으면 단추가 화면
    밖으로 밀리거나 다른 것에 가려 **눌러도 안 들어간다.** 그래서 누르기 전에
    늘 맨 위로 올려 둔다. 이미 맨 위면 아무 일도 안 일어난다.

    휠은 **커서가 놓인 창**으로 간다(윈도 10부터). 그래서 커서를 그 창
    한복판에 두고 굴린다.
    """
    try:
        left, top, width, height = winctrl.size_of(win.hwnd)
    except Exception:  # noqa: BLE001 — 창이 사라졌을 수도 있다
        return
    if width <= 0 or height <= 0:
        return
    x, y = left + width // 2, top + height // 2
    if not on_screen(x, y):
        return
    sender.mouse_move(x, y)
    for _ in range(max(1, times)):
        check(ctx)
        sender.mouse_wheel(120)      # 위로
        sender.precise_sleep(0.02)
    note(ctx, f"휠 위로 ×{times}", "페이지를 맨 위로")
    nap(ctx, 0.3)


def in_window(win, x: int, y: int) -> bool:
    """그 자리가 창 안인가. 창 밖이면 눌러도 그 창이 안 받는다.

    **크기를 못 재면 '안'으로 본다.** 모르는 것을 '밖'으로 치면, 멀쩡한 자리를
    두고 괜히 더 굴리며 헤맨다.
    """
    try:
        left, top, width, height = winctrl.size_of(win.hwnd)
    except Exception:  # noqa: BLE001
        return True
    if width <= 1 or height <= 1:
        return True
    return left <= x < left + width and top <= y < top + height


def browsers(setup: CraftSetup) -> list:
    """홈페이지가 열려 있을 만한 **브라우저 창들.** 제목이 맞는 것부터."""
    rows = []
    needle = setup.site_title.strip().lower()
    for info in window.list_windows(""):
        if winctrl.exe_of(info.hwnd) not in BROWSERS:
            continue
        _x, _y, width, height = winctrl.size_of(info.hwnd)
        if width <= 1 or height <= 1:
            continue
        rank = 0 if needle and needle in info.title.lower() else 1
        rows.append((rank, info))
    rows.sort(key=lambda row: row[0])
    return [info for _rank, info in rows]


def press_game_start(setup: CraftSetup, ctx: RunContext) -> bool:
    """홈페이지의 [GAME START]를 누른다.

    **자리가 아니라 이름으로 찾는다.** 브라우저는 지금 띄운 쪽의 내용을 이름으로
    알려 주므로(z9/uia.py), 창을 옮기든 스크롤을 내리든 확대를 바꾸든 그 단추를
    찾아낸다. 찾은 자리를 진짜 마우스로 누르는 것은 사람이 하는 것과 같다.

    못 찾으면 주소를 열어 한 번 더 보고, 그래도 없으면 찍어 둔 자리로 누른다.
    """
    names = setup.names()
    why = "브라우저 창이 없습니다"
    for attempt in (1, 2):
        for info in browsers(setup):
            point, why = uia.find_named(info.hwnd, names)
            if point is None:
                continue
            page = window.GameWindow(info.hwnd, info.title)
            bring_front(page, ctx, "홈페이지")
            # **창을 화면 가득 키운다.** 작은 창으로 떠 있으면 [GAME START]가
            # 창 밖으로 밀리거나 다른 창에 가려 눌러도 안 들어간다.
            if not page.maximized():
                if page.maximize():
                    ctx.log("  홈페이지 창을 화면 가득 키웠습니다.")
                nap(ctx, 0.5)
                bring_front(page, ctx, "홈페이지")
            nap(ctx, 0.3)
            # **누르기 전에 맨 위로 올린다.** 페이지가 내려가 있으면 단추가
            # 가려지거나 화면 밖으로 밀린다.
            scroll_top(page, ctx)
            # 앞으로 올리거나 키우거나 굴리면 자리가 달라진다. 그 뒤에 다시 잰다.
            fresh, again = uia.find_named(info.hwnd, names)
            if fresh is not None:
                point, why = fresh, again
            if not in_window(page, point[0], point[1]):
                # 아직도 창 밖이다. 한 번 더 올려 보고 다시 잰다.
                ctx.log(f"  단추가 창 밖에 있습니다 {point} — 더 올려 봅니다.")
                scroll_top(page, ctx, times=20)
                fresh, again = uia.find_named(info.hwnd, names)
                if fresh is not None:
                    point, why = fresh, again
            ctx.log(f"  홈페이지: {why} — '{info.title}'")
            if not click_at(point[0], point[1], ctx, "홈페이지 [GAME START]"):
                continue
            nap(ctx, setup.step_gap_s)
            return True
        if attempt == 1:
            ctx.log(f"  브라우저에서 단추를 못 찾았습니다 ({why}) — 주소를 엽니다.")
            if open_site(setup, ctx) is None:
                break
            nap(ctx, 1.5)

    ctx.log("  ⚠ 이름으로 못 찾아 찍어 둔 자리로 누릅니다.")
    site = find(setup.site_title)
    if site is not None:
        bring_front(site, ctx, "홈페이지")
        nap(ctx, setup.step_gap_s)
    return click(setup.start_game, ctx, "홈페이지 [게임 시작]",
                 gap_s=setup.step_gap_s)


def reconnect(setup: CraftSetup, ctx: RunContext, find_macro, save=None) -> bool:
    """게임을 끄고 홈페이지로 다시 들어간다.

        강제 종료 → 홈페이지 [GAME START] → 클라이언트 창 → (10초) → [Start]
        → 게임 창 → 채널 접속 매크로

    **[Start]를 눌러도 게임이 안 뜨는 때가 있다.** 그때는 홈페이지부터 다시
    한다 — 클라이언트 창만 붙들고 기다려 봐야 영영 안 뜨기 때문이다. 다시 하기
    전에 남은 클라이언트 창은 끈다. 그대로 두면 다음 [GAME START]가 안 먹는다.
    """
    gap = setup.step_gap_s
    kill_game(ctx)
    nap(ctx, setup.after_kill_s)

    fresh = None
    for attempt in range(1, max(1, setup.connect_tries) + 1):
        if attempt > 1:
            ctx.log(f"  홈페이지부터 다시 합니다 ({attempt}번째).")
        if not press_game_start(setup, ctx):
            return False

        # 클라이언트 창이 뜨기를 기다린다. **그냥 자는 것보다 창을 기다리는
        # 편이 낫다** — 빨리 뜨면 바로 가고, 늦게 떠도 안 놓친다.
        ctx.log(f"  클라이언트 창('{setup.client_title}')을 기다립니다…")
        client = wait_for(setup.client_title, ctx, "클라이언트",
                          limit_s=setup.client_wait_s)
        if client is None:
            ctx.log(f"  ⚠ 클라이언트 창('{setup.client_title}')이 "
                    f"{setup.client_wait_s:g}초 안에 안 떴습니다.")
            continue
        bring_front(client, ctx, "클라이언트")
        # 창은 금세 뜨지만 그 안이 다 그려지려면 더 걸린다. 일찍 누르면 헛손질이다.
        ctx.log(f"  클라이언트 창이 떴습니다 — {setup.load_wait_s:g}초 뒤에 "
                "[Start]를 누릅니다.")
        nap(ctx, setup.load_wait_s)
        bring_front(client, ctx, "클라이언트")  # 그 사이 딴 창이 앞에 왔을 수 있다
        if not click(setup.start_btn, ctx, "클라이언트 [Start]", gap_s=gap):
            return False

        # 게임 창이 새로 뜬다. **손잡이가 바뀌므로 여기서 다시 잡아 준다** —
        # 이걸 빼면 그 뒤의 매크로가 죽은 창에 입력을 쏜다.
        fresh = wait_for(ctx.settings.window_pattern, ctx, "게임",
                         limit_s=setup.game_wait_s)
        if fresh is not None:
            break
        ctx.log(f"  ⚠ [Start]를 눌렀는데 게임 창이 {setup.game_wait_s:g}초 안에 "
                "안 떴습니다.")
        kill_window(setup.client_title, ctx, "클라이언트")
        nap(ctx, setup.after_kill_s)

    if fresh is None:
        ctx.log(f"  ⚠ {setup.connect_tries}번 해 봤지만 게임이 안 떴습니다.")
        return False
    ctx.window = fresh
    fresh.activate(timeout=1.0)
    nap(ctx, gap)

    edit, number = channel_edit(setup, ctx)
    if not _run_macro_step(setup.channel_macro, ctx, find_macro,
                           f"  채널 접속 ({number}채널)" if number else "  채널 접속",
                           edit=edit):
        raise Aborted()
    if edit is not None:
        setup.channel_done()
        nxt, _spot = setup.channel_spot()
        ctx.log(f"  다음 접속은 {nxt}채널입니다.")
        if save is not None:
            save()
    return True


# --------------------------------------------------------------------------
# 한 바퀴
# --------------------------------------------------------------------------
def run_craft(setup: CraftSetup, ctx: RunContext, find_macro=None,
              cycles: int = 0, save=None) -> None:
    """무한 반복. [정지]를 누를 때까지 돈다.

    cycles를 주면 그만큼만 돈다 (시험용).
    """
    board = getattr(ctx, "board", None)
    problems = setup.problems()
    if problems:
        ctx.log("제작: 아직 못 정한 것이 있습니다 —")
        for line in problems:
            ctx.log(f"  · {line}")
        return

    ctx.log("제작 시작 — [정지]를 누를 때까지 돕니다.")
    check_sizes(setup, ctx)
    ctx.log(f"  ① 마이홈 '{setup.home_macro}'  ②  치트엔진 {setup.speed_value}배"
            f"  ③ 소리 {setup.quiet_s:g}초 무음이면 끊김  ④ 채널 '{setup.channel_macro}'")
    done = 0
    while True:
        check(ctx)
        if cycles and done >= cycles:
            ctx.log(f"제작 끝 — {done}바퀴 돌았습니다.")
            return
        done += 1
        setup.cycles += 1
        if board is not None:
            board.set(제작바퀴=f"{done}바퀴째 (여태 {setup.cycles}번)")

        # 게임이 꺼져 있으면(처음부터 꺼져 있었든, 튕겼든) **먼저 켠다.**
        # 마지막 단계인 '다시 접속'이 곧 게임을 켜는 단계다.
        if find(ctx.settings.window_pattern) is None:
            say(ctx, board, "④ 다시 접속", "게임이 꺼져 있어 먼저 켭니다")
            retry(lambda: reconnect(setup, ctx, find_macro, save), setup, ctx,
                  "게임 켜기")

        # ⓪ 맨 먼저 [Esc] — 떠 있는 창을 닫는다.
        say(ctx, board, "⓪ 시작", f"[Esc] {setup.esc_times}번으로 창 닫기")
        press_esc(setup, ctx)

        # ⓪ 버프 — 마이홈 매크로 **직전에** 주기가 된 것만 쓴다.
        say(ctx, board, "⓪ 버프", "주기가 된 것이 있는지 봅니다")
        use_buffs(setup, ctx, save)

        # ① 마이홈 개설·이동
        say(ctx, board, "① 마이홈", f"{done}바퀴째 — 매크로 '{setup.home_macro}'")
        if not _run_macro_step(setup.home_macro, ctx, find_macro, "  마이홈"):
            raise Aborted()

        # ② 치트엔진
        say(ctx, board, "② 치트엔진", f"{setup.speed_value}배 걸기")
        if not retry(lambda: speedhack(setup, ctx), setup, ctx, "치트엔진"):
            continue

        # ③ 제작 — 소리가 멎을 때까지
        say(ctx, board, "③ 제작", "소리를 듣는 중")
        why = listen(setup, ctx)
        if why in ("no-sound", "no-ear"):
            nap(ctx, setup.retry_s)
            continue

        # ④ 다시 접속
        say(ctx, board, "④ 다시 접속", "게임 끄고 홈페이지로")
        retry(lambda: reconnect(setup, ctx, find_macro, save), setup, ctx,
              "다시 접속")


def say(ctx: RunContext, board, step: str, detail: str) -> None:
    if board is not None:
        board.set(단계=f"{step} — {detail}")
    ctx.log(f"{step} · {detail}")


def retry(work, setup: CraftSetup, ctx: RunContext, label: str) -> bool:
    """될 때까지 다시 한다. [정지]를 누르면 그때 멈춘다.

    무한 반복이 목표이므로 **여기서 포기하면 안 된다.** 창을 못 찾은 것은 대개
    잠깐이다(로딩 중이거나 아직 안 떴거나). 몇 초 쉬었다가 같은 일을 다시 한다.
    """
    tries = 0
    while True:
        check(ctx)
        tries += 1
        try:
            if work():
                return True
        except Aborted:
            raise
        except Exception as exc:  # noqa: BLE001 — 한 단계가 터져도 멈추지 않는다
            ctx.log(f"  ⚠ {label}에서 문제가 났습니다: {exc!r}")
        ctx.log(f"  {label}을(를) {setup.retry_s:g}초 뒤에 다시 해 봅니다 "
                f"({tries}번째).")
        nap(ctx, setup.retry_s)


__all__ = ["run_craft", "speedhack", "listen", "reconnect", "kill_game"]
