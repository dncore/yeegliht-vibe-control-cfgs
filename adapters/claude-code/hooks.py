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
    """POST to bridge relay (fast: 0.3s timeout, localhost)"""
    try:
        body = json.dumps(data).encode()
        req = Request(f"{BRIDGE_URL}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        urlopen(req, timeout=0.3)
    except Exception:
        pass


# ═══════════════ stdin 事件读取 ═══════════════

def _read_event():
    """
    Read Claude Code hook event JSON from stdin.
    
    Uses buffer.readline() (bytes mode, faster on Windows) + 0.5s timeout.
    Claude Code sends single-line JSON with newline → readline returns instantly.
    """
    result = [None]

    def _do_read():
        try:
            raw = sys.stdin.buffer.readline().decode("utf-8")
            if raw and raw.strip():
                result[0] = json.loads(raw)
        except Exception:
            pass

    t = threading.Thread(target=_do_read, daemon=True)
    t.start()
    t.join(0.5)
    return result[0]


def _read_event_blocking():
    """
    Read event with blocking readline (no timeout).
    For events that ALWAYS have stdin data (PreToolUse, PostToolUse).
    Faster because no thread overhead, but blocks until data arrives.
    """
    try:
        raw = sys.stdin.buffer.readline().decode("utf-8")
        if raw and raw.strip():
            return json.loads(raw)
    except Exception:
        pass
    return None


# ═══════════════ Hook 事件处理 ═══════════════

def handle_user_prompt():
    """UserPromptSubmit: 用户提交 Prompt → thinking"""
    _post("/api/state", {"state": "thinking", "pid": "claude-hook"})


def handle_pre_tool():
    """PreToolUse: tool about to execute. Use blocking read — data is always on stdin."""
    event = _read_event_blocking()
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
    """PostToolUse: tool finished. Use blocking read."""
    event = _read_event_blocking()
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
