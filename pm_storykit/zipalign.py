"""纯 Python 的 ``zipalign``。

为什么不用官方那个
------------------
Android build-tools 里的 ``zipalign`` 是**各平台预编译的原生程序**。Google
没有为 Android/ARM 出这一份 —— 所以在 Termux（手机）上它压根跑不起来，
哪怕 Java 装好了、``apksigner.jar`` 能用，还是卡在这一步。

而它做的事其实很简单：**把 zip 里「不压缩」的条目挪到 4 字节对齐的偏移上**
（Android 会 ``mmap`` 这些条目，对齐了才能直接映射）。压缩过的条目不用管，
反正要解压。

做法：重写一遍 zip，给需要对齐的条目的**本地头**塞一段 extra field 当填充，
长度取 4~7 字节里能凑齐对齐的那个；中央目录里的偏移跟着改。
"""

from __future__ import annotations

import struct
import zipfile
from pathlib import Path

#: 本地文件头除 extra field 外的固定长度
_LOCAL_FIXED = 30
#: extra field 自己的头（id 2 字节 + size 2 字节）
_EXTRA_HDR = 4


def _local_extra_len(fh, header_offset: int) -> int:
    """从本地头里读 extra field 的长度（第 28 字节起，2 字节）。"""
    fh.seek(header_offset + 28)
    return struct.unpack("<H", fh.read(2))[0]


def _pad_len(data_off_without_extra: int, align: int) -> int:
    """本地头要加多少字节 extra，才能让数据落在 align 的倍数上。

    ★ 传进来的必须是**这条目在文件里的真实偏移**加上 header 长度，
      不能只算 header 长度 —— 上一条目的数据长度会把这个偏移推歪，
      同一段 header 在不同位置需要的填充量是不一样的（踩过这个坑：
      只按 header 长度算，结果 114 个 png 全都歪着）。
    """
    need = (-data_off_without_extra) % align
    if need == 0:
        return 0            # 本来就在边界上，一个字都别加（加 4 反而弄歪）
    # extra field 自己的头占 4 字节，不够就再凑一轮
    while need < _EXTRA_HDR:
        need += align
    return need


def align(apk: str | Path, out: str | Path, *, align: int = 4) -> tuple[bool, str]:
    """把 ``apk`` 重新对齐后写到 ``out``。返回 ``(成功, 说明)``。"""
    src, dst = Path(apk), Path(out)
    if src.resolve() == dst.resolve():
        return False, "输入输出不能是同一个文件"

    done = 0
    try:
        with zipfile.ZipFile(src) as zin, \
                open(src, "rb") as fin, \
                open(dst, "wb") as fout:
            entries = []
            for info in zin.infolist():
                name = info.filename.encode("utf-8")
                # ★ 关键：要的是**原始压缩字节**，不是解压后的。
                #   zin.read() 给的是解压结果，拿去配上 compress_type=DEFLATED
                #   和 compress_size 就彻底对不上 —— zip 直接坏掉（踩过）。
                if info.is_dir():
                    data = b""
                else:
                    fin.seek(info.header_offset + _LOCAL_FIXED
                             + len(name) + _local_extra_len(fin, info.header_offset))
                    data = fin.read(info.compress_size)

                # 只对齐「不压缩」的条目；压缩的反正要解压，Android 不 mmap 它
                stored = info.compress_type == zipfile.ZIP_STORED
                extra = b""
                if stored and data:
                    # 用「即将写入的位置」算，不是 header 长度
                    pad = _pad_len(fout.tell() + _LOCAL_FIXED + len(name), align)
                    if pad:
                        # 一段哑 extra field：id 0xFFFF（没人用），内容全 0
                        extra = (struct.pack("<HH", 0xFFFF, pad - _EXTRA_HDR)
                                 + b"\0" * (pad - _EXTRA_HDR))
                        done += 1

                hdr = struct.pack(
                    "<IHHHHHIIIHH",
                    0x04034B50,                 # 本地文件头签名
                    20,                         # 需要版本
                    info.flag_bits,
                    info.compress_type,
                    info.date_time[4], info.date_time[3] + (info.date_time[1] << 5) + (info.date_time[0] - 1980 << 9),
                    info.CRC,
                    info.compress_size, info.file_size,
                    len(name), len(extra),
                )
                offset = fout.tell()
                fout.write(hdr)
                fout.write(name)
                fout.write(extra)
                fout.write(data)
                entries.append((info, offset, name, extra))

            cd_start = fout.tell()
            for info, offset, name, extra in entries:
                fout.write(struct.pack(
                    "<IHHHHHHIIIHHHHHII",
                    0x02014B50,                 # 中央目录签名
                    20, 20,
                    info.flag_bits, info.compress_type,
                    info.date_time[4], info.date_time[3] + (info.date_time[1] << 5) + (info.date_time[0] - 1980 << 9),
                    info.CRC, info.compress_size, info.file_size,
                    len(name), len(extra), 0, 0, 0,
                    info.external_attr, offset,
                ))
                fout.write(name)
                fout.write(extra)
            cd_size = fout.tell() - cd_start
            n = len(entries)
            fout.write(struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, n, n,
                                   cd_size, cd_start, 0))
    except Exception as exc:  # noqa: BLE001
        dst.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}: {exc}"
    return True, f"已 {align} 字节对齐（处理 {done} 个未压缩条目）"


def verify(apk: str | Path, *, align: int = 4) -> tuple[bool, str]:
    """检查未压缩条目是不是都对齐了（用来兜底验证）。"""
    bad = []
    with zipfile.ZipFile(apk) as z:
        for info in z.infolist():
            if info.compress_type != zipfile.ZIP_STORED or info.is_dir():
                continue
            # 从本地头里读实际的 extra 长度（第 28 字节起是 2 字节）
            with open(apk, "rb") as fh:
                fh.seek(info.header_offset + 28)
                elen = struct.unpack("<H", fh.read(2))[0]
            data_off = info.header_offset + _LOCAL_FIXED + len(info.filename.encode()) + elen
            if data_off % align:
                bad.append(f"{info.filename}@{data_off}")
    if bad:
        return False, f"{len(bad)} 个条目没对齐：{bad[:3]}"
    return True, "全部对齐"
