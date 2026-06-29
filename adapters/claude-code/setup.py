#!/usr/bin/env python3
"""
Yeelight Vibe Bridge — Claude Code 适配器安装
==============================================
前提: 已安装 bridge 公共核心 (python bridge/setup.py)

用法: python setup.py
"""

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BRIDGE_DIR = Path.home() / ".yeelight-vibe-bridge"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


def merge_hooks(existing_hooks, new_hooks):
    """Merge new hook matchers into existing hooks dict. Preserves non-yeelight hooks."""
    merged = dict(existing_hooks)
    for event, matchers in new_hooks.items():
        if event not in merged:
            merged[event] = []
        merged[event].extend(matchers)
    return merged


def main():
    print("=" * 55)
    print("  Yeelight Vibe Bridge — Claude Code 适配器安装")
    print("=" * 55)
    print()
    print(f"  Bridge 目录: {BRIDGE_DIR}")
    print(f"  hooks 配置:  {CLAUDE_SETTINGS}")
    print()

    # 检查 bridge 是否已安装
    if not (BRIDGE_DIR / "yeelight_relay.py").exists():
        print("  ❌ Bridge 公共核心未安装！")
        print("    请先运行: python bridge/setup.py")
        print("    或: cd bridge && python setup.py")
        sys.exit(1)

    # 安装 hooks.py 到 bridge 目录
    src_hooks = SCRIPT_DIR / "hooks.py"
    dst_hooks = BRIDGE_DIR / "hooks.py"
    dst_hooks.write_bytes(src_hooks.read_bytes())
    print(f"  ✓ hooks.py → {dst_hooks}")

    # 生成 hooks 配置
    hooks_path = dst_hooks.as_posix()
    python = sys.executable or "python3"
    hooks_config = {
        "UserPromptSubmit": [{
            "hooks": [{"type": "command", "command": f'{python} "{hooks_path}" user_prompt'}]
        }],
        "PreToolUse": [{
            "hooks": [{"type": "command", "command": f'{python} "{hooks_path}" pre_tool'}]
        }],
        "PostToolUse": [{
            "hooks": [{"type": "command", "command": f'{python} "{hooks_path}" post_tool'}]
        }],
        "Stop": [{
            "hooks": [{"type": "command", "command": f'{python} "{hooks_path}" stop'}]
        }],
        "SubagentStop": [{
            "hooks": [{"type": "command", "command": f'{python} "{hooks_path}" subagent_stop'}]
        }],
        "Notification": [{
            "hooks": [{"type": "command", "command": f'{python} "{hooks_path}" notification'}]
        }],
    }

    # 读取现有 settings.json
    existing = {}
    if CLAUDE_SETTINGS.exists():
        try:
            existing = json.loads(CLAUDE_SETTINGS.read_text("utf-8"))
        except json.JSONDecodeError:
            print(f"  ⚠ {CLAUDE_SETTINGS} 格式错误，将创建新文件")

    # 合并 hooks（保留已有的非 yeelight hooks）
    existing["hooks"] = merge_hooks(existing.get("hooks", {}), hooks_config)

    # LAN 模式检测：读取当前环境变量
    relay_url = os.environ.get("YEELIGHT_RELAY_URL", "")
    api_key = os.environ.get("YEELIGHT_API_KEY", "")

    if relay_url:
        print()
        print(f"  🌐 检测到 LAN 模式: YEELIGHT_RELAY_URL={relay_url}")
        existing.setdefault("env", {})
        existing["env"]["YEELIGHT_RELAY_URL"] = relay_url
        if api_key:
            existing["env"]["YEELIGHT_API_KEY"] = api_key
            print(f"  🔑 API_KEY: {'*' * 8}（已写入）")
        print(f"  💡 环境变量已写入 settings.json 的 env 段")
    else:
        print()
        print(f"  🏠 本地模式（默认连接 127.0.0.1:9877）")
        print(f"  💡 LAN 模式: 先 export YEELIGHT_RELAY_URL + YEELIGHT_API_KEY，再运行 setup.py")

    # 写入 settings.json
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), "utf-8"
    )

    print()
    print(f"  ✓ hooks 配置已合并到 {CLAUDE_SETTINGS}")
    print(f"    共 6 个 hook 事件:")
    print(f"      UserPromptSubmit → 🧠 thinking")
    print(f"      PreToolUse       → 🟡 waiting / 工具状态")
    print(f"      PostToolUse      → ✅ thinking / 🔴 error")
    print(f"      Stop             → 🟢 success")
    print(f"      SubagentStop     → 🧠 thinking")
    print(f"      Notification     → —（维持 relay）")
    print()
    print("=" * 55)
    print("  ✅ Claude Code 适配器安装完成！")
    print()
    print("  ⚠️  重启 Claude Code 使 hooks 生效")
    print("=" * 55)


if __name__ == "__main__":
    main()
