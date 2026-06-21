#!/usr/bin/env python3
"""
Yeelight Vibe Bridge — Claude Code 适配器安装
==============================================
前提: 已安装 bridge 公共核心 (python bridge/setup.py)

用法: python setup.py
"""

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
BRIDGE_DIR = Path.home() / ".yeelight-vibe-bridge"
CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"


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
    hooks_config = {
        "UserPromptSubmit": [{
            "hooks": [{"type": "command", "command": f'python "{hooks_path}" user_prompt'}]
        }],
        "PreToolUse": [{
            "hooks": [{"type": "command", "command": f'python "{hooks_path}" pre_tool'}]
        }],
        "PostToolUse": [{
            "hooks": [{"type": "command", "command": f'python "{hooks_path}" post_tool'}]
        }],
        "Stop": [{
            "hooks": [{"type": "command", "command": f'python "{hooks_path}" stop'}]
        }],
        "SubagentStop": [{
            "hooks": [{"type": "command", "command": f'python "{hooks_path}" subagent_stop'}]
        }],
        "Notification": [{
            "hooks": [{"type": "command", "command": f'python "{hooks_path}" notification'}]
        }],
    }

    # 合并到 ~/.claude/settings.json
    existing = {}
    if CLAUDE_SETTINGS.exists():
        try:
            existing = json.loads(CLAUDE_SETTINGS.read_text("utf-8"))
        except json.JSONDecodeError:
            print(f"  ⚠ {CLAUDE_SETTINGS} 格式错误，将创建新文件")

    existing["hooks"] = hooks_config
    CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), "utf-8"
    )

    print(f"  ✓ hooks 配置已写入 {CLAUDE_SETTINGS}")
    print(f"    共 6 个 hook 事件:")
    print(f"      UserPromptSubmit → 🧠 thinking")
    print(f"      PreToolUse       → 🟡 waiting / 工具状态")
    print(f"      PostToolUse      → ✅ thinking / 🔴 error")
    print(f"      Stop             → 🟢 success")
    print(f"      SubagentStop     → 🧠 thinking")
    print(f"      Notification     → — (维持 relay)")
    print()
    print("=" * 55)
    print("  ✅ Claude Code 适配器安装完成！")
    print()
    print("  ⚠️  重启 Claude Code 使 hooks 生效")
    print("=" * 55)


if __name__ == "__main__":
    main()
