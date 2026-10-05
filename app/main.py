#!/usr/bin/env python3
"""口蘑剧情编辑器 · 图形界面（独立版）

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

from storykit import session as session_mod  # noqa: E402
from storykit import story as story_mod  # noqa: E402
from storykit import sysenv  # noqa: E402

APP_NAME = "口蘑剧情编辑器"

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
        self._st_reset()
        self.autotest = int(os.environ.get("PM_STORY_AUTOTEST", "0") or "0")
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

    def _export(self, out_dir: str) -> str:
        r = self.sess.output_cache(out_dir, allow_broken=True)
        return f"✓ 导出到 {r['dir']}（{len(r['written'])} 个包）"

    _TABS = ("quest", "trainer", "npc", "avatar", "world")

    def _autotest(self) -> None:
        """每帧切一个页签 —— 必须**真的画一遍**每个页签。

        只在循环里换状态是不够的：`_draw_story_editor` 只画当前页签，
        循环结束时停在最后一个，前面几个的绘制路径根本没走到。
        （免疫：我方皮肤那个页签会调 immvision.image，色彩顺序没设的话
        正好是在这一步 panic，光换状态是发现不了的。）
        """
        pin = os.environ.get("PM_STORY_TAB")
        if self._frame == 1 and self.sess.source is not None:
            self.show_story = True
            self._st_reset()
            if pin:
                self.st_tab = pin
        elif self._frame >= 2 and self.sess.source is not None:
            i = (self._frame - 2) % len(self._TABS)
            tab = pin or self._TABS[i]
            self.st_tab = tab
            rows = self._st_rows()
            assert rows, f"「{tab}」读不到条目"
            if self.st_sel not in [r["id"] for r in rows]:
                self.st_sel = next((r["id"] for r in rows if r.get("team_n")), rows[0]["id"])
            self.st_loaded = ""
            self._st_load()
            assert self.st_fields, f"「{tab}」读不到文本"
            if i == len(self._TABS) - 1:
                print(f"[自检] 剧情：{self._st_overview().counts()}", flush=True)
        if self._frame >= self.autotest:
            print(f"[自检] 渲染 {self._frame} 帧无异常，退出", flush=True)

    # ------------------------------------------------------------ 剧情编辑器
    #
    # 单人剧情拆在**两个地方**：spdata 的表（任务/训练师/地图的数据）
    # 和 text/<语言> 的段（对白文本）。这个窗口把两边并到一起改。

    STORY_TABS = [
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
        self.st_new_id = ""
        self.st_all_langs = False
        self._st_img = None

    def _st_overview(self):
        from storykit import story as ST

        if self.st_ov is None:
            self.st_ov = ST.overview(self.sess, self.st_lang)
        return self.st_ov

    def _st_rows(self) -> list[dict]:
        ov = self._st_overview()
        return {
            "quest": ov.quests, "trainer": ov.trainers, "npc": ov.npcs,
            "avatar": ov.avatars, "world": ov.worlds,
        }.get(self.st_tab, [])

    def _st_load(self) -> None:
        """把选中的那条读进编辑缓冲。"""
        from storykit import story as ST

        if self.st_loaded == f"{self.st_tab}:{self.st_sel}":
            return
        self.st_loaded = f"{self.st_tab}:{self.st_sel}"
        self.st_fields = {}
        self.st_team = []
        self._st_img = None
        if not self.st_sel:
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

    def _st_avatar_img(self, avatar_asset: str):
        """我方皮肤的形象图（包里的 CharacterXxx 贴图）。"""
        from storykit import entries as E

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
        from storykit import story as ST

        if not self.st_sel:
            return "✗ 先选一条"
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
                lines.append("✓ " + ST.set_table_row(
                    self.sess, "WorldInfo", self.st_sel,
                    {k: self.st_table.get(k, "") for k in
                     ("materialid", "segmentwidth", "segmentdepth", "nodesetids")}))
        except Exception as exc:  # noqa: BLE001
            lines.append(f"⚠ 表格写入失败：{exc}")
        self._text_cache.clear()
        return "\n".join(lines)

    def _st_new(self) -> str:
        from storykit import story as ST

        nid = (self.st_new_id or "").strip()
        if not nid or not self.st_sel:
            return "✗ 填个新 ID，并先选一个克隆源"
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
        from storykit import story as ST

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
        from storykit import story as ST

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
        elif self.st_tab in ("avatar", "world", "quest"):
            self._draw_story_table_fields()

    def _draw_story_team(self) -> None:
        """对手队伍编辑器 —— 「对方皮肤」就是挑不同的莫蒂上场。"""
        from storykit import entries as E
        from storykit import story as ST

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

    def _draw_story_table_fields(self) -> None:
        from storykit import story as ST

        table = {"quest": "QuestInfo", "avatar": "PlayerAvatarInfo",
                 "world": "WorldInfo"}[self.st_tab]
        _text_colored(YELLOW, "▸ 数据（spdata/" + table + "）")
        data = self._st_row(table)
        for k in sorted(data):
            if k in ("id", "content", "morties", "items"):
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

    shot = os.environ.get("PM_STORY_SHOT")
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
