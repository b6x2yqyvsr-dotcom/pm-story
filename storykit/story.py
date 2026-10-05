"""单人剧情编辑器 —— 数据层。

游戏把单机剧情拆在**两个地方**，改的时候两边都要动：

====================  ==========================================  ==========================
内容                  数据表（``spdata``）                        文本（``text/<语言>``）
====================  ==========================================  ==========================
剧情任务              ``QuestInfo``                                ``Quest``
任务给予者 / NPC      ``NPCInfo``                                  ``NPC``
对战训练师            ``TrainerInfo``（队伍 + 奖励）                ``Trainer``（战前/战后对白）
我方皮肤              ``PlayerAvatarInfo``                         ``PlayerAvatar``
地图                  ``WorldInfo``                                ``Dimensions``
传送门 / 场景互动     ``InteractionInfo``                          ``Interactions``
路牌                  ``SignPostInfo``                             ``SignPost``
锦标赛对白            ``TournamentDialogueInfo``                   ``TournamentDialogue``
====================  ==========================================  ==========================

**只改一边没用**：把 ``QuestInfo`` 的奖励改了但 ``text/Quest`` 的对白没改，
游戏里就是「对白说给你三个芯片，实际给了一个」这种错位。

实测（加强版）：
- 剧情任务 **21** 个，每个有 4 段对白（接取前 / 拒绝 / 接受 / 完成）+ 描述 + 给予者
- 对战训练师 **57** 个，每个有 3 段战前对白 + 1 段战后对白，队伍写成 ``"MortyA:3,MortyB:5"``
- NPC **72** 个，我方皮肤 **202** 个，地图 **18** 张
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .session import Session

#: 支持编辑的语言（实测 11 种）
LANGS = ["ZH_CN", "ZH_TW", "EN", "JP", "KO", "DE", "ES", "FR", "IT", "PT_BR", "RU"]

LANG_LABEL = {
    "ZH_CN": "简体中文", "ZH_TW": "繁体中文", "EN": "英语", "JP": "日语",
    "KO": "韩语", "DE": "德语", "ES": "西班牙语", "FR": "法语",
    "IT": "意大利语", "PT_BR": "葡语(巴西)", "RU": "俄语",
}


# ---------------------------------------------------------------- 各段定义


@dataclass
class TextSection:
    """``text/<语言>`` 里的一个段，以及它对应的中文说明。"""

    key: str                     # 段名，例如 "Quest"
    label: str                   # 中文名
    fields: list[tuple[str, str]]  # (字段名, 中文名)
    table: str = ""              # 对应的 spdata 表（没有就空）


SECTIONS = [
    TextSection("Quest", "剧情任务", [
        ("name", "任务名"),
        ("givername", "给予者名字"),
        ("description", "任务描述"),
        ("activedialogue", "进行中对白"),
        ("rejectdialogue", "交不齐时的对白"),
        ("acceptdialogue", "完成时的对白"),
        ("completedialogue", "交付后的对白"),
    ], table="QuestInfo"),
    TextSection("Trainer", "对战训练师", [
        ("name", "名字"),
        ("dialogueprebattle1", "战前对白 1"),
        ("dialogueprebattle2", "战前对白 2"),
        ("dialogueprebattle3", "战前对白 3"),
        ("dialoguepostbattle", "战后对白"),
    ], table="TrainerInfo"),
    TextSection("NPC", "NPC 对白", [
        ("name", "名字"),
        ("dialogue", "对白"),
    ], table="NPCInfo"),
    TextSection("PlayerAvatar", "我方皮肤", [
        ("name", "显示名"),
    ], table="PlayerAvatarInfo"),
    TextSection("Dimensions", "地图名", [
        ("label", "显示名"),
    ], table="WorldInfo"),
    TextSection("Interactions", "场景互动", [
        ("name", "名字"),
        ("dialogue", "对白"),
    ], table="InteractionInfo"),
    TextSection("SignPost", "路牌提示", [
        ("dialogue", "提示文字"),
    ], table="SignPostInfo"),
    TextSection("TournamentDialogue", "锦标赛对白", [
        ("name", "说话人"),
        ("dialogue", "对白"),
    ], table="TournamentDialogueInfo"),
]

SECTION_BY_KEY = {s.key: s for s in SECTIONS}

#: 新手教程的文本都在 ``TextDefs`` 里（那个段有 1295 个键，绝大多数和教程无关，
#: 所以按前缀挑出来分组）。实测结构：
#:
#: * ``WORLD_DIALOGUE_TUTORIAL_PHASE_1..5`` —— **主线教程对白**，5 个阶段 18 段
#:   （阶段 3/4 里还有 ``_BABY`` / ``_PARAMERTIZED`` 这种分支变体）
#: * ``RAID_TUTORIAL_*`` —— 突袭教程 6 段
#: * ``SWITCH_MODE_TUTORIAL_*`` —— 战役/多人切换教程 4 段
TUTORIAL_GROUPS: list[tuple[str, str, str]] = [
    ("world", "主线教程对白", r"^WORLD_DIALOGUE_TUTORIAL_PHASE_(\d+)"),
    ("raid", "突袭教程", r"^RAID_TUTORIAL"),
    ("switch", "多人模式教程", r"^SWITCH_MODE_TUTORIAL"),
    ("storage", "仓库引导", r"^FTUE_QUEST_"),
    ("dim", "次元新手引导", r"^MP_DIMENSION_FTUE|^[A-Z]+_DIMENSION_FTUE"),
    ("shiny", "闪光药水引导", r"^SHINYPOTION_FTUE"),
]

#: 教程用到的那几张表/条目（除文本之外的）
TUTORIAL_TABLES = [
    ("SignPostInfo", "SignPost", "教程路牌", r"^SignPostTutorial"),
    ("TrainerInfo", "Trainer", "教程训练师", r"^TrainerTutorial"),
    ("WorldInfo", "Dimensions", "教程世界", r"^Tutorial$"),
    ("InteractionInfo", "Interactions", "教程入口", r"^Tutorial"),
]

#: 数据表里的字段中文名
TABLE_FIELD_LABEL = {
    "QuestInfo": {
        "id": "任务 ID", "badgereq": "徽章需求", "completereq": "完成前置",
        "giverassetid": "给予者形象", "wanderer": "是否游荡",
        "solutionids": "需要的物品", "content": "完成奖励",
    },
    "NPCInfo": {
        "id": "NPC ID", "assetid": "形象", "randomworldid": "随机世界",
        "wanderer": "是否游荡",
    },
    "TrainerInfo": {
        "id": "训练师 ID", "assetid": "形象", "type": "类型",
        "morties": "出场队伍", "items": "携带道具", "content": "战斗奖励",
    },
    "PlayerAvatarInfo": {
        "id": "皮肤 ID", "assetid": "形象", "category": "分类",
        "cost": "价格", "currency": "货币", "councilmemberreq": "议会等级需求",
        "displayorder": "排序", "includeingacha": "能否抽到",
    },
    "WorldInfo": {
        "id": "世界 ID", "segmentid": "区块 ID", "nodesetids": "节点集",
        "issegmented": "是否分块", "isdimensionportal": "是否传送门维度",
        "materialid": "材质主题", "segmentwidth": "宽度", "segmentdepth": "深度",
        "camerabounds": "镜头边界", "nodelimits": "节点上限", "itemparttypesplit": "物品/箱子比例",
    },
    "InteractionInfo": {
        "id": "互动 ID", "assetid": "形象", "interactiontype": "互动类型",
        "transitiondirection": "过渡方向", "transitionentrance": "入口",
    },
    "SignPostInfo": {
        "id": "路牌 ID", "israndompool": "随机池", "badgereq": "徽章需求",
    },
    "TournamentDialogueInfo": {
        "id": "对白 ID",
    },
}


def field_label(table: str, name: str) -> str:
    return (TABLE_FIELD_LABEL.get(table) or {}).get(name, name)


# ---------------------------------------------------------------- 读写


def _read_json(sess: Session, bundle: str, asset: str):
    try:
        b = sess.bundle(bundle, eager=True)
    except Exception:  # noqa: BLE001
        return None, None
    if b is None or not b.ok:
        return None, None
    e = next((a for a in b.assets if a.name == asset and a.type == "TextAsset"), None)
    if e is None:
        return None, None
    try:
        return b, json.loads(b.preview_text(e))
    except Exception:  # noqa: BLE001
        return None, None


def read_texts(sess: Session, lang: str) -> dict[str, dict]:
    """读某个语言的**全部**剧情段。"""
    _, data = _read_json(sess, "text", lang)
    return data if isinstance(data, dict) else {}


def read_table(sess: Session, table: str) -> dict:
    """读 spdata 里的一张剧情表。"""
    _, data = _read_json(sess, "spdata", table)
    return data if isinstance(data, dict) else {}


def list_ids(sess: Session, section_key: str) -> list[str]:
    sec = SECTION_BY_KEY.get(section_key)
    if sec is None:
        return []
    if sec.table:
        return sorted(read_table(sess, sec.table))
    texts = read_texts(sess, "ZH_CN")
    return sorted(texts.get(section_key) or {})


# ---------------------------------------------------------------- 概览


@dataclass
class StoryOverview:
    """整个单人剧情的一览。"""

    quests: list[dict] = field(default_factory=list)
    trainers: list[dict] = field(default_factory=list)
    npcs: list[dict] = field(default_factory=list)
    avatars: list[dict] = field(default_factory=list)
    worlds: list[dict] = field(default_factory=list)
    interactions: list[dict] = field(default_factory=list)
    signs: list[dict] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {
            "任务": len(self.quests), "训练师": len(self.trainers),
            "NPC": len(self.npcs), "皮肤": len(self.avatars),
            "地图": len(self.worlds),
        }


def overview(sess: Session, lang: str = "ZH_CN") -> StoryOverview:
    """把剧情相关的几张表和文本合成一份可读的清单。"""
    tx = read_texts(sess, lang)
    ov = StoryOverview()

    def sec(key: str) -> dict:
        return tx.get(key) or {}

    for qid, row in sorted(read_table(sess, "QuestInfo").items()):
        t = sec("Quest").get(qid) or {}
        row = row if isinstance(row, dict) else {}
        ov.quests.append({
            "id": qid,
            "name": t.get("name") or qid,
            "giver": t.get("givername") or "",
            "giver_asset": row.get("giverassetid") or "",
            "badge": row.get("badgereq"),
            "needs": row.get("solutionids") or "",
            "has_text": bool(t),
        })
    for tid, row in sorted(read_table(sess, "TrainerInfo").items()):
        t = sec("Trainer").get(tid) or {}
        row = row if isinstance(row, dict) else {}
        ov.trainers.append({
            "id": tid,
            "name": t.get("name") or tid,
            "asset": row.get("assetid") or "",
            "team": row.get("morties") or "",
            "team_n": len(parse_team(row.get("morties") or "")),
        })
    for nid, row in sorted(read_table(sess, "NPCInfo").items()):
        t = sec("NPC").get(nid) or {}
        row = row if isinstance(row, dict) else {}
        ov.npcs.append({
            "id": nid, "name": t.get("name") or nid,
            "asset": row.get("assetid") or "",
            "dialogue": (t.get("dialogue") or "")[:60],
        })
    for aid, row in sorted(read_table(sess, "PlayerAvatarInfo").items()):
        t = sec("PlayerAvatar").get(aid) or {}
        row = row if isinstance(row, dict) else {}
        ov.avatars.append({
            "id": aid, "name": t.get("name") or aid,
            "asset": row.get("assetid") or "",
            "category": row.get("category") or "",
            "cost": row.get("cost"), "currency": row.get("currency") or "",
        })
    for wid, row in sorted(read_table(sess, "WorldInfo").items()):
        t = sec("Dimensions").get(wid) or {}
        row = row if isinstance(row, dict) else {}
        ov.worlds.append({
            "id": wid, "name": t.get("label") or wid,
            "material": row.get("materialid") or "",
            "w": row.get("segmentwidth"), "d": row.get("segmentdepth"),
            "segmented": str(row.get("issegmented", "")).upper() == "TRUE",
            "nodeset": row.get("nodesetids") or "",
        })
    for iid, row in sorted(read_table(sess, "InteractionInfo").items()):
        t = sec("Interactions").get(iid) or {}
        row = row if isinstance(row, dict) else {}
        ov.interactions.append({
            "id": iid, "name": t.get("name") or iid,
            "type": row.get("interactiontype") or "",
            "asset": row.get("assetid") or "",
        })
    for sid, row in sorted(read_table(sess, "SignPostInfo").items()):
        t = sec("SignPost").get(sid) or {}
        ov.signs.append({"id": sid, "text": (t.get("dialogue") or "")[:60]})
    return ov


# ---------------------------------------------------------------- 队伍


def parse_team(text: str) -> list[dict]:
    """``"MortyA:3,MortyB:5"`` → ``[{"id":"MortyA","level":3}, ...]``。"""
    out: list[dict] = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        mid, _, lv = part.partition(":")
        try:
            level = int(lv.strip() or 1)
        except ValueError:
            level = 1
        out.append({"id": mid.strip(), "level": level})
    return out


def format_team(team: list[dict]) -> str:
    return ",".join(f"{m['id']}:{int(m.get('level') or 1)}" for m in team if m.get("id"))


# ---------------------------------------------------------------- 写


def set_texts(sess: Session, section_key: str, entry_id: str, values: dict[str, str],
              langs: list[str] | None = None) -> list[str]:
    """改一条剧情文本。

    ``langs`` 指定改哪些语言；不指定就只改简中。
    想「所有语言都写同一段文字」就传全部语言。
    """
    sec = SECTION_BY_KEY.get(section_key)
    if sec is None:
        raise ValueError(f"不认识的段 {section_key!r}")
    langs = langs or ["ZH_CN"]
    done: list[str] = []
    for lang in langs:
        b, data = _read_json(sess, "text", lang)
        if b is None or not isinstance(data, dict):
            continue
        section = data.get(section_key)
        if not isinstance(section, dict):
            section = {}
            data[section_key] = section
        row = section.get(entry_id)
        if not isinstance(row, dict):
            row = {}
            section[entry_id] = row
        changed = False
        for k, v in values.items():
            if row.get(k) != v:
                row[k] = v
                changed = True
            # 段里所有条目字段结构要一致，缺的补上空串
        for f, _zh in sec.fields:
            row.setdefault(f, "")
        if changed or entry_id not in section:
            e = next((a for a in b.assets if a.name == lang), None)
            if e is not None:
                b.modify_text(e, json.dumps(data, ensure_ascii=False))
                done.append(f"{LANG_LABEL.get(lang, lang)} 已更新")
    return done


def set_table_row(sess: Session, table: str, entry_id: str, values: dict) -> str:
    """改 spdata 里某一行。"""
    b, data = _read_json(sess, "spdata", table)
    if b is None or not isinstance(data, dict):
        raise ValueError(f"读不到 {table}")
    row = data.get(entry_id)
    if not isinstance(row, dict):
        raise ValueError(f"{table} 里没有 {entry_id}")
    for k, v in values.items():
        row[k] = v
    e = next((a for a in b.assets if a.name == table), None)
    if e is None:
        raise ValueError(f"找不到资源 {table}")
    b.modify_text(e, json.dumps(data, ensure_ascii=False))
    return f"{table}/{entry_id} 已更新（{len(values)} 个字段）"


def add_entry(sess: Session, section_key: str, new_id: str, clone_from: str) -> list[str]:
    """克隆一条剧情条目（文本 + 数据表一起）。"""
    sec = SECTION_BY_KEY.get(section_key)
    if sec is None:
        raise ValueError(f"不认识的段 {section_key!r}")
    done: list[str] = []
    # 文本
    b, data = _read_json(sess, "text", "ZH_CN")
    if b is not None and isinstance(data, dict):
        section = data.get(section_key) or {}
        if clone_from in section:
            section[new_id] = dict(section[clone_from])
            data[section_key] = section
            e = next((a for a in b.assets if a.name == "ZH_CN"), None)
            if e is not None:
                b.modify_text(e, json.dumps(data, ensure_ascii=False))
                done.append(f"text/ZH_CN.{section_key} 新增 {new_id}")
    # 数据表
    if sec.table:
        b2, d2 = _read_json(sess, "spdata", sec.table)
        if b2 is not None and isinstance(d2, dict):
            if clone_from in d2:
                row = dict(d2[clone_from])
                row["id"] = new_id
                d2[new_id] = row
                e2 = next((a for a in b2.assets if a.name == sec.table), None)
                if e2 is not None:
                    b2.modify_text(e2, json.dumps(d2, ensure_ascii=False))
                    done.append(f"{sec.table} 新增 {new_id}")
    if not done:
        raise ValueError(f"没找到可克隆的 {clone_from}")
    return done


# ---------------------------------------------------------------- 校验


# ---------------------------------------------------------------- 新手教程


def _textdef_label(row) -> str:
    """``TextDefs`` 的条目字段叫 ``label``（不是 name/dialogue）。"""
    if isinstance(row, dict):
        return str(row.get("label", "") or "")
    return str(row or "")


def tutorial_texts(sess: Session, lang: str = "ZH_CN") -> list[dict]:
    """把所有教程文本按组整理出来。

    返回 ``[{key, label, stage, items:[{id, text}]}]`` —— ``stage`` 是主线教程的
    阶段号（1~5），其它组为 0。
    """
    import re

    tx = read_texts(sess, lang)
    td = tx.get("TextDefs") or {}
    out: list[dict] = []
    used: set[str] = set()
    for gkey, glabel, pattern in TUTORIAL_GROUPS:
        rx = re.compile(pattern)
        hits = [k for k in td if rx.search(k)]
        if not hits:
            continue
        used.update(hits)
        # 主线教程按阶段再分一层
        if gkey == "world":
            stages: dict[int, list[str]] = {}
            for k in hits:
                m = rx.search(k)
                n = int(m.group(1)) if m and m.groups() else 0
                stages.setdefault(n, []).append(k)
            for n in sorted(stages):
                out.append({
                    "key": f"world{n}", "label": f"阶段 {n}", "stage": n,
                    "group": glabel,
                    "items": [{"id": k, "text": _textdef_label(td[k])}
                              for k in sorted(stages[n])],
                })
        else:
            out.append({
                "key": gkey, "label": glabel, "stage": 0, "group": glabel,
                "items": [{"id": k, "text": _textdef_label(td[k])} for k in sorted(hits)],
            })
    return out


def tutorial_extras(sess: Session, lang: str = "ZH_CN") -> list[dict]:
    """教程相关的**非文本**部分：路牌、训练师、世界、入口。"""
    import re

    tx = read_texts(sess, lang)
    out: list[dict] = []
    for table, sec, label, pattern in TUTORIAL_TABLES:
        rx = re.compile(pattern)
        data = read_table(sess, table)
        hits = {k: v for k, v in data.items() if rx.search(k)}
        if not hits:
            continue
        rows = []
        for k, v in sorted(hits.items()):
            v = v if isinstance(v, dict) else {}
            t = (tx.get(sec) or {}).get(k) or {}
            item = {"id": k, "data": v, "text": t}
            if table == "TrainerInfo":
                item["team"] = parse_team(v.get("morties") or "")
            if table == "SignPostInfo":
                item["dialogue"] = t.get("dialogue", "")
            if table == "WorldInfo":
                item["size"] = f"{v.get('segmentwidth')}×{v.get('segmentdepth')}"
                item["theme"] = v.get("materialid") or ""
            rows.append(item)
        out.append({"table": table, "section": sec, "label": label, "rows": rows})
    return out


def set_textdef(sess: Session, key: str, value: str,
                langs: list[str] | None = None) -> list[str]:
    """改 ``TextDefs``（教程文本）里的一条。"""
    langs = langs or ["ZH_CN"]
    done: list[str] = []
    for lang in langs:
        b, data = _read_json(sess, "text", lang)
        if b is None or not isinstance(data, dict):
            continue
        td = data.get("TextDefs")
        if not isinstance(td, dict):
            td = {}
            data["TextDefs"] = td
        row = td.get(key)
        if isinstance(row, dict):
            if row.get("label") == value:
                continue
            row["label"] = value
        else:
            td[key] = {"label": value}
        e = next((a for a in b.assets if a.name == lang), None)
        if e is not None:
            b.modify_text(e, json.dumps(data, ensure_ascii=False))
            done.append(f"{LANG_LABEL.get(lang, lang)} 已更新")
    return done


# ---------------------------------------------------------------- 教程阵容


def tutorial_lineups(sess: Session, lang: str = "ZH_CN") -> dict:
    """新手教程的**双方阵容**和**野怪**。

    查清楚的情况
    ------------
    * **对方阵容**：``TrainerInfo`` 里两个教程训练师的 ``morties`` 字段，
      形如 ``"MortyMustache:4"`` —— **直接能改**（实测就是这两条）。
    * **野怪**：教程世界 ``Tutorial`` 的 ``nodelimits`` 里有 ``{MORTY:...}``，
      但**具体是哪只莫蒂不在任何数据表里** —— 游戏脚本挑的。
      能确定的是它从 ``preload`` 包预载的那 4 只里挑（那 4 只就是为教程准备的）：
      ``MortyBaby`` / ``MortyMustache`` / ``MortyScruffy`` / ``MortyStrayCat``。
      对白也点了名 —— 阶段 3 说「他跟我长得一模一样，就是比我脏了一点」，
      对应 ``MortyScruffy``（邋遢莫蒂）；另有 ``_BABY`` 分支对应 ``MortyBaby``。
    * **我方阵容**：教程里你抓到的那只野怪就是你的第一只莫蒂。
      所以改野怪 = 改我方阵容。想直接送莫蒂的话，
      ``QuestInfo`` 的 ``content`` 支持 ``{"reward":"MORTY","parameters":{"ids":[...]}}``。
    """
    tx = read_texts(sess, lang)
    tr = read_table(sess, "TrainerInfo")
    mt = read_table(sess, "MortyInfo")
    loc_m = (tx.get("Morty") or {})

    opponents: list[dict] = []
    for tid, row in sorted(tr.items()):
        if not tid.startswith("TrainerTutorial"):
            continue
        row = row if isinstance(row, dict) else {}
        t = (tx.get("Trainer") or {}).get(tid) or {}
        opponents.append({
            "id": tid,
            "name": t.get("name") or tid,
            "asset": row.get("assetid") or "",
            "team": parse_team(row.get("morties") or ""),
            "rewards": row.get("content") or [],
        })

    # 野怪候选：preload 里预载的那 4 只
    candidates: list[dict] = []
    for mid in ("MortyBaby", "MortyMustache", "MortyScruffy", "MortyStrayCat"):
        r = mt.get(mid)
        if not isinstance(r, dict):
            continue
        r = dict(r)
        r["id"] = mid
        # text/Morty 的条目是 {"name":...,"description":...}，别直接当字符串用
        candidates.append({
            "id": mid,
            "name": (loc_m.get(mid) or {}).get("name") or mid,
            "asset": r.get("assetid") or "",
            "number": r.get("number"), "division": r.get("division"),
            "hp": r.get("hpbase"), "atk": r.get("attackbase"),
            "row": r,
        })

    w = read_table(sess, "WorldInfo").get("Tutorial") or {}
    w = w if isinstance(w, dict) else {}
    limits = {}
    import re as _re

    for m in _re.finditer(r"\{([A-Z_]+):(-?\d+)\}", w.get("nodelimits") or ""):
        limits[m.group(1)] = int(m.group(2))

    return {
        "opponents": opponents,
        "candidates": candidates,
        "world": {
            "id": "Tutorial",
            "size": f"{w.get('segmentwidth')}×{w.get('segmentdepth')}",
            "theme": w.get("materialid") or "",
            "limits": limits,
            "morty_quota": limits.get("MORTY", 0),
        },
    }


def set_trainer_team(sess: Session, trainer_id: str, team: list[dict]) -> str:
    """改一个训练师的出场阵容。"""
    return set_table_row(sess, "TrainerInfo", trainer_id, {"morties": format_team(team)})


def validate(sess: Session, lang: str = "ZH_CN") -> list[str]:
    """体检：剧情表和文本对不对得上。"""
    issues: list[str] = []
    tx = read_texts(sess, lang)
    for sec in SECTIONS:
        if not sec.table:
            continue
        if sec.key == "Dimensions":
            continue   # 键是 MP_WORLD_TITLE_x，和 WorldInfo 的 id 不是一套
        ids = set(read_table(sess, sec.table))
        texts = set(tx.get(sec.key) or {})
        if not ids:
            continue
        miss = sorted(ids - texts)
        if miss:
            issues.append(
                f"{sec.label}：{len(miss)} 个条目在 text/{lang}.{sec.key} 里没有文本"
                f"（例如 {miss[0]}）—— 游戏里会显示成 ID")
    # 教程文本：主线五个阶段别缺段
    td = tx.get("TextDefs") or {}
    for n in range(1, 6):
        pref = f"WORLD_DIALOGUE_TUTORIAL_PHASE_{n}_TEXT_1"
        if not any(k.startswith(pref) for k in td):
            issues.append(f"新手教程：主线阶段 {n} 的第 1 段文本没了（{pref}*）—— "
                          f"游戏走到那一步会显示成 ID")

    # 训练师队伍里的莫蒂存不存在
    morties = set(read_table(sess, "MortyInfo"))
    for tid, row in read_table(sess, "TrainerInfo").items():
        row = row if isinstance(row, dict) else {}
        for m in parse_team(row.get("morties") or ""):
            if m["id"] not in morties:
                issues.append(f"训练师 {tid} 的队伍里有不存在的莫蒂 {m['id']}")
                break
    return issues
