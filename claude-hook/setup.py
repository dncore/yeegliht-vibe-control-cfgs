#!/usr/bin/env python3
"""
Yeelight Vibe Control — Claude Code 版安装向导
================================================
一键配置：自动发现灯泡 → 保存配置 → 写入 Claude Code hooks

用法: python setup.py
"""

import json
import os
import sys
import socket
import time
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

SCRIPT_DIR = Path(__file__).parent.resolve()
BULBS_FILE = SCRIPT_DIR / "bulbs.json"

# ═══════════════════ 帮助函数 ═══════════════════

def load_bulbs():
    """加载灯泡配置"""
    try:
        if BULBS_FILE.exists():
            return json.loads(BULBS_FILE.read_text("utf-8"))
    except Exception:
        pass
    return {"bulbs": []}

def save_bulbs(cfg):
    """保存灯泡配置"""
    BULBS_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8"
    )
    print(f"  ✓ 配置已保存到 {BULBS_FILE}")

# ═══════════════════ 智能子网发现 ═══════════════════

# 常见虚拟网卡前缀（VirtualBox, Docker, Hyper-V, VPN 等）
_SKIP_PREFIXES = {
    "192.168.56.",   # VirtualBox Host-Only
    "192.168.99.",   # Docker Machine
    "10.0.2.",       # VirtualBox NAT
    "10.0.3.",       # QEMU
    "172.",          # Docker bridge
}

def get_primary_subnet():
    """
    通过默认路由找到本机主要局域网网段。
    优先用系统路由表，回退用本机 IP 过滤虚拟网卡。
    """
    # 方法1: 读系统路由表
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["route", "print", "0.0.0.0"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0] == "0.0.0.0":
                    gw = parts[2]
                    if any(gw.startswith(p) for p in ("192.168.", "10.")):
                        return gw.rsplit(".", 1)[0] + "."
        else:
            # Linux / macOS
            result = subprocess.run(
                ["ip", "route", "show", "default"],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if "default" in line and "via" in line:
                    parts = line.split()
                    for p in parts:
                        if any(p.startswith(x) for x in ("192.168.", "10.")):
                            return p.rsplit(".", 1)[0] + "."
    except Exception:
        pass

    # 方法2: 从本机 IP 推断，过滤虚拟网卡
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if ip.startswith("192.168.") or ip.startswith("10."):
                if any(ip.startswith(s) for s in _SKIP_PREFIXES):
                    continue
                return ip.rsplit(".", 1)[0] + "."
    except Exception:
        pass

    return None


def scan_lan():
    """
    扫描局域网内 Yeelight 设备。
    优先 SSDP 多播 (秒级)，回退 TCP 端口扫描 (仅扫主网段)。
    """
    print("\n  🔍 正在发现 Yeelight 设备...")

    # 方法1: SSDP 多播发现（最快，几秒内返回）
    try:
        from yeelight import discover_bulbs
        bulbs = discover_bulbs(timeout=3)
        if bulbs:
            print(f"  ✓ SSDP 协议发现 {len(bulbs)} 个设备")
            result = []
            for b in bulbs:
                result.append({
                    "ip": b.get("ip", ""),
                    "name": b.get("name", f"Yeelight-{b.get('ip', '??')}"),
                    "model": b.get("model", "unknown"),
                })
            return result
    except ImportError:
        print("  ⚠ yeelight 包未安装，跳过 SSDP 发现")
    except Exception as e:
        print(f"  ⚠ SSDP 发现失败: {e}")

    # 方法2: TCP 端口 55443 扫描（只扫主网段，约 30 秒）
    subnet = get_primary_subnet()
    if not subnet:
        print("  ⚠ 无法确定局域网网段，请手动输入灯泡 IP")
        return []

    print(f"  ⚡ 扫描子网 {subnet}0/24 端口 55443 ...")
    print(f"     (约 30 秒)")

    def probe(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.1)
            s.connect((ip, 55443))
            s.close()
            return {"ip": ip, "name": f"Yeelight-{ip}", "model": "unknown"}
        except Exception:
            return None

    targets = [f"{subnet}{h}" for h in range(1, 255)]
    result = []
    done = 0
    last_reported = 0

    with ThreadPoolExecutor(max_workers=100) as pool:
        futures = {pool.submit(probe, t): t for t in targets}
        for future in as_completed(futures):
            done += 1
            r = future.result()
            if r:
                result.append(r)
                print(f"    ✓ 发现: {r['ip']}")
            # 每 50 个报告一次进度
            if done - last_reported >= 50:
                pct = int(done / len(targets) * 100)
                print(f"    进度: {pct}%", end="\r")
                last_reported = done

    return result


# ═══════════════════ 灯泡验证 ═══════════════════

def validate_bulb(ip, timeout=4):
    """
    快速验证 IP 是否是真实可达的 Yeelight 灯泡。
    只做轻量属性查询，不改变灯光状态。
    """
    try:
        from yeelight import Bulb
        b = Bulb(ip, auto_on=False, effect="sudden")
        # get_properties 会发起完整的命令交互，能确认是真实 Yeelight
        b.get_properties()
        return True
    except Exception:
        return False


# ═══════════════════ Claude Code 设置合并 ═══════════════════

def get_claude_settings_path():
    """返回 Claude Code 全局设置文件路径"""
    return Path.home() / ".claude" / "settings.json"


def generate_hooks_config():
    """
    生成 hooks 配置块，自动使用当前脚本的绝对路径。
    在 JSON 中使用正斜杠以兼容所有平台。
    """
    hooks_path = (SCRIPT_DIR / "hooks.py").as_posix()
    return {
        "UserPromptSubmit": [{
            "hooks": [{
                "type": "command",
                "command": f'python "{hooks_path}" user_prompt'
            }]
        }],
        "PreToolUse": [{
            "hooks": [{
                "type": "command",
                "command": f'python "{hooks_path}" pre_tool'
            }]
        }],
        "PostToolUse": [{
            "hooks": [{
                "type": "command",
                "command": f'python "{hooks_path}" post_tool'
            }]
        }],
        "Stop": [{
            "hooks": [{
                "type": "command",
                "command": f'python "{hooks_path}" stop'
            }]
        }],
        "SubagentStop": [{
            "hooks": [{
                "type": "command",
                "command": f'python "{hooks_path}" subagent_stop'
            }]
        }],
        "Notification": [{
            "hooks": [{
                "type": "command",
                "command": f'python "{hooks_path}" notification'
            }]
        }],
    }


def merge_claude_settings(dry_run=False):
    """
    将 hooks 配置合并写入 ~/.claude/settings.json。
    保留已有配置，只更新 hooks 字段。
    返回 (settings_path, is_new)。
    """
    settings_path = get_claude_settings_path()
    hooks_config = generate_hooks_config()

    # 读已有配置（如果存在）
    existing = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text("utf-8"))
        except json.JSONDecodeError:
            print(f"  ⚠ {settings_path} 格式错误，将创建新文件")
            existing = {}

    # 合并 hooks（不覆盖其他已有配置）
    existing["hooks"] = hooks_config

    if dry_run:
        return settings_path, existing

    # 确保目录存在并写入
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), "utf-8"
    )

    return settings_path, existing


# ═══════════════════ 手动添加 ═══════════════════

def manual_add():
    """手动输入灯泡 IP 和名称"""
    ip = input("\n  灯泡 IP 地址: ").strip()
    if not ip:
        print("  已取消")
        return None
    name = input("  灯泡名称 (可选): ").strip()
    if not name:
        name = f"Yeelight-{ip}"
    return {"id": f"bulb_{int(time.time())}", "name": name, "ip": ip}


# ═══════════════════ 交互式菜单 ═══════════════════

def interactive_menu(cfg):
    """已有的灯泡配置交互式管理（手动添加/扫描/编辑/删除）"""
    if cfg["bulbs"]:
        print(f"\n  已保存 {len(cfg['bulbs'])} 个灯泡:")
        for b in cfg["bulbs"]:
            mark = "★" if cfg.get("default") == b["id"] else " "
            print(f"    {mark} {b['name']} ({b['ip']})")

    while True:
        print()
        print("  操作:")
        print("    1. ➕ 手动添加灯泡")
        print("    2. 🔍 扫描局域网")
        if cfg["bulbs"]:
            print("    3. ✏️  设置默认灯泡")
            print("    4. 🗑  删除灯泡")
        print("    5. ✅ 完成退出")
        print()

        choice = input("  选择 [1-5]: ").strip()

        if choice == "1":
            bulb = manual_add()
            if bulb:
                cfg["bulbs"].append(bulb)
                if not cfg.get("default"):
                    cfg["default"] = bulb["id"]
                print(f"  ✓ 已添加: {bulb['name']} ({bulb['ip']})")

        elif choice == "2":
            bulbs = scan_lan()
            if not bulbs:
                print("  ⚠ 未发现任何设备。")
                print("    检查: 灯泡通电? 局域网控制已开启? 同一网络?")
                continue
            print(f"\n  发现 {len(bulbs)} 个设备:")
            for i, b in enumerate(bulbs):
                print(f"    {i+1}. {b['name']} ({b['ip']}) [{b.get('model', '?')}]")
            sel = input("\n  输入编号添加 (多个用逗号分隔, 回车添加全部): ").strip()
            indices = set()
            if sel:
                for idx_str in sel.split(","):
                    try:
                        indices.add(int(idx_str.strip()) - 1)
                    except ValueError:
                        pass
            else:
                indices = set(range(len(bulbs)))
            for idx in sorted(indices):
                if 0 <= idx < len(bulbs):
                    b = bulbs[idx]
                    bulb_id = f"bulb_{int(time.time()) + idx}"
                    cfg["bulbs"].append({
                        "id": bulb_id, "name": b["name"], "ip": b["ip"],
                    })
                    if not cfg.get("default"):
                        cfg["default"] = bulb_id
                    print(f"  ✓ 已添加: {b['name']} ({b['ip']})")

        elif choice == "3" and cfg["bulbs"]:
            print("\n  选择默认灯泡:")
            for i, b in enumerate(cfg["bulbs"]):
                print(f"    {i+1}. {b['name']} ({b['ip']})")
            sel = input("\n  输入编号: ").strip()
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(cfg["bulbs"]):
                    cfg["default"] = cfg["bulbs"][idx]["id"]
                    print(f"  ✓ 默认灯泡: {cfg['bulbs'][idx]['name']}")
            except ValueError:
                pass

        elif choice == "4" and cfg["bulbs"]:
            print("\n  选择要删除的灯泡:")
            for i, b in enumerate(cfg["bulbs"]):
                print(f"    {i+1}. {b['name']} ({b['ip']})")
            sel = input("\n  输入编号: ").strip()
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(cfg["bulbs"]):
                    removed = cfg["bulbs"][idx]
                    cfg["bulbs"].pop(idx)
                    if cfg.get("default") == removed["id"]:
                        cfg["default"] = cfg["bulbs"][0]["id"] if cfg["bulbs"] else ""
                    print(f"  ✓ 已删除: {removed['name']}")
            except ValueError:
                pass

        elif choice == "5":
            break
        else:
            print("  无效选择")

    return cfg


# ═══════════════════ 主流程 ═══════════════════

def main():
    print("=" * 55)
    print("  Yeelight Vibe Control — Claude Code 版安装向导")
    print("=" * 55)
    print()
    print("  本向导将完成:")
    print("    1. 发现局域网中的 Yeelight 灯泡")
    print("    2. 保存灯泡配置")
    print("    3. 自动写入 Claude Code hooks 配置到 ~/.claude/settings.json")
    print()
    print("  前提条件:")
    print("    • Python 3.8+ 已安装")
    print("    • pip install yeelight 已完成")
    print("    • 灯泡「局域网控制」已在 Yeelight App 中开启")
    print()

    # 前置检查: yeelight 包
    try:
        import yeelight  # noqa: F401
    except ImportError:
        print("  ❌ yeelight 包未安装！")
        print("    请运行: pip install yeelight")
        sys.exit(1)

    cfg = load_bulbs()

    # --- 已有灯泡？选择复用或重新配置 -----------------------------------
    if cfg["bulbs"]:
        print(f"  已保存 {len(cfg['bulbs'])} 个灯泡:")
        for b in cfg["bulbs"]:
            mark = "★" if cfg.get("default") == b["id"] else " "
            print(f"    {mark} {b['name']} ({b['ip']})")
        print()
        print("  选项:")
        print("    [回车] 使用已有配置 → 直接写入 Claude hooks")
        print("    [r]    重新配置灯泡（扫描/手动添加/编辑）")
        print("    [q]    退出")
        choice = input("\n  选择: ").strip().lower()
        if choice == "q":
            sys.exit(0)
        elif choice == "r":
            cfg = interactive_menu({"bulbs": [], "default": ""})
        # 否则复用已有配置，跳过灯泡配置

    # --- 无灯泡？自动扫描 -----------------------------------------------
    if not cfg["bulbs"]:
        print()
        print("  未配置灯泡 — 自动扫描网络中...")
        bulbs = scan_lan()

        if bulbs:
            print(f"\n  ✅ 发现 {len(bulbs)} 个设备:")
            for i, b in enumerate(bulbs):
                print(f"    {i + 1}. {b['name']} ({b['ip']}) [{b.get('model', '?')}]")

            sel = input(
                "\n  输入编号添加 (多个用逗号分隔, 回车=全部添加): "
            ).strip()
            indices = set()
            if sel:
                for idx_str in sel.split(","):
                    try:
                        indices.add(int(idx_str.strip()) - 1)
                    except ValueError:
                        pass
            else:
                indices = set(range(len(bulbs)))

            for idx in sorted(indices):
                if 0 <= idx < len(bulbs):
                    b = bulbs[idx]
                    bulb_id = f"bulb_{int(time.time()) + idx}"
                    cfg["bulbs"].append({
                        "id": bulb_id, "name": b["name"], "ip": b["ip"],
                    })
                    if not cfg.get("default"):
                        cfg["default"] = bulb_id
                    print(f"  ✓ 已添加: {b['name']} ({b['ip']})")
        else:
            print("\n  ⚠ 未自动发现任何灯泡。")
            print("  常见原因:")
            print("    - 灯泡「局域网控制」未在 Yeelight App 中开启")
            print("    - 灯泡与电脑不在同一局域网")
            print("    - 防火墙阻止了 SSDP/UDP 或 TCP 55443 端口")
            print()
            manual_choice = input("  是否手动输入 IP? [Y/n]: ").strip().lower()
            if manual_choice not in ("n", "no"):
                bulb = manual_add()
                if bulb:
                    cfg["bulbs"].append(bulb)
                    if not cfg.get("default"):
                        cfg["default"] = bulb["id"]
                    print(f"  ✓ 已添加: {bulb['name']} ({bulb['ip']})")

    # --- 仍然没有灯泡 → 退出 --------------------------------------------
    if not cfg["bulbs"]:
        print("\n  ❌ 未配置任何灯泡，无法继续。")
        sys.exit(1)

    # --- 验证灯泡连通性 -------------------------------------------------
    print("\n  🔌 验证灯泡连通性...")
    default_bulb = next(
        (b for b in cfg["bulbs"] if b["id"] == cfg.get("default")),
        cfg["bulbs"][0]
    )
    if validate_bulb(default_bulb["ip"]):
        print(f"  ✓ {default_bulb['name']} ({default_bulb['ip']}) 连通正常")
    else:
        print(f"  ⚠ {default_bulb['name']} ({default_bulb['ip']}) 无法连接")
        print("    请确认: 灯泡已通电 | 局域网控制已开启 | IP 地址正确")
        print("    跳过连通性检查，仍会写入 hooks 配置...")

    save_bulbs(cfg)

    # --- 写入 Claude Code hooks 配置 -----------------------------------
    print()
    print("-" * 55)
    print("  📝 配置 Claude Code hooks ...")

    try:
        settings_path, final_settings = merge_claude_settings()
        print(f"  ✓ hooks 已写入 {settings_path}")
        print(f"    共配置 6 个事件钩子:")
        print(f"      • UserPromptSubmit  → 🧠 思考中")
        print(f"      • PreToolUse        → 🟡 等授权 / 🛠 工具状态")
        print(f"      • PostToolUse       → ✅ 成功 / 🔴 错误")
        print(f"      • Stop              → 💤 恢复待命")
        print(f"      • SubagentStop      → 🧠 子任务完成")
        print(f"      • Notification      → 🔄 保持活跃")
    except Exception as e:
        print(f"  ⚠ 自动写入失败: {e}")
        hooks_path = (SCRIPT_DIR / "hooks.py").as_posix()
        print()
        print("  请手动将以下 JSON 添加到 ~/.claude/settings.json:")
        print()
        print(f'  "hooks": {{')
        print(f'    "UserPromptSubmit": [{{')
        print(f'      "hooks": [{{"type": "command", "command": "python \\"{hooks_path}\\" user_prompt"}}]')
        print(f'    }}],')
        print(f'    "PreToolUse": [{{')
        print(f'      "hooks": [{{"type": "command", "command": "python \\"{hooks_path}\\" pre_tool"}}]')
        print(f'    }}],')
        print(f'    "PostToolUse": [{{')
        print(f'      "hooks": [{{"type": "command", "command": "python \\"{hooks_path}\\" post_tool"}}]')
        print(f'    }}],')
        print(f'    "Stop": [{{')
        print(f'      "hooks": [{{"type": "command", "command": "python \\"{hooks_path}\\" stop"}}]')
        print(f'    }}],')
        print(f'    "SubagentStop": [{{')
        print(f'      "hooks": [{{"type": "command", "command": "python \\"{hooks_path}\\" subagent_stop"}}]')
        print(f'    }}],')
        print(f'    "Notification": [{{')
        print(f'      "hooks": [{{"type": "command", "command": "python \\"{hooks_path}\\" notification"}}]')
        print(f'    }}]')
        print(f'  }}')

    # --- 完成 ----------------------------------------------------------
    print()
    print("=" * 55)
    print("  ✅ 安装完成！")
    print()
    print("  下一步:")
    print("    1. ⚠️  重启 Claude Code 使 hooks 生效")
    print("    2. 测试灯光: ")
    print(f"       cd {SCRIPT_DIR}")
    print("       python hooks.py direct thinking")
    print("    3. 启动新 Claude Code 会话 — 灯泡会自动响应！")
    print("=" * 55)


if __name__ == "__main__":
    main()
