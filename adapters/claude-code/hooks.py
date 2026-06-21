#!/usr/bin/env python3
"""
Yeelight Vibe Bridge — Claude Code 适配器
==========================================
Claude Code hook 事件 → HTTP → bridge relay (9877)

职责: 仅负责事件转换和 HTTP 通信。
      不管理 relay 生命周期，不读写 bulbs.json，
      不包含灯泡发现逻辑。

所有底层功能由 ~/.yeelight-vibe-bridge/ 提供。

用法: python hooks.py <mode>
  mode: user_prompt | pre_tool | post_tool | stop | subagent_stop | notification
"""

import json
import sys
import threading
from urllib.request import Request, urlopen
from urllib.error import URLError

# ═══════════════ 配置 ═══════════════

BRIDGE_URL = "http://127.0.0.1:9877"

# ═══════════════ 工具 → 灯光状态映射 ═══════════════

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


# ═══════════════ HTTP 通信 ═══════════════

def _post(path, data):
    """POST 到 bridge relay"""
    try:
        body = json.dumps(data).encode()
        req = Request(f"{BRIDGE_URL}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        urlopen(req, timeout=1)
    except Exception:
        pass


# ═══════════════ stdin 事件读取 ═══════════════

def _read_event():
    """
    从 stdin 读取 Claude Code 传入的 JSON 事件。

    用独立线程 + 2 秒超时。使用 readline() 而非 read()：
    read() 会阻塞直到管道 EOF，但 hook 管道不会关闭 → 永远超时 fallback。
    readline() 在收到换行符时立即返回。
    """
    result = [None]

    def _do_read():
        try:
            raw = sys.stdin.readline()
            if raw and raw.strip():
                result[0] = json.loads(raw)
        except json.JSONDecodeError:
            try:
                rest = sys.stdin.read()
                full = raw + rest
                if full and full.strip():
                    result[0] = json.loads(full)
            except Exception:
                pass
        except Exception:
            pass

    t = threading.Thread(target=_do_read, daemon=True)
    t.start()
    t.join(2)
    return result[0]


# ═══════════════ Hook 事件处理 ═══════════════

def handle_user_prompt():
    """UserPromptSubmit: 用户提交 Prompt → thinking"""
    _post("/api/state", {"state": "thinking", "pid": "claude-hook"})


def handle_pre_tool():
    """PreToolUse: 工具即将执行"""
    event = _read_event()
    if event is None:
        _post("/api/state", {"state": "thinking", "pid": "claude-hook"})
        return

    # 权限询问 → waiting
    permission = (
        event.get("permissionDecision")
        or event.get("permission_decision", "")
    )
    if permission == "ask":
        _post("/api/state", {"state": "waiting", "pid": "claude-hook"})
        return

    # 工具类型 → 对应状态
    tool_name = event.get("tool_name", event.get("toolName", ""))
    tool_input = event.get("tool_input", event.get("toolInput", {}))
    state = tool_to_state(tool_name, tool_input)
    _post("/api/state", {"state": state, "pid": "claude-hook"})


def handle_post_tool():
    """PostToolUse: 工具执行完毕"""
    event = _read_event()
    if event is None:
        _post("/api/state", {"state": "thinking", "pid": "claude-hook"})
        return

    is_error = False
    tool_response = event.get("tool_response", event.get("toolResponse", {}))
    if isinstance(tool_response, dict):
        is_error = tool_response.get("isError", tool_response.get("is_error", False))
    elif isinstance(tool_response, str) and tool_response.lower().startswith("error"):
        is_error = True

    state = "error" if is_error else "thinking"
    _post("/api/state", {"state": state, "pid": "claude-hook"})


def handle_stop():
    """Stop: 会话结束 → success（直接应用，不经过协调）"""
    _post("/api/direct", {"state": "success"})


def handle_subagent_stop():
    """SubagentStop: 子代理结束 → thinking"""
    _post("/api/state", {"state": "thinking", "pid": "claude-hook"})


def handle_notification():
    """Notification: 系统通知 → 仅维持 relay 活跃（不改变状态）"""
    # 不发任何状态，桥接层自动淘汰过期 session
    pass


# ═══════════════ CLI 入口 ═══════════════

HANDLERS = {
    "user_prompt":    handle_user_prompt,
    "pre_tool":       handle_pre_tool,
    "post_tool":      handle_post_tool,
    "stop":           handle_stop,
    "subagent_stop":  handle_subagent_stop,
    "notification":   handle_notification,
}

def main():
    if len(sys.argv) < 2:
        print("用法: python hooks.py <mode>")
        print(f"可用模式: {', '.join(HANDLERS)}")
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode in HANDLERS:
        HANDLERS[mode]()
    else:
        print(f"未知模式: {mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
