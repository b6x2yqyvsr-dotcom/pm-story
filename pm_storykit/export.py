"""四种导出方式。

改完剧情之后，产物可以按四种方式出来 —— 对应四种「怎么让游戏用上」：

======================  ============================================  ==================
方式                    产出                                          什么时候用
======================  ============================================  ==================
**UnityCache 目录**      ``UnityCache/Shared/<包>/<目录名>/__data``    推到手机上，**不用重装**
**CDN 目录**            ``AssetBundles/<group>/Android/*``            自建服务器分发
**.pmmod 模组包**       一个 zip（mod.json + 改动的包）               发给别人用
**重打包 APK**          签名好的新 APK                                想直接安装
======================  ============================================  ==================

前三种**不需要任何额外工具**，哪台机器都能跑。重打包 APK 要
**JDK + Android build-tools**（``apksigner`` / ``zipalign``），
手机上基本没有 —— 所以那一项在手机上会自己置灰并说明原因。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import sysenv
from .session import Session


@dataclass
class ExportKind:
    key: str
    label: str
    hint: str
    #: 需要什么才能用（空 = 什么都不需要）
    needs: str = ""
    #: 要不要用户填个名字（模组包用）
    ask_name: bool = False
    #: 要不要选源 APK（重打包用；默认用打开的那个）
    ask_apk: bool = False

    def available(self) -> tuple[bool, str]:
        if self.needs == "buildtools":
            missing = [n for n in ("apksigner", "zipalign", "java")
                       if not sysenv.find_build_tool(n)]
            if missing:
                return False, (
                    f"重打包 APK 需要 {'、'.join(missing)}（JDK + Android build-tools），"
                    "这台机器上没有。用前三种方式就行 —— "
                    "UnityCache 推上去一样生效，还不用重装。")
            return True, ""
        return True, ""


KINDS: list[ExportKind] = [
    ExportKind("cache", "UnityCache 目录",
               "推到手机即生效，不用重装 APK，也不用签名", ),
    ExportKind("modpack", ".pmmod 模组包",
               "一个文件，可以发给别人用", ask_name=True),
    ExportKind("cdn", "CDN 目录",
               "自建服务器分发用（会顺手更新 manifest 里的 version）"),
    ExportKind("apk", "重打包 APK",
               "直接能装的新 APK —— 需要 JDK + Android build-tools",
               needs="buildtools", ask_apk=True),
]

BY_KEY = {k.key: k for k in KINDS}


def catalog() -> list[dict]:
    """四种方式的清单 + 各自能不能用。"""
    out = []
    for k in KINDS:
        ok, why = k.available()
        out.append({"key": k.key, "label": k.label, "hint": k.hint,
                    "ok": ok, "why": why, "ask_name": k.ask_name,
                    "ask_apk": k.ask_apk})
    return out


def run(sess: Session, key: str, out_dir: str | Path, *,
        name: str = "", author: str = "", description: str = "",
        src_apk: str | Path | None = None, do_sign: bool = True,
        bump_versions: bool = True, prebuilt: bool = True,
        progress=None) -> dict:
    """跑一种导出。返回 ``{ok, kind, path, message, files}``。"""
    kind = BY_KEY.get(key)
    if kind is None:
        return {"ok": False, "message": f"不认识的导出方式 {key!r}"}
    ok, why = kind.available()
    if not ok:
        return {"ok": False, "message": why, "blocked": True}

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if key == "cache":
        if not sess.modified:
            return {"ok": False, "kind": key,
                    "message": "还没有改任何东西 —— 先去改点剧情，再回来导出。"}
        r = sess.output_cache(out / "UnityCache产物", allow_broken=True,
                              progress=progress)
        names = "、".join(list(sess.modified)[:4])
        return {"ok": True, "kind": key, "path": str(r["dir"]),
                "files": len(r["written"]),
                "message": f"✓ UnityCache 已导出：{len(r['written'])} 个包（{names}）\n"
                           f"  {r['dir']}\n"
                           f"  推到 /sdcard/Android/data/com.conspiracyrick.pocketmortys"
                           f"/files/UnityCache 即生效"}
    if key == "cdn":
        if not sess.modified:
            return {"ok": False, "kind": key, "message": "还没有改任何东西 —— 先去改点剧情。"}
        r = sess.output_cdn(out / "CDN产物")
        return {"ok": True, "kind": key, "path": str(r.get("dir", out)),
                "files": len(r.get("written") or []),
                "message": f"✓ CDN 目录已导出到 {r.get('dir', out)}"}
    if key == "modpack":
        if not sess.modified:
            return {"ok": False, "kind": key, "message": "还没有改任何东西 —— 先去改点剧情。"}
        p = sess.output_modpack(out / f"{name or 'story'}.pmmod",
                                name=name or "剧情模组", author=author,
                                description=description, prebuilt=prebuilt,
                                allow_broken=True)
        return {"ok": True, "kind": key, "path": str(p), "files": 1,
                "message": f"✓ 模组包已导出：{p}"}
    if key == "apk":
        src = src_apk
        if not src:
            # 用打开的那个 APK。注意取的是 **root**（完整路径）不是 label ——
            # label 是给界面显示的短名，拿去开文件会 FileNotFound
            for c in (sess.source.containers if sess.source else []):
                root = Path(getattr(c, "root", ""))
                if root.suffix.lower() == ".apk" and root.is_file():
                    src = str(root)
                    break
        if not src:
            return {"ok": False, "message": "没找到源 APK —— 重打包需要指定一个 APK"}
        dst = out / (Path(src).stem + "-剧情版.apk")
        r = sess.output_apk(src, dst, do_sign=do_sign,
                            bump_versions=bump_versions, allow_broken=True,
                            progress=progress)
        return {"ok": True, "kind": key, "path": str(dst), "files": 1,
                "message": f"✓ 重打包完成：{dst}（{dst.stat().st_size/1048576:.0f} MB）"
                           + ("\n  " + "；".join(r.get("steps", [])) if r.get("steps") else "")}
    return {"ok": False, "message": f"没实现 {key}"}
