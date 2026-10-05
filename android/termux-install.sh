#!/data/data/com.termux/files/usr/bin/bash
# 口蘑剧情工坊 · Android (Termux) 安装
#
# 手机端跑的是**网页版**：后端 Python 装在 Termux 里，界面用手机浏览器打开
# （可以「添加到主屏幕」，装完跟 App 一样）。
#
# 用法：
#   pkg install -y git
#   git clone <本项目> && cd pm-storykit
#   bash android/termux-install.sh
set -u
cd "$(dirname "$0")/.." || exit 1

step(){ printf '\n\033[1;34m==> %s\033[0m\n' "$1"; }
ok(){   printf '    \033[32m✓\033[0m %s\n' "$1"; }
bad(){  printf '    \033[33m!\033[0m %s\n' "$1"; }

echo
echo "  口蘑剧情工坊 · Android/Termux 安装"
echo "  ────────────────────────────────────────"

step "1/3 安装系统包"
pkg update -y >/dev/null 2>&1 || bad "pkg update 有警告，继续"
# Pillow / lz4 / brotli 走 Termux 仓库的预编译包，比 pip 现场编译快得多
pkg install -y python python-pip python-pillow libjpeg-turbo libpng zlib \
    lz4 brotli >/dev/null 2>&1 || bad "部分系统包没装上，继续试试 pip"
ok "系统包完成"

step "2/3 安装 Python 依赖（只装网页版要的，不装 imgui/numpy）"
if [ ! -d .venv ]; then
  python3 -m venv .venv 2>/dev/null || bad "建虚拟环境失败，改用系统 Python"
fi
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" -m pip install -q --upgrade pip 2>/dev/null
"$PY" -m pip install -q -r requirements-web.txt || {
  bad "有些包装不上，试着手动： $PY -m pip install -r requirements-web.txt"; }
ok "依赖完成"

step "3/3 自检"
"$PY" - <<'PYEOF'
import sys
sys.path.insert(0, ".")
try:
    import UnityPy, PIL  # noqa: F401
    from pm_storykit import story, session, export  # noqa: F401
except Exception as exc:  # noqa: BLE001
    print(f"    ✗ 自检没过：{type(exc).__name__}: {exc}")
    raise SystemExit(1)
print("    ✓ 依赖齐全，pm_storykit 能导入")
PYEOF
[ $? -ne 0 ] && exit 1

echo
echo "  装好了。启动："
echo "      bash android/termux-run.sh"
echo
echo "  然后手机浏览器打开它打印的地址，Chrome 菜单里可以「添加到主屏幕」。"
echo
