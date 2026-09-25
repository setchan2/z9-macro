"""최소 PNG 읽기 / 쓰기.

Pillow 없이 아이콘 이미지를 주고받기 위한 것이다. 파이썬 3.14에 Pillow 휠이
없을 수도 있고, 이 프로그램은 표준 라이브러리만으로 돌아가는 것을 원칙으로 한다.
PNG는 결국 zlib으로 압축한 스캔라인 묶음이라 필요한 만큼만 직접 다루면 된다.

지원 범위 — 비트 깊이 8, 인터레이스 없음, 컬러 타입 0(회색) · 2(RGB) ·
3(팔레트) · 4(회색+알파) · 6(RGBA). 게임 아이콘을 캡처하거나 저장하는 용도로는
충분하다. 그 밖의 형식은 읽을 때 명확한 오류를 낸다.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PngError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# 쓰기
# --------------------------------------------------------------------------
def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_rgb(path: Path | str, width: int, height: int, rgb: bytes) -> None:
    """RGB 바이트(행 우선, 채널당 1바이트)를 PNG로 저장한다."""
    expected = width * height * 3
    if len(rgb) != expected:
        raise PngError(f"픽셀 데이터 크기가 맞지 않습니다: {len(rgb)} != {expected}")

    stride = width * 3
    # 필터는 전부 0(None)으로 둔다. 아이콘 크기에서는 압축률 차이가 의미 없고,
    # 코드가 단순해진다.
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += rgb[y * stride : (y + 1) * stride]

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    blob = (
        SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b"")
    )
    Path(path).write_bytes(blob)


# --------------------------------------------------------------------------
# 읽기
# --------------------------------------------------------------------------
_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(data: bytes, width: int, height: int, channels: int) -> bytearray:
    """PNG 스캔라인 필터를 풀어 원본 바이트로 되돌린다."""
    stride = width * channels
    out = bytearray(stride * height)
    pos = 0
    for y in range(height):
        if pos >= len(data):
            raise PngError("이미지 데이터가 중간에 끊겼습니다.")
        filter_type = data[pos]
        pos += 1
        line = data[pos : pos + stride]
        if len(line) < stride:
            raise PngError("이미지 데이터가 중간에 끊겼습니다.")
        pos += stride

        base = y * stride
        prior = base - stride
        if filter_type == 0:
            out[base : base + stride] = line
        elif filter_type == 1:  # Sub
            for i in range(stride):
                left = out[base + i - channels] if i >= channels else 0
                out[base + i] = (line[i] + left) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                up = out[prior + i] if y > 0 else 0
                out[base + i] = (line[i] + up) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = out[base + i - channels] if i >= channels else 0
                up = out[prior + i] if y > 0 else 0
                out[base + i] = (line[i] + ((left + up) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = out[base + i - channels] if i >= channels else 0
                up = out[prior + i] if y > 0 else 0
                upleft = (
                    out[prior + i - channels] if (y > 0 and i >= channels) else 0
                )
                out[base + i] = (line[i] + _paeth(left, up, upleft)) & 0xFF
        else:
            raise PngError(f"알 수 없는 스캔라인 필터: {filter_type}")
    return out


def read_rgb(path: Path | str) -> tuple[int, int, bytes]:
    """PNG를 읽어 (너비, 높이, RGB 바이트)로 돌려준다. 알파는 버린다."""
    blob = Path(path).read_bytes()
    if not blob.startswith(SIGNATURE):
        raise PngError("PNG 파일이 아닙니다.")

    pos = len(SIGNATURE)
    width = height = 0
    depth = color_type = 0
    palette = b""
    idat = bytearray()

    while pos + 8 <= len(blob):
        (length,) = struct.unpack(">I", blob[pos : pos + 4])
        tag = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + length]
        pos += 12 + length  # 길이(4) + 태그(4) + 데이터 + CRC(4)

        if tag == b"IHDR":
            width, height, depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if depth != 8:
                raise PngError(f"비트 깊이 {depth}는 지원하지 않습니다 (8만 가능).")
            if interlace:
                raise PngError("인터레이스 PNG는 지원하지 않습니다.")
            if color_type not in _CHANNELS:
                raise PngError(f"컬러 타입 {color_type}은 지원하지 않습니다.")
        elif tag == b"PLTE":
            palette = data
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break

    if not width or not height:
        raise PngError("IHDR을 찾지 못했습니다.")
    if not idat:
        raise PngError("이미지 데이터가 없습니다.")

    channels = _CHANNELS[color_type]
    raw = _unfilter(zlib.decompress(bytes(idat)), width, height, channels)

    # 어떤 형식이든 RGB로 통일한다. 비교할 때 채널 수가 달라지면 곤란하다.
    count = width * height
    rgb = bytearray(count * 3)
    if color_type == 2:
        return (width, height, bytes(raw))
    if color_type == 6:
        for i in range(count):
            rgb[i * 3 : i * 3 + 3] = raw[i * 4 : i * 4 + 3]
    elif color_type == 0:
        for i in range(count):
            value = raw[i]
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = value
    elif color_type == 4:
        for i in range(count):
            value = raw[i * 2]
            rgb[i * 3] = rgb[i * 3 + 1] = rgb[i * 3 + 2] = value
    elif color_type == 3:
        if not palette:
            raise PngError("팔레트 PNG인데 PLTE 청크가 없습니다.")
        for i in range(count):
            index = raw[i] * 3
            if index + 3 > len(palette):
                raise PngError("팔레트 범위를 벗어난 색인이 있습니다.")
            rgb[i * 3 : i * 3 + 3] = palette[index : index + 3]

    return (width, height, bytes(rgb))
