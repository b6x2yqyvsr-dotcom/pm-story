"""检测打开的来源够不够用 —— 「这个 APK 是完整版吗？」

为什么要做这个
--------------
游戏的资源分两种放法：

* **官方客户端 / 精简包**：APK 里几乎什么都没有，只有 ``text``（启动就要读的
  本地化），其余的资源包是**首次运行时下载**到 ``UnityCache`` 的。
  实测：官方 V2.41.0 和「加强版-精简」里都只有 **2 个** ``.assetbundle``。
* **加强版（完整版）**：APK 里塞了全部资源，实测 **156 个**，
  自带 ``pmseed`` 播种表，装完即玩。

这个区分对剧情编辑器是**致命**的：剧情数据全在 ``spdata`` 里，
**官方客户端和精简包里根本没有这个包**。你打开这种 APK 之后：

* ✓ 能改**对白文本**（``text`` 在 APK 里）
* ✗ 改不了**任务数据**（奖励、需要的物品）
* ✗ 改不了**对战训练师的出场队伍**
* ✗ 改不了**地图参数**（尺寸、主题、节点配额）
* ✗ 改不了**我方皮肤**的资产映射

所以打开来源之后**自动检一遍**，不完整就直接说清楚哪些用不了、怎么办。

「装不进去」是什么意思
----------------------
就算你把数据包（``口蘑数据包.zip``）一起追加进来，``spdata`` 也只是在
**数据包里**，不在 APK 里。这时候：

* 改动**导不进 APK**（APK 里没这个条目，替换无从谈起）
* 但可以走 **UnityCache 路线** —— 导出目录 ``adb push`` 到设备的
  ``files/UnityCache``，一样生效，而且不用重装 APK

检测会把这两种情况分开说。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .session import Session

#: 剧情功能 → 需要哪些包
FEATURE_NEEDS: list[tuple[str, tuple[str, ...], str]] = [
    ("剧情对白 / 名字", ("text",), "本地化文本"),
    ("剧情任务", ("text", "spdata"), "任务数据在 spdata"),
    ("对战训练师", ("text", "spdata"), "队伍和奖励在 spdata"),
    ("NPC 对白", ("text", "spdata"), "NPC 表在 spdata"),
    ("我方皮肤", ("text", "spdata"), "皮肤表在 spdata"),
    ("地图", ("text", "spdata"), "地图参数在 spdata"),
    ("皮肤形象图预览", ("appdata",), "形象映射在 BundleAssetAssignment"),
]

#: 判断「完整版」的门槛：这么多包以上才算自带全部资源
COMPLETE_MIN_BUNDLES = 50

#: 非完整版里常见的那几个包（官方客户端就带这些）
MINIMAL_BUNDLES = ("text",)


@dataclass
class SourceFile:
    """一个来源文件，以及它自带几个资源包。"""

    label: str
    kind: str          # 'APK' / '压缩包' / '目录'
    bundles: int = 0

    @property
    def complete(self) -> bool:
        return self.kind == "APK" and self.bundles >= COMPLETE_MIN_BUNDLES


@dataclass
class FeatureStatus:
    name: str
    need: tuple[str, ...]
    note: str
    #: 主 APK 的文件名（判断「能不能打进 APK」用）
    primary: str = ""
    #: 需要的包分别在哪儿：包名 -> 来源文件名 / '' (没有)
    where: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(self.where.get(n) for n in self.need)

    @property
    def missing(self) -> list[str]:
        return [n for n in self.need if not self.where.get(n)]

    @property
    def in_apk(self) -> bool:
        """需要的包是不是**都在主 APK 里**（决定能不能打进那个 APK）。

        注意是「主 APK」而不是「随便哪个 APK」：有人会同时打开精简包
        （要改的目标）和加强版（当数据源），两个都是 .apk。
        这时候数据虽然读得到，但**打不进精简包** —— 精简包里没那个条目。
        """
        return self.ok and all(self.where.get(n) == self.primary for n in self.need)

    def state(self) -> str:
        if not self.ok:
            return "缺"
        if self.in_apk:
            return "可以打进 APK"
        return "只能导出 UnityCache"


@dataclass
class Report:
    files: list[SourceFile] = field(default_factory=list)
    total_bundles: int = 0
    apk_bundles: int = 0
    self_contained: bool = False
    #: 主 APK：第一个 .apk 来源。改动要打进 APK 就是打进它
    primary: str = ""
    features: list[FeatureStatus] = field(default_factory=list)
    #: 所有来源里出现过的包名（用来判断某个包在不在）
    has: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return bool(self.primary) and self.apk_bundles >= COMPLETE_MIN_BUNDLES

    @property
    def blocked(self) -> list[FeatureStatus]:
        return [f for f in self.features if not f.ok]

    @property
    def apk_unpackable(self) -> list[FeatureStatus]:
        """能用、但**打不进 APK** 的（只能走 UnityCache）。"""
        return [f for f in self.features if f.ok and not f.in_apk]

    def headline(self) -> str:
        if not self.primary:
            return "没打开 APK（只有数据包 / 目录）"
        if self.complete:
            return f"✓ 完整版：{self.primary} 自带全部资源"
        return (f"⚠ 不是完整版：{self.primary} 里只有 {self.apk_bundles} 个资源包"
                f"（完整版有 {COMPLETE_MIN_BUNDLES}+ 个）")

    def advice(self) -> list[str]:
        out: list[str] = []
        if not self.complete:
            out.append("这个 APK 是官方/精简那种「资源靠下载」的包，"
                       "剧情数据表不在里面。")
            has_data = any(f.where.get("spdata") for f in self.features)
            if not has_data:
                out.append("把「口蘑数据包.zip」（或加强版 APK）一起拖进来"
                           "当追加源，剧情数据才能读到。")
            else:
                out.append("数据表是从数据包读到的 —— 能改、能导出 UnityCache，"
                           "但**打不进 APK**（APK 里没这个条目）。")
        if self.apk_unpackable:
            names = "、".join(f.name for f in self.apk_unpackable)
            out.append(f"这些只能走 UnityCache 路线：{names}")
        return out


def inspect(sess: Session) -> Report:
    """扫一遍当前打开的来源，判断够不够用。"""
    rep = Report()
    if sess.source is None:
        return rep

    src = sess.source
    names = set(src.bundle_names())
    rep.total_bundles = len(names)

    origin: dict[str, str] = {}
    apk_names: set[str] = set()
    for c in src.containers:
        label = str(getattr(c, "label", ""))
        low = label.lower()
        kind = ("APK" if low.endswith(".apk") else
                "目录" if getattr(c, "is_dir", False) else "压缩包")
        bset = {n.split("/")[-1][: -len(".assetbundle")]
                for n in c.names() if n.endswith(".assetbundle")}
        rep.files.append(SourceFile(label=Path(label).name, kind=kind, bundles=len(bset)))
        if kind == "APK":
            if not rep.primary:
                rep.primary = Path(label).name      # 第一个 APK 当主目标
            apk_names |= bset
        for b in bset:
            origin.setdefault(b, Path(label).name)

    rep.apk_bundles = sum(1 for b in apk_names
                          if origin.get(b) == rep.primary) if rep.primary else 0
    rep.has = origin
    rep.self_contained = bool(getattr(src, "is_self_contained", False))

    for name, need, note in FEATURE_NEEDS:
        st = FeatureStatus(name=name, need=need, note=note)
        st.primary = rep.primary
        for n in need:
            st.where[n] = origin.get(n, "")
        rep.features.append(st)
    return rep


def format_report(rep: Report, *, brief: bool = False) -> str:
    """给人看的文字版。``brief=True`` 只给一行结论（打开时记日志用）。"""
    if not rep.files:
        return "还没打开来源。"
    if brief:
        line = rep.headline()
        n = len(rep.blocked)
        if n:
            line += f" · {n} 项功能用不了"
        return line

    lines = ["", "  来源检测", "  " + "─" * 46]
    for f in rep.files[:5]:
        flag = "✓ 完整版" if f.complete else (f"{f.bundles} 个包")
        lines.append(f"    [{f.kind}] {f.label}   {flag}")
    if len(rep.files) > 5:
        lines.append(f"    …还有 {len(rep.files) - 5} 个来源")
    lines.append(f"    合计 {rep.total_bundles} 个资源包；主 APK 里 {rep.apk_bundles} 个")
    lines.append("")
    lines.append("  " + rep.headline())
    lines.append("")
    for st in rep.features:
        mark = {"可以打进 APK": "✓", "只能导出 UnityCache": "⚠", "缺": "✗"}[st.state()]
        lines.append(f"    {mark} {st.name:<14} {st.state()}")
        if not st.ok:
            lines.append(f"        缺：{'、'.join(st.missing)}（{st.note}）")
        elif not st.in_apk:
            srcs = "、".join(f"{k} ← {v}" for k, v in st.where.items() if v)
            lines.append(f"        {srcs}")
    adv = rep.advice()
    if adv:
        lines.append("")
        lines.append("  怎么办")
        for a in adv:
            lines.append("    · " + a)
    return "\n".join(lines)
