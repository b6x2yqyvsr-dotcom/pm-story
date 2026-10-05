#!/usr/bin/env python3
"""口蘑剧情工坊 · 图形界面（独立版）

只做一件事：改 Pocket Mortys 的单人剧情。
—— 任务对白、对战训练师（含出场队伍）、我方皮肤、地图。

窗口里那句「剧情」按钮打开的就是编辑器本体，其余是打开来源和导出。
"""

from __future__ import annotations


def _force_utf8() -> None:
    """Windows 控制台默认 cp1252/cp936，print 中文会 UnicodeEncodeError。"""
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


_force_utf8()

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from imgui_bundle import hello_imgui, immapp, imgui, immvision, portable_file_dialogs as pfd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm_storykit import session as session_mod  # noqa: E402
from pm_storykit import story as story_mod  # noqa: E402
from pm_storykit import sysenv  # noqa: E402

APP_NAME = "口蘑剧情工坊"

# ---------------------------------------------------------------- 视觉

YELLOW = (1.00, 0.83, 0.15, 1.0)
GREEN = (0.36, 0.86, 0.50, 1.0)
DIM = (0.60, 0.60, 0.66, 1.0)
WARN = (1.00, 0.72, 0.30, 1.0)
OK = (0.44, 0.86, 0.52, 1.0)

FONTS: dict[str, object] = {"ui": None, "mono": None}


def _text_colored(col, text: str) -> None:
    imgui.text_colored(col, text)


def _mono(text: str) -> None:
    f = FONTS.get("mono")
    if f is not None:
        imgui.push_font(f, 0.0)
    _text_colored(DIM, text)
    if f is not None:
        imgui.pop_font()


def _chip(text: str, col=None, *, filled: bool = False) -> None:
    col = col or DIM
    if filled:
        imgui.push_style_color(imgui.Col_.button, (col[0], col[1], col[2], 0.85))
        imgui.push_style_color(imgui.Col_.text, (0.06, 0.06, 0.08, 1.0))
        imgui.button(text)
        imgui.pop_style_color(2)
    else:
        imgui.push_style_color(imgui.Col_.button, (0.16, 0.16, 0.19, 1.0))
        imgui.push_style_color(imgui.Col_.text, col)
        imgui.button(text)
        imgui.pop_style_color(2)


def _tip(text: str) -> None:
    if imgui.is_item_hovered():
        imgui.set_tooltip(text)


def _center_next_window(size: imgui.ImVec2) -> None:
    imgui.set_next_window_size(size, imgui.Cond_.first_use_ever)
    vp = imgui.get_main_viewport()
    imgui.set_next_window_pos(
        imgui.ImVec2(vp.work_pos.x + (vp.work_size.x - size.x) * 0.5,
                     vp.work_pos.y + (vp.work_size.y - size.y) * 0.5),
        imgui.Cond_.first_use_ever,
    )


FONT_CANDIDATES = sysenv.cjk_font_candidates()


def load_fonts() -> None:
    for cand in FONT_CANDIDATES:
        if Path(cand).is_file():
            try:
                FONTS["ui"] = hello_imgui.load_font(cand, 16.5)
                break
            except Exception:  # noqa: BLE001
                continue
    mono = sysenv.find_mono_font()
    if mono:
        try:
            FONTS["mono"] = hello_imgui.load_font(mono, 12.5)
        except Exception:  # noqa: BLE001
            FONTS["mono"] = None



def _step(n: int, title: str, *, done: bool = False, active: bool = True) -> None:
    col = GREEN if done else (YELLOW if active else DIM)
    imgui.text_colored(col, "①②③④⑤"[n - 1] if n <= 5 else str(n))
    imgui.same_line()
    _text_colored(col, title)


def _section(title: str, latin: str = "", *, color=None) -> None:
    imgui.spacing()
    _text_colored(color or YELLOW, "▸ " + title)
    if latin:
        imgui.same_line()
        _mono("  " + latin.upper())
    imgui.spacing()


def _bar(fraction: float, width: float = 120.0, height: float = 6.0,
         color=None) -> None:
    col = color or YELLOW
    pos = imgui.get_cursor_screen_pos()
    dl = imgui.get_window_draw_list()
    dl.add_rect_filled(imgui.ImVec2(pos.x, pos.y + 4),
                       imgui.ImVec2(pos.x + width, pos.y + 4 + height),
                       imgui.get_color_u32(imgui.ImVec4(0.18, 0.18, 0.21, 1.0)), 3.0)
    w = max(2.0, width * max(0.0, min(1.0, fraction)))
    dl.add_rect_filled(imgui.ImVec2(pos.x, pos.y + 4),
                       imgui.ImVec2(pos.x + w, pos.y + 4 + height),
                       imgui.get_color_u32(imgui.ImVec4(*col)), 3.0)
    imgui.dummy(imgui.ImVec2(width, height + 8))


F_SOURCES = ["游戏文件", "*.apk *.zip *.tar *.gz", "所有文件", "*"]


class StoryApp:
    def __init__(self, paths: list[str] | None = None) -> None:
        self.sess = session_mod.Session()
        self.logs: list[str] = []
        self.busy_msg = ""
        self._lock = threading.Lock()
        self._text_cache: dict = {}
        self.show_story = False
        self.diag = None
        self.show_diag = False
        self._st_reset()
        self.autotest = int(os.environ.get("PM_STORYKIT_AUTOTEST", "0") or "0")
        self._frame = 0
        for p in (paths or []):
            if Path(p).exists():
                self._open_now([p])

    # ------------------------------------------------------------ 基础

    def log(self, msg: str) -> None:
        with self._lock:
            self.logs.append(msg)
            if len(self.logs) > 400:
                del self.logs[:100]

    def busy(self) -> bool:
        return bool(self.busy_msg)

    def start(self, label: str, fn) -> None:
        if self.busy():
            return
        self.busy_msg = label

        def _run():
            try:
                r = fn()
                if r:
                    self.log(str(r))
            except Exception as exc:  # noqa: BLE001
                self.log(f"✗ {label}失败：{exc}")
            finally:
                self.busy_msg = ""

        threading.Thread(target=_run, daemon=True).start()

    def pick_open(self, title: str, filters: list[str], multi: bool = True) -> list[str]:
        # 枚举名是 pfd.opt.multiselect，不是 multiselect_files（后者不存在）
        opt = pfd.opt.multiselect if multi else pfd.opt.none
        dlg = pfd.open_file(title, str(Path.home()), filters, opt)
        return list(dlg.result() or [])

    def _open_now(self, paths: list[str]) -> None:
        try:
            if self.sess.source is None:
                self.sess.open(*paths)
            else:
                self.sess.add_source(*paths)
            self.show_story = True
            self._st_reset()
            self.log(f"✓ 打开 {len(paths)} 个来源，"
                     f"{len(self.sess.source.bundle_names())} 个资源包")
            # 自动检测：不是完整版就直接说清楚哪些用不了
            from pm_storykit import diagnose as DG

            self.diag = DG.inspect(self.sess)
            for line in DG.format_report(self.diag, brief=False).split("\n"):
                if line.strip():
                    self.log(line)
        except Exception as exc:  # noqa: BLE001
            self.log(f"✗ 打开失败：{exc}")

    # ------------------------------------------------------------ 绘制

    def draw(self) -> None:
        self._draw_toolbar()
        avail = imgui.get_content_region_avail()
        imgui.begin_child("##left", imgui.ImVec2(max(220.0, avail.x * 0.26), 0), True)
        _text_colored(YELLOW, "来源")
        if self.sess.source is None:
            _text_colored(DIM, "还没打开。\n点上面「打开源」，\n或者把 APK / 数据包拖进来。")
        else:
            for c in self.sess.source.containers:
                imgui.text(_ellipsis(Path(c.label).name, 26))
            imgui.separator()
            _text_colored(DIM, f"{len(self.sess.source.bundle_names())} 个资源包")
            if self.sess.modified:
                _text_colored(GREEN, f"已改 {len(self.sess.modified)} 个包")
                for n in self.sess.modified:
                    imgui.text("  · " + n)
        imgui.end_child()

        imgui.same_line()
        imgui.begin_child("##right", imgui.ImVec2(0, 0), False)
        _text_colored(YELLOW, "日志")
        imgui.begin_child("##logs", imgui.ImVec2(0, -8), True)
        with self._lock:
            for line in self.logs[-200:]:
                col = (GREEN if line.startswith("✓") else
                       (WARN if ("✗" in line or "⚠" in line) else DIM))
                _text_colored(col, line)
        imgui.end_child()
        imgui.end_child()

        if self.busy():
            _text_colored(WARN, f"  {self.busy_msg}")

        if self.show_story:
            self._draw_story()
        if self.show_diag:
            self._draw_diag()

        if self.autotest:
            self._frame += 1
            self._autotest()
            if self._frame >= self.autotest:
                hello_imgui.get_runner_params().app_shall_exit = True

    def _draw_toolbar(self) -> None:
        if imgui.button("打开源…"):
            got = self.pick_open("游戏文件（APK / 数据包 zip，可多选）", F_SOURCES)
            if got:
                self._open_now(got)
        _tip("打开 APK / 数据包 zip。\n可以一次选多个，也可以分几次「追加源」")
        imgui.same_line()
        imgui.begin_disabled(self.sess.source is None or self.busy())
        if imgui.button("追加源…"):
            got = self.pick_open("追加到当前源", F_SOURCES)
            if got:
                self._open_now(got)
        imgui.same_line()
        if imgui.button("剧情"):
            self.show_story = True
            self._st_reset()
        _tip("单人剧情编辑器：任务对白、对战训练师、我方皮肤、地图")
        imgui.same_line()
        if imgui.button("检测"):
            from pm_storykit import diagnose as DG

            self.diag = DG.inspect(self.sess)
            self.show_diag = True
        _tip("看看这个 APK 是不是完整版；\n不是的话，哪些改动装不进 APK")
        imgui.same_line()
        if imgui.button("导出…"):
            d = pfd.select_folder("导出到哪个目录")
            if d.result():
                self.start("导出中…", lambda: self._export(d.result()))
        _tip("输出 UnityCache 目录，adb push 到设备即生效，不用重装 APK")
        imgui.end_disabled()
        imgui.same_line()
        if self.sess.source is not None:
            _text_colored(DIM, "  " + (self.sess.source.summary()
                                       if hasattr(self.sess.source, "summary") else ""))
        imgui.separator()

    def _draw_diag(self) -> None:
        """来源检测报告。"""
        from pm_storykit import diagnose as DG

        _center_next_window(imgui.ImVec2(700, 620))
        opened, self.show_diag = imgui.begin("来源检测", self.show_diag)
        if not opened:
            imgui.end()
            return
        rep = self.diag or (DG.inspect(self.sess) if self.sess.source else None)
        if rep is None or not rep.files:
            _text_colored(WARN, "还没打开来源。")
            imgui.end()
            return

        _text_colored(YELLOW, "计划 04")
        imgui.same_line()
        _mono("· SOURCE CHECK")
        imgui.text("这个 APK 是完整版吗")
        _text_colored(DIM, "游戏有两种放法：官方/精简包的资源靠首次运行下载，"
                           "加强版（完整版）把资源全塞进 APK。")
        imgui.separator()

        for f in rep.files[:6]:
            if f.complete:
                _text_colored(GREEN, f"  ✓ [{f.kind}] {f.label}   自带 {f.bundles} 个包")
            else:
                _text_colored(DIM, f"    [{f.kind}] {f.label}   {f.bundles} 个包")
        _text_colored(DIM, f"    合计 {rep.total_bundles} 个包；主 APK 里 {rep.apk_bundles} 个")
        imgui.separator()

        _text_colored(GREEN if rep.complete else WARN, "  " + rep.headline())
        imgui.spacing()
        for st in rep.features:
            if not st.ok:
                col, mark = (1.0, 0.45, 0.45, 1.0), "✗"
            elif st.in_apk:
                col, mark = GREEN, "✓"
            else:
                col, mark = WARN, "⚠"
            _text_colored(col, f"  {mark} {st.name}")
            imgui.same_line(240)
            _text_colored(col, st.state())
            if not st.ok:
                _text_colored(DIM, f"        缺 {'、'.join(st.missing)} —— {st.note}")
            elif not st.in_apk:
                srcs = "、".join(f"{k} ← {v}" for k, v in st.where.items() if v)
                _text_colored(DIM, f"        {srcs}")

        adv = rep.advice()
        if adv:
            imgui.separator()
            _text_colored(YELLOW, "  ▸ 怎么办")
            for a in adv:
                _text_colored(DIM, "    · " + a)
        imgui.end()

    def _export(self, out_dir: str) -> str:
        r = self.sess.output_cache(out_dir, allow_broken=True)
        return f"✓ 导出到 {r['dir']}（{len(r['written'])} 个包）"

    _TABS = ("tutorial", "quest", "trainer", "npc", "avatar", "world")

    def _autotest(self) -> None:
        """每帧切一个页签 —— 必须**真的画一遍**每个页签。

        只在循环里换状态是不够的：`_draw_story_editor` 只画当前页签，
        循环结束时停在最后一个，前面几个的绘制路径根本没走到。
        （免疫：我方皮肤那个页签会调 immvision.image，色彩顺序没设的话
        正好是在这一步 panic，光换状态是发现不了的。）
        """
        pin = os.environ.get("PM_STORYKIT_TAB")
        if self._frame == 1 and self.sess.source is not None:
            self.show_story = True
            self._st_reset()
            if os.environ.get("PM_STORYKIT_SHOW_DIAG") == "1":
                from pm_storykit import diagnose as DG

                self.diag = DG.inspect(self.sess)
                self.show_diag = True
            if pin:
                self.st_tab = pin
        elif self._frame >= 2 and self.sess.source is not None:
            from pm_storykit import diagnose as DG

            rep = DG.inspect(self.sess)
            if any("spdata" in f.missing for f in rep.blocked):
                # 这个来源根本没有 spdata（官方/精简包），剧情表读不到 ——
                # 这正是「检测」要报告的事，不是 bug。这里验证报告本身。
                assert not rep.complete, "没有 spdata 却判成完整版了"
                assert rep.headline(), "检测报告没有结论"
                assert rep.advice(), "检测报告没给怎么办"
                only_text = [f for f in rep.features if f.ok]
                assert any("对白" in f.name for f in only_text), \
                    "text 在 APK 里，对白应该还能改"
                if self._frame == 2:
                    print(f"[自检] 非完整版检测：{rep.headline()}", flush=True)
                    print(f"[自检] 用不了的功能 {len(rep.blocked)} 项，"
                          f"还能用的 {len(only_text)} 项", flush=True)
                return
            i = (self._frame - 2) % len(self._TABS)
            tab = pin or self._TABS[i]
            self.st_tab = tab
            rows = self._st_rows()
            assert rows, f"「{tab}」读不到条目"
            want = os.environ.get("PM_STORYKIT_SEL")
            if want and any(r["id"] == want for r in rows):
                self.st_sel = want
            elif self.st_sel not in [r["id"] for r in rows]:
                self.st_sel = next((r["id"] for r in rows if r.get("team_n")), rows[0]["id"])
            self.st_loaded = ""
            self._st_load()
            if self.st_sel.startswith("lineup"):
                # 阵容那一组没有文本字段，但要有双方队伍和野怪候选
                L = getattr(self, "st_lineup", None) or {}
                assert L.get("opponents"), "教程对方阵容读不到"
                assert L.get("candidates"), "教程野怪候选读不到"
                assert L["world"].get("id") == "Tutorial", "教程世界不对"
                if self._frame <= 3:
                    print(f"[自检] 教程阵容：对方 {len(L['opponents'])} 个训练师，"
                          f"野怪候选 {len(L['candidates'])} 只，"
                          f"世界 {L['world']['id']} {L['world']['size']}", flush=True)
                return
            assert self.st_fields, f"「{tab}」读不到文本"
            if tab == "world":
                # 边界：18 张地图全过一遍 —— 有 0×0 的、没主题的、limits 空的。
                # 只挑第一张（15×15）是发现不了这些的，TournamentLobby 就是 0×0。
                from pm_storykit import story as ST
                from pm_storykit import worldmap as WM

                saved = self.st_map
                bad = []
                for wr in ST.read_table(self.sess, "WorldInfo").items():
                    wid, row = wr
                    m = WM.from_row(dict(row, id=wid) if "id" not in row else row)
                    m["id"] = wid
                    self.st_map = m
                    try:
                        r = self._draw_map_canvas(m, 300.0)   # 直接调，验证不崩
                        assert isinstance(r, tuple) and len(r) == 3, \
                            f"{wid} 画布返回值不对: {r!r}"
                    except Exception as exc:  # noqa: BLE001
                        bad.append(f"{wid}: {type(exc).__name__}: {exc}")
                    # 写回的格式也要能过
                    WM.format_limits(m.get("limits") or {})
                    WM.to_row_patch(m)
                self.st_map = saved          # 扫描是**只读**的，别污染编辑器状态
                assert not bad, f"地图画布在这些世界上崩了: {bad[:3]}"
                print(f"[自检] 地图画布：18 张全过（含 0×0 的 TournamentLobby）", flush=True)
                assert getattr(self, "st_map", None), "地图状态没建起来"
                assert self.st_map.get("limits"), "nodelimits 没解析出来"
                print(f"[自检] 地图：{self.st_map['id']} "
                      f"{self.st_map['w']}×{self.st_map['h']} "
                      f"主题={self.st_map['theme']} "
                      f"配额={len(self.st_map['limits'])} 种", flush=True)
            if i == len(self._TABS) - 1:
                print(f"[自检] 剧情：{self._st_overview().counts()}", flush=True)
        if self._frame >= self.autotest:
            print(f"[自检] 渲染 {self._frame} 帧无异常，退出", flush=True)

    # ------------------------------------------------------------ 剧情编辑器
    #
    # 单人剧情拆在**两个地方**：spdata 的表（任务/训练师/地图的数据）
    # 和 text/<语言> 的段（对白文本）。这个窗口把两边并到一起改。

    STORY_TABS = [
        ("tutorial", "新手教程", "TUTORIAL"),
        ("quest", "剧情任务", "QUESTS"),
        ("trainer", "对战训练师", "TRAINERS"),
        ("npc", "NPC 对白", "NPC"),
        ("avatar", "我方皮肤", "SKINS"),
        ("world", "地图", "MAPS"),
    ]

    def _st_reset(self) -> None:
        self.st_tab = "quest"
        self.st_lang = "ZH_CN"
        self.st_sel = ""
        self.st_filter = ""
        self.st_loaded = ""
        self.st_fields = {}
        self.st_team = []
        self.st_msg = ""
        self.st_ov = None
        self.st_map = None
        self.st_tut_extra = None
        self._st_tut = None
        self.st_map_show_sim = True
        self._st_themes = []
        self.st_new_id = ""
        self.st_all_langs = False
        self._st_img = None

    def _st_overview(self):
        from pm_storykit import story as ST

        if self.st_ov is None:
            self.st_ov = ST.overview(self.sess, self.st_lang)
        return self.st_ov

    def _st_rows(self) -> list[dict]:
        ov = self._st_overview()
        if self.st_tab == "tutorial":
            return self._st_tut_rows()
        return {
            "quest": ov.quests, "trainer": ov.trainers, "npc": ov.npcs,
            "avatar": ov.avatars, "world": ov.worlds,
        }.get(self.st_tab, [])

    def _st_tut_rows(self) -> list[dict]:
        """新手教程的「列表」：文本分组 + 非文本部分。"""
        from pm_storykit import story as ST

        if getattr(self, "_st_tut", None) is None:
            self._st_tut = (ST.tutorial_texts(self.sess, self.st_lang),
                            ST.tutorial_extras(self.sess, self.st_lang))
        texts, extras = self._st_tut
        rows: list[dict] = []
        for g in texts:
            rows.append({
                "id": "text:" + g["key"],
                "name": f"{g['group']} · {g['label']}" if g["stage"] else g["group"],
                "zh": g["label"], "kind": "text", "group": g,
                "n": len(g["items"]),
            })
        rows.append({
            "id": "lineup", "name": "双方阵容 / 野怪", "zh": "阵容",
            "kind": "lineup", "n": 0,
        })
        for e in extras:
            rows.append({
                "id": "tbl:" + e["table"], "name": e["label"],
                "zh": e["label"], "kind": "table", "extra": e, "n": len(e["rows"]),
            })
        return rows

    def _st_tut_load(self) -> None:
        """把选中的教程分组读进编辑缓冲。"""
        row = next((r for r in self._st_tut_rows() if r["id"] == self.st_sel), None)
        if row is None:
            return
        self.st_fields = {}
        self.st_team = []
        if row["kind"] == "lineup":
            from pm_storykit import story as ST

            self.st_lineup = ST.tutorial_lineups(self.sess, self.st_lang)
            self.st_team = [dict(t) for t in
                            (self.st_lineup["opponents"][0]["team"] if
                             self.st_lineup["opponents"] else [])]
            return
        if row["kind"] == "text":
            for it in row["group"]["items"]:
                self.st_fields[it["id"]] = it["text"]
        else:
            e = row["extra"]
            self.st_tut_extra = e
            for r in e["rows"]:
                if r.get("dialogue") is not None:
                    self.st_fields[r["id"]] = r.get("dialogue", "")

    def _st_load(self) -> None:
        """把选中的那条读进编辑缓冲。"""
        from pm_storykit import story as ST

        if self.st_loaded == f"{self.st_tab}:{self.st_sel}":
            return
        self.st_loaded = f"{self.st_tab}:{self.st_sel}"
        self.st_fields = {}
        self.st_team = []
        self._st_img = None
        self.st_tut_extra = None
        if not self.st_sel:
            return
        if self.st_tab == "tutorial":
            self._st_tut_load()
            return

        sec_key = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
                   "avatar": "PlayerAvatar", "world": "Dimensions"}[self.st_tab]
        sec = ST.SECTION_BY_KEY[sec_key]
        tx = ST.read_texts(self.sess, self.st_lang).get(sec_key) or {}
        row = tx.get(self.st_sel) or {}
        for f, _zh in sec.fields:
            self.st_fields[f] = str(row.get(f, "") or "")

        tbl = {"quest": "QuestInfo", "trainer": "TrainerInfo", "npc": "NPCInfo",
               "avatar": "PlayerAvatarInfo", "world": "WorldInfo"}[self.st_tab]
        data = ST.read_table(self.sess, tbl).get(self.st_sel) or {}
        self.st_table = data
        if self.st_tab == "trainer":
            self.st_team = ST.parse_team(data.get("morties") or "")
        if self.st_tab == "avatar":
            self._st_img = self._st_avatar_img(data.get("assetid") or "")
        if self.st_tab == "world":
            self._st_map_load(data)
            if not getattr(self, "_st_themes", None):
                from pm_storykit import worldmap as WM

                self._st_themes = WM.all_themes(
                    [WM.from_row(r) for r in
                     (self._st_overview().worlds or [])])

    def _st_avatar_img(self, avatar_asset: str):
        """我方皮肤的形象图（包里的 CharacterXxx 贴图）。"""
        from pm_storykit import entries as E

        try:
            b = self.sess.bundle("appdata", eager=True)
            e = next((a for a in b.assets if a.name == "BundleAssetAssignment"), None)
            if e is None:
                return None
            baa = json.loads(b.preview_text(e))
            bundle = str((baa.get(avatar_asset) or {}).get("version") or "")
            if not bundle:
                return None
            ab = self.sess.bundle(bundle, eager=True)
            hit = next((a for a in ab.assets
                        if a.type == "Texture2D" and a.name == f"{avatar_asset}Front"), None)
            if hit is None:
                return None
            img = ab.preview_image(hit)
            if img is None:
                return None
            r = min(1.0, 110.0 / max(img.size))
            if r < 1.0:
                img = img.resize((max(1, int(img.width * r)), max(1, int(img.height * r))),
                                 Image.LANCZOS)
            return np.ascontiguousarray(np.array(img.convert("RGBA")))
        except Exception:  # noqa: BLE001
            return None

    def _st_apply(self) -> str:
        from pm_storykit import story as ST

        if not self.st_sel:
            return "✗ 先选一条"
        if self.st_tab == "tutorial":
            return self._st_tut_apply()
        sec_key = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
                   "avatar": "PlayerAvatar", "world": "Dimensions"}[self.st_tab]
        langs = ST.LANGS if self.st_all_langs else [self.st_lang]
        lines: list[str] = []
        try:
            done = ST.set_texts(self.sess, sec_key, self.st_sel, self.st_fields, langs)
            lines.append(f"✓ 文本：{'、'.join(done) if done else '没有变化'}")
        except Exception as exc:  # noqa: BLE001
            return f"✗ 文本写入失败：{exc}"

        # 表格那边：训练师的队伍、皮肤的字段
        try:
            if self.st_tab == "trainer":
                lines.append("✓ " + ST.set_table_row(
                    self.sess, "TrainerInfo", self.st_sel,
                    {"morties": ST.format_team(self.st_team)}))
            elif self.st_tab == "avatar":
                lines.append("✓ " + ST.set_table_row(
                    self.sess, "PlayerAvatarInfo", self.st_sel,
                    {k: self.st_table.get(k, "") for k in
                     ("assetid", "category", "cost", "currency", "displayorder")}))
            elif self.st_tab == "world":
                from pm_storykit import worldmap as WM

                patch = WM.to_row_patch(self.st_map or {})
                patch["camerabounds"] = self.st_table.get("camerabounds", "")
                lines.append("✓ " + ST.set_table_row(
                    self.sess, "WorldInfo", self.st_sel, patch))
        except Exception as exc:  # noqa: BLE001
            lines.append(f"⚠ 表格写入失败：{exc}")
        self._text_cache.clear()
        return "\n".join(lines)

    def _st_new(self) -> str:
        from pm_storykit import story as ST

        nid = (self.st_new_id or "").strip()
        if not nid or not self.st_sel:
            return "✗ 填个新 ID，并先选一个克隆源"
        if self.st_tab == "tutorial":
            return "✗ 教程文本是固定的一串键（PHASE_1..5），没有「克隆一条」这回事"
        sec_key = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
                   "avatar": "PlayerAvatar", "world": "Dimensions"}[self.st_tab]
        try:
            done = ST.add_entry(self.sess, sec_key, nid, self.st_sel)
        except Exception as exc:  # noqa: BLE001
            return f"✗ {exc}"
        self.st_ov = None
        self.st_sel = nid
        self.st_loaded = ""
        return "✓ 新建：" + "；".join(done)

    # ------------------------------------------------------------ 绘制

    def _draw_story(self) -> None:
        vp = imgui.get_main_viewport()
        _center_next_window(imgui.ImVec2(min(1120.0, vp.work_size.x - 60),
                                         min(880.0, vp.work_size.y - 60)))
        opened, self.show_story = imgui.begin("剧情编辑器", self.show_story)
        if not opened:
            imgui.end()
            return
        if self.sess.source is None:
            _text_colored(WARN, "先打开数据源。")
            imgui.end()
            return
        from pm_storykit import story as ST

        try:
            ov = self._st_overview()
        except Exception as exc:  # noqa: BLE001
            _text_colored(WARN, f"读不到剧情数据：{exc}")
            imgui.end()
            return

        # ---- 标题
        _text_colored(YELLOW, "计划 03")
        imgui.same_line()
        _mono("· STORY EDITOR")
        imgui.same_line(imgui.get_content_region_avail().x - 60)
        _chip("进行中", YELLOW, filled=True)
        imgui.text("单人剧情编辑器")
        imgui.same_line()
        _mono("  QUESTS · TRAINERS · SKINS · MAPS")
        c = ov.counts()
        _text_colored(DIM, "  ".join(f"{k} {v}" for k, v in c.items())
                           + f"   文本语言：{ST.LANG_LABEL.get(self.st_lang, self.st_lang)}")
        imgui.separator()

        # ---- 页签
        for i, (key, zh, en) in enumerate(self.STORY_TABS):
            on = self.st_tab == key
            if on:
                imgui.push_style_color(imgui.Col_.button, (0.28, 0.24, 0.06, 1.0))
                imgui.push_style_color(imgui.Col_.text, YELLOW)
            if imgui.button(f"{zh}##sttab{key}"):
                self.st_tab = key
                self.st_sel = ""
                self.st_loaded = ""
            if on:
                imgui.pop_style_color(2)
            imgui.same_line()
        imgui.set_next_item_width(150)
        langs = list(ST.LANG_LABEL)
        ci = langs.index(self.st_lang) if self.st_lang in langs else 0
        ch, ci = imgui.combo("##stlang", ci, [ST.LANG_LABEL[x] for x in langs])
        if ch:
            self.st_lang = langs[ci]
            self.st_ov = None
            self._st_tut = None
            self.st_loaded = ""
        _tip("改哪个语言的文本。上面「应用到全部语言」勾上就是 11 种一起写。")

        body_h = max(240.0, min(600.0, imgui.get_content_region_avail().y - 150))
        imgui.begin_child("##stbody", imgui.ImVec2(0, body_h), True)
        tbl_flags = (imgui.TableFlags_.resizable | imgui.TableFlags_.sizing_stretch_prop
                     | imgui.TableFlags_.no_saved_settings)
        if imgui.begin_table("##stcols", 2, tbl_flags):
            imgui.table_setup_column("列表", imgui.TableColumnFlags_.width_fixed, 300)
            imgui.table_setup_column("编辑", imgui.TableColumnFlags_.width_stretch)

            imgui.table_next_row()
            imgui.table_set_column_index(0)
            imgui.set_next_item_width(-1)
            _, self.st_filter = imgui.input_text_with_hint(
                "##stf", f"搜 id 或名字（{len(self._st_rows())} 条）", self.st_filter)
            f = (self.st_filter or "").strip().lower()
            rows = [r for r in self._st_rows()
                    if not f or f in r["id"].lower() or f in (r.get("name") or "").lower()]
            imgui.begin_child("##stlist", imgui.ImVec2(0, body_h - 60), True)
            for i, r in enumerate(rows[:400]):
                label = f"{r.get('name') or r['id']}##st{i}"
                on = self.st_sel == r["id"]
                if on:
                    imgui.push_style_color(imgui.Col_.header, (0.28, 0.24, 0.06, 1.0))
                if imgui.selectable(label, on, 0, imgui.ImVec2(0, 0))[0]:
                    self.st_sel = r["id"]
                if on:
                    imgui.pop_style_color()
                imgui.same_line()
                if self.st_tab == "tutorial":
                    # 教程行的 id 是 text:xxx / tbl:Xxx，显示出来没意义，改成段数
                    imgui.same_line(max(0.0, imgui.get_window_width() - 60))
                    _text_colored(GREEN if r.get("kind") == "text" else DIM, f"{r['n']} 段")
                else:
                    _mono(r["id"])
                if self.st_tab == "trainer" and r.get("team_n"):
                    imgui.same_line(max(0.0, imgui.get_window_width() - 60))
                    _text_colored(GREEN, f"{r['team_n']}只")
                elif self.st_tab == "world" and r.get("w"):
                    imgui.same_line(max(0.0, imgui.get_window_width() - 90))
                    _text_colored(DIM, f"{r['w']}×{r['d']}")
            imgui.end_child()

            # ---- 右栏
            imgui.table_set_column_index(1)
            self._st_load()
            if not self.st_sel:
                _text_colored(DIM, "左边挑一条，这里改它的文本和数据。")
            else:
                self._draw_story_editor()
            imgui.end_table()
        imgui.end_child()

        # ---- 底部
        imgui.separator()
        if imgui.button("应用", imgui.ImVec2(110, 0)):
            self.st_msg = self._st_apply()
        imgui.same_line()
        _, self.st_all_langs = imgui.checkbox("应用到全部 11 种语言", self.st_all_langs)
        imgui.same_line()
        imgui.set_next_item_width(190)
        _, self.st_new_id = imgui.input_text_with_hint("##stnew", "新 ID（克隆用）", self.st_new_id)
        imgui.same_line()
        if imgui.button("克隆一条"):
            self.st_msg = self._st_new()
        imgui.same_line()
        if imgui.button("刷新"):
            self.st_ov = None
            self.st_loaded = ""
            self.st_msg = "已刷新"
        if self.st_msg:
            for line in self.st_msg.split("\n"):
                _text_colored(GREEN if line.startswith("✓") else
                              (WARN if "✗" in line or "⚠" in line else DIM), "  " + line)
        imgui.end()

    def _st_row(self, table: str) -> dict:
        return getattr(self, "st_table", {}) or {}

    def _draw_story_editor(self) -> None:
        from pm_storykit import story as ST

        if self.st_tab == "tutorial":
            self._draw_tutorial_editor()
            return
        sec_key = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
                   "avatar": "PlayerAvatar", "world": "Dimensions"}[self.st_tab]
        sec = ST.SECTION_BY_KEY[sec_key]
        row = self._st_row("")

        imgui.text(f"{row.get('name') or self.st_sel}")
        imgui.same_line()
        _mono("  " + self.st_sel)

        # 皮肤：左边放形象图
        if self.st_tab == "avatar" and self._st_img is not None:
            imgui.same_line()
            h, w = self._st_img.shape[:2]
            imgui.set_cursor_pos_x(max(0.0, imgui.get_window_width() - w - 20))
            p = immvision.ImageParams()
            p.image_display_size = (w, h)
            p.show_options_button = False
            p.show_options_panel = False
            p.show_pixel_info = False
            p.show_image_info = False
            p.show_zoom_buttons = False
            immvision.image("##stavatar", self._st_img, p)

        imgui.separator()
        _text_colored(YELLOW, f"▸ 文本（{ST.LANG_LABEL.get(self.st_lang, self.st_lang)}）")
        for fname, zh in sec.fields:
            multi = fname in ("description", "dialogue", "activedialogue",
                              "rejectdialogue", "acceptdialogue", "completedialogue",
                              "dialoguepostbattle")
            imgui.text(zh)
            imgui.same_line(96)
            _mono(fname)
            val = self.st_fields.get(fname, "")
            imgui.set_next_item_width(-1)
            if multi:
                ch, v = imgui.input_text_multiline(f"##stf_{fname}", val, imgui.ImVec2(0, 52))
            else:
                ch, v = imgui.input_text(f"##stf_{fname}", val)
            if ch:
                self.st_fields[fname] = v
            if not val.strip():
                _text_colored(DIM, "  （空 —— 游戏里这段不显示）")

        # ---- 数据表那部分
        imgui.spacing()
        if self.st_tab == "trainer":
            self._draw_story_team()
        elif self.st_tab == "world":
            self._draw_story_map()
            imgui.spacing()
            _text_colored(DIM, "▸ 其它字段")
            self._draw_story_table_fields(skip=("materialid", "segmentwidth",
                                                "segmentdepth", "nodesetids",
                                                "nodelimits"))
        elif self.st_tab in ("avatar", "quest"):
            self._draw_story_table_fields()

    def _draw_story_team(self) -> None:
        """对手队伍编辑器 —— 「对方皮肤」就是挑不同的莫蒂上场。"""
        from pm_storykit import entries as E
        from pm_storykit import story as ST

        _text_colored(YELLOW, "▸ 出场队伍")
        imgui.same_line()
        _mono("  TEAM")
        _text_colored(DIM, "  换一只莫蒂就是换形象；等级也在这里调")
        if not self.st_team:
            _text_colored(DIM, "  （空队伍 —— 这场可能不是莫蒂对战）")

        try:
            morties = E.list_ids(self.sess, "morty")
        except Exception:  # noqa: BLE001
            morties = []
        loc = {}
        try:
            b = self.sess.bundle("text", eager=True)
            e = next((a for a in b.assets if a.name == "ZH_CN"), None)
            if e is not None:
                loc = json.loads(b.preview_text(e)).get("Morty") or {}
        except Exception:  # noqa: BLE001
            pass

        drop = None
        for i, m in enumerate(self.st_team):
            imgui.text(f"{i + 1}.")
            imgui.same_line(34)
            imgui.set_next_item_width(280)
            cur = morties.index(m["id"]) if m["id"] in morties else 0
            ch, ci = imgui.combo(f"##stm{i}", cur,
                                 [f"{(loc.get(x) or x)} · {x}" for x in morties] or ["（读不到）"])
            if ch and morties:
                m["id"] = morties[ci]
            imgui.same_line()
            imgui.set_next_item_width(90)
            cl, lv = imgui.input_int(f"##stlv{i}", int(m.get("level") or 1))
            if cl:
                m["level"] = max(1, lv)
            imgui.same_line()
            if imgui.small_button(f"×##stdel{i}"):
                drop = i
        if drop is not None:
            self.st_team.pop(drop)
        if imgui.small_button("+ 加一只"):
            self.st_team.append({"id": morties[0] if morties else "", "level": 5})
        imgui.same_line()
        _text_colored(DIM, "队伍写法：" + (ST.format_team(self.st_team) or "（空）")[:60])

    # ------------------------------------------------------------ 地图编辑（图形化）
    #
    # 游戏的地图是**按参数运行时生成**的，数据里没有逐格数组，所以这里不是
    # 「画笔刷格子」，而是把参数画出来：网格画布 + 尺寸滑条 + 节点配额 + 主题调色板，
    # 再按参数模拟一份布局给你看密度。

    def _st_map_load(self, data: dict) -> None:
        from pm_storykit import worldmap as WM

        self.st_map = WM.from_row(data) if data else None
        self.st_map_show_sim = True

    def _draw_tutorial_editor(self) -> None:
        """新手教程的编辑区。

        教程文本在 ``TextDefs`` 里，键形如
        ``WORLD_DIALOGUE_TUTORIAL_PHASE_3_TEXT_1`` —— 一个阶段好几段。
        所以这里不是「一条记录几个字段」，而是**一段一段往下排**。
        """
        from pm_storykit import story as ST

        row = next((r for r in self._st_tut_rows() if r["id"] == self.st_sel), None)
        if row is None:
            _text_colored(DIM, "左边挑一组。")
            return

        _text_colored(YELLOW, f"▸ {row['name']}")
        imgui.same_line()
        _mono(f"  {row['n']} 段")
        if row["kind"] == "text":
            _text_colored(DIM, "   教程对白 —— 每段都能改，改完点底部「应用」")
        else:
            _text_colored(DIM, "   这一组不是纯文本，下面是它的数据和可改的文本")

        imgui.separator()

        if row["kind"] == "lineup":
            self._draw_tutorial_lineup()
            return

        # 非文本组：先把它是什么说清楚
        if row["kind"] == "table":
            e = row["extra"]
            for r in e["rows"]:
                imgui.text(r["id"])
                imgui.same_line(240)
                bits = []
                if r.get("team") is not None:
                    bits.append(f"队伍 {len(r['team'])} 只")
                if r.get("size"):
                    bits.append(f"{r['size']} 主题 {r['theme']}")
                if r.get("data", {}).get("interactiontype"):
                    bits.append(str(r["data"]["interactiontype"]))
                if bits:
                    _text_colored(GREEN, " · ".join(bits))
            imgui.separator()

        # 一段一段的文本
        for fname, val in self.st_fields.items():
            _mono(fname)
            imgui.set_next_item_width(-1)
            ch, v = imgui.input_text_multiline(f"##tut_{fname}", val, imgui.ImVec2(0, 46))
            if ch:
                self.st_fields[fname] = v
            if not str(val).strip():
                _text_colored(DIM, "  （空 —— 游戏里这段不显示）")

    def _st_tut_apply(self) -> str:
        """写回教程文本（TextDefs）。"""
        from pm_storykit import story as ST

        row = next((r for r in self._st_tut_rows() if r["id"] == self.st_sel), None)
        if row is None:
            return "✗ 先选一组"
        if row["kind"] == "lineup":
            from pm_storykit import story as ST

            L = getattr(self, "st_lineup", None) or {}
            n = 0
            for op in L.get("opponents") or []:
                ST.set_trainer_team(self.sess, op["id"], op["team"])
                n += 1
            self._text_cache.clear()
            return f"✓ 教程对方阵容：改了 {n} 个训练师"
        if row["kind"] != "text":
            return "✗ 这一组不是纯文本 —— 教程路牌/训练师请到对应的页签改"
        langs = ST.LANGS if self.st_all_langs else [self.st_lang]
        n = 0
        for k, v in self.st_fields.items():
            if ST.set_textdef(self.sess, k, v, langs):
                n += 1
        self._text_cache.clear()
        self._st_tut = None      # 让列表里的文本刷新
        return f"✓ {row['name']}：改了 {n} 段（{len(langs)} 种语言）"

    def _draw_tutorial_lineup(self) -> None:
        """新手教程的双方阵容 + 野怪。"""
        from pm_storykit import entries as E
        from pm_storykit import story as ST

        L = getattr(self, "st_lineup", None)
        if not L:
            _text_colored(DIM, "读不到教程阵容。")
            return

        try:
            morties = E.list_ids(self.sess, "morty")
        except Exception:  # noqa: BLE001
            morties = []
        loc = {}
        try:
            b = self.sess.bundle("text", eager=True)
            e = next((a for a in b.assets if a.name == "ZH_CN"), None)
            if e is not None:
                loc = json.loads(b.preview_text(e)).get("Morty") or {}
        except Exception:  # noqa: BLE001
            loc = {}

        def mlabel(mid: str) -> str:
            nm = (loc.get(mid) or {}).get("name") or mid
            return f"{nm} · {mid}"

        # ---- 对方阵容
        _text_colored(YELLOW, "▸ 对方阵容")
        imgui.same_line()
        _text_colored(GREEN, "  这个直接能改（TrainerInfo.morties）")
        for i, op in enumerate(L["opponents"]):
            imgui.spacing()
            imgui.text(op["name"])
            imgui.same_line(150)
            _mono(op["id"])
            team = op["team"] or [{"id": morties[0] if morties else "", "level": 5}]
            drop = None
            for j, m in enumerate(team):
                imgui.text(f"    {j + 1}.")
                imgui.same_line(34)
                imgui.set_next_item_width(300)
                cur = morties.index(m["id"]) if m["id"] in morties else 0
                ch, ci = imgui.combo(f"##tlm{i}_{j}", cur,
                                     [mlabel(x) for x in morties] or ["（读不到）"])
                if ch and morties:
                    m["id"] = morties[ci]
                imgui.same_line()
                imgui.set_next_item_width(80)
                cl, lv = imgui.input_int(f"##tll{i}_{j}", int(m.get("level") or 1))
                if cl:
                    m["level"] = max(1, lv)
                imgui.same_line()
                if imgui.small_button(f"×##tld{i}_{j}"):
                    drop = j
            if drop is not None:
                team.pop(drop)
            imgui.same_line()
            if imgui.small_button(f"+ 加一只##tla{i}"):
                team.append({"id": morties[0] if morties else "", "level": 5})
            op["team"] = team

        imgui.spacing()
        imgui.separator()

        # ---- 野怪
        w = L["world"]
        _text_colored(YELLOW, "▸ 教程野怪")
        imgui.same_line()
        _text_colored(DIM, f"  教程世界 {w['id']} {w['size']} 主题 {w['theme']}"
                           f" · 野怪配额 {'不限' if w['morty_quota'] < 0 else w['morty_quota']}")
        _text_colored(DIM, "  对白点名：「他跟我长得一模一样，就是比我脏了一点」→ 邋遢莫蒂")
        imgui.text("   候选（preload 预载的 4 只，游戏脚本从里面挑）：")
        for c in L["candidates"]:
            mark = "●" if c["id"] == "MortyScruffy" else "○"
            imgui.text(f"      {mark} {c['name']}")
            imgui.same_line(170)
            _mono(c["id"])
            imgui.same_line(320)
            _text_colored(DIM, f"编号 {c['number']}  体力 {c['hp']}  攻击 {c['atk']}")
        _text_colored(WARN, "    ⚠ 具体哪只写死在游戏脚本里，数据表里没有。")
        _text_colored(DIM, "      但改这几只的**数值 / 形象 / 名字**，教程里的野怪会跟着变 ——")
        _text_colored(DIM, "      它们本来就是为教程预载的。去「新增条目」或「图鉴」里改就行。")

    def _draw_story_map(self) -> None:
        from pm_storykit import worldmap as WM

        st = getattr(self, "st_map", None)
        if not st:
            _text_colored(DIM, "这条地图没有可用参数。")
            return
        # 主题调色板懒加载（有些世界没有主题）
        if not getattr(self, "_st_themes", None):
            from pm_storykit import worldmap as WM

            self._st_themes = WM.all_themes(
                [WM.from_row(r) for r in (self._st_overview().worlds or [])]) or [""]

        _text_colored(YELLOW, "▸ 地图编辑")
        imgui.same_line()
        _mono("  MAP")
        _text_colored(DIM, "   游戏按下面这些参数**实时生成**地图（数据里没有逐格数组），"
                           "所以这里是参数可视化 + 布局模拟")

        avail_w = imgui.get_content_region_avail().x
        canvas_w = max(260.0, avail_w - 340)
        cw, chh, placed_n = self._draw_map_canvas(st, canvas_w)

        imgui.same_line(0, 14)
        imgui.begin_group()
        imgui.push_item_width(130)
        ch, w = imgui.slider_int("宽##mapw", int(st["w"]), 5, 80)
        if ch:
            st["w"] = w
        ch, h = imgui.slider_int("深##maph", int(st["h"]), 5, 80)
        if ch:
            st["h"] = h
        ch, sp = imgui.slider_float("物品/箱子##mapsplit", float(st.get("split") or 0.5),
                                    0.0, 1.0, "%.2f")
        if ch:
            st["split"] = f"{sp:.2f}"

        imgui.spacing()
        _text_colored(YELLOW, "主题")
        imgui.same_line()
        themes = getattr(self, "_st_themes", []) or [st.get("theme") or ""]
        cur = themes.index(st["theme"]) if st.get("theme") in themes else 0
        imgui.set_next_item_width(-30)
        ch, ci = imgui.combo("##maptheme", cur, themes or ["（无）"])
        if ch and themes:
            st["theme"] = themes[ci]
        c = WM.theme_color(st.get("theme") or "")
        pp = imgui.get_cursor_screen_pos()
        imgui.get_window_draw_list().add_rect_filled(
            imgui.ImVec2(pp.x, pp.y + 3), imgui.ImVec2(pp.x + 18, pp.y + 21),
            imgui.get_color_u32(imgui.ImVec4(*c, 1.0)), 3.0)
        imgui.dummy(imgui.ImVec2(20, 22))

        imgui.spacing()
        _text_colored(YELLOW, "▸ 节点配额")
        imgui.same_line()
        _mono("nodelimits")
        _text_colored(DIM, "  −1 = 不限")
        limits = st.setdefault("limits", {})
        imgui.begin_child("##maplims", imgui.ImVec2(300, 190), True)
        for kind in WM.NODE_LABEL:
            if kind not in limits:
                continue
            v = int(limits[kind])
            imgui.text(WM.node_label(kind))
            imgui.same_line(108)
            pp = imgui.get_cursor_screen_pos()
            imgui.get_window_draw_list().add_rect_filled(
                imgui.ImVec2(pp.x, pp.y + 4), imgui.ImVec2(pp.x + 11, pp.y + 15),
                imgui.get_color_u32(imgui.ImVec4(*WM.node_color(kind), 1.0)), 2.0)
            imgui.dummy(imgui.ImVec2(15, 20))
            imgui.same_line()
            imgui.set_next_item_width(90)
            ch, nv = imgui.input_int(f"##maplim{kind}", v)
            if ch:
                limits[kind] = nv
            imgui.same_line()
            _text_colored(DIM if v < 0 else GREEN, WM.limit_display(v))
        imgui.end_child()
        _text_colored(DIM, f"  合计会铺 {WM.total_nodes(limits)} 个")
        if imgui.small_button("全不限"):
            for k in limits:
                limits[k] = -1
        imgui.same_line()
        if imgui.small_button("全 0"):
            for k in limits:
                limits[k] = 0
        imgui.same_line()
        _, self.st_map_show_sim = imgui.checkbox("模拟布局", self.st_map_show_sim)
        imgui.end_group()

        # 图例放画布下面（这时才换行）
        _text_colored(DIM, f"  {st['w']} × {st['h']} 格 · 主题 {st.get('theme') or '—'}"
                           + (f" · 模拟 {placed_n} 个节点" if placed_n else ""))
        used = [k for k in WM.NODE_LABEL if int((st.get("limits") or {}).get(k, 0)) > 0]
        for i, k in enumerate(used):
            if i % 4:
                imgui.same_line(0, 10)
            pp = imgui.get_cursor_screen_pos()
            imgui.get_window_draw_list().add_rect_filled(
                imgui.ImVec2(pp.x, pp.y + 4), imgui.ImVec2(pp.x + 10, pp.y + 14),
                imgui.get_color_u32(imgui.ImVec4(*WM.node_color(k), 1.0)), 2.0)
            imgui.dummy(imgui.ImVec2(13, 0))
            imgui.same_line()
            _text_colored(DIM, WM.node_label(k))

    def _draw_map_canvas(self, st: dict, width: float) -> None:
        """把地图画出来：主题底色 + 网格 + 模拟节点。"""
        from pm_storykit import worldmap as WM

        w, h = int(st["w"]), int(st["h"])
        if w <= 0 or h <= 0:
            # 有几张地图就是 0×0（TournamentLobby），别当异常 ——
            # 但**必须照样返回三元组**，外面是解包调用的（踩过）
            _text_colored(DIM, f"这张地图没有尺寸（{w}×{h}）—— 它不在世界里生成，"
                               f"是直接挂场景的，改改主题就行")
            imgui.dummy(imgui.ImVec2(max(200.0, width), 60))
            return max(200.0, width), 60.0, 0
        cell = max(6.0, min(20.0, min((width - 8) / max(1, w), 330.0 / max(1, h))))
        cw, chh = cell * w, cell * h
        p0 = imgui.get_cursor_screen_pos()
        dl = imgui.get_window_draw_list()
        theme = WM.theme_color(st.get("theme") or "")

        # 底色
        dl.add_rect_filled(imgui.ImVec2(p0.x, p0.y),
                           imgui.ImVec2(p0.x + cw, p0.y + chh),
                           imgui.get_color_u32(imgui.ImVec4(*theme, 1.0)), 2.0)
        # 网格
        grid = imgui.get_color_u32(imgui.ImVec4(0, 0, 0, 0.22))
        if cell >= 8:
            for x in range(w + 1):
                dl.add_line(imgui.ImVec2(p0.x + x * cell, p0.y),
                            imgui.ImVec2(p0.x + x * cell, p0.y + chh), grid, 1.0)
            for y in range(h + 1):
                dl.add_line(imgui.ImVec2(p0.x, p0.y + y * cell),
                            imgui.ImVec2(p0.x + cw, p0.y + y * cell), grid, 1.0)
        # 模拟节点
        placed = []
        if getattr(self, "st_map_show_sim", True):
            placed = WM.simulate(st.get("id", ""), w, h, st.get("limits") or {})
            for nd in placed:
                x, y = nd["x"], nd["y"]
                col = WM.node_color(nd["kind"])
                a = imgui.ImVec2(p0.x + x * cell + 1, p0.y + y * cell + 1)
                b = imgui.ImVec2(p0.x + (x + 1) * cell - 1, p0.y + (y + 1) * cell - 1)
                dl.add_rect_filled(a, b, imgui.get_color_u32(imgui.ImVec4(*col, 1.0)), 2.0)
                if cell >= 16:
                    # add_rect(p_min, p_max, col, rounding, thickness, flags)
                    dl.add_rect(a, b, imgui.get_color_u32(imgui.ImVec4(0, 0, 0, 0.6)),
                                2.0, 1.0)
        # 边框
        dl.add_rect(imgui.ImVec2(p0.x, p0.y), imgui.ImVec2(p0.x + cw, p0.y + chh),
                    imgui.get_color_u32(imgui.ImVec4(0.5, 0.5, 0.55, 0.8)), 2.0, 1.5)
        imgui.dummy(imgui.ImVec2(cw, chh))
        # 注意：这里**只能有 dummy**，后面不能再画文字 ——
        # 一旦换行，调用方的 same_line() 就接不到画布右边了（踩过）
        return cw, chh, len(placed)

    def _draw_story_table_fields(self, skip: tuple = ()) -> None:
        from pm_storykit import story as ST

        table = {"quest": "QuestInfo", "avatar": "PlayerAvatarInfo",
                 "world": "WorldInfo"}[self.st_tab]
        _text_colored(YELLOW, "▸ 数据（spdata/" + table + "）")
        data = self._st_row(table)
        for k in sorted(data):
            if k in ("id", "content", "morties", "items") or k in skip:
                continue
            v = str(data.get(k, "") or "")
            imgui.text(ST.field_label(table, k))
            imgui.same_line(150)
            _mono(k)
            imgui.set_next_item_width(-1)
            ch, nv = imgui.input_text(f"##stt_{k}", v)
            if ch:
                data[k] = nv

def _ellipsis(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def main() -> int:
    # ImmVision 要求**先声明通道顺序**再显示任何图（2024-10 起的破坏性变更）。
    # 不设的话第一次 immvision.image() 就 panic。抽离时漏过一次。
    immvision.use_rgb_color_order()

    paths = [p for p in sys.argv[1:] if Path(p).exists()]
    app = StoryApp(paths)
    params = hello_imgui.RunnerParams()
    params.callbacks.show_gui = app.draw
    params.callbacks.load_additional_fonts = load_fonts
    params.app_window_params.window_title = APP_NAME
    params.app_window_params.window_geometry.size = (1180, 800)
    params.imgui_window_params.default_imgui_window_type = (
        hello_imgui.DefaultImGuiWindowType.provide_full_screen_window)
    params.imgui_window_params.show_status_bar = False
    try:
        immapp.run(params)
    except KeyboardInterrupt:
        return 130

    shot = os.environ.get("PM_STORYKIT_SHOT")
    if shot and app.autotest:
        try:
            arr = np.asarray(hello_imgui.final_app_window_screenshot())
            Image.fromarray(arr).save(shot)
            print(f"[自检] 截图已保存：{shot}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[自检] 截图失败：{exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
