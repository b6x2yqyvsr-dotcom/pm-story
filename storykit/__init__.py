"""口蘑剧情编辑器 · 内核

这是从 pm-modkit 里**独立出来**的单人剧情编辑器。依赖的那几个基础模块
（解包、读 bundle、改文本）一并带了进来，所以它不依赖 pm-modkit，可以单独装。

    storykit.paths     缓存目录名的编解码
    storykit.sysenv    平台探测 / 找字体 / 找构建工具
    storykit.source    来源：APK / zip / 目录 → 容器 → bundle 引用
    storykit.bundle    单个 bundle 的读写（UnityFS）
    storykit.assetops  资源的导入导出
    storykit.session   一次编辑会话（打开来源、改、出产物）
    storykit.entries   条目操作（列莫蒂等，剧情编辑器要用）
    storykit.effects   技能效果两种编码互转
    storykit.fields    字段中英文对照
    storykit.story     **单人剧情本体**：任务对白 / 训练师 / 皮肤 / 地图
"""

__version__ = "1.0.0"

from . import (  # noqa: F401
    apkbuild,
    assetops,
    bundle,
    effects,
    entries,
    fields,
    modpack,
    paths,
    session,
    source,
    story,
    sysenv,
)

__all__ = [
    "apkbuild", "assetops", "bundle", "effects", "entries", "fields",
    "modpack", "paths", "session", "source", "story", "sysenv",
    "__version__",
]
