"""地图编辑器 —— 数据层。

先说清楚一件事：**这个游戏的地图不是逐格存的。**
``spdata/WorldInfo`` 里只有这些参数：

======================  ==========================================================
``segmentwidth/depth``  网格多大（实测 15×15、19×19、67×19）
``materialid``          视觉主题（Summer / Cave / Citadel / Snow / Flesh …）
``nodesetids``          可以从哪几套「节点集」里抽（决定出现哪些元素）
``nodelimits``          每种节点放几个（``{MORTY:-1}``，``-1`` = 不限）
``itemparttypesplit``   物品和箱子的比例
``issegmented``         是不是分块世界
``camerabounds``        镜头边界
======================  ==========================================================

游戏**运行时按这些参数实时生成**地图。所以：

* **做不到**「像 RPG Maker 那样逐格刷图」—— 数据里根本没有格子数组
  （全 22 张 spdata 表里没有 segment / tile / map 表，也没有主题贴图）
* **做得到**把参数变成看得见的东西：网格画布、尺寸滑条、节点配额、
  主题调色板，再按参数**模拟**一份布局预览

预览是**模拟**不是真实布局 —— 游戏的生成算法（随机种子、分布规则）
在 il2cpp 里，没法精确复现。它是给你看「密度大概什么样」的。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 节点类型的中文名 + 画布上的颜色
NODE_LABEL: dict[str, tuple[str, tuple[float, float, float]]] = {
    "MORTY": ("野生莫蒂", (0.35, 0.62, 1.00)),
    "TRAINER": ("训练师", (0.95, 0.36, 0.36)),
    "NPC": ("NPC", (1.00, 0.80, 0.25)),
    "ITEM_PART_OR_CRATE": ("物品/箱子", (0.55, 0.85, 0.45)),
    "QUEST_GIVER": ("任务给予者", (0.85, 0.50, 0.95)),
    "PORTAL": ("传送门", (0.30, 0.85, 0.85)),
    "SIGN_POST": ("路牌", (0.75, 0.70, 0.55)),
    "GYM": ("道馆", (1.00, 0.55, 0.20)),
    "GACHA_OR_CRAFT": ("抽卡/合成", (0.65, 0.65, 0.90)),
}

#: 没在表里出现过的类型也给个兜底颜色
DEFAULT_NODE_COLOR = (0.6, 0.6, 0.65)

#: 主题 → 画布底色（这些是**示意色**，不是游戏里的真实贴图颜色 ——
#: 材质是引擎里的场景材质，资源包里没有）
THEME_COLOR: dict[str, tuple[float, float, float]] = {
    "Summer": (0.36, 0.55, 0.24),
    "Autumn": (0.60, 0.38, 0.16),
    "Ash": (0.32, 0.30, 0.30),
    "Alien": (0.32, 0.45, 0.40),
    "Beach": (0.68, 0.62, 0.40),
    "Blue": (0.25, 0.38, 0.58),
    "Cave": (0.26, 0.24, 0.28),
    "Citadel": (0.28, 0.32, 0.45),
    "Contaminated": (0.42, 0.45, 0.22),
    "Crystal": (0.42, 0.34, 0.58),
    "Desert": (0.66, 0.55, 0.32),
    "Flesh": (0.55, 0.26, 0.30),
    "Night": (0.18, 0.20, 0.32),
    "Snow": (0.72, 0.76, 0.80),
    "Spaceship": (0.34, 0.36, 0.42),
    "Swamp": (0.30, 0.38, 0.22),
    "TournamentLobby": (0.40, 0.34, 0.44),
}
DEFAULT_THEME_COLOR = (0.30, 0.32, 0.36)


def theme_color(name: str) -> tuple[float, float, float]:
    return THEME_COLOR.get(name, DEFAULT_THEME_COLOR)


def node_label(kind: str) -> str:
    return NODE_LABEL.get(kind, (kind, DEFAULT_NODE_COLOR))[0]


def node_color(kind: str) -> tuple[float, float, float]:
    return NODE_LABEL.get(kind, (kind, DEFAULT_NODE_COLOR))[1]


# ---------------------------------------------------------------- nodelimits


_LIMIT_RE = re.compile(r"\{([A-Z_]+):(-?\d+)\}")


def parse_limits(text: str) -> dict[str, int]:
    """``"{MORTY:-1},{NPC:3}"`` → ``{"MORTY": -1, "NPC": 3}``。"""
    out: dict[str, int] = {}
    for m in _LIMIT_RE.finditer(str(text or "")):
        out[m.group(1)] = int(m.group(2))
    return out


def format_limits(limits: dict[str, int]) -> str:
    """写回游戏的格式。顺序按 NODE_LABEL 来，新类型排后面。"""
    keys = [k for k in NODE_LABEL if k in limits]
    keys += [k for k in limits if k not in NODE_LABEL]
    return ",".join(f"{{{k}:{int(limits[k])}}}" for k in keys)


def limit_display(v: int) -> str:
    return "不限" if v < 0 else str(v)


def total_nodes(limits: dict[str, int]) -> int:
    return sum(v for v in limits.values() if v > 0)


# ---------------------------------------------------------------- 布局模拟


def simulate(world_id: str, w: int, h: int, limits: dict[str, int],
             *, margin: int = 1) -> list[dict]:
    """按参数**模拟**一份布局，纯粹给眼睛看。

    不是真实布局 —— 游戏的生成算法在 il2cpp 里，没法精确复现。
    这里用 ``world_id`` 当种子做确定性放置，所以同一个世界每次画出来一样。

    规则（尽量贴近常识）：
    * 留一圈边（``margin``），和游戏里「边缘不出节点」的感觉一致
    * 每种类型按配额铺开，超出可用格子的就铺满为止
    * ``-1``（不限）不铺 —— 那种世界是随机撒的，铺出来反而误导
    """
    import random

    if w <= 0 or h <= 0:
        return []
    rng = random.Random(f"{world_id}:{w}x{h}")
    cells = [(x, y) for y in range(margin, max(margin, h - margin))
             for x in range(margin, max(margin, w - margin))]
    if not cells:
        cells = [(x, y) for y in range(h) for x in range(w)]
    rng.shuffle(cells)

    out: list[dict] = []
    i = 0
    for kind, n in limits.items():
        if n <= 0:
            continue
        for _ in range(n):
            if i >= len(cells):
                break
            x, y = cells[i]
            i += 1
            out.append({"kind": kind, "x": x, "y": y})
    return out


def from_row(row: dict) -> dict:
    """把 WorldInfo 的一行整理成编辑用的结构。"""
    def num(k, d=0):
        try:
            return int(float(row.get(k, d) or d))
        except (TypeError, ValueError):
            return d

    return {
        "id": row.get("id", ""),
        "w": num("segmentwidth"),
        "h": num("segmentdepth"),
        "theme": str(row.get("materialid") or ""),
        "nodesets": [s for s in str(row.get("nodesetids") or "").split(",") if s],
        "limits": parse_limits(row.get("nodelimits") or ""),
        "split": str(row.get("itemparttypesplit") or "0.5"),
        "segmented": str(row.get("issegmented", "")).upper() == "TRUE",
        "portal": str(row.get("isdimensionportal", "")).upper() == "TRUE",
        "cambounds": str(row.get("camerabounds") or ""),
    }


def to_row_patch(state: dict) -> dict:
    """把编辑状态转成要写回 WorldInfo 的字段。"""
    return {
        "segmentwidth": str(state.get("w", 0)),
        "segmentdepth": str(state.get("h", 0)),
        "materialid": str(state.get("theme") or ""),
        "nodesetids": ",".join(state.get("nodesets") or []),
        "nodelimits": format_limits(state.get("limits") or {}),
        "itemparttypesplit": str(state.get("split") or "0.5"),
    }


def all_themes(worlds: list[dict]) -> list[str]:
    """所有出现过的主题（拿来当调色板）。"""
    seen = {w.get("theme") or "" for w in worlds}
    seen.discard("")
    return sorted(seen)


def all_nodesets(worlds: list[dict]) -> list[str]:
    out: set[str] = set()
    for w in worlds:
        out.update(w.get("nodesets") or [])
    return sorted(out)
