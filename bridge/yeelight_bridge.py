#!/usr/bin/env python3
"""
Yeelight Vibe Bridge — 管理 CLI
================================
公共桥接层的统一管理入口。所有智能体适配器（Claude Code、Pi Agent 等）
共用同一个 relay 守护进程，通过 HTTP API 通信。

用法:
    python yeelight_bridge.py install             安装 bridge 到 ~/.yeelight-vibe-bridge/
    python yeelight_bridge.py start [bulb_ip]      启动 relay 守护进程
    python yeelight_bridge.py stop                 停止 relay 守护进程
    python yeelight_bridge.py status               检查 relay 状态
    python yeelight_bridge.py discover             局域网发现灯泡
    python yeelight_bridge.py setup-bulbs          交互式灯泡配置
    python yeelight_bridge.py test <state> [ip]    直接测试灯光状态
    python yeelight_bridge.py strategy <name>       切换协调策略
"""

import json
import os
import sys
import time
import signal
import subprocess
import socket
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ═══════════════ 常量 ═══════════════

SCRIPT_DIR = Path(__file__).parent.resolve()
BRIDGE_DIR = Path.home() / ".yeelight-vibe-bridge"
RELAY_SCRIPT_NAME = "yeelight_relay.py"
DISCOVER_SCRIPT_NAME = "yeelight_discover.py"
BULBS_FILE_NAME = "bulbs.json"
RELAY_PORT = 9877
RELAY_URL = f"http://127.0.0.1:{RELAY_PORT}"

# ═══════════════ 工具函数 ═══════════════

def find_python():
    """查找可用的 Python (需安装 yeelight 包)"""
    def has_yeelight(cmd):
        try:
            r = subprocess.run([cmd, "-c", "import yeelight"], capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    if has_yeelight(sys.executable):
        return sys.executable
    for cmd in ["python3", "python"]:
        if has_yeelight(cmd):
            return cmd
    fallbacks = [
        os.path.expanduser("~\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        "C:\\Python312\\python.exe",
        "/usr/bin/python3", "/usr/local/bin/python3",
    ]
    for p in fallbacks:
        if os.path.exists(p) and has_yeelight(p):
            return p
    return sys.executable

PYTHON_CMD = find_python()

def relay_request(path, data=None, timeout=3):
    """向 relay 发送 HTTP 请求"""
    url = f"{RELAY_URL}{path}"
    try:
        if data is None:
            req = Request(url, method="GET")
        else:
            body = json.dumps(data).encode()
            req = Request(url, data=body, method="POST")
            req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def is_relay_running():
    r = relay_request("/api/health", timeout=2)
    return r.get("ok", False)

def load_bulbs():
    bulbs_file = BRIDGE_DIR / BULBS_FILE_NAME
    try:
        if bulbs_file.exists():
            return json.loads(bulbs_file.read_text("utf-8"))
    except Exception:
        pass
    return {"bulbs": [], "default": ""}

def save_bulbs(cfg):
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    (BRIDGE_DIR / BULBS_FILE_NAME).write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8"
    )
    print(f"  ✓ 灯泡配置已保存到 {BRIDGE_DIR / BULBS_FILE_NAME}")

def get_default_bulb():
    cfg = load_bulbs()
    if cfg.get("default") and any(b["id"] == cfg["default"] for b in cfg["bulbs"]):
        return next(b for b in cfg["bulbs"] if b["id"] == cfg["default"])
    return cfg["bulbs"][0] if cfg["bulbs"] else None

def kill_relay_process():
    """清理已有 relay 进程"""
    pid_file = BRIDGE_DIR / "relay.pid"
    if pid_file.exists():
        try:
            saved_pid = int(pid_file.read_text().strip())
            if saved_pid:
                try:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/PID", str(saved_pid), "/F"],
                                       capture_output=True, timeout=5)
                    else:
                        os.kill(saved_pid, signal.SIGTERM)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            pid_file.unlink()
        except Exception:
            pass

    # 备用：按进程名杀
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "python.exe", "/FI", "WINDOWTITLE eq relay*"],
                capture_output=True, timeout=5
            )
    except Exception:
        pass

# ═══════════════ 命令实现 ═══════════════

def cmd_install():
    """安装 bridge 到 ~/.yeelight-vibe-bridge/"""
    print("=" * 55)
    print("  Yeelight Vibe Bridge — 公共桥接层安装")
    print("=" * 55)
    print()
    print(f"  安装目录: {BRIDGE_DIR}")
    print()

    # 复制运行文件
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
    runtime_files = [
        RELAY_SCRIPT_NAME,
        DISCOVER_SCRIPT_NAME,
        "yeelight_bridge.py",
        BULBS_FILE_NAME,
    ]
    for fn in runtime_files:
        src = SCRIPT_DIR / fn
        if src.exists():
            dst = BRIDGE_DIR / fn
            dst.write_bytes(src.read_bytes())
            print(f"  ✓ 已安装: {fn}")

    # bulbs.json 合并
    src_bulbs = SCRIPT_DIR / BULBS_FILE_NAME
    dst_bulbs = BRIDGE_DIR / BULBS_FILE_NAME
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

    print()
    print(f"  ✅ Bridge 已安装到 {BRIDGE_DIR}")
    print()
    print("  下一步:")
    print(f"    cd {BRIDGE_DIR}")
    print(f"    python yeelight_bridge.py setup-bulbs    # 配置灯泡")
    print(f"    python yeelight_bridge.py start [ip]      # 启动 relay")
    print("=" * 55)


def cmd_start(ip=None):
    """启动 relay 守护进程"""
    # 已经在运行？
    if is_relay_running():
        info = relay_request("/api/health")
        print(f"  ✓ relay 已在运行 (灯泡: {info.get('bulb_ip', '?')})")
        return

    # 确定灯泡 IP
    if not ip:
        bulb = get_default_bulb()
        if not bulb:
            print("  ❌ 未配置灯泡。请先运行: python yeelight_bridge.py setup-bulbs")
            sys.exit(1)
        ip = bulb["ip"]

    relay_script = BRIDGE_DIR / RELAY_SCRIPT_NAME
    if not relay_script.exists():
        print(f"  ❌ 未找到 relay 脚本: {relay_script}")
        print("    请先运行: python yeelight_bridge.py install")
        sys.exit(1)

    kill_relay_process()

    print(f"  启动 relay (IP={ip}, 端口={RELAY_PORT})...")
    try:
        proc = subprocess.Popen(
            [PYTHON_CMD, str(relay_script), str(RELAY_PORT), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        pid_file = BRIDGE_DIR / "relay.pid"
        pid_file.write_text(str(proc.pid))
    except Exception as e:
        print(f"  ❌ 启动失败: {e}")
        sys.exit(1)

    # 等待就绪
    for _ in range(30):
        time.sleep(0.2)
        if is_relay_running():
            print(f"  ✓ relay 已启动 (PID={proc.pid})")
            return

    print("  ⚠ relay 启动超时，请检查 Python 和 yeelight 包")


def cmd_stop():
    """停止 relay 守护进程"""
    if not is_relay_running():
        print("  relay 未在运行")
        kill_relay_process()
        return

    # 恢复灯泡日常照明
    relay_request("/api/stop")
    time.sleep(0.5)
    kill_relay_process()
    print("  ✓ relay 已停止")


def cmd_status():
    """查看 relay 状态"""
    info = relay_request("/api/status")
    health = relay_request("/api/health")

    print("=" * 45)
    print("  Yeelight Vibe Bridge 状态")
    print("=" * 45)
    print(f"  relay 运行: {'✅ 是' if info.get('ok') else '❌ 否'}")
    if info.get("ok"):
        print(f"  yeelight 包: {'✅' if health.get('yeelight_available') else '❌'}")
        print(f"  灯泡连接:   {'✅' if health.get('bulb_connected') else '❌'}")
        print(f"  灯泡 IP:    {health.get('bulb_ip', '?')}")
        print(f"  活跃会话:   {info.get('sessions', 0)}")
        print(f"  协调策略:   {info.get('strategy', '?')}")
    print("=" * 45)


def cmd_discover():
    """发现局域网灯泡"""
    # 需要 relay 运行（用于 SSDP 发现）
    if not is_relay_running():
        print("  relay 未运行，使用备用 TCP 扫描...")
        discover_script = BRIDGE_DIR / DISCOVER_SCRIPT_NAME
        if discover_script.exists():
            subprocess.run([PYTHON_CMD, str(discover_script)])
        else:
            print(f"  ❌ 未找到发现脚本: {discover_script}")
        return

    result = relay_request("/api/discover", {})
    if not result.get("ok"):
        print(f"  ❌ 发现失败: {result.get('error', '未知错误')}")
        return

    bulbs = result.get("bulbs", [])
    if not bulbs:
        print("  ⚠ 未发现任何 Yeelight 设备")
        print("    请检查: 灯泡通电? 局域网控制已开启? 同一网络?")
        return

    print(f"\n  ✅ 发现 {len(bulbs)} 个设备:")
    for i, b in enumerate(bulbs):
        print(f"    {i+1}. {b.get('name', b.get('ip'))} ({b.get('ip')}) [{b.get('model', '?')}]")


def cmd_setup_bulbs():
    """交互式灯泡配置"""
    cfg = load_bulbs()

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
            ip = input("  灯泡 IP 地址: ").strip()
            if not ip:
                continue
            name = input("  灯泡名称 (可选): ").strip()
            if not name:
                name = f"Yeelight-{ip}"
            bulb_id = f"bulb_{int(time.time())}"
            cfg["bulbs"].append({"id": bulb_id, "name": name, "ip": ip})
            if not cfg.get("default"):
                cfg["default"] = bulb_id
            print(f"  ✓ 已添加: {name} ({ip})")

        elif choice == "2":
            if not is_relay_running():
                print("  relay 未运行，使用备用 TCP 扫描...")
                discover_script = BRIDGE_DIR / DISCOVER_SCRIPT_NAME
                if discover_script.exists():
                    subprocess.run([PYTHON_CMD, str(discover_script)])
                continue

            result = relay_request("/api/discover", {})
            if not result.get("ok") or not result.get("bulbs"):
                print("  ⚠ 未发现任何设备")
                continue

            bulbs = result["bulbs"]
            print(f"\n  发现 {len(bulbs)} 个设备:")
            for i, b in enumerate(bulbs):
                print(f"    {i+1}. {b.get('name', b.get('ip'))} ({b.get('ip')})")

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
                    cfg["bulbs"].append({"id": bulb_id, "name": b.get("name", f"Yeelight-{b['ip']}"), "ip": b["ip"]})
                    if not cfg.get("default"):
                        cfg["default"] = bulb_id
                    print(f"  ✓ 已添加: {b.get('name', b['ip'])}")

        elif choice == "3" and cfg["bulbs"]:
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
            for i, b in enumerate(cfg["bulbs"]):
                print(f"    {i+1}. {b['name']} ({b['ip']})")
            sel = input("\n  输入编号: ").strip()
            try:
                idx = int(sel) - 1
                if 0 <= idx < len(cfg["bulbs"]):
                    removed = cfg["bulbs"].pop(idx)
                    if cfg.get("default") == removed["id"]:
                        cfg["default"] = cfg["bulbs"][0]["id"] if cfg["bulbs"] else ""
                    print(f"  ✓ 已删除: {removed['name']}")
            except ValueError:
                pass

        elif choice == "5":
            break
        else:
            print("  无效选择")

    save_bulbs(cfg)


def cmd_test(state, ip=None):
    """直接测试灯光状态"""
    if not ip:
        bulb = get_default_bulb()
        if not bulb:
            print("  ❌ 未配置灯泡")
            sys.exit(1)
        ip = bulb["ip"]

    if not is_relay_running():
        print("  relay 未运行，正在启动...")
        cmd_start(ip)
        time.sleep(1)

    result = relay_request("/api/direct", {"state": state})
    if result.get("ok"):
        print(f"  ✓ 灯光已设置为: {state}")
    else:
        print(f"  ❌ 设置失败: {result.get('error', '未知错误')}")


def cmd_strategy(name):
    """切换协调策略"""
    if name not in ("priority", "active", "carousel"):
        print(f"  ❌ 未知策略: {name}")
        print(f"    可用: priority, active, carousel")
        sys.exit(1)

    result = relay_request("/api/strategy", {"strategy": name})
    if result.get("ok"):
        print(f"  ✓ 策略已切换为: {name}")
    else:
        print(f"  ❌ 切换失败: {result.get('error', '未知错误')}")


def cmd_ensure(ip=None):
    """确保 relay 在运行（适配器调用，不输出提示）"""
    if is_relay_running():
        return True

    if not ip:
        bulb = get_default_bulb()
        if not bulb:
            return False
        ip = bulb["ip"]

    relay_script = BRIDGE_DIR / RELAY_SCRIPT_NAME
    if not relay_script.exists():
        return False

    kill_relay_process()
    try:
        proc = subprocess.Popen(
            [PYTHON_CMD, str(relay_script), str(RELAY_PORT), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        (BRIDGE_DIR / "relay.pid").write_text(str(proc.pid))
    except Exception:
        return False

    for _ in range(30):
        time.sleep(0.2)
        if is_relay_running():
            return True
    return False


# ═══════════════ CLI 入口 ═══════════════

COMMANDS = {
    "install":     (cmd_install,     "安装 bridge 到 ~/.yeelight-vibe-bridge/"),
    "start":       (cmd_start,       "启动 relay 守护进程 [可选: 灯泡IP]"),
    "stop":        (cmd_stop,        "停止 relay 守护进程"),
    "status":      (cmd_status,      "查看 relay 状态"),
    "discover":    (cmd_discover,    "局域网发现灯泡"),
    "setup-bulbs": (cmd_setup_bulbs, "交互式灯泡配置"),
    "test":        (cmd_test,        "直接测试灯光状态 <state> [ip]"),
    "strategy":    (cmd_strategy,    "切换协调策略 <priority|active|carousel>"),
    "ensure":      (cmd_ensure,      "确保 relay 在运行（适配器内部调用）"),
}

def main():
    if len(sys.argv) < 2:
        print("Yeelight Vibe Bridge — 公共桥接层管理")
        print()
        print("用法: python yeelight_bridge.py <命令> [参数...]")
        print()
        max_len = max(len(k) for k in COMMANDS)
        for name, (fn, desc) in COMMANDS.items():
            print(f"  {name:<{max_len+2}} {desc}")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd not in COMMANDS:
        print(f"未知命令: {cmd}")
        print(f"可用命令: {', '.join(COMMANDS)}")
        sys.exit(1)

    fn, _ = COMMANDS[cmd]

    # 传递剩余参数
    if cmd == "test":
        if len(sys.argv) < 3:
            print("用法: python yeelight_bridge.py test <state> [ip]")
            sys.exit(1)
        fn(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    elif cmd == "start":
        fn(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "ensure":
        ok = fn(sys.argv[2] if len(sys.argv) > 2 else None)
        sys.exit(0 if ok else 1)
    elif cmd == "strategy":
        if len(sys.argv) < 3:
            print("用法: python yeelight_bridge.py strategy <priority|active|carousel>")
            sys.exit(1)
        fn(sys.argv[2])
    else:
        fn()


if __name__ == "__main__":
    main()
