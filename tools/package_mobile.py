#!/usr/bin/env python3
"""打手机端的包（Android / iOS）。

手机端**不是原生 App** —— 这个工具的核心是 Python + UnityPy，要 lz4 /
brotli / texture2ddecoder 这些原生扩展，它们没有 Android / iOS 的轮子。
所以手机端走**网页版**：

* **Android**：后端装在 Termux 里，浏览器打开（可添加到主屏）
* **iOS**：后端跑在电脑上，iPhone 用 Safari 连过来（可添加到主屏）

    python3 tools/package_mobile.py -o dist
"""

from __future__ import annotations


def _force_utf8() -> None:
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


_force_utf8()

import argparse  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COMMON = ["pm_storykit", "web", "tools", "app", "docs",
          "requirements-web.txt", "requirements.txt", "README.md",
          "setup.sh", "setup.bat"]

ANDROID_README = """口蘑剧情工坊 · Android（Termux）
==================================

手机端跑的是**网页版**：后端 Python 装在 Termux 里，界面用手机浏览器打开。

为什么不做原生 APK
------------------
这个工具的核心是 Python + UnityPy，要 lz4 / brotli / texture2ddecoder 这些
**原生扩展**，它们没有 Android 的预编译轮子。硬做出来的 APK 装不上或者
一打开就崩，不如老实走网页版 —— 功能完全一样，还能「添加到主屏幕」当 App。

怎么装（三步）
--------------
1. 装 Termux
   从 F-Droid 装：https://f-droid.org/packages/com.termux/
   （别用 Google Play 那个，版本太老装不上新包）

2. 把本压缩包弄进 Termux

       termux-setup-storage
       cd ~ && cp /sdcard/Download/pm-storykit-Android.zip .
       pkg install -y unzip && unzip -q pm-storykit-Android.zip
       cd pm-storykit

3. 一键装 + 启动

       bash android/termux-install.sh
       bash android/termux-run.sh

   它会打印地址，手机浏览器打开 http://127.0.0.1:8765 就是完整界面。

装成 App（推荐）
----------------
Chrome 里点右上角菜单 →「添加到主屏幕」。之后从桌面图标进去是全屏的、
没有地址栏，跟 App 一样。

怎么用（三步）
--------------
1. **打开游戏文件** —— 把 APK 或数据包 zip 拖进来（或者点选）
   官方客户端 / 精简版里只有 text，打开后会自动告诉你哪些改不了
2. **点一个分类** —— 新手教程 / 剧情任务 / 对战训练师 / NPC 对白 / 我方皮肤 / 地图
3. **改完点应用，然后导出** —— 四种导出方式随你挑

四种导出
--------
| 方式 | 什么时候用 | 手机上行吗 |
|---|---|---|
| UnityCache 目录 | 推到手机即生效 | ✓ 导完下载 zip |
| .pmmod 模组包 | 发给别人 | ✓ |
| CDN 目录 | 自建服务器 | ✓ |
| 重打包 APK | 直接安装 | ✗ 要 JDK，一般没有（会自动置灰） |

**手机上推荐 UnityCache**：导出后下载 zip，解压推到
`/sdcard/Android/data/com.conspiracyrick.pocketmortys/files/UnityCache`
即生效，不用重装 APK，也不用签名。
"""

IOS_README = """口蘑剧情工坊 · iOS / iPadOS
=============================

iOS 上跑不了这个后端（原生扩展没有轮子，App Store 也不让装 Python 运行时）。
正确用法：**电脑上跑服务，iPhone 用 Safari 连过去**。

算力在电脑上，手机只负责显示和操作 —— 手机上拖文件、改剧情、导出，
实际都是电脑在算，所以手机不会卡。

三步
----
1. 在电脑上起服务

   macOS：双击 启动服务.command
   Windows：双击 启动服务.bat
   或者命令行：

       python3 web/server.py --port 8765

   服务默认监听所有网卡，手机能连。

2. 查电脑的局域网 IP

   macOS：  ipconfig getifaddr en0
   Windows：ipconfig    （看「IPv4 地址」）

3. iPhone 的 Safari 里打开

       http://<电脑的IP>:8765

装成 App（推荐）
----------------
Safari 里点底部「分享」→「添加到主屏幕」→ 添加。
桌面会出现图标，点开是全屏的，没有地址栏。

安全提醒
--------
这一步是把服务开给**整个局域网**。只在自己家的 Wi-Fi 上这么用，
公共网络（咖啡厅、酒店）别开。
"""

SERVER_COMMAND = """#!/bin/bash
# 口蘑剧情工坊 · 在 macOS 上起服务（给 iPhone / iPad 连）
cd "$(dirname "$0")" || exit 1
PORT="${PM_STORYKIT_PORT:-8765}"

# 用自己的 venv：macOS 的系统 Python 默认拒绝 pip 安装（PEP 668）
if [ ! -x ".venv/bin/python" ]; then
  echo
  echo "  第一次要先建环境并装依赖（一两分钟）…"
  echo
  python3 -m venv .venv || { echo "  建虚拟环境失败，先装 Python 3.10+"; exit 1; }
  .venv/bin/python -m pip install -q --upgrade pip
  .venv/bin/python -m pip install -q -r requirements-web.txt || {
    echo "  装依赖失败。手动： .venv/bin/python -m pip install -r requirements-web.txt"
    exit 1; }
fi
PY=.venv/bin/python
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
echo
echo "  口蘑剧情工坊 · 服务已启动"
echo "  ────────────────────────────────────────"
echo "  这台电脑：        http://127.0.0.1:$PORT"
[ -n "${IP:-}" ] && echo "  iPhone 用 Safari 打开：http://$IP:$PORT"
echo
echo "  然后 Safari 底部「分享」→「添加到主屏幕」就装成 App 了"
echo "  按 Ctrl+C 停止"
echo
exec "$PY" web/server.py --port "$PORT"
"""

SERVER_BAT = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PORT=8765
if not "%PM_STORYKIT_PORT%"=="" set PORT=%PM_STORYKIT_PORT%
where python >nul 2>&1 || (echo   没找到 python，先装 Python 3.10+ & pause & exit /b 1)
if not exist ".venv\Scripts\python.exe" (
  echo   第一次要先建环境并装依赖（一两分钟）…
  python -m venv .venv || (echo   建虚拟环境失败 & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -q -r requirements-web.txt || (
    echo   装依赖失败 & pause & exit /b 1)
)
echo.
echo   口蘑剧情工坊 · 服务已启动
echo   ----------------------------------------
echo   这台电脑：http://127.0.0.1:%PORT%
echo.
echo   查本机 IP（下面找 IPv4 地址）：
ipconfig | findstr /i "IPv4"
echo.
echo   在 iPhone 的 Safari 里打开  http://^<上面的IP^>:%PORT%
echo   然后「分享」-^>「添加到主屏幕」就装成 App 了
echo.
".venv\Scripts\python.exe" web/server.py --port %PORT%
pause
"""


def _copy(dst: Path, extras: dict[str, str] | None = None, *, mobile: bool) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for rel in COMMON:
        src = ROOT / rel
        if not src.exists():
            continue
        tgt = dst / rel
        if src.is_dir():
            shutil.copytree(src, tgt, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
    if mobile:
        (dst / "android").mkdir(exist_ok=True)
        for f in ("termux-install.sh", "termux-run.sh"):
            s = ROOT / "android" / f
            if s.exists():
                shutil.copy2(s, dst / "android" / f)
    for name, text in (extras or {}).items():
        p = dst / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if name.endswith((".sh", ".command")):
            p.chmod(0o755)


def _zip(src: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(src.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(src.parent).as_posix()
            zi = zipfile.ZipInfo(rel, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = (0o755 if rel.endswith((".sh", ".command", ".bat"))
                                else 0o644) << 16
            zi.flag_bits |= 0x800      # 文件名是 UTF-8，不设的话解压出来中文乱码
            z.writestr(zi, p.read_bytes())
    return out


def build(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        a = t / "pm-storykit"
        _copy(a, {"安卓安装说明.md": ANDROID_README}, mobile=True)
        made.append(_zip(a, out_dir / "pm-storykit-Android.zip"))

        i = t / "pm-storykit-ios"
        _copy(i, {"iPhone安装说明.md": IOS_README,
                  "启动服务.command": SERVER_COMMAND,
                  "启动服务.bat": SERVER_BAT}, mobile=False)
        made.append(_zip(i, out_dir / "pm-storykit-iOS.zip"))
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description="打手机端的包")
    ap.add_argument("-o", "--out", default="dist")
    a = ap.parse_args()
    for p in build(Path(a.out)):
        print(f"  {p}  ({p.stat().st_size / 1048576:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
