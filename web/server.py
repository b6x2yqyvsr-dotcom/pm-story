#!/usr/bin/env python3
"""口蘑剧情工坊 · 网页版后端

手机（Android / iOS）和没有图形环境的机器走这条路。只做剧情编辑，
接口少、操作简单：

    /api/open          打开来源（拖进来的文件路径，或已经上传的）
    /api/upload-many   拖拽上传（multipart）
    /api/state         当前状态：来源、检测、六个板块各有多少条
    /api/list          某个板块的条目列表
    /api/get           某一条的详细内容（可编辑的字段）
    /api/set           写回
    /api/export        导出 UnityCache 目录
    /api/download      把导出的目录打成 zip 下载（手机上用）
"""

from __future__ import annotations


def _force_utf8() -> None:
    """Windows 控制台默认 cp1252/cp936，print 中文会 UnicodeEncodeError。"""
    import sys
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


_force_utf8()

import argparse  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
import urllib.parse  # noqa: E402
import zipfile  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pm_storykit import diagnose as DG  # noqa: E402
from pm_storykit import export as EX  # noqa: E402
from pm_storykit import session as session_mod  # noqa: E402
from pm_storykit import story as ST  # noqa: E402
from pm_storykit import worldmap as WM  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent
WORK = Path(os.environ.get("PM_STORYKIT_WORK", Path.home() / "pm-storykit-工作区"))
UPLOAD = WORK / "上传"
OUT = WORK / "导出"

#: 六个板块 —— 网页上就是六个大按钮
TABS = [
    ("tutorial", "新手教程", "教程对白、双方阵容、野怪"),
    ("quest", "剧情任务", "任务名、给予者、四段对白"),
    ("trainer", "对战训练师", "战前/战后对白、出场队伍"),
    ("npc", "NPC 对白", "名字和对白"),
    ("avatar", "我方皮肤", "显示名、形象、价格"),
    ("world", "地图", "尺寸、主题、节点配额"),
]


def _jsonable(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)


class App:
    def __init__(self) -> None:
        self.sess = session_mod.Session()
        self.lock = threading.RLock()
        self.last_export: Path | None = None
        self.last_export_file: Path | None = None

    # ------------------------------------------------------------ 状态

    def state(self) -> dict:
        s = self.sess
        if s.source is None:
            return {"opened": False, "tabs": [{"key": k, "label": l, "hint": h}
                                             for k, l, h in TABS]}
        rep = DG.inspect(s)
        counts = {}
        try:
            ov = ST.overview(s)
            counts = {"quest": len(ov.quests), "trainer": len(ov.trainers),
                      "npc": len(ov.npcs), "avatar": len(ov.avatars),
                      "world": len(ov.worlds)}
            counts["tutorial"] = len(ST.tutorial_texts(s)) + len(ST.tutorial_extras(s))
        except Exception:  # noqa: BLE001
            pass
        return {
            "opened": True,
            "files": [f.label for f in rep.files],
            "bundles": rep.total_bundles,
            "complete": rep.complete,
            "headline": rep.headline(),
            "blocked": [f.name for f in rep.blocked],
            "modified": list(s.modified),
            "exported": str(self.last_export) if self.last_export else "",
            "export_kinds": EX.catalog(),
            "counts": counts,
            "tabs": [{"key": k, "label": l, "hint": h} for k, l, h in TABS],
            "log": s.log[-40:],
        }

    # ------------------------------------------------------------ 列表

    def list_items(self, tab: str) -> list[dict]:
        s = self.sess
        if tab == "tutorial":
            out = []
            for g in ST.tutorial_texts(s):
                out.append({"id": "text:" + g["key"],
                            "name": (f"{g['group']} · {g['label']}" if g["stage"]
                                     else g["group"]),
                            "info": f"{len(g['items'])} 段", "kind": "text"})
            out.append({"id": "lineup", "name": "双方阵容 / 野怪",
                        "info": "对方队伍 + 野怪候选", "kind": "lineup"})
            for e in ST.tutorial_extras(s):
                out.append({"id": "tbl:" + e["table"], "name": e["label"],
                            "info": f"{len(e['rows'])} 条", "kind": "table"})
            return out
        ov = ST.overview(s)
        rows = {"quest": ov.quests, "trainer": ov.trainers, "npc": ov.npcs,
                "avatar": ov.avatars, "world": ov.worlds}.get(tab, [])
        out = []
        for r in rows:
            info = ""
            if tab == "trainer":
                info = f"队伍 {r.get('team_n', 0)} 只"
            elif tab == "world":
                info = f"{r.get('w')}×{r.get('d')} 主题 {r.get('material')}"
            elif tab == "avatar":
                info = f"{r.get('category') or '—'} · {r.get('cost')}{r.get('currency') or ''}"
            elif tab == "quest":
                info = r.get("giver") or ""
            out.append({"id": r["id"], "name": r.get("name") or r["id"],
                        "info": info, "kind": "row"})
        return out

    # ------------------------------------------------------------ 取一条

    def get_item(self, tab: str, item_id: str) -> dict:
        s = self.sess
        if tab == "tutorial":
            return self._get_tutorial(item_id)
        sec_key = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
                   "avatar": "PlayerAvatar", "world": "Dimensions"}[tab]
        sec = ST.SECTION_BY_KEY[sec_key]
        tx = ST.read_texts(s, "ZH_CN").get(sec_key) or {}
        row = tx.get(item_id) or {}
        fields = [{"name": f, "label": zh, "value": str(row.get(f, "") or ""),
                   "multiline": f in ("description", "dialogue", "activedialogue",
                                      "rejectdialogue", "acceptdialogue",
                                      "completedialogue", "dialoguepostbattle")}
                  for f, zh in sec.fields]
        extra = {}
        team = []
        if tab == "trainer":
            d = ST.read_table(s, "TrainerInfo").get(item_id) or {}
            team = ST.parse_team(d.get("morties") or "")
        elif tab == "avatar":
            d = ST.read_table(s, "PlayerAvatarInfo").get(item_id) or {}
            extra = {k: str(d.get(k, "") or "") for k in
                     ("assetid", "category", "cost", "currency")}
        elif tab == "world":
            d = ST.read_table(s, "WorldInfo").get(item_id) or {}
            w = WM.from_row(dict(d, id=item_id))
            extra = {"w": w["w"], "h": w["h"], "theme": w["theme"],
                     "split": w["split"], "limits": w["limits"],
                     "themes": WM.all_themes([WM.from_row(dict(x, id=k))
                                              for k, x in
                                              ST.read_table(s, "WorldInfo").items()])}
        return {"ok": True, "id": item_id, "name": row.get("name") or item_id,
                "fields": fields, "team": team, "extra": extra,
                "kind": "row", "sec": sec_key}

    def _get_tutorial(self, item_id: str) -> dict:
        s = self.sess
        if item_id == "lineup":
            L = ST.tutorial_lineups(s)
            return {"ok": True, "kind": "lineup", "id": item_id,
                    "name": "双方阵容 / 野怪",
                    "opponents": _jsonable(L["opponents"]),
                    "candidates": _jsonable(L["candidates"]),
                    "world": _jsonable(L["world"])}
        if item_id.startswith("text:"):
            key = item_id[5:]
            for g in ST.tutorial_texts(s):
                if g["key"] == key:
                    return {"ok": True, "kind": "text", "id": item_id,
                            "name": f"{g['group']} · {g['label']}",
                            "fields": [{"name": it["id"], "label": it["id"],
                                        "value": it["text"], "multiline": True}
                                       for it in g["items"]]}
        if item_id.startswith("tbl:"):
            table = item_id[4:]
            for e in ST.tutorial_extras(s):
                if e["table"] == table:
                    rows = []
                    for r in e["rows"]:
                        rows.append({"id": r["id"], "dialogue": r.get("dialogue", ""),
                                     "team": r.get("team"), "size": r.get("size"),
                                     "theme": r.get("theme")})
                    return {"ok": True, "kind": "table", "id": item_id,
                            "name": e["label"], "rows": _jsonable(rows),
                            "fields": [{"name": r["id"], "label": r["id"],
                                        "value": r.get("dialogue", ""), "multiline": False}
                                       for r in e["rows"] if r.get("dialogue") is not None]}
        return {"ok": False, "error": f"不认识的条目 {item_id}"}

    # ------------------------------------------------------------ 写一条

    def set_item(self, body: dict) -> dict:
        s = self.sess
        tab, item_id = body.get("tab", ""), body.get("id", "")
        langs = ST.LANGS if body.get("all_langs") else ["ZH_CN"]
        done: list[str] = []
        if tab == "tutorial":
            kind = body.get("kind")
            if kind == "lineup":
                for op in body.get("opponents") or []:
                    ST.set_trainer_team(s, op["id"], op.get("team") or [])
                return {"ok": True, "message": "✓ 教程对方阵容已更新"}
            if kind == "text":
                n = 0
                for k, v in (body.get("fields") or {}).items():
                    if ST.set_textdef(s, k, v, langs):
                        n += 1
                return {"ok": True, "message": f"✓ 改了 {n} 段教程文本"}
            if kind == "table":
                return {"ok": False, "error": "这一组不是纯文本，请到对应板块改"}
        vals = body.get("fields") or {}
        if vals:
            sec_key = {"quest": "Quest", "trainer": "Trainer", "npc": "NPC",
                       "avatar": "PlayerAvatar", "world": "Dimensions"}[tab]
            done = ST.set_texts(s, sec_key, item_id, vals, langs)
        if tab == "trainer" and body.get("team") is not None:
            ST.set_trainer_team(s, item_id, body["team"])
            done.append("出场队伍已更新")
        if tab == "avatar" and body.get("extra"):
            ST.set_table_row(s, "PlayerAvatarInfo", item_id,
                             {k: v for k, v in body["extra"].items()
                              if k in ("assetid", "category", "cost", "currency")})
            done.append("皮肤数据已更新")
        if tab == "world" and body.get("extra"):
            e = body["extra"]
            patch = {"segmentwidth": str(e.get("w", "")),
                     "segmentdepth": str(e.get("h", "")),
                     "materialid": e.get("theme", ""),
                     "itemparttypesplit": str(e.get("split", "0.5"))}
            if e.get("limits"):
                patch["nodelimits"] = WM.format_limits(
                    {k: int(v) for k, v in e["limits"].items()})
            ST.set_table_row(s, "WorldInfo", item_id, patch)
            done.append("地图参数已更新")
        return {"ok": bool(done), "message": "✓ " + "；".join(done) if done else "没有变化"}

    # ------------------------------------------------------------ 导出

    def export_kinds(self) -> list[dict]:
        return EX.catalog()

    def export(self, how: str = "cache", name: str = "") -> dict:
        OUT.mkdir(parents=True, exist_ok=True)
        r = EX.run(self.sess, how, OUT, name=name or "剧情模组")
        if r.get("ok") and r.get("path"):
            p = Path(r["path"])
            self.last_export = p if p.is_dir() else p.parent
            self.last_export_file = p if p.is_file() else None
        return r

    def download_zip(self) -> bytes:
        f = getattr(self, "last_export_file", None)
        if f and Path(f).is_file():
            return Path(f).read_bytes()      # 单个文件（.pmmod / .apk）直接给
        if not self.last_export or not Path(self.last_export).exists():
            raise ValueError("还没导出过")
        buf = io.BytesIO()
        root = Path(self.last_export)
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for p in sorted(root.rglob("*")):
                if p.is_file():
                    zi = zipfile.ZipInfo(str(p.relative_to(root)).replace(os.sep, "/"),
                                         date_time=(2026, 1, 1, 0, 0, 0))
                    zi.flag_bits |= 0x800
                    z.writestr(zi, p.read_bytes())
        return buf.getvalue()


APP = App()


class Handler(BaseHTTPRequestHandler):
    server_version = "pm-storykit"

    def log_message(self, *a):  # noqa: D102
        pass

    # -------------------------------------------------------- 工具

    def _send(self, code, body: bytes, ctype: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(_jsonable(obj), ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _body(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _json_body(self) -> dict:
        raw = self._body()
        return json.loads(raw.decode()) if raw else {}

    # -------------------------------------------------------- GET

    def do_GET(self):  # noqa: N802
        try:
            u = urllib.parse.urlparse(self.path)
            path, q = u.path, dict(urllib.parse.parse_qsl(u.query))
            if path in ("/", "/index.html"):
                f = WEB_DIR / "index.html"
                return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
            if path == "/manifest.webmanifest":
                f = WEB_DIR / "manifest.webmanifest"
                if f.is_file():
                    return self._send(200, f.read_bytes(),
                                      "application/manifest+json; charset=utf-8")
            if path == "/sw.js":
                f = WEB_DIR / "sw.js"
                if f.is_file():
                    return self._send(200, f.read_bytes(),
                                      "application/javascript; charset=utf-8")
            if path.startswith("/icon") and path.endswith(".png"):
                f = (WEB_DIR / path.lstrip("/")).resolve()
                if str(f).startswith(str(WEB_DIR.resolve())) and f.is_file():
                    return self._send(200, f.read_bytes(), "image/png")
            if path == "/api/state":
                with APP.lock:
                    return self._json(APP.state())
            if path == "/api/list":
                with APP.lock:
                    return self._json({"ok": True,
                                       "items": APP.list_items(q.get("tab", "quest"))})
            if path == "/api/get":
                with APP.lock:
                    return self._json(APP.get_item(q.get("tab", "quest"),
                                                   q.get("id", "")))
            if path == "/api/download":
                with APP.lock:
                    data = APP.download_zip()
                return self._send(200, data, "application/zip", {
                    "Content-Disposition": 'attachment; filename="story-export.zip"'})
            return self._json({"ok": False, "error": "没有这个路径"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc()[-800:]}, 400)

    # -------------------------------------------------------- POST

    def do_POST(self):  # noqa: N802
        try:
            u = urllib.parse.urlparse(self.path)
            path, q = u.path, dict(urllib.parse.parse_qsl(u.query))

            if path == "/api/upload-many":
                import email
                from email import policy

                raw = self._body()
                ctype = self.headers.get("Content-Type", "")
                parts = []
                if "multipart/form-data" in ctype:
                    msg = email.message_from_bytes(
                        b"Content-Type: " + ctype.encode()
                        + b"\r\nMIME-Version: 1.0\r\n\r\n" + raw,
                        policy=policy.default)
                    for part in msg.iter_parts():
                        fn = part.get_filename()
                        if fn:
                            parts.append((Path(fn).name, part.get_payload(decode=True) or b""))
                if not parts:
                    return self._json({"ok": False, "error": "没收到文件"})
                UPLOAD.mkdir(parents=True, exist_ok=True)
                got = []
                for fn, data in parts:
                    dest = UPLOAD / fn
                    i = 1
                    while dest.exists():
                        dest = UPLOAD / f"{Path(fn).stem}-{i}{Path(fn).suffix}"
                        i += 1
                    dest.write_bytes(data)
                    got.append(str(dest))
                append = APP.sess.source is not None
                ok = fail = 0
                msg = []
                with APP.lock:
                    for one in got:
                        try:
                            APP.sess.add_source(one) if append else APP.sess.open(one)
                            append = True
                            ok += 1
                        except Exception as exc:  # noqa: BLE001
                            fail += 1
                            msg.append(f"{Path(one).name}: {exc}")
                    if ok:
                        APP.sess.say(f"拖入 {ok} 个文件"
                                     + (f"，{fail} 个失败" if fail else ""))
                return self._json({"ok": bool(ok), "added": ok, "failed": msg})

            body = self._json_body()
            if path == "/api/open":
                with APP.lock:
                    paths = body.get("paths") or []
                    append = bool(body.get("append"))
                    for p in paths:
                        APP.sess.add_source(p) if append else APP.sess.open(p)
                        append = True
                    APP.sess.say(f"打开 {len(paths)} 个来源")
                return self._json({"ok": True})
            if path == "/api/set":
                with APP.lock:
                    return self._json(APP.set_item(body))
            if path == "/api/export-kinds":
                with APP.lock:
                    return self._json({"ok": True, "kinds": APP.export_kinds()})
            if path == "/api/export":
                with APP.lock:
                    return self._json(APP.export(body.get("how", "cache"),
                                                 body.get("name", "")))
            if path == "/api/reset":
                with APP.lock:
                    APP.sess = session_mod.Session()
                    APP.last_export = None
                    APP.last_export_file = None
                return self._json({"ok": True})
            return self._json({"ok": False, "error": "没有这个路径"}, 404)
        except Exception as exc:  # noqa: BLE001
            self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                        "trace": traceback.format_exc()[-800:]}, 400)


def main() -> int:
    ap = argparse.ArgumentParser(description="口蘑剧情工坊 网页版")
    ap.add_argument("--host", default="0.0.0.0",
                    help="监听地址。默认所有网卡（手机/别的电脑能连）")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("paths", nargs="*", help="启动时先打开这些文件")
    a = ap.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    for p in a.paths:
        try:
            APP.sess.open(p) if APP.sess.source is None else APP.sess.add_source(p)
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ 启动时打开失败：{exc}")

    print()
    print("  口蘑剧情工坊 · 网页版")
    print("  " + "─" * 40)
    print(f"  本机：      http://127.0.0.1:{a.port}")
    print(f"  手机/局域网：http://<这台机器的IP>:{a.port}")
    print(f"  工作区：    {WORK}")
    print("  按 Ctrl+C 停止")
    print()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
