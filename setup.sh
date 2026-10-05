#!/usr/bin/env bash
# 口蘑剧情工坊 · 建虚拟环境并装依赖
set -u
cd "$(dirname "$0")" || exit 1

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "  没找到 python3，先装 Python 3.10+"; exit 1; }

echo
echo "  口蘑剧情工坊 · 环境准备"
echo "  ────────────────────────────────────────"
echo "  使用解释器：$("$PY" -c 'import sys;print(sys.version.split()[0], "(" + sys.executable + ")")')"

echo
echo "  [1/3] 创建 .venv"
[ -d .venv ] || "$PY" -m venv .venv || { echo "  建虚拟环境失败"; exit 1; }
VPY=".venv/bin/python"
[ -x "$VPY" ] || VPY=".venv/Scripts/python.exe"

echo "  [2/3] 安装依赖（第一次会下载约 100MB）"
"$VPY" -m pip install -q --upgrade pip
"$VPY" -m pip install -q -r requirements.txt || {
  echo "  依赖装失败。手动试试： $VPY -m pip install -r requirements.txt"; exit 1; }

echo "  [3/3] 环境自检"
"$VPY" - <<'PYEOF'
import sys
sys.path.insert(0, ".")
try:
    import imgui_bundle, UnityPy, PIL, numpy  # noqa: F401
    from pm_storykit import story, session  # noqa: F401
except Exception as exc:  # noqa: BLE001
    print(f"  ✗ 自检没过：{type(exc).__name__}: {exc}")
    raise SystemExit(1)
print("  ✓ 依赖齐全，pm_storykit 能导入")
PYEOF
[ $? -ne 0 ] && exit 1

echo
echo "  完成。启动方式："
echo "      ./启动.command       macOS 双击即可"
echo "      bash 启动.sh         Linux"
echo "      启动.bat             Windows"
echo "  或直接： $VPY app/main.py"
echo "  命令行： $VPY tools/cli.py --help"
echo
