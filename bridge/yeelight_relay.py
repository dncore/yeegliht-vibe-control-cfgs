#!/usr/bin/env python3
"""
Yeelight HTTP Relay — Pi Agent 持久连接守护进程
=================================================
- 保持单一 TCP 连接到灯泡，复用到底
- 提供 HTTP API 供 pi 扩展调用
- 支持局域网设备发现

用法: python yeelight_relay.py [端口] [灯泡IP] [策略]
      端口默认 9877, IP 默认 192.168.2.205

API:
  POST /api/direct    {"state": "thinking"}   直接应用（无协调，TUI 用）
  POST /api/state     {"state": "thinking"}   经多实例协调后应用（auto-tracking 用）
  POST /api/discover  {}                      扫描局域网发现灯泡
  POST /api/stop      {}                      终止所有灯效，恢复日常照明
  GET  /api/status    → 当前状态
"""

import atexit
import json
import os
import signal
import socket
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock, Thread
from urllib.parse import urlparse

DEFAULT_IP = "192.168.2.205"

# ═══════════════ HCI / 交通信号色彩 ═══════════════

_STATES = {
    "idle":      { "rgb": ( 68, 136, 255), "bri": 20, "mode": "solid",   "label": "冰蓝待机" },
    "waiting":   { "rgb": (255, 140,   0), "bri": 50, "mode": "solid",   "label": "等待用户" },
    "success":   { "rgb": (  0, 220,  80), "bri": 80, "mode": "solid",   "label": "完成成功" },
    "error":     { "rgb": (255,  30,  30), "bri": 50, "mode": "solid",   "label": "出错停止" },
    "thinking":  { "rgb": (  0,  68, 255), "bri": 50, "mode": "breathe", "label": "思考中" },
    "reading":   { "rgb": (  0, 200, 255), "bri": 60, "mode": "breathe", "label": "读取文件" },
    "writing":   { "rgb": (255,  50, 120), "bri": 60, "mode": "breathe", "label": "写入编辑" },
    "executing": { "rgb": (220,  90,   0), "bri": 60, "mode": "breathe", "label": "执行命令" },
    "querying":  { "rgb": (  0, 160, 100), "bri": 60, "mode": "breathe", "label": "查询上下文" },
    "fetching":  { "rgb": (  0, 100, 255), "bri": 40, "mode": "flash",   "label": "访问网络" },
    "off":       { "mode": "off", "label": "关闭" },
}

_ALIASES = {
    "green": "idle", "orange": "waiting", "flash": "thinking",
    "context": "querying", "bash": "executing", "web": "fetching",
    "read": "reading", "write": "writing", "purple": "writing", "cyan": "reading",
}

_PRIORITY = {
    "error": 0, "fetching": 1, "executing": 2, "writing": 3,
    "reading": 4, "querying": 5, "thinking": 6, "waiting": 7,
    "idle": 8, "success": 9, "off": 99,
}
_IDLE_STATES = {"idle", "waiting", "success", "off"}
_GROUP_MAP = {
    "fetching": "net", "executing": "exec", "writing": "write",
    "reading": "read", "querying": "query", "thinking": "think",
    "waiting": "idle", "idle": "idle", "success": "idle", "off": "idle",
}

# ═══════════════ Yeelight 控制 ═══════════════

try:
    from yeelight import Bulb, Flow, discover_bulbs
    from yeelight.transitions import RGBTransition
    _BULB_AVAILABLE = True
except ImportError:
    _BULB_AVAILABLE = False

_bulb_instance = None
_persistent_bulb = None
_persistent_ip = None
_bulb_lock = Lock()

@atexit.register
def _cleanup():
    if _persistent_bulb is not None:
        try:
            _persistent_bulb.stop_flow()
        except Exception:
            pass

signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))
signal.signal(signal.SIGINT,  lambda *_: (_cleanup(), sys.exit(0)))

def _get_bulb(ip: str, reconnect: bool = False):
    global _persistent_bulb, _persistent_ip
    if reconnect or _persistent_bulb is None or _persistent_ip != ip:
        try:
            _persistent_bulb = Bulb(ip, auto_on=False, effect="sudden")
            _persistent_ip = ip
        except Exception:
            _persistent_bulb = None
            raise
    return _persistent_bulb

def _solid(bulb, r, g, b, bri=20):
    bulb.set_rgb(r, g, b, effect="sudden")
    bulb.set_brightness(bri, effect="sudden")

def _breathe(bulb, r, g, b, bri=50):
    dr, dg, db = max(1, r//20), max(1, g//20), max(1, b//20)
    flow = Flow(count=6, transitions=[
        RGBTransition(r, g, b, duration=50,   brightness=bri),      # 瞬间到位
        RGBTransition(dr, dg, db, duration=1500, brightness=1),      # 线性变暗
        RGBTransition(dr, dg, db, duration=200, brightness=1),       # 暗部停留
        RGBTransition(r, g, b, duration=1500, brightness=bri),       # 线性变亮
    ])
    bulb.start_flow(flow)

def _flash(bulb, r, g, b, bri=40):
    dr, dg, db = max(1, r//30), max(1, g//30), max(1, b//30)
    flow = Flow(count=10, transitions=[
        RGBTransition(r, g, b, duration=100,  brightness=bri),      # 到位
        RGBTransition(dr, dg, db, duration=300, brightness=1),       # 线性变暗
        RGBTransition(r, g, b, duration=300, brightness=bri),        # 线性变亮
    ])
    bulb.start_flow(flow)

def stop_effects(bulb):
    bulb.stop_flow()
    bulb.turn_on()
    bulb.set_color_temp(4000, effect="sudden")
    bulb.set_brightness(80, effect="sudden")

def _apply(bulb, state_name):
    global _bulb_instance
    _bulb_instance = bulb
    s = _STATES.get(state_name)
    if not s:
        return
    mode = s.get("mode", "solid")
    if mode == "off":
        try:
            bulb.turn_off(effect="sudden")
        except Exception:
            pass
        return
    r, g, b = s["rgb"]
    bri = s["bri"]
    if mode == "solid":
        _solid(bulb, r, g, b, bri)
    elif mode == "breathe":
        _breathe(bulb, r, g, b, bri)
    elif mode == "flash":
        _flash(bulb, r, g, b, bri)


def _apply_locked(bulb, state_name):
    global _persistent_bulb, _persistent_ip
    with _bulb_lock:
        try:
            if state_name == "stop":
                stop_effects(bulb)
            else:
                _apply(bulb, state_name)
        except Exception:
            # 连接断开时重新连接灯泡并重试一次
            try:
                _persistent_bulb = _get_bulb(_persistent_ip or "127.0.0.1", reconnect=True)
                if state_name == "stop":
                    stop_effects(_persistent_bulb)
                else:
                    _apply(_persistent_bulb, state_name)
            except Exception:
                pass

# ═══════════════ 多实例协调 ═══════════════

STATE_FILE = os.path.expanduser("~/.yeelight-vibe-bridge/yeelight-shared.json")
STALE_TIMEOUT = 30
CAROUSEL_INTERVAL = 3

def read_shared():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"strategy": "priority", "sessions": {}}

def write_shared(data):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def aggregate(data):
    sessions = data.get("sessions", {})
    if not sessions:
        return None
    strategy = data.get("strategy", "priority")
    now = time.time()
    for pid in list(sessions.keys()):
        if now - sessions[pid].get("updatedAt", 0) > STALE_TIMEOUT:
            del sessions[pid]
    if strategy == "active":
        active = {k: v for k, v in sessions.items() if v.get("state") not in _IDLE_STATES}
        if not active:
            return "idle"
        sessions = active
    elif strategy == "carousel":
        groups = {}
        for info in sessions.values():
            st = info.get("state", "off")
            grp = _GROUP_MAP.get(st, "idle")
            groups.setdefault(grp, []).append(st)
        if not groups:
            return None
        idx = data.get("_carousel_idx", 0)
        ts = data.get("_carousel_ts", 0)
        keys = sorted(groups.keys(),
                      key=lambda g: min(_PRIORITY.get(s, 999) for s in groups[g]))
        if now - ts >= CAROUSEL_INTERVAL:
            idx = (idx + 1) % len(keys)
            data["_carousel_idx"] = idx
            data["_carousel_ts"] = now
            write_shared(data)
        states_in = groups[keys[idx]]
        best, bp = None, 999
        for s in states_in:
            p = _PRIORITY.get(s, 999)
            if p < bp:
                bp, best = p, s
        return best
    best, bp = None, 999
    for info in sessions.values():
        st = info.get("state", "off")
        p = _PRIORITY.get(st, 999)
        if p < bp:
            bp, best = p, st
    return best

def apply_state(state, ip):
    if not _BULB_AVAILABLE:
        return {"ok": False, "error": "yeelight 包未安装"}
    s = _STATES.get(state)
    if not s:
        return {"ok": False, "error": f"未知状态: {state}"}
    try:
        bulb = _get_bulb(ip)
        _apply_locked(bulb, state)
        return {"ok": True}
    except Exception as e:
        _persistent_bulb = None
        try:
            bulb = _get_bulb(ip)
            _apply_locked(bulb, state)
            return {"ok": True}
        except Exception as e2:
            return {"ok": False, "error": str(e2)}

# ═══════════════ HTTP Handler ═══════════════

class RelayHandler(BaseHTTPRequestHandler):
    bulb_ip = DEFAULT_IP

    def log_message(self, fmt, *args):
        pass  # 静默

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/status":
            data = read_shared()
            self._send_json({
                "strategy": data.get("strategy","priority"),
                "sessions": len(data.get("sessions",{})),
                "yeelight": _BULB_AVAILABLE,
                "bulb_ready": _persistent_bulb is not None,
                "ok": True
            })
        elif path == "/api/health":
            self._send_json({
                "ok": True,
                "yeelight_available": _BULB_AVAILABLE,
                "bulb_connected": _persistent_bulb is not None,
                "bulb_ip": RelayHandler.bulb_ip
            })
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/direct":
            raw = body.get("state", "").lower()
            state = raw if raw == "stop" else _ALIASES.get(raw, raw)
            # 先回 OK，再后台执行（避免客户端等灯泡响应超时）
            s = None if state == "stop" else _STATES.get(state)
            if not s and state != "stop":
                self._send_json({"ok": False, "error": f"未知状态: {state}"}, 400)
                return
            self._send_json({"ok": True, "state": state, "label": s["label"] if s else "已终止灯效"})
            # 后台线程执行实际灯泡操作
            def _run():
                try:
                    bulb = _get_bulb(self.bulb_ip)
                    _apply_locked(bulb, state)
                except Exception:
                    pass
            Thread(target=_run, daemon=True).start()

        elif path == "/api/state":
            raw = body.get("state", "").lower()
            state = _ALIASES.get(raw, raw)
            pid = body.get("pid", f"remote_{int(time.time())}")
            data = read_shared()
            data.setdefault("sessions", {})[pid] = {"state": state, "updatedAt": time.time()}
            write_shared(data)
            final = aggregate(data)
            label_text = ""
            if final:
                s = _STATES.get(final)
                label_text = s["label"] if s else final
            self._send_json({"ok": True, "state": final, "label": label_text,
                             "strategy": data.get("strategy","priority"),
                             "sessions": len(data.get("sessions",{}))})
            # 后台执行
            if final:
                def _run():
                    try:
                        result = apply_state(final, self.bulb_ip)
                    except Exception:
                        pass
                Thread(target=_run, daemon=True).start()

        elif path == "/api/discover":
            try:
                if not _BULB_AVAILABLE:
                    self._send_json({"ok": False, "error": "yeelight 包未安装"})
                    return

                result = []

                # 1. 先尝试 SSDP 多播发现
                try:
                    bulbs = discover_bulbs(timeout=3)
                    for info in bulbs:
                        result.append({
                            "ip": info.get("ip", ""),
                            "port": info.get("port", 55443),
                            "model": info.get("model", "unknown"),
                            "name": info.get("name", f"Yeelight-{info.get('ip', '??')}"),
                        })
                except Exception:
                    pass

                # 2. SSDP 没结果 → 扫本机所在子网 55443 端口
                if not result:
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    def probe(ip):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(0.2)
                            s.connect((ip, 55443))
                            s.close()
                            return {"ip": ip, "port": 55443, "name": f"Yeelight-{ip}"}
                        except Exception:
                            return None

                    # 取本机所有私有网段
                    def local_prefixes():
                        prefixes = []
                        try:
                            for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
                                if ip.startswith("192.168.") or ip.startswith("10."):
                                    prefixes.append(ip.rsplit(".", 1)[0] + ".")
                        except Exception:
                            pass
                        return prefixes or ["192.168.2."]

                    targets = []
                    for prefix in local_prefixes():
                        for h in range(1, 255):
                            targets.append(f"{prefix}{h}")

                    with ThreadPoolExecutor(max_workers=50) as pool:
                        futures = {pool.submit(probe, t): t for t in targets}
                        for future in as_completed(futures):
                            r = future.result()
                            if r:
                                result.append(r)

                self._send_json({"ok": True, "bulbs": result, "count": len(result)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})

        elif path == "/api/stop":
            try:
                bulb = _get_bulb(self.bulb_ip)
                stop_effects(bulb)
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})

        elif path == "/api/debug":
            """同步测试灯泡连接，返回详细错误（失败时自动重连一次）"""
            def _try_debug():
                bulb = _get_bulb(self.bulb_ip)
                bulb.turn_on()
                bulb.set_rgb(0, 220, 80, effect="sudden")
                bulb.set_brightness(80, effect="sudden")
            try:
                _try_debug()
                self._send_json({"ok": True, "msg": "灯泡应变为翠绿"})
            except Exception as e:
                # 连接断开，重建 TCP 连接后重试
                try:
                    _persistent_bulb = _get_bulb(self.bulb_ip, reconnect=True)
                    _try_debug()
                    self._send_json({"ok": True, "msg": "灯泡应变为翠绿 (重连后)"})
                except Exception as e2:
                    self._send_json({"ok": False, "error": str(e2), "exception_type": type(e2).__name__})

        elif path == "/api/strategy":
            strategy = body.get("strategy", "").lower()
            if strategy not in ("priority", "active", "carousel"):
                self._send_json({"ok": False, "error": f"未知策略: {strategy}"}, 400)
                return
            data = read_shared()
            data["strategy"] = strategy
            data.pop("_carousel_idx", None)
            data.pop("_carousel_ts", None)
            write_shared(data)
            self._send_json({"ok": True, "strategy": strategy})

        else:
            self._send_json({"error": "not found"}, 404)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9877
    bulb_ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_IP
    RelayHandler.bulb_ip = bulb_ip

    if not _BULB_AVAILABLE:
        print("⚠ yeelight 包未安装: pip install yeelight")

    server = HTTPServer(("127.0.0.1", port), RelayHandler)
    # 启动时预连接灯泡（避免首次请求等待 TCP 握手）
    def _warmup():
        try:
            b = _get_bulb(bulb_ip)
            b.turn_on()  # 真正触发 socket 连接
        except Exception:
            pass
    Thread(target=_warmup, daemon=True).start()
    print(f"[relay] 端口 {port} 灯泡 {bulb_ip}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()
        server.shutdown()


if __name__ == "__main__":
    main()
