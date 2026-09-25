"""게임 소리를 엿듣는다 — 낚시 성공 효과음을 알아보려고.

화면으로 낚음을 가리는 것이 번번이 어긋났다. 빨간 글씨는 가리거나 밀리면 못 보고,
낚싯대 흔들림은 너무 미세해서 문턱을 잡기 어려웠다. 그런데 **낚시에 성공하면 효과음이
울린다.** 소리는 가려지지도, 밀리지도, 미세하지도 않다.

## 어떻게 듣나 — WASAPI 루프백

마이크가 아니라 **스피커로 나가는 소리를 되받아** 듣는다(loopback). 그래야 스피커를
꺼 두든 이어폰을 꽂았든 상관없이 게임 소리가 들어온다. 윈도우가 주는 길은 WASAPI뿐이고,
그건 COM이라 ctypes로 vtable을 직접 두드려야 한다. 외부 라이브러리를 안 쓰기로 한
프로젝트라 달리 방법이 없다.

    MMDeviceEnumerator ─▶ 기본 재생 장치
                          └─▶ IAudioClient (LOOPBACK 켜고 Initialize)
                                └─▶ IAudioCaptureClient ─▶ 소리 조각들

## 무엇으로 알아보나 — 소리의 결

소리 크기만 보면 배경 음악이나 다른 효과음에 그대로 속는다. 그래서 **어느 높이의
소리가 얼마나 섞여 있는지**(대역별 세기)를 재서, 미리 배워 둔 것과 결이 같은지 본다.

높이별 세기는 괴르첼(Goertzel)로 낸다. 푸리에 변환을 통째로 하면 필요 없는 수천 개
높이까지 다 구하게 되는데, 우리는 열두 개만 있으면 된다. 괴르첼은 **원하는 높이 하나만**
값싸게 뽑는 방법이다.

그래도 파이썬 반복문이라 비싸다. 그래서 먼저 **4분의 1로 솎는다**(48kHz → 12kHz).
사람이 듣는 효과음의 결은 6kHz 아래에 다 들어 있으므로 잃는 것이 없고, 셈은 네 배
싸진다.

## 왜 따로 도는 실 위에서 듣나

소리는 흘러간다. 화면은 언제 찍어도 그때 것이 나오지만, 소리는 **그때 안 받아 두면
사라진다.** 낚시 상태 기계는 미니게임을 푸느라 몇 초씩 딴짓을 하므로, 그동안 소리를
받아 둘 사람이 따로 있어야 한다. 그래서 조용한 실(thread) 하나가 계속 듣고, 상태
기계는 "그동안 그 소리 났었니?"만 물어본다.
"""

from __future__ import annotations

import ctypes
import math
import struct
import threading
import time
from ctypes import POINTER, byref, c_float, c_uint32, c_uint64, c_void_p

ole32 = ctypes.windll.ole32

# -- COM 알맹이 -------------------------------------------------------------
CLSCTX_ALL = 23
COINIT_MULTITHREADED = 0x0
S_OK = 0

# 소리 조각에 쓸모 있는 것이 없다는 표시. 그래도 자리는 차지하므로 넘겨야 한다.
AUDCLNT_BUFFERFLAGS_SILENT = 0x2

AUDCLNT_SHAREMODE_SHARED = 0
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000

# 재생 장치 / 기본 쓰임새
eRender = 0
eConsole = 0

WAVE_FORMAT_PCM = 1
WAVE_FORMAT_IEEE_FLOAT = 3
WAVE_FORMAT_EXTENSIBLE = 0xFFFE


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text: str = "") -> None:
        super().__init__()
        if text:
            ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(self))


CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")
# 32비트 실수 소리인지 가리는 데 쓴다 (WAVE_FORMAT_EXTENSIBLE일 때).
SUBTYPE_IEEE_FLOAT = GUID("{00000003-0000-0010-8000-00AA00389B71}")
SUBTYPE_PCM = GUID("{00000001-0000-0010-8000-00AA00389B71}")


class WAVEFORMATEX(ctypes.Structure):
    """소리 형식.

    **_pack_ = 1이 없으면 안 된다.** 필드를 더하면 18바이트인데, 그 안에 4바이트
    짜리가 있다는 이유로 ctypes가 20바이트로 부풀린다. 윈도우는 18바이트로 주므로
    뒤따라오는 것들이 통째로 두 바이트씩 밀린다 — 32비트 실수 소리를 정수로 잘못
    읽어 알아들을 수 없는 잡음이 된다.
    """

    _pack_ = 1
    _fields_ = [("wFormatTag", ctypes.c_uint16),
                ("nChannels", ctypes.c_uint16),
                ("nSamplesPerSec", ctypes.c_uint32),
                ("nAvgBytesPerSec", ctypes.c_uint32),
                ("nBlockAlign", ctypes.c_uint16),
                ("wBitsPerSample", ctypes.c_uint16),
                ("cbSize", ctypes.c_uint16)]


class WAVEFORMATEXTENSIBLE(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("Format", WAVEFORMATEX),
                ("Samples", ctypes.c_uint16),
                ("dwChannelMask", ctypes.c_uint32),
                ("SubFormat", GUID)]


class SoundError(RuntimeError):
    """소리를 못 듣는다. 왜 못 듣는지 사람이 읽을 말로 담는다."""


# -- 게임 소리만 따로 듣기 (프로세스 되받기, 윈도 10 2004 이상) ---------------
#
# 스피커로 나가는 소리를 되받으면 **윈도 음량을 0으로 두거나 음소거했을 때** 같이
# 조용해질 수 있다. 게임 소리는 키워 두고 스피커만 꺼 두는 쓰임에서는 그게 곧
# "효과음을 못 듣는다"가 된다. 프로세스 되받기는 **그 프로그램이 낸 소리를 스피커
# 음량을 거치기 전에** 받는다 — 음소거해도, 음량이 0이어도 그대로 들어온다.
PROCESS_LOOPBACK_PATH = "VAD\\Process_Loopback"
ACTIVATION_PROCESS_LOOPBACK = 1
INCLUDE_TARGET_PROCESS_TREE = 0
VT_BLOB = 65
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000
E_NOINTERFACE = 0x80004002 - 0x100000000


class _LoopbackParams(ctypes.Structure):
    _fields_ = [("TargetProcessId", ctypes.c_uint32),
                ("ProcessLoopbackMode", ctypes.c_int)]


class _ActivationParams(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int),
                ("ProcessLoopbackParams", _LoopbackParams)]


class _Blob(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("pBlobData", c_void_p)]


class _PropVariant(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("blob", _Blob)]


_QI = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p, POINTER(c_void_p))
_REF = ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)
_DONE = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, c_void_p)


class _HandlerVtbl(ctypes.Structure):
    _fields_ = [("QueryInterface", _QI), ("AddRef", _REF), ("Release", _REF),
                ("ActivateCompleted", _DONE)]


class _HandlerObj(ctypes.Structure):
    _fields_ = [("lpVtbl", POINTER(_HandlerVtbl))]


class _Activation:
    """ActivateAudioInterfaceAsync가 다 되면 불러 주는 COM 객체를 파이썬으로 만든다.

    윈도우는 이 객체를 **다른 실에서** 부른다. 우리는 '다 됐다' 깃발만 세우고,
    결과는 기다리던 실이 꺼내 간다.
    """

    _GOOD: list[bytes] | None = None

    def __init__(self) -> None:
        if _Activation._GOOD is None:
            _Activation._GOOD = [bytes(GUID(t)) for t in (
                "{00000000-0000-0000-C000-000000000046}",   # IUnknown
                "{41D949AB-9862-444A-80F6-C261334DA5EB}",   # 완료 알림 받는 쪽
                "{94EA2B94-E9CC-49E0-C0FF-EE64CA8F5B90}",   # IAgileObject
            )]
        self.done = threading.Event()
        # 불릴 함수들은 이 객체가 사는 동안 꼭 붙잡아 둔다 (안 그러면 사라진다).
        self._qi = _QI(self._query)
        self._add = _REF(lambda _this: 1)
        self._rel = _REF(lambda _this: 1)
        self._fin = _DONE(self._finished)
        self._vtbl = _HandlerVtbl(self._qi, self._add, self._rel, self._fin)
        self.obj = _HandlerObj(ctypes.pointer(self._vtbl))

    def _query(self, this, riid, out):
        want = ctypes.string_at(riid, ctypes.sizeof(GUID))
        if want in (_Activation._GOOD or []):
            out[0] = this
            return S_OK
        out[0] = None
        return E_NOINTERFACE

    def _finished(self, _this, _op):
        self.done.set()
        return S_OK


def game_pid(window) -> int:
    """게임 창을 띄운 프로그램의 번호. 모르면 0."""
    hwnd = getattr(window, "hwnd", 0) if window is not None else 0
    if not hwnd:
        return 0
    try:
        from .window import _window_process_id

        return int(_window_process_id(hwnd))
    except (ImportError, OSError):
        return 0


def _call(obj: c_void_p, slot: int, restype, *argtypes):
    """COM 함수 하나를 부를 수 있게 꺼내 온다.

    COM 객체는 맨 앞에 함수 표(vtable)를 가리키는 값을 하나 들고 있다. 그 표의
    몇 번째 칸인지가 곧 함수다. IUnknown이 0·1·2를 쓰므로 제 함수는 3번부터다.
    """
    vtable = ctypes.cast(obj, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtable, POINTER(c_void_p))[slot]
    proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
    return proto(fn)


def _release(obj) -> None:
    if obj:
        _call(obj, 2, ctypes.c_uint32)(obj)


def _check(hr: int, what: str) -> None:
    if hr != S_OK:
        raise SoundError(f"{what} 실패 (0x{hr & 0xFFFFFFFF:08X})")


# --------------------------------------------------------------------------
# 소리 조각에서 결 뽑기
# --------------------------------------------------------------------------
# 몇 분의 1로 솎을지. 44.1kHz를 4로 솎으면 11kHz — 5.5kHz까지 들린다. 효과음의
# 결은 그 아래에 다 있고, 셈은 네 배 싸진다.
#
# 솎기 전에 높은 소리를 걸러 내지 않으므로, 5.5kHz보다 높은 것은 접혀서 낮은 쪽에
# 섞여 든다. **알고도 치르는 값이다** — 배울 때도 알아볼 때도 똑같이 접히므로
# 견주는 데는 지장이 없고, 거르개를 두면 조각마다 파이썬 반복이 하나 더 는다.
DECIMATE = 4

# 볼 높이들(Hz). 낮은 쪽을 촘촘히 둔 것은 사람이 그렇게 듣기 때문이다 — 200Hz와
# 400Hz는 딴 소리지만 5000Hz와 5200Hz는 같은 소리로 들린다.
BANDS = (180.0, 260.0, 370.0, 520.0, 740.0, 1040.0,
         1460.0, 2050.0, 2880.0, 4050.0, 5000.0, 5700.0)

# 이보다 조용하면 아예 안 본다. 고요한 방에서 결을 재 봐야 잡음만 나온다.
QUIET = 0.004


def to_mono(raw: bytes, fmt) -> list[float]:
    """소리 조각을 -1.0~1.0 사이 홑소리 목록으로. 솎는 것도 여기서 한다.

    채널이 여럿이면 **첫 번째 것만** 쓴다. 다 더해 평균 내면 더 곱겠지만, 게임
    효과음은 좌우가 거의 같고 우리는 결만 보면 되므로 값을 치를 까닭이 없다.
    """
    ch = max(1, fmt.nChannels)
    if fmt.wBitsPerSample == 32 and fmt.is_float:
        step = ch * DECIMATE
        count = len(raw) // (4 * step)
        if count <= 0:
            return []
        # 솎을 자리만 골라 푼다. 다 풀고 버리면 네 배를 헛일한다.
        return [struct.unpack_from("<f", raw, i * 4 * step)[0]
                for i in range(count)]
    if fmt.wBitsPerSample == 16:
        step = ch * DECIMATE
        count = len(raw) // (2 * step)
        if count <= 0:
            return []
        return [struct.unpack_from("<h", raw, i * 2 * step)[0] / 32768.0
                for i in range(count)]
    raise SoundError(
        f"다룰 줄 모르는 소리 형식입니다 ({fmt.wBitsPerSample}비트). "
        "윈도우 소리 설정에서 16비트나 32비트로 맞춰 주세요.")


def loudness(samples: list[float]) -> float:
    """얼마나 큰 소리인가 (0.0~1.0쯤)."""
    if not samples:
        return 0.0
    return math.sqrt(sum(v * v for v in samples) / len(samples))


_WINDOWS: dict[int, list[float]] = {}


def _window(n: int) -> list[float]:
    """한 조각의 앞뒤를 부드럽게 깎는 값들 (해닝 창).

    이걸 안 씌우면 조각이 뚝 끊긴 자리가 **없던 높이의 소리로 새어 나온다.**
    880Hz 소리를 넣었더니 740Hz도 1040Hz도 아닌 520Hz가 가장 세게 나온 적이
    있는데, 그게 이 샘 때문이었다. 앞뒤를 0으로 깎아 두면 새는 것이 훨씬 준다.

    조각 길이는 늘 같으므로 한 번 만들어 두고 쓴다.
    """
    got = _WINDOWS.get(n)
    if got is None:
        if n < 2:
            got = [1.0] * n
        else:
            got = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1))
                   for i in range(n)]
        _WINDOWS[n] = got
    return got


def band_energy(samples: list[float], rate: int,
                bands: tuple[float, ...] = BANDS) -> list[float]:
    """높이별 세기 — 괴르첼.

    한 높이의 세기를 구하는 데 곱셈 한 번, 덧셈 두 번이면 된다. 푸리에 변환을
    통째로 돌리면 안 쓸 수천 개 높이까지 다 나오는데, 우리는 열두 개뿐이다.

    솎아 낸 뒤라 **절반 높이(나이퀴스트)보다 높은 소리는 들을 수 없다.** 그런
    대역은 재 봐야 접혀 들어온 엉뚱한 값이 나오므로 그냥 0으로 둔다. 자리는
    남겨 둔다 — 배워 둔 결과 길이가 어긋나면 견줄 수 없기 때문이다.
    """
    n = len(samples)
    if n < 32:
        return [0.0] * len(bands)
    # 절반 높이 바로 아래까지는 제대로 들린다. 44.1kHz를 솎으면 5292Hz까지다.
    ceiling = rate * 0.48
    win = _window(n)
    shaped = [v * w for v, w in zip(samples, win)]
    out = []
    for hz in bands:
        if hz >= ceiling:
            out.append(0.0)
            continue
        k = 2.0 * math.cos(2.0 * math.pi * hz / rate)
        s1 = s2 = 0.0
        for v in shaped:
            s0 = v + k * s1 - s2
            s2 = s1
            s1 = s0
        # |X(k)|^2 을 표본 수로 나눠 길이에 안 흔들리게 한다.
        out.append(math.sqrt(max(0.0, s1 * s1 + s2 * s2 - k * s1 * s2)) / n)
    return out


def shape_of(samples: list[float], rate: int) -> list[float] | None:
    """세기를 걷어 낸 **결**만. 크게 틀든 작게 틀든 같은 소리는 같은 결이다.

    소리 크기로 가리면 볼륨을 바꾸는 순간 못 알아본다. 그래서 대역별 세기를
    길이 1로 맞춰(정규화) 방향만 남긴다.
    """
    got = band_energy(samples, rate)
    size = math.sqrt(sum(v * v for v in got))
    if size <= 1e-9:
        return None
    return [v / size for v in got]


def likeness(a: list[float], b: list[float]) -> float:
    """두 결이 얼마나 닮았나. 1.0이면 똑같고 0이면 딴판."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return max(0.0, min(1.0, sum(x * y for x, y in zip(a, b))))


# --------------------------------------------------------------------------
# 귀 — 따로 도는 실 위에서 쉬지 않고 듣는다
# --------------------------------------------------------------------------
class Format:
    """소리 형식 중 우리가 쓰는 것만."""

    __slots__ = ("nChannels", "nSamplesPerSec", "wBitsPerSample", "is_float")

    def __init__(self, wfx: WAVEFORMATEX, is_float: bool) -> None:
        self.nChannels = wfx.nChannels
        self.nSamplesPerSec = wfx.nSamplesPerSec
        self.wBitsPerSample = wfx.wBitsPerSample
        self.is_float = is_float

    @property
    def rate(self) -> int:
        """솎고 난 뒤의 초당 표본 수."""
        return max(1, self.nSamplesPerSec // DECIMATE)

    def describe(self) -> str:
        kind = "실수" if self.is_float else "정수"
        return (f"{self.nSamplesPerSec}Hz · {self.nChannels}채널 · "
                f"{self.wBitsPerSample}비트 {kind}")


class Ear:
    """스피커로 나가는 소리를 계속 받아 결을 재 둔다.

    쓰는 쪽은 [열기] → [heard()로 물어보기] → [닫기]만 하면 된다. COM이며 실이며
    하는 것은 전부 이 안에 가둔다.
    """

    # 한 번에 재는 소리 길이(초). 짧으면 낮은 소리의 결이 안 잡히고, 길면
    # 짧은 효과음이 앞뒤 고요에 묻힌다.
    FRAME_S = 0.04

    def __init__(self, pid: int = 0) -> None:
        self.fmt: Format | None = None
        self.error = ""
        # 게임 프로그램 번호. 주면 **게임 소리만** 스피커 음량과 상관없이 듣는다.
        self.pid = int(pid or 0)
        # 실제로 무엇을 듣고 있나 — 로그에 쓴다.
        self.source = ""
        self._op = None
        self._event = None
        self._handler = None
        self._thread = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._frames: list[tuple[float, float, list[float]]] = []  # 때·세기·결
        # 최근 몇 조각까지 들고 있을지 (약 60초). 미니게임 한 판(최대 30초 남짓)
        # 동안 난 클릭 소리를 판이 끝난 뒤에 한꺼번에 센다 — 판을 푸는 반복문
        # 안에서 소리를 들여다보면 그만큼 클릭이 늦어진다.
        self._keep = 1500
        self._client = None
        self._capture = None
        self._enum = None
        self._device = None

    # -- 열고 닫기 --------------------------------------------------------
    def open(self) -> None:
        """소리를 듣기 시작한다. 못 들으면 SoundError."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="z9-ear")
        ready = threading.Event()
        self._ready = ready
        self._thread.start()
        ready.wait(3.0)
        if self.error:
            self._thread = None
            raise SoundError(self.error)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1.5)
            self._thread = None

    @property
    def listening(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- 물어보기 ---------------------------------------------------------
    def recent(self, since: float) -> list[tuple[float, float, list[float]]]:
        """그 시각 뒤로 들어온 조각들."""
        with self._lock:
            return [f for f in self._frames if f[0] > since]

    def latest(self) -> tuple[float, float, list[float]] | None:
        with self._lock:
            return self._frames[-1] if self._frames else None

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()

    # -- 실 안쪽 ----------------------------------------------------------
    def _run(self) -> None:
        try:
            self._setup()
        except SoundError as exc:
            self.error = str(exc)
            self._ready.set()
            return
        except OSError as exc:  # ctypes가 터지는 경우
            self.error = f"소리 장치를 여는 중 문제가 생겼습니다: {exc}"
            self._ready.set()
            return
        self.error = ""
        self._ready.set()
        try:
            self._listen()
        finally:
            self._teardown()

    def _setup(self) -> None:
        ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        if self.pid:
            try:
                self._setup_process()
                self.source = "게임 소리만 (스피커 음량·음소거와 상관없음)"
                return
            except (SoundError, OSError, AttributeError) as exc:
                # 오래된 윈도라 안 되면 예전 방식으로. 그래도 듣기는 한다.
                self._teardown_client()
                self.source = f"스피커로 나가는 소리 (게임만 듣기 실패: {exc})"
        else:
            self.source = "스피커로 나가는 소리"
        self._setup_endpoint()

    def _setup_process(self) -> None:
        """게임 프로그램이 내는 소리만 받는다 — 스피커 음량·음소거와 상관없다."""
        params = _ActivationParams()
        params.ActivationType = ACTIVATION_PROCESS_LOOPBACK
        params.ProcessLoopbackParams.TargetProcessId = self.pid
        params.ProcessLoopbackParams.ProcessLoopbackMode = INCLUDE_TARGET_PROCESS_TREE
        self._params = params
        prop = _PropVariant()
        prop.vt = VT_BLOB
        prop.blob.cbSize = ctypes.sizeof(params)
        prop.blob.pBlobData = ctypes.cast(ctypes.pointer(params), c_void_p)
        self._prop = prop

        activate = ctypes.WinDLL("Mmdevapi.dll").ActivateAudioInterfaceAsync
        activate.argtypes = [ctypes.c_wchar_p, POINTER(GUID), POINTER(_PropVariant),
                             c_void_p, POINTER(c_void_p)]
        activate.restype = ctypes.c_long
        handler = _Activation()
        self._handler = handler  # 끝날 때까지 살아 있어야 한다
        op = c_void_p()
        hr = activate(PROCESS_LOOPBACK_PATH, byref(IID_IAudioClient), byref(prop),
                      ctypes.cast(ctypes.pointer(handler.obj), c_void_p), byref(op))
        _check(hr, "게임 소리 통로 열기")
        self._op = op
        if not handler.done.wait(3.0):
            raise SoundError("게임 소리 통로가 열리지 않습니다 (시간 초과)")
        result = ctypes.c_long(0)
        client = c_void_p()
        hr = _call(op, 3, ctypes.c_long, POINTER(ctypes.c_long),
                   POINTER(c_void_p))(op, byref(result), byref(client))
        _check(hr, "게임 소리 통로 받기")
        _check(result.value, "게임 소리 통로")
        self._client = client

        # 이 방식은 형식을 알려 주지 않는다 — 우리가 정해 준다 (48kHz 16비트 둘).
        wfx = WAVEFORMATEX()
        wfx.wFormatTag = WAVE_FORMAT_PCM
        wfx.nChannels = 2
        wfx.nSamplesPerSec = 48000
        wfx.wBitsPerSample = 16
        wfx.nBlockAlign = wfx.nChannels * wfx.wBitsPerSample // 8
        wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign
        wfx.cbSize = 0
        self._wfx_keep = wfx
        self.fmt = Format(wfx, False)

        flags = (AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK
                 | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                 | AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
        hr = _call(client, 3, ctypes.c_long, ctypes.c_int, ctypes.c_uint32,
                   ctypes.c_int64, ctypes.c_int64, POINTER(WAVEFORMATEX),
                   c_void_p)(client, AUDCLNT_SHAREMODE_SHARED, flags,
                             10_000_000, 0, byref(wfx), None)
        _check(hr, "게임 소리 받기 준비")
        # 알림 방식으로 열었으니 알림 깃발을 달아 줘야 시작된다.
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateEventW.restype = c_void_p
        event = kernel32.CreateEventW(None, False, False, None)
        self._event = event
        hr = _call(client, 13, ctypes.c_long, c_void_p)(client, event)
        _check(hr, "게임 소리 알림 달기")

        capture = c_void_p()
        hr = _call(client, 14, ctypes.c_long, POINTER(GUID),
                   POINTER(c_void_p))(client, byref(IID_IAudioCaptureClient),
                                      byref(capture))
        _check(hr, "게임 소리 받는 통로 열기")
        self._capture = capture
        hr = _call(client, 10, ctypes.c_long)(client)
        _check(hr, "게임 소리 듣기 시작")

    def _teardown_client(self) -> None:
        """반쯤 열다 만 것을 치운다 (예전 방식으로 갈아타기 전에)."""
        for obj in (self._capture, self._client, self._op):
            try:
                _release(obj)
            except OSError:
                pass
        self._capture = self._client = self._op = None
        if self._event:
            try:
                ctypes.windll.kernel32.CloseHandle(c_void_p(self._event))
            except OSError:
                pass
            self._event = None

    def _setup_endpoint(self) -> None:
        """스피커로 나가는 소리를 되받는다 (예전 방식)."""
        enum = c_void_p()
        hr = ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None,
                                    CLSCTX_ALL, byref(IID_IMMDeviceEnumerator),
                                    byref(enum))
        _check(hr, "소리 장치 목록 열기")
        self._enum = enum

        device = c_void_p()
        hr = _call(enum, 4, ctypes.HRESULT, ctypes.c_int, ctypes.c_int,
                   POINTER(c_void_p))(enum, eRender, eConsole, byref(device))
        _check(hr, "기본 재생 장치 찾기")
        self._device = device

        client = c_void_p()
        hr = _call(device, 3, ctypes.HRESULT, POINTER(GUID), ctypes.c_uint32,
                   c_void_p, POINTER(c_void_p))(
            device, byref(IID_IAudioClient), CLSCTX_ALL, None, byref(client))
        _check(hr, "소리 통로 열기")
        self._client = client

        wfx_ptr = POINTER(WAVEFORMATEX)()
        hr = _call(client, 8, ctypes.HRESULT,
                   POINTER(POINTER(WAVEFORMATEX)))(client, byref(wfx_ptr))
        _check(hr, "소리 형식 알아보기")
        wfx = wfx_ptr.contents
        is_float = wfx.wFormatTag == WAVE_FORMAT_IEEE_FLOAT
        if wfx.wFormatTag == WAVE_FORMAT_EXTENSIBLE:
            ext = ctypes.cast(wfx_ptr,
                              POINTER(WAVEFORMATEXTENSIBLE)).contents
            is_float = bytes(ext.SubFormat) == bytes(SUBTYPE_IEEE_FLOAT)
        self.fmt = Format(wfx, is_float)
        needed = ctypes.sizeof(WAVEFORMATEX) + wfx.cbSize
        keep = (ctypes.c_byte * needed)()
        ctypes.memmove(keep, wfx_ptr, needed)
        self._wfx_keep = keep  # Initialize가 끝날 때까지 살아 있어야 한다

        # 1초짜리 그릇. 넉넉해야 우리가 잠깐 딴짓해도 소리가 안 흘러넘친다.
        hr = _call(client, 3, ctypes.HRESULT, ctypes.c_int, ctypes.c_uint32,
                   ctypes.c_int64, ctypes.c_int64, POINTER(WAVEFORMATEX),
                   c_void_p)(
            client, AUDCLNT_SHAREMODE_SHARED, AUDCLNT_STREAMFLAGS_LOOPBACK,
            10_000_000, 0,
            ctypes.cast(keep, POINTER(WAVEFORMATEX)), None)
        ole32.CoTaskMemFree(wfx_ptr)  # 윈도우가 잡아 준 자리를 돌려준다
        _check(hr, "되받아 듣기 시작 준비")

        capture = c_void_p()
        hr = _call(client, 14, ctypes.HRESULT, POINTER(GUID),
                   POINTER(c_void_p))(
            client, byref(IID_IAudioCaptureClient), byref(capture))
        _check(hr, "소리 받는 통로 열기")
        self._capture = capture

        hr = _call(client, 10, ctypes.HRESULT)(client)
        _check(hr, "듣기 시작")

    def _listen(self) -> None:
        cap = self._capture
        fmt = self.fmt
        get_next = _call(cap, 5, ctypes.HRESULT, POINTER(c_uint32))
        get_buf = _call(cap, 3, ctypes.HRESULT, POINTER(POINTER(ctypes.c_byte)),
                        POINTER(c_uint32), POINTER(ctypes.c_uint32),
                        POINTER(c_uint64), POINTER(c_uint64))
        release = _call(cap, 4, ctypes.HRESULT, c_uint32)
        block = fmt.nChannels * (fmt.wBitsPerSample // 8)
        want = max(1, int(fmt.nSamplesPerSec * self.FRAME_S))
        pending = bytearray()

        while not self._stop.is_set():
            size = c_uint32(0)
            if get_next(cap, byref(size)) != S_OK:
                break
            if size.value == 0:
                time.sleep(0.005)
                continue
            data = POINTER(ctypes.c_byte)()
            frames = c_uint32(0)
            flags = ctypes.c_uint32(0)
            if get_buf(cap, byref(data), byref(frames), byref(flags),
                       None, None) != S_OK:
                break
            count = frames.value
            if count:
                if flags.value & AUDCLNT_BUFFERFLAGS_SILENT or not data:
                    # 고요할 때 윈도우는 알맹이를 안 준다. 0으로 채워야 시간이
                    # 제대로 흐른다 — 안 그러면 고요가 통째로 사라진다.
                    pending += bytes(count * block)
                else:
                    pending += ctypes.string_at(data, count * block)
            release(cap, frames)

            step = want * block
            while len(pending) >= step:
                chunk = bytes(pending[:step])
                del pending[:step]
                self._digest(chunk)

    def _digest(self, chunk: bytes) -> None:
        try:
            mono = to_mono(chunk, self.fmt)
        except SoundError:
            return
        if not mono:
            return
        level = loudness(mono)
        shape = shape_of(mono, self.fmt.rate) if level >= QUIET else None
        now = time.perf_counter()
        with self._lock:
            self._frames.append((now, level, shape or []))
            if len(self._frames) > self._keep:
                del self._frames[:len(self._frames) - self._keep]

    def _teardown(self) -> None:
        try:
            if self._client:
                _call(self._client, 11, ctypes.HRESULT)(self._client)
        except OSError:
            pass
        for obj in (self._capture, self._client, self._device, self._enum, self._op):
            try:
                _release(obj)
            except OSError:
                pass
        self._capture = self._client = self._device = self._enum = self._op = None
        if self._event:
            try:
                ctypes.windll.kernel32.CloseHandle(c_void_p(self._event))
            except OSError:
                pass
            self._event = None
        try:
            ole32.CoUninitialize()
        except OSError:
            pass


def can_listen(pid: int = 0) -> tuple[bool, str]:
    """지금 이 컴퓨터에서 소리를 들을 수 있나. (된다, 이유) 로 돌려준다."""
    ear = Ear(pid)
    try:
        ear.open()
    except SoundError as exc:
        return (False, str(exc))
    fmt = ear.fmt.describe() if ear.fmt else "?"
    ear.close()
    return (True, fmt)


# --------------------------------------------------------------------------
# 배우고 알아보기
# --------------------------------------------------------------------------
def learn(frames: list[tuple[float, float, list[float]]],
          floor: float = QUIET) -> tuple[list[float], float] | None:
    """들은 조각들에서 **그 소리의 결**을 뽑는다. (결, 그때 크기)

    가장 큰 조각 하나만 쓰지 않는다. 효과음은 울리는 동안 결이 조금씩 바뀌는데,
    한 순간만 붙잡으면 하필 그 순간과 다를 때 못 알아본다. 그래서 **가장 큰 데를
    가운데 두고 그 언저리 몇 조각을 평균** 낸다.

    조용한 조각은 아예 뺀다. 고요의 결이란 잡음의 결이고, 그걸 섞으면 배운 것이
    흐려진다.
    """
    loud = [f for f in frames if f[1] >= floor and f[2]]
    if not loud:
        return None
    peak = max(loud, key=lambda f: f[1])
    # 가장 큰 데서 크게 벗어나지 않는 조각만. 앞뒤 고요가 섞이면 흐려진다.
    near = [f for f in loud
            if abs(f[0] - peak[0]) <= 0.25 and f[1] >= peak[1] * 0.35]
    if not near:
        near = [peak]
    size = len(BANDS)
    total = [0.0] * size
    for _t, _lvl, shape in near:
        for i in range(size):
            total[i] += shape[i]
    length = math.sqrt(sum(v * v for v in total))
    if length <= 1e-9:
        return None
    return ([v / length for v in total], peak[1])


class SoundPrint:
    """배워 둔 소리 하나. 저장하고 불러올 수 있다."""

    __slots__ = ("shape", "level", "bands")

    def __init__(self, shape: list[float], level: float = 0.0,
                 bands: tuple[float, ...] = BANDS) -> None:
        self.shape = list(shape)
        self.level = level  # 배울 때 얼마나 컸는지 (참고용)
        self.bands = tuple(bands)

    @property
    def ready(self) -> bool:
        return len(self.shape) == len(BANDS) and any(self.shape)

    def to_list(self) -> list[float]:
        return [round(v, 5) for v in self.shape]

    def describe(self) -> str:
        if not self.ready:
            return "안 배움"
        top = sorted(range(len(self.shape)), key=lambda i: -self.shape[i])[:3]
        parts = [f"{BANDS[i]:.0f}Hz" for i in top if self.shape[i] > 0.05]
        return "가장 센 높이 " + " · ".join(parts or ["?"])


def events(frames, cues: dict, gap_s: float = 0.12) -> list[tuple[float, str, float]]:
    """조각들에서 **소리가 몇 번 났는지** 센다. [(때, 이름, 가장 닮은 정도)].

    cues 는 {이름: (결, near, floor, hits)}.

    match()는 "그 소리가 있었나"만 알려 준다. 클릭 소리는 한 판에 수십 번 나므로
    몇 번인지를 세야 한다. 같은 이름으로 닮은 조각이 gap_s 안에 이어지면 한 번으로
    친다 — 그래서 아주 촘촘한 연타는 몇 번이 한 번으로 묶일 수 있다. 그래도 **0번과
    0번이 아닌 것**은 확실히 가른다. 그게 "게임이 클릭을 받았나"의 답이다.

    소리를 둘 이상 배워 두었으면 조각마다 **가장 닮은 쪽**에 붙인다. 맞음 소리와
    빗나감 소리가 비슷하면 한 조각이 둘 다의 문턱을 넘을 수 있기 때문이다.
    """
    out: list[tuple[float, str, float]] = []
    run = None  # [시작, 마지막, 이름, 조각 수, 가장 닮은 정도]

    def close(got) -> None:
        if got is not None and got[3] >= max(1, cues[got[2]][3]):
            out.append((got[0], got[2], got[4]))

    for when, level, shape in frames:
        if not shape:
            continue
        best_name, best_score = None, 0.0
        for name, (print_shape, near, floor, _hits) in cues.items():
            if level < floor:
                continue
            score = likeness(shape, print_shape)
            if score >= near and score > best_score:
                best_name, best_score = name, score
        if best_name is None:
            continue
        if run is not None and run[2] == best_name and when - run[1] <= gap_s:
            run[1] = when
            run[3] += 1
            run[4] = max(run[4], best_score)
            continue
        close(run)
        run = [when, when, best_name, 1, best_score]
    close(run)
    return out


def match(frames, print_: SoundPrint, near: float, floor: float,
          hits: int) -> tuple[bool, float]:
    """그 조각들 안에 배운 소리가 들어 있나. (있다, 가장 닮았던 정도)

    한 조각만 닮아도 됐다고 하면 지나가는 소리에 속는다. 효과음은 여러 조각에
    걸쳐 울리므로 **닮은 조각이 몇 개는 나와야** 한다고 본다.
    """
    if not print_.ready:
        return (False, 0.0)
    best = 0.0
    good = 0
    for _t, level, shape in frames:
        if level < floor or not shape:
            continue
        score = likeness(shape, print_.shape)
        best = max(best, score)
        if score >= near:
            good += 1
    return (good >= max(1, hits), best)
