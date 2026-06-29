#!/usr/bin/env python3
"""
Yeelight Vibe Bridge — 一键安装向导
====================================
安装公共桥接层到 ~/.yeelight-vibe-bridge/。
此步骤是所有智能体适配器的前提条件。

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
BRIDGE_DIR = Path.home() / ".yeelight-vibe-bridge"

# ═══════════════ 灯泡发现 ═══════════════

_SKIP_PREFIXES = {
    "192.168.56.", "192.168.99.", "10.0.2.", "10.0.3.", "172.",
}

def get_primary_subnet():
    try:
        if sys.platform == "win32":
            result = subprocess.run(["route", "print", "0.0.0.0"],
                                    capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 4 and parts[0] == "0.0.0.0":
                    gw = parts[2]
                    if any(gw.startswith(p) for p in ("192.168.", "10.")):
                        return gw.rsplit(".", 1)[0] + "."
        elif sys.platform == "darwin":
            # macOS: use route get default
            result = subprocess.run(["route", "-n", "get", "default"],
                                    capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if "gateway:" in line:
                    gw = line.split(":")[-1].strip()
                    if any(gw.startswith(p) for p in ("192.168.", "10.")):
                        return gw.rsplit(".", 1)[0] + "."
        else:
            # Linux: use ip route
            result = subprocess.run(["ip", "route", "show", "default"],
                                    capture_output=True, text=True, timeout=5)
            for line in result.stdout.splitlines():
                if "default" in line and "via" in line:
                    parts = line.split()
                    for p in parts:
                        if any(p.startswith(x) for x in ("192.168.", "10.")):
                            return p.rsplit(".", 1)[0] + "."
    except Exception:
        pass
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
    print("\n  🔍 正在发现 Yeelight 设备...")
    try:
        from yeelight import discover_bulbs
        bulbs = discover_bulbs(timeout=3)
        if bulbs:
            print(f"  ✓ SSDP 协议发现 {len(bulbs)} 个设备")
            return [{"ip": b.get("ip", ""), "name": b.get("name", f"Yeelight-{b.get('ip', '??')}"),
                     "model": b.get("model", "unknown")} for b in bulbs]
    except ImportError:
        print("  ⚠ yeelight 包未安装，跳过 SSDP 发现")
    except Exception as e:
        print(f"  ⚠ SSDP 发现失败: {e}")

    subnet = get_primary_subnet()
    if not subnet:
        print("  ⚠ 无法确定局域网网段")
        return []

    print(f"  ⚡ 扫描子网 {subnet}0/24 端口 55443 ...")

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
    result, done, last_reported = [], 0, 0

    with ThreadPoolExecutor(max_workers=100) as pool:
        futures = {pool.submit(probe, t): t for t in targets}
        for future in as_completed(futures):
            done += 1
            r = future.result()
            if r:
                result.append(r)
                print(f"    ✓ 发现: {r['ip']}")
            if done - last_reported >= 50:
                print(f"    进度: {int(done / len(targets) * 100)}%", end="\r")
                last_reported = done
    return result


def validate_bulb(ip, timeout=4):
    try:
        from yeelight import Bulb
        b = Bulb(ip, auto_on=False, effect="sudden")
        b.get_properties()
        return True
    except Exception:
        return False


def manual_add():
    ip = input("\n  灯泡 IP 地址: ").strip()
    if not ip:
        return None
    name = input("  灯泡名称 (可选): ").strip()
    if not name:
        name = f"Yeelight-{ip}"
    return {"id": f"bulb_{int(time.time())}", "name": name, "ip": ip}


# ═══════════════ 安装流程 ═══════════════

def install_bridge():
    """安装 bridge 文件到 ~/.yeelight-vibe-bridge/"""
    print()
    print("  📦 安装 bridge 到共享目录...")
    print(f"     目标: {BRIDGE_DIR}")
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)

    runtime_files = [
        "yeelight_relay.py",
        "yeelight_discover.py",
        "yeelight_bridge.py",
        "yeelight_cube_lite.py",
        "cube_fonts.py",
        "cube_patterns.py",
        "bulbs.json",
    ]
    for fn in runtime_files:
        src = SCRIPT_DIR / fn
        if src.exists():
            dst = BRIDGE_DIR / fn
            dst.write_bytes(src.read_bytes())
            print(f"  ✓ {fn}")

    # bulbs.json 合并
    src_bulbs = SCRIPT_DIR / "bulbs.json"
    dst_bulbs = BRIDGE_DIR / "bulbs.json"
    if src_bulbs.exists():
        try:
            src_cfg = json.loads(src_bulbs.read_text("utf-8"))
            if dst_bulbs.exists():
                dst_cfg = json.loads(dst_bulbs.read_text("utf-8"))
                dst_ips = {b["ip"] for b in dst_cfg.get("bulbs", [])}
                for b in src_cfg.get("bulbs", []):
                    if b["ip"] not in dst_ips:
                        dst_cfg.setdefault("bulbs", []).append(b)
                src_cfg = dst_cfg
            dst_bulbs.write_text(json.dumps(src_cfg, indent=2, ensure_ascii=False), "utf-8")
        except Exception:
            pass

    print(f"\n  ✅ Bridge 公共核心已安装到 {BRIDGE_DIR}")
    print(f"     此目录供所有智能体适配器共用")


# ═══════════════ 主流程 ═══════════════

def main():
    print("=" * 55)
    print("  Yeelight Vibe Bridge — 公共桥接层安装向导")
    print("=" * 55)
    print()
    print("  本向导将完成:")
    print("    1. 发现局域网中的 Yeelight 灯泡")
    print("    2. 保存灯泡配置")
    print("    3. 安装 bridge 公共核心到 ~/.yeelight-vibe-bridge/")
    print()
    print("  📁 架构说明:")
    print("    • bridge 是公共平台，所有智能体适配器共用")
    print("    • 适配器 (Claude Code / Pi Agent / ...) 可分别按需安装")
    print("    • 多 session / 跨 agent 竞态由 relay 内置优先级聚合处理")
    print()
    print("  前提条件:")
    print("    • Python 3.8+ 已安装")
    print("    • pip install yeelight 已完成")
    print("    • 灯泡「局域网控制」已在 Yeelight App 中开启")
    print()

    # 前置检查
    try:
        import yeelight  # noqa: F401
    except ImportError:
        print("  ❌ yeelight 包未安装！")
        print("    请运行: pip install yeelight")
        sys.exit(1)

    # 读取已有配置
    existing_cfg = {"bulbs": [], "default": ""}
    bulbs_file = BRIDGE_DIR / "bulbs.json"
    if bulbs_file.exists():
        try:
            existing_cfg = json.loads(bulbs_file.read_text("utf-8"))
        except Exception:
            pass

    # 已有灯泡 → 选择复用或重新配置
    if existing_cfg.get("bulbs"):
        print(f"  已保存 {len(existing_cfg['bulbs'])} 个灯泡:")
        for b in existing_cfg["bulbs"]:
            mark = "★" if existing_cfg.get("default") == b["id"] else " "
            print(f"    {mark} {b['name']} ({b['ip']})")
        print()
        print("  [回车] 使用已有配置 → 直接安装 bridge")
        print("  [r]    重新扫描/添加灯泡")
        print("  [q]    退出")
        choice = input("\n  选择: ").strip().lower()
        if choice == "q":
            sys.exit(0)
        elif choice == "r":
            existing_cfg = {"bulbs": [], "default": ""}

    # 无灯泡 → 自动扫描
    if not existing_cfg.get("bulbs"):
        print()
        print("  未配置灯泡 — 自动扫描网络中...")
        bulbs = scan_lan()

        if bulbs:
            print(f"\n  ✅ 发现 {len(bulbs)} 个设备:")
            for i, b in enumerate(bulbs):
                print(f"    {i+1}. {b['name']} ({b['ip']}) [{b.get('model', '?')}]")

            sel = input("\n  输入编号添加 (多个用逗号分隔, 回车=全部): ").strip()
            indices = set()
            if sel:
                for s in sel.split(","):
                    try:
                        indices.add(int(s.strip()) - 1)
                    except ValueError:
                        pass
            else:
                indices = set(range(len(bulbs)))

            for idx in sorted(indices):
                if 0 <= idx < len(bulbs):
                    b = bulbs[idx]
                    bulb_id = f"bulb_{int(time.time()) + idx}"
                    existing_cfg["bulbs"].append({
                        "id": bulb_id, "name": b["name"], "ip": b["ip"],
                    })
                    if not existing_cfg.get("default"):
                        existing_cfg["default"] = bulb_id
                    print(f"  ✓ 已添加: {b['name']} ({b['ip']})")
        else:
            print("\n  ⚠ 未自动发现任何灯泡。")
            print("  常见原因: 局域网控制未开启 / 不在同一网络 / 防火墙拦截")
            manual_choice = input("\n  是否手动输入 IP? [Y/n]: ").strip().lower()
            if manual_choice not in ("n", "no"):
                bulb = manual_add()
                if bulb:
                    existing_cfg["bulbs"].append(bulb)
                    if not existing_cfg.get("default"):
                        existing_cfg["default"] = bulb["id"]
                    print(f"  ✓ 已添加: {bulb['name']} ({bulb['ip']})")

    if not existing_cfg.get("bulbs"):
        print("\n  ❌ 未配置任何灯泡，无法继续。可稍后运行:")
        print(f"    python {BRIDGE_DIR / 'yeelight_bridge.py'} setup-bulbs")
        sys.exit(1)

    # 验证连通性
    print("\n  🔌 验证灯泡连通性...")
    default_bulb = next(
        (b for b in existing_cfg["bulbs"] if b["id"] == existing_cfg.get("default")),
        existing_cfg["bulbs"][0]
    )
    if validate_bulb(default_bulb["ip"]):
        print(f"  ✓ {default_bulb['name']} ({default_bulb['ip']}) 连通正常")
    else:
        print(f"  ⚠ {default_bulb['name']} ({default_bulb['ip']}) 无法连接")
        print("    跳过连通性检查，仍会安装 bridge...")

    # 保存配置
    bulbs_file.parent.mkdir(parents=True, exist_ok=True)
    bulbs_file.write_text(json.dumps(existing_cfg, indent=2, ensure_ascii=False), "utf-8")
    print(f"  ✓ 灯泡配置已保存")

    # 安装 bridge
    install_bridge()

    # 完成
    print()
    print("=" * 55)
    print("  ✅ Bridge 安装完成！")
    print()
    print("  📁 共享目录: ~/.yeelight-vibe-bridge/")
    print()
    print("  下一步 — 安装智能体适配器:")
    print("    Claude Code: cd ../adapters/claude-code && python setup.py")
    print("    Pi Agent:    复制 adapters/pi-agent/ 到 ~/.pi/agent/extensions/yeelight-vibe/")
    print()
    print("  测试 bridge:")
    print(f"    cd {BRIDGE_DIR}")
    print(f"    python yeelight_bridge.py start     # 启动 relay")
    print(f"    python yeelight_bridge.py test thinking  # 测试灯光")
    print("=" * 55)


if __name__ == "__main__":
    main()
