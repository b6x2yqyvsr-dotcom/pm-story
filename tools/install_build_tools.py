#!/usr/bin/env python3
"""装「重打包 APK」要用的工具（JDK + Android build-tools）。

第四个导出方式（重打包 APK）跟另外三个不一样：它要外部工具。

    java        JDK，跑 apksigner
    apksigner   Android build-tools 里的，给 APK 签名（v2/v3）
    zipalign    把未压缩条目对齐到 4 字节

    python3 tools/install_build_tools.py            # 装
    python3 tools/install_build_tools.py --check    # 只看缺什么，不动手

各平台
------
============  ============================  ==========================
平台          JDK                            build-tools
============  ============================  ==========================
macOS         brew install openjdk          Google 的 cmdline-tools
Windows       winget install Temurin.21     Google 的 cmdline-tools
Debian/Ubuntu sudo apt install openjdk-17    Google 的 cmdline-tools
Termux(手机)  pkg install openjdk-17        **只取 apksigner.jar**
============  ============================  ==========================

手机上为什么特殊
----------------
Google 的 build-tools 里 ``zipalign`` 是**各平台预编译的原生程序**，
只出了 x86_64，没有 Android/ARM 版 —— 手机上根本装不上也跑不起来。
所以 Termux 这条路只装 JDK + 拿 ``apksigner.jar``，
对齐那步交给纯 Python 的实现（``pm_storykit/zipalign.py``）。
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
import os  # noqa: E402
import platform  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import urllib.request  # noqa: E402
import zipfile  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

#: Google 的命令行工具（三个平台一个版本号）
CMDLINE_VER = "11076708"
CMDLINE_URL = ("https://dl.google.com/android/repository/"
               f"commandlinetools-{{plat}}-{CMDLINE_VER}_latest.zip")
#: 装哪个版本的 build-tools
BUILD_TOOLS_VER = os.environ.get("PM_STORYKIT_BUILD_TOOLS", "34.0.0")
#: 装到哪
SDK_DIR = Path(os.environ.get("ANDROID_SDK_ROOT")
               or os.environ.get("ANDROID_HOME")
               or Path.home() / "android-sdk")


def _run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def detect() -> str:
    """返回 ``macos`` / ``windows`` / ``termux`` / ``linux``。"""
    if "com.termux" in os.environ.get("PREFIX", "") or Path("/data/data/com.termux").is_dir():
        return "termux"
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    return "linux"


def status() -> dict[str, str | None]:
    from pm_storykit import sysenv

    return {n: sysenv.find_build_tool(n)
            for n in ("java", "apksigner", "zipalign", "keytool")}


def _say(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- JDK

def install_jdk(where: str, *, dry: bool = False) -> bool:
    if shutil.which("java"):
        _say("    ✓ 已经有 java，跳过")
        return True
    cmds = {
        "macos": ["brew", "install", "openjdk"],
        "windows": ["winget", "install", "-e", "--id",
                    "EclipseAdoptium.Temurin.21.JDK",
                    "--accept-package-agreements", "--accept-source-agreements"],
        "termux": ["pkg", "install", "-y", "openjdk-17"],
        "linux": ["sudo", "apt-get", "install", "-y", "openjdk-17-jdk-headless"],
    }
    cmd = cmds.get(where)
    if not cmd:
        _say(f"    ! 不认识 {where}，请手动装 JDK 17+")
        return False
    if not shutil.which(cmd[0]):
        _say(f"    ! 没找到 {cmd[0]}，请手动装 JDK 17+")
        return False
    _say(f"    → {' '.join(cmd)}")
    if dry:
        return True
    r = _run(cmd)
    if r.returncode != 0:
        _say(f"    ✗ 失败：{(r.stderr or r.stdout).strip()[:200]}")
        return False
    _say("    ✓ JDK 装好了")
    if where == "macos":
        # brew 的 openjdk 是 keg-only，要手动加进 PATH
        for cand in Path("/opt/homebrew/opt").glob("openjdk*/bin"):
            if (cand / "java").exists():
                os.environ["PATH"] = f"{cand}:{os.environ['PATH']}"
                _say(f"    · 已把 {cand} 加进本次的 PATH")
                break
    return True


# ---------------------------------------------------------------- build-tools

def _plat_tag(where: str) -> str:
    return {"macos": "mac", "windows": "win", "linux": "linux",
            "termux": "linux"}.get(where, "linux")


def install_build_tools(where: str, *, dry: bool = False) -> bool:
    if where == "termux":
        return _install_jar_only(where, dry=dry)

    sdk = SDK_DIR
    sm = sdk / "cmdline-tools" / "latest" / "bin" / ("sdkmanager.bat" if where == "windows"
                                                     else "sdkmanager")
    if not sm.exists():
        url = CMDLINE_URL.format(plat=_plat_tag(where))
        _say(f"    → 下载命令行工具\n      {url}")
        if dry:
            return True
        try:
            sdk.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as tmp:
                zf = Path(tmp) / "clt.zip"
                urllib.request.urlretrieve(url, zf)
                with zipfile.ZipFile(zf) as z:
                    z.extractall(tmp)
                src = Path(tmp) / "cmdline-tools"
                dst = sdk / "cmdline-tools" / "latest"
                dst.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst, dirs_exist_ok=True)
                # sdkmanager 要求自己在 cmdline-tools/latest/ 这一层
                for junk in ("bin", "lib"):
                    pass
            _say(f"    ✓ 解到 {dst}")
        except Exception as exc:  # noqa: BLE001
            _say(f"    ✗ 下载/解压失败：{type(exc).__name__}: {exc}")
            return False
    if where == "windows":
        sm = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"
    if not sm.exists():
        _say(f"    ! 找不到 sdkmanager（{sm}）")
        return False

    env = dict(os.environ, ANDROID_SDK_ROOT=str(sdk), ANDROID_HOME=str(sdk))
    java = _find_java()
    if java:
        env["JAVA_HOME"] = str(Path(java).resolve().parent.parent)
    _say(f"    → sdkmanager --install build-tools;{BUILD_TOOLS_VER}")
    if dry:
        return True
    # 先自动接受许可，否则 sdkmanager 会停下来等输入
    _run([str(sm), "--sdk_root", str(sdk), "--licenses"], input="y\n" * 40, env=env)
    r = _run([str(sm), "--sdk_root", str(sdk), "--install",
              f"build-tools;{BUILD_TOOLS_VER}"], input="y\n" * 40, env=env)
    if r.returncode != 0:
        _say(f"    ✗ {(r.stderr or r.stdout).strip()[:200]}")
        return False
    _say(f"    ✓ build-tools {BUILD_TOOLS_VER} 装到 {sdk / 'build-tools' / BUILD_TOOLS_VER}")
    return True


def _find_java() -> str | None:
    j = shutil.which("java")
    if j:
        return j
    for base in (Path("/opt/homebrew/opt"), Path("/usr/lib/jvm")):
        for cand in sorted(base.glob("openjdk*/bin/java")) + sorted(base.glob("java-*/bin/java")):
            if cand.exists():
                return str(cand)
    return None


def _install_jar_only(where: str, *, dry: bool = False) -> bool:
    """手机（Termux）这条路：只拿 apksigner.jar，不要原生 zipalign。"""
    lib = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) / "share" / "pm-storykit"
    jar = lib / "apksigner.jar"
    if jar.exists():
        _say(f"    ✓ 已经有 {jar}")
        return True
    url = ("https://dl.google.com/android/repository/"
           f"build-tools_r{BUILD_TOOLS_VER.split('.')[0]}-linux.zip")
    _say(f"    → 取 apksigner.jar（只取这一个文件，不要原生 zipalign）\n      {url}")
    if dry:
        return True
    try:
        lib.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            zf = Path(tmp) / "bt.zip"
            urllib.request.urlretrieve(url, zf)
            with zipfile.ZipFile(zf) as z:
                hit = [n for n in z.namelist() if n.endswith("lib/apksigner.jar")]
                if not hit:
                    hit = [n for n in z.namelist()
                           if n.endswith("apksigner.jar")]
                if not hit:
                    _say("    ✗ 压缩包里没找到 apksigner.jar")
                    return False
                jar.write_bytes(z.read(hit[0]))
        _say(f"    ✓ 拿到 {jar}（对齐用纯 Python 那份，不需要原生 zipalign）")
        return True
    except Exception as exc:  # noqa: BLE001
        _say(f"    ✗ {type(exc).__name__}: {exc}")
        return False


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="装「重打包 APK」要用的工具")
    ap.add_argument("--check", action="store_true", help="只看缺什么，不安装")
    ap.add_argument("--dry-run", action="store_true", help="只打印要做什么")
    ap.add_argument("--only", choices=["jdk", "tools"], help="只装其中一项")
    a = ap.parse_args()

    where = detect()
    _say("")
    _say("  口蘑剧情工坊 · 装 Android 打包工具")
    _say("  " + "─" * 46)
    _say(f"  平台：{where}")
    _say(f"  SDK： {SDK_DIR}")

    st = status()
    _say("")
    _say("  当前状态")
    for n in ("java", "apksigner", "zipalign", "keytool"):
        v = st[n]
        note = ""
        if n == "zipalign" and not v and where == "termux":
            note = "  ← 手机上正常，自动用纯 Python 对齐"
        _say(f"    {'✓' if v else '✗'} {n:<10}{v or '（没有）'}{note}")

    if a.check:
        need = [n for n, v in st.items() if not v and not (n == "zipalign" and where == "termux")]
        _say("")
        _say(f"  还缺 {len(need)} 项：{'、'.join(need) or '无'}" if need else "  ✓ 全都齐了")
        _say("")
        return 1 if need else 0

    _say("")
    _say("  开始安装")
    ok = True
    if not a.only or a.only == "jdk":
        _say("  [1] JDK")
        ok &= install_jdk(where, dry=a.dry_run)
    if not a.only or a.only == "tools":
        _say("  [2] Android build-tools")
        ok &= install_build_tools(where, dry=a.dry_run)

    if not a.dry_run:
        st = status()
        _say("")
        _say("  装完的状态")
        for n in ("java", "apksigner", "zipalign", "keytool"):
            v = st[n]
            mark = "✓" if v else ("·" if n == "zipalign" and where == "termux" else "✗")
            _say(f"    {mark} {n:<10}{v or '（没有）'}")
        _say("")
        if st["apksigner"] or (where == "termux" and st["java"]):
            _say("  重打包 APK 可以用了。重启一下工具，第四个导出方式就亮了。")
        else:
            _say("  还没齐 —— 手动装也行，见 README「四种导出方式」那节。")
    _say("")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
