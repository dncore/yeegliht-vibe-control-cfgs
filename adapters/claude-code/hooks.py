#!/usr/bin/env python3
"""Claude Code hook → bridge relay. Minimal imports for fast startup on Windows.

Remote usage (LAN): set env vars to point at another machine's bridge.
  YEELIGHT_RELAY_URL=http://192.168.x.x:9877
  YEELIGHT_API_KEY=<api-key>
"""
import json, sys, os, time
from urllib.request import Request, urlopen

BRIDGE = os.environ.get("YEELIGHT_RELAY_URL", "http://127.0.0.1:9877")
API_KEY = os.environ.get("YEELIGHT_API_KEY", "")
LOG = os.path.expanduser("~/.yeelight-vibe-bridge/hook_debug.log")
READ_TOOLS = {"Read","LS","Grep","Glob","Task","TodoRead","NotebookRead"}
WRITE_TOOLS = {"Write","Edit","NotebookEdit"}
EXEC_TOOLS = {"Bash","PowerShell"}
WEB_TOOLS = {"WebSearch","WebFetch"}
WEB_KW = ["curl","wget","http ","fetch","npx ","npm ","pip "]

def post(path, data):
    try:
        body = json.dumps(data).encode()
        req = Request(f"{BRIDGE}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        if API_KEY:
            req.add_header("Authorization", f"Bearer {API_KEY}")
        urlopen(req, timeout=0.3)
        with open(LOG, "a") as f:
            f.write(f"[{time.time():.0f}] {path} {data.get('state','?')} OK\n")
    except Exception as e:
        with open(LOG, "a") as f:
            f.write(f"[{time.time():.0f}] {path} {data.get('state','?')} ERROR: {e}\n")

def read_event():
    try:
        raw = sys.stdin.buffer.readline().decode("utf-8")
        return json.loads(raw) if raw.strip() else None
    except Exception: return None

def tool_state(name, inp=None):
    if name in READ_TOOLS: return "reading"
    if name in WRITE_TOOLS: return "writing"
    if name in EXEC_TOOLS:
        cmd = str(inp.get("command","") if isinstance(inp, dict) else "")
        return "fetching" if any(kw in cmd.lower() for kw in WEB_KW) else "executing"
    if name in WEB_TOOLS: return "fetching"
    return "thinking"

def user_prompt():
    post("/api/state", {"state":"thinking","pid":"claude-hook"})

def pre_tool():
    ev = read_event()
    if not ev:
        return post("/api/state", {"state":"thinking","pid":"claude-hook"})
    # Check all possible permission field names
    perm = (ev.get("permissionDecision") or ev.get("permission_decision")
         or ev.get("permission_required") or ev.get("requires_permission")
         or ev.get("permission") or ev.get("decision") or "")
    if perm == "ask":
        return post("/api/state", {"state":"waiting","pid":"claude-hook"})
    tn = ev.get("tool_name") or ev.get("toolName","")
    ti = ev.get("tool_input") or ev.get("toolInput",{})
    post("/api/state", {"state":tool_state(tn, ti),"pid":"claude-hook"})

def post_tool():
    ev = read_event()
    if not ev:
        return post("/api/state", {"state":"thinking","pid":"claude-hook"})
    tr = ev.get("tool_response") or ev.get("toolResponse",{})
    err = tr.get("isError") or tr.get("is_error",False) if isinstance(tr,dict) else False
    post("/api/state", {"state":"error" if err else "thinking","pid":"claude-hook"})

def stop():
    """Clear session then show success so it's not overwritten by stale thinking."""
    post("/api/state", {"state":"idle", "pid":"claude-hook"})
    post("/api/direct", {"state":"success"})

def subagent_stop():
    post("/api/state", {"state":"thinking","pid":"claude-hook"})

def notification():
    pass

H = {"user_prompt":user_prompt,"pre_tool":pre_tool,"post_tool":post_tool,
     "stop":stop,"subagent_stop":subagent_stop,"notification":notification}

if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if mode in H: H[mode]()
