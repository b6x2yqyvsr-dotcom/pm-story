#!/usr/bin/env python3
"""口蘑剧情编辑器 · 命令行

    python3 tools/cli.py list   <来源>                 列出剧情清单
    python3 tools/cli.py show   <来源> --quest QuestX  看一个任务的全文
    python3 tools/cli.py check  <来源>                 剧情体检
    python3 tools/cli.py set    <来源> --quest QuestX --field name=新名字
    python3 tools/cli.py team   <来源> --trainer TrainerX --morties "MortyA:5,MortyB:5"
    python3 tools/cli.py export <来源> -o 输出目录      导出改好的包
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
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from storykit import session as session_mod  # noqa: E402
from storykit import story as ST  # noqa: E402

SEC = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
       "avatar": "PlayerAvatar", "world": "Dimensions"}
TBL = {"quest": "QuestInfo", "trainer": "TrainerInfo", "npc": "NPCInfo",
       "avatar": "PlayerAvatarInfo", "world": "WorldInfo"}


def _open(paths, lang="ZH_CN"):
    s = session_mod.Session()
    s.open(*paths)
    return s


def cmd_list(a) -> int:
    s = _open(a.paths, a.lang)
    ov = ST.overview(s, a.lang)
    print(f"\n  剧情清单（{ST.LANG_LABEL.get(a.lang, a.lang)}）")
    print("  " + "  ".join(f"{k} {v}" for k, v in ov.counts().items()))
    which = a.what
    rows = {"quest": ov.quests, "trainer": ov.trainers, "npc": ov.npcs,
            "avatar": ov.avatars, "world": ov.worlds}[which]
    print()
    for r in rows:
        extra = ""
        if which == "trainer":
            extra = f"  队伍 {r['team_n']} 只"
        elif which == "world":
            extra = f"  {r.get('w')}×{r.get('d')}"
        print(f"  {r['id']:<30} {r.get('name',''):<20}{extra}")
    print(f"\n  共 {len(rows)} 条")
    return 0


def cmd_show(a) -> int:
    s = _open(a.paths, a.lang)
    key = SEC[a.what]
    sec = ST.SECTION_BY_KEY[key]
    tx = ST.read_texts(s, a.lang).get(key) or {}
    row = tx.get(a.id)
    data = ST.read_table(s, TBL[a.what]).get(a.id) or {}
    if row is None and not data:
        print(f"  没找到 {a.id}")
        return 1
    print(f"\n  === {a.id} ===")
    for f, zh in sec.fields:
        v = (row or {}).get(f, "")
        if v:
            print(f"  {zh:<12} {v}")
    if a.what == "trainer":
        team = ST.parse_team(data.get("morties") or "")
        print(f"  出场队伍 ({len(team)})")
        for i, m in enumerate(team, 1):
            print(f"      {i}. {m['id']}  等级 {m['level']}")
    others = {k: v for k, v in data.items()
              if k not in ("id", "content", "morties") and v not in ("", None)}
    if others:
        print("  数据：")
        for k, v in others.items():
            print(f"      {ST.field_label(TBL[a.what], k):<14} {v}")
    return 0


def cmd_check(a) -> int:
    s = _open(a.paths, a.lang)
    issues = ST.validate(s, a.lang)
    print()
    if not issues:
        print("  ✓ 剧情体检通过")
        return 0
    print(f"  ✗ {len(issues)} 个问题：")
    for i in issues:
        print("    ⚠ " + i)
    return 1


def cmd_set(a) -> int:
    s = _open(a.paths, a.lang)
    vals = {}
    for spec in a.field or []:
        k, _, v = spec.partition("=")
        vals[k.strip()] = v
    if not vals:
        print("  至少给一个 --field 键=值")
        return 2
    langs = ST.LANGS if a.all_langs else [a.lang]
    done = ST.set_texts(s, SEC[a.what], a.id, vals, langs)
    print(f"\n  ✓ {a.id}: {'、'.join(done) if done else '没有变化'}")
    for k, v in vals.items():
        print(f"      {k} = {v}")
    if a.out:
        r = s.output_cache(a.out, allow_broken=True)
        print(f"  ✓ 导出到 {r['dir']}（{len(r['written'])} 个包）")
    return 0


def cmd_team(a) -> int:
    s = _open(a.paths, a.lang)
    team = ST.parse_team(a.morties)
    if not team:
        print("  --morties 格式：MortyA:5,MortyB:5")
        return 2
    msg = ST.set_table_row(s, "TrainerInfo", a.trainer, {"morties": ST.format_team(team)})
    print(f"\n  ✓ {msg}")
    for i, m in enumerate(team, 1):
        print(f"      {i}. {m['id']}  等级 {m['level']}")
    if a.out:
        r = s.output_cache(a.out, allow_broken=True)
        print(f"  ✓ 导出到 {r['dir']}（{len(r['written'])} 个包）")
    return 0


def cmd_diagnose(a) -> int:
    """检测来源够不够用。"""
    from storykit import diagnose as DG

    s = _open(a.paths, a.lang)
    rep = DG.inspect(s)
    print(DG.format_report(rep))
    return 0 if rep.complete else 1


def cmd_export(a) -> int:
    s = _open(a.paths, a.lang)
    r = s.output_cache(a.out, allow_broken=True)
    print(f"\n  ✓ 导出到 {r['dir']}（{len(r['written'])} 个包）")
    print("      adb push 到设备的 files/UnityCache 即生效，不用重装 APK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="口蘑剧情编辑器")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("paths", nargs="+", help="APK / 数据包 zip")
        p.add_argument("--lang", default="ZH_CN", help="语言（默认 ZH_CN）")

    p = sub.add_parser("list", help="列出剧情清单")
    common(p)
    p.add_argument("--what", default="quest",
                   choices=["quest", "trainer", "npc", "avatar", "world"])
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("show", help="看一条的全文")
    common(p)
    p.add_argument("--what", default="quest",
                   choices=["quest", "trainer", "npc", "avatar", "world"])
    p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("check", help="剧情体检")
    common(p)
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("set", help="改剧情文本")
    common(p)
    p.add_argument("--what", default="quest",
                   choices=["quest", "trainer", "npc", "avatar", "world"])
    p.add_argument("--id", required=True)
    p.add_argument("--field", action="append", metavar="键=值")
    p.add_argument("--all-langs", action="store_true", help="11 种语言一起写")
    p.add_argument("-o", "--out", help="改完顺便导出到这个目录")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("team", help="改训练师的出场队伍")
    common(p)
    p.add_argument("--trainer", required=True)
    p.add_argument("--morties", required=True, help='例如 "MortyA:5,MortyB:5"')
    p.add_argument("-o", "--out")
    p.set_defaults(fn=cmd_team)

    p = sub.add_parser("diagnose", help="检测 APK 是不是完整版（不完整就列出哪些用不了）")
    common(p)
    p.set_defaults(fn=cmd_diagnose)

    p = sub.add_parser("export", help="导出改好的包")
    common(p)
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_export)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
