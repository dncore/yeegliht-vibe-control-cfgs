#!/usr/bin/env python3
"""
Yeelight Vibe Control — Claude Code 官方 Hooks 版本 (v2)
==========================================================
基于 Claude Code 全部 6 种 hook 事件重新设计灯光控制逻辑。

设计原则:
  - "thinking"  = Claude 正在工作（默认态，用户应等待）
  - "waiting"   = Claude 被阻塞，等待用户操作（权限确认）
  - 工具状态    = 描述 Claude 正在做什么（读/写/执行/网络）
  - "success"   = 会话结束，任务完成
  - "error"     = 出错了
  - 状态映射与 Pi Agent 版对齐：相同语义 → 相同灯光

用法:
    python hooks.py <mode>     # mode: pre_tool | post_tool | stop | ...

架构:
    Claude Code hooks → hooks.py → HTTP → relay 守护进程(9877) → 持久 TCP → 灯泡
"""

import json
import os
import sys
import time
import threading
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

    if has_yeelight(sys.executable):
        return sys.executable
    for cmd in ["python3", "python"]:
        if has_yeelight(cmd):
            return cmd
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
    try:
        req = Request(f"{RELAY_URL}/api/health", method="GET")
        with urlopen(req, timeout=2) as resp:
            data = json.loads(resp.read())
            return data.get("ok", False)
    except Exception:
        return False

def kill_old_relay():
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

def start_relay(bulb_ip=None):
    bulb = get_default_bulb()
    if not bulb and not bulb_ip:
        return False
    ip = bulb_ip or bulb["ip"]

    if is_relay_running():
        try:
            req = Request(f"{RELAY_URL}/api/health", method="GET")
            with urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                if data.get("bulb_ip") == ip:
                    return True
        except Exception:
            pass
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

        for _ in range(30):
            time.sleep(0.2)
            if is_relay_running():
                return True
        return False
    except Exception:
        return False

def stop_relay():
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
    if is_relay_running():
        return True
    bulb = get_default_bulb()
    if not bulb:
        return False
    return start_relay(bulb["ip"])

# ═══════════════════════════════════════════════════════════════════
#  工具 → 灯光状态映射
# ═══════════════════════════════════════════════════════════════════

READ_TOOLS = {
    "Read", "LS", "Grep", "Glob",
    "Task", "TodoRead", "NotebookRead",
}
WRITE_TOOLS = {
    "Write", "Edit", "NotebookEdit",
}
WEB_TOOLS = {
    "WebSearch", "WebFetch",
}

def tool_to_state(tool_name, tool_input=None):
    """
    Claude Code 工具名 → 灯光状态。
    
    设计意图:
      - 让用户通过灯光颜色一眼看出 Claude 在做什么类型的操作
      - 读文件 = 青色呼吸、写文件 = 玫红呼吸、执行命令 = 橙色呼吸
      - 网络操作 = 蓝色闪烁（频率更高，一眼可见）
    """
    if tool_name in READ_TOOLS:
        return "reading"
    if tool_name in WRITE_TOOLS:
        return "writing"
    if tool_name == "Bash":
        cmd = ""
        if tool_input and isinstance(tool_input, dict):
            cmd = tool_input.get("command", "")
        web_keywords = ["curl", "wget", "http ", "fetch", "npx ", "npm ", "pip "]
        if any(kw in str(cmd).lower() for kw in web_keywords):
            return "fetching"
        return "executing"
    if tool_name in WEB_TOOLS:
        return "fetching"
    return "thinking"

# ═══════════════════════════════════════════════════════════════════
#  HTTP 通信
# ═══════════════════════════════════════════════════════════════════

def send_state(state):
    """通过协调层更新灯光状态（多实例安全）"""
    if not ensure_relay():
        return
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
    """直接控制灯光（绕过协调层，用于 Stop 及手动测试）"""
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
#  Hook 事件处理 — 基于 Claude Code 官方 6 种事件重新设计
# ═══════════════════════════════════════════════════════════════════

def handle_user_prompt():
    """
    UserPromptSubmit: 用户提交了 Prompt。
    
    灯光: "thinking" (🧠 蓝呼吸)
    含义: Claude 开始工作，正在分析请求、生成思考过程。
          用户应该等待，不需要操作。
    
    设计理由: 区别于 "waiting" (等用户授权)。
             "thinking" = Claude 在忙，"waiting" = Claude 在等你。
    """
    ensure_relay()
    send_state("thinking")


def _read_event():
    """
    从 stdin 读取 Claude Code 传入的 JSON 事件。
    
    防御策略:
      1. isatty() 检查: 如果 stdin 是交互终端（非管道），不可能有数据
      2. 超时保护: 用独立线程读取，超时 2 秒自动放弃
      
    sys.stdin.read() 是阻塞调用 — 如果 Claude Code 没有向管道写数据，
    会永久卡住，导致 Claude Code TUI 冻结。这个函数用线程超时规避此问题。
    """
    # stdin 是终端 = 没有管道数据（Claude Code 不会以 TTY 方式传事件）
    if sys.stdin.isatty():
        return None
    
    # 带超时的线程读取 — 防止 stdin.read() 永久阻塞
    result = [None]
    def _do_read():
        try:
            raw = sys.stdin.read()
            if raw and raw.strip():
                result[0] = json.loads(raw)
        except Exception:
            pass
    
    t = threading.Thread(target=_do_read, daemon=True)
    t.start()
    t.join(2)  # 最多等 2 秒
    
    return result[0]


def handle_pre_tool():
    """
    PreToolUse: Claude 即将调用一个工具。
    
    三级判断:
      1. permissionDecision == "ask"   → "waiting" (🟡 琥珀)
         Claude 弹出了 "Do you want to proceed?"，需要用户确认。
         这是唯一真正需要用户交互的阻塞点。
         
      2. 工具类型映射 → 具体状态
         Bash         → "executing" (🟧 橙呼吸)
         Bash(网络)   → "fetching"   (🟦 蓝闪烁)
         Read/Grep等  → "reading"   (🟦 青呼吸)
         Write/Edit   → "writing"   (🟪 玫红呼吸)
         WebSearch等  → "fetching"   (🟦 蓝闪烁)
         
      3. 未知工具      → "thinking"  (🧠 蓝呼吸)
    """
    if not ensure_relay():
        return

    event = _read_event()
    if event is None:
        send_state("thinking")
        return

    # 第 1 级: 权限检查 — Claude 在等用户
    permission = (
        event.get("permissionDecision")
        or event.get("permission_decision", "")
    )
    if permission == "ask":
        send_state("waiting")
        return

    # 第 2 级: 工具类型映射
    tool_name = event.get("tool_name", event.get("toolName", ""))
    tool_input = event.get("tool_input", event.get("toolInput", {}))
    state = tool_to_state(tool_name, tool_input)
    send_state(state)


def handle_post_tool():
    """
    PostToolUse: Claude 刚完成一个工具调用。
    
    灯光:
      - 出错: "error" (🔴 正红常亮) — 工具执行失败
      - 成功: "thinking" (🧠 蓝呼吸) — 继续工作/准备下一个工具
    
    设计理由: 工具结束后 Claude 可能继续调用下一个工具或生成文本。
             回到 "thinking" 是正确的默认态。
             错误时用醒目的红色让用户知道出了问题。
    """
    if not ensure_relay():
        return

    event = _read_event()
    if event is None:
        send_state("thinking")
        return

    # 检测错误
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
    """
    Stop: Agent 会话结束。
    
    灯光: "success" (🟩 翠绿常亮)
    含义: Claude 完成了所有工作，任务成功结束。
          与 Pi Agent 的 agent_end → success 对齐。
    
    注意: 使用 send_direct 而非 send_state，因为 Stop 是最终状态，
          不需要经过多实例协调。
    """
    send_direct("success")

    # 可选: 完全关闭 relay 释放连接
    # stop_relay()


def handle_subagent_stop():
    """
    SubagentStop: 子代理任务完成。
    
    灯光: "thinking" (🧠 蓝呼吸)
    含义: 子任务完成，主代理继续工作。
          对用户来说，这只是 Claude 工作流程中的一步。
    
    注意: 子代理可能有自已的事件，但我们不关心细节，
          只恢复主代理的工作状态。
    """
    if not ensure_relay():
        return
    send_state("thinking")


def handle_notification():
    """
    Notification: Claude Code 系统通知事件。
    
    策略: 保持 relay 活跃，不改变当前灯光状态。
    
    原因: 通知事件有多种类型（状态更新、系统消息等），
          大多数不表示 Claude 工作状态的变化。
          灯光应该保持当前的 "thinking" / "executing" / "reading" 等状态。
          
    未来可根据 notification_type 做更精细的控制。
    """
    ensure_relay()


# ═══════════════════════════════════════════════════════════════════
#  CLI 入口
# ═══════════════════════════════════════════════════════════════════

HANDLERS = {
    "pre_tool":       handle_pre_tool,
    "post_tool":      handle_post_tool,
    "stop":           handle_stop,
    "subagent_stop":  handle_subagent_stop,
    "user_prompt":    handle_user_prompt,
    "notification":   handle_notification,
}

def main():
    if len(sys.argv) < 2:
        print("用法: python hooks.py <mode> [args...]")
        print()
        print("Hook 事件 (Claude Code 设置中配置):")
        print("  user_prompt      UserPromptSubmit — 用户提交 Prompt")
        print("  pre_tool         PreToolUse      — 工具即将执行")
        print("  post_tool        PostToolUse     — 工具执行完毕")
        print("  stop             Stop            — 会话停止")
        print("  subagent_stop    SubagentStop    — 子代理停止")
        print("  notification     Notification    — 系统通知")
        print()
        print("手动控制 (调试/测试):")
        print("  direct <state>   直接控制灯泡")
        print("  setup            启动 relay 守护进程")
        print("  shutdown         关闭 relay 守护进程")
        print()
        print("可用状态: idle thinking reading writing executing fetching waiting success error stop off")
        sys.exit(1)

    mode = sys.argv[1].lower()

    if mode in HANDLERS:
        HANDLERS[mode]()

    elif mode == "direct":
        if len(sys.argv) < 3:
            print("用法: python hooks.py direct <state>")
            sys.exit(1)
        state = sys.argv[2]
        aliases = {
            "green": "idle", "orange": "waiting", "flash": "thinking",
            "context": "querying", "bash": "executing", "web": "fetching",
            "read": "reading", "write": "writing",
        }
        state = aliases.get(state, state)
        if state == "stop":
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
