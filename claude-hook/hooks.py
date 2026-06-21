#!/usr/bin/env python3
"""
Yeelight Vibe Control — Claude Code 官方 Hooks 版本
====================================================
通过 Yeelight 智能灯实时显示 Claude Code 运行状态。

用法:
    python hooks.py pre_tool     # PreToolUse hook → 映射工具类型 → HTTP → relay
    python hooks.py post_tool    # PostToolUse hook → 错误检测 → HTTP → relay
    python hooks.py stop         # Stop hook → 恢复 idle → 关闭 relay
    python hooks.py user_prompt  # UserPromptSubmit hook → 确保 relay 在线
    python hooks.py direct <state>  # 手动测试，直接控制灯泡

架构:
    Claude Code hooks → hooks.py → HTTP → relay 守护进程 → 持久 TCP → 灯泡

状态颜色基于交通信号灯 + HCI 色彩理论设计。
"""

import json
import os
import sys
import time
import subprocess
import signal
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

# ═══════════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).parent.resolve()
BULBS_FILE = SCRIPT_DIR / "bulbs.json"
RELAY_SCRIPT = SCRIPT_DIR / "yeelight_relay.py"
RELAY_PID_FILE = SCRIPT_DIR / "relay.pid"
RELAY_PORT = 9877
RELAY_URL = f"http://127.0.0.1:{RELAY_PORT}"

# ═══════════════════════════════════════════════════════════════════
#  灯泡配置读取
# ═══════════════════════════════════════════════════════════════════

def load_bulbs():
    try:
        if BULBS_FILE.exists():
            return json.loads(BULBS_FILE.read_text("utf-8"))
    except Exception:
        pass
    return {"bulbs": []}

def get_default_bulb():
    cfg = load_bulbs()
    if cfg.get("default") and any(b["id"] == cfg["default"] for b in cfg["bulbs"]):
        return next(b for b in cfg["bulbs"] if b["id"] == cfg["default"])
    return cfg["bulbs"][0] if cfg["bulbs"] else None

# ═══════════════════════════════════════════════════════════════════
#  Relay 管理
# ═══════════════════════════════════════════════════════════════════

def find_python():
    """查找可用的 Python (需安装 yeelight 包)"""
    def has_yeelight(cmd):
        try:
            r = subprocess.run(
                [cmd, "-c", "import yeelight"],
                capture_output=True, timeout=5
            )
            return r.returncode == 0
        except Exception:
            return False

    # 1. 优先使用当前 Python
    if has_yeelight(sys.executable):
        return sys.executable

    # 2. 尝试常见命令
    for cmd in ["python3", "python"]:
        if has_yeelight(cmd):
            return cmd

    # 3. 回退硬编码路径
    fallbacks = [
        os.path.expanduser("~\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"),
        "C:\\Python312\\python.exe",
        "/usr/bin/python3",
        "/usr/local/bin/python3",
    ]
    for p in fallbacks:
        if os.path.exists(p) and has_yeelight(p):
            return p

    return sys.executable

PYTHON_CMD = find_python()

def is_relay_running():
    """检查 relay 是否在运行且可用"""
    try:
        req = Request(f"{RELAY_URL}/api/health", method="GET")
        with urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("ok", False)
    except Exception:
        return False

def kill_old_relay():
    """清理旧的 relay 进程"""
    # 方法1: 通过 PID 文件
    if RELAY_PID_FILE.exists():
        try:
            saved_pid = int(RELAY_PID_FILE.read_text().strip())
            if saved_pid:
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/PID", str(saved_pid), "/F"],
                            capture_output=True, timeout=5
                        )
                    else:
                        os.kill(saved_pid, signal.SIGTERM)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            RELAY_PID_FILE.unlink()
        except Exception:
            pass

    # 方法2: 杀旧 relay 进程
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/IM", "python.exe", "/FI", "WINDOWTITLE eq relay*"],
                capture_output=True, timeout=5
            )
        else:
            subprocess.run(["pkill", "-f", "yeelight_relay.py"], capture_output=True)
    except Exception:
        pass

def start_relay(bulb_ip):
    """启动 relay 守护进程"""
    bulb = get_default_bulb()
    if not bulb and not bulb_ip:
        return False
    ip = bulb_ip or bulb["ip"]

    if is_relay_running():
        # 检查是否连接正确灯泡
        try:
            req = Request(f"{RELAY_URL}/api/health", method="GET")
            with urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                if data.get("bulb_ip") == ip:
                    return True
        except Exception:
            pass
        # IP 不匹配，重启 relay
        kill_old_relay()

    kill_old_relay()

    try:
        proc = subprocess.Popen(
            [PYTHON_CMD, str(RELAY_SCRIPT), str(RELAY_PORT), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        if proc.pid:
            RELAY_PID_FILE.write_text(str(proc.pid))

        # 等待 relay 就绪
        for _ in range(30):
            time.sleep(0.2)
            if is_relay_running():
                return True

        return False
    except Exception:
        return False

def stop_relay():
    """停止 relay 守护进程"""
    # 发送 off 状态
    try:
        data = json.dumps({"state": "off", "pid": "claude-hook"}).encode()
        req = Request(f"{RELAY_URL}/api/state", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        urlopen(req, timeout=2)
    except Exception:
        pass

    time.sleep(0.5)
    kill_old_relay()

def ensure_relay():
    """确保 relay 在线，不在则启动"""
    if is_relay_running():
        return True
    bulb = get_default_bulb()
    if not bulb:
        return False
    return start_relay(bulb["ip"])

# ═══════════════════════════════════════════════════════════════════
#  状态映射
# ═══════════════════════════════════════════════════════════════════

# 工具类型 → 灯光状态
READ_TOOLS = {"Read", "LS", "Grep", "Glob", "Task", "TodoRead", "NotebookRead"}
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
WEB_TOOLS = {"WebSearch", "WebFetch"}

def tool_to_state(tool_name, tool_input=None):
    """Claude Code 工具名 → 灯光状态"""
    if tool_name in READ_TOOLS:
        return "reading"
    if tool_name in WRITE_TOOLS:
        return "writing"
    if tool_name == "Bash":
        # 检查 bash 命令内容识别网络操作
        cmd = ""
        if tool_input and isinstance(tool_input, dict):
            cmd = tool_input.get("command", "")
        web_keywords = ["curl", "wget", "http ", "fetch", "npx ", "npm ", "pip "]
        if any(kw in str(cmd).lower() for kw in web_keywords):
            return "fetching"
        return "executing"
    if tool_name in WEB_TOOLS:
        return "fetching"
    # 默认: 思考中
    return "thinking"

# ═══════════════════════════════════════════════════════════════════
#  HTTP 通信
# ═══════════════════════════════════════════════════════════════════

def send_state(state):
    """通过协调层更新灯光状态"""
    if not ensure_relay():
        return  # relay 不可用，静默跳过
    try:
        data = json.dumps({
            "state": state,
            "pid": "claude-hook",
        }).encode()
        req = Request(f"{RELAY_URL}/api/state", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        urlopen(req, timeout=1)
    except Exception:
        pass

def send_direct(state):
    """直接控制灯光（绕过协调，用于手动测试及 stop）"""
    if not ensure_relay():
        return
    try:
        data = json.dumps({"state": state}).encode()
        req = Request(f"{RELAY_URL}/api/direct", data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        urlopen(req, timeout=1)
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════
#  Hook 事件处理
# ═══════════════════════════════════════════════════════════════════

def handle_user_prompt():
    """UserPromptSubmit: 确保 relay 在线，显示等待状态"""
    ensure_relay()
    send_state("waiting")

def handle_pre_tool():
    """PreToolUse: 根据即将调用的工具设置灯光"""
    if not ensure_relay():
        return

    # 从 stdin 读取 Claude Code hook 传入的 JSON
    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        # 无法解析 stdin，fallback 到 thinking
        send_state("thinking")
        return

    # 当工具需要用户授权时 (permissionDecision == "ask")，
    # Claude Code 会弹出 "Do you want to proceed?" 对话框等待用户响应。
    # 此时应显示 "等待用户" 而非工具状态。
    permission = (
        event.get("permissionDecision")
        or event.get("permission_decision", "")
    )
    if permission == "ask":
        send_state("waiting")
        return

    tool_name = event.get("tool_name", event.get("toolName", ""))
    tool_input = event.get("tool_input", event.get("toolInput", {}))
    state = tool_to_state(tool_name, tool_input)
    send_state(state)

def handle_post_tool():
    """PostToolUse: 检测结果状态"""
    if not ensure_relay():
        return

    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        send_state("thinking")
        return

    # 检查是否有错误
    is_error = False
    tool_response = event.get("tool_response", event.get("toolResponse", {}))
    if isinstance(tool_response, dict):
        is_error = tool_response.get("isError", tool_response.get("is_error", False))
    elif isinstance(tool_response, str) and tool_response.lower().startswith("error"):
        is_error = True

    if is_error:
        send_state("error")
    else:
        send_state("thinking")

def handle_stop():
    """Stop: agent 停止，恢复空闲状态"""
    send_direct("idle")
    # 可选: 完全关闭 relay
    # stop_relay()

def handle_subagent_stop():
    """SubagentStop: 子代理停止"""
    send_state("thinking")

def handle_notification():
    """Notification: 处理通知事件"""
    # 不改变灯光状态，仅保持 relay 活跃
    ensure_relay()

# ═══════════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("用法: python hooks.py <mode> [args...]")
        print("模式:")
        print("  pre_tool        PreToolUse hook")
        print("  post_tool       PostToolUse hook")
        print("  stop            Stop hook")
        print("  user_prompt     UserPromptSubmit hook")
        print("  subagent_stop   SubagentStop hook")
        print("  notification    Notification hook")
        print("  direct <state>  直接控制灯泡 (测试用)")
        print("  setup           启动 relay (手动)")
        print("  shutdown        关闭 relay (手动)")
        sys.exit(1)

    mode = sys.argv[1].lower()

    handlers = {
        "pre_tool": handle_pre_tool,
        "post_tool": handle_post_tool,
        "stop": handle_stop,
        "subagent_stop": handle_subagent_stop,
        "user_prompt": handle_user_prompt,
        "notification": handle_notification,
    }

    if mode in handlers:
        handlers[mode]()
    elif mode == "direct":
        if len(sys.argv) < 3:
            print("用法: python hooks.py direct <state>")
            print("状态: idle, thinking, reading, writing, executing, fetching, waiting, success, error, off, stop")
            sys.exit(1)
        state = sys.argv[2]
        # 兼容旧名称
        aliases = {
            "green": "idle", "orange": "waiting", "flash": "thinking",
            "context": "querying", "bash": "executing", "web": "fetching",
            "read": "reading", "write": "writing",
        }
        state = aliases.get(state, state)
        if state in ("stop",):
            # stop 效果: 终止灯效恢复白光
            send_direct("stop")
            print(f"OK - 已终止灯效")
        else:
            send_direct(state)
            print(f"OK - {state}")
    elif mode == "setup":
        bulb = get_default_bulb()
        if not bulb:
            print("错误: 未配置灯泡，请先运行 setup.py")
            sys.exit(1)
        ok = start_relay(bulb["ip"])
        print(f"OK - relay {'已启动' if ok else '启动失败'}")
    elif mode == "shutdown":
        stop_relay()
        print("OK - relay 已关闭")
    else:
        print(f"未知模式: {mode}")
        sys.exit(1)

if __name__ == "__main__":
    main()
