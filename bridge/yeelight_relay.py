#!/usr/bin/env python3
"""
Yeelight HTTP Relay — 多设备并发守护进程
==========================================
- 从 bulbs.json 读取所有设备，同时保持连接
- 每个设备独立类型检测、独立连接、独立渲染
- 同一个状态指令广播到所有设备
- 提供 HTTP API 供 agent 适配器调用
- 支持局域网设备发现

用法: python yeelight_relay.py [端口]
      端口默认 9877
      设备列表从 ~/.yeelight-vibe-bridge/bulbs.json 读取

API:
  POST /api/direct    {"state": "thinking"}   直接应用（无协调，TUI 用）
  POST /api/state     {"state": "thinking"}   经多实例协调后应用（auto-tracking 用）
  POST /api/discover  {}                      扫描局域网发现灯泡
  POST /api/stop      {}                      终止所有灯效，恢复日常照明
  GET  /api/status    → 当前状态
"""

import atexit
import asyncio
import json
import os
import signal
import socket
import sys
import time as _time
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Lock, Thread
from urllib.parse import urlparse

# ═══════════════ HCI / 交通信号色彩 ═══════════════

_STATES = {
    "idle":      { "rgb": ( 68, 136, 255), "bri": 20, "mode": "solid",   "label": "冰蓝待机" },
    "waiting":   { "rgb": (255, 140,   0), "bri": 50, "mode": "solid",   "label": "等待用户" },
    "success":   { "rgb": (255, 240, 230), "bri": 30, "mode": "solid",   "label": "完成成功" },
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

# Cube Lite support
_CUBE_AVAILABLE = False
try:
    from .yeelight_cube_lite import CubeLiteController, is_cube_device
    _CUBE_AVAILABLE = True
except ImportError:
    try:
        from yeelight_cube_lite import CubeLiteController, is_cube_device
        _CUBE_AVAILABLE = True
    except ImportError:
        pass

# ═══════════════ 灯泡控制函数 (无状态, 接受 bulb 参数) ═══════════════

def _solid(bulb, r, g, b, bri=20):
    bulb.set_rgb(r, g, b, effect="sudden")
    bulb.set_brightness(bri, effect="sudden")

def _breathe(bulb, r, g, b, bri=50):
    dr, dg, db = max(1, r//20), max(1, g//20), max(1, b//20)
    flow = Flow(count=6, transitions=[
        RGBTransition(r, g, b, duration=50,   brightness=bri),
        RGBTransition(dr, dg, db, duration=1500, brightness=1),
        RGBTransition(dr, dg, db, duration=200, brightness=1),
        RGBTransition(r, g, b, duration=1500, brightness=bri),
    ])
    bulb.start_flow(flow)

def _flash(bulb, r, g, b, bri=40):
    dr, dg, db = max(1, r//30), max(1, g//30), max(1, b//30)
    flow = Flow(count=10, transitions=[
        RGBTransition(r, g, b, duration=100,  brightness=bri),
        RGBTransition(dr, dg, db, duration=300, brightness=1),
        RGBTransition(r, g, b, duration=300, brightness=bri),
    ])
    bulb.start_flow(flow)

def stop_bulb_effects(bulb):
    bulb.stop_flow()
    bulb.turn_on()
    bulb.set_color_temp(4000, effect="sudden")
    bulb.set_brightness(80, effect="sudden")

def _apply_bulb(bulb, state_name):
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

# ═══════════════ 设备连接池 ═══════════════

BULBS_CONFIG_PATH = os.path.expanduser("~/.yeelight-vibe-bridge/bulbs.json")

class DeviceConnection:
    """Manages connection and state dispatch for a single device."""

    def __init__(self, ip: str, dev_type: str = "auto", name: str = ""):
        self.ip = ip
        self.name = name
        self.declared_type = dev_type  # "bulb", "cube_lite", or "auto"
        self.detected_type = None      # resolved after connect
        self.bulb = None               # yeelight.Bulb (for bulbs)
        self.cube = None               # CubeLiteController (for cube_lite)
        self.lock = Lock()
        self.connected = False

    def detect_and_connect(self):
        """Detect device type and establish connection."""
        # If type is declared, try that first
        if self.declared_type == "cube_lite" and _CUBE_AVAILABLE:
            if self._try_cube():
                return
        elif self.declared_type == "bulb" and _BULB_AVAILABLE:
            if self._try_bulb():
                return

        # Auto-detect: try Cube protocol first, then standard bulb
        if self.declared_type == "auto":
            if _CUBE_AVAILABLE and self._try_cube():
                return
            if _BULB_AVAILABLE and self._try_bulb():
                return

        # Fallback: try the other type if declared type failed
        if self.declared_type == "cube_lite" and _BULB_AVAILABLE:
            print(f"[relay] [{self.ip}] Cube Lite 连接失败，回退到标准灯泡")
            if self._try_bulb():
                return
        elif self.declared_type == "bulb" and _CUBE_AVAILABLE:
            print(f"[relay] [{self.ip}] 标准灯泡连接失败，尝试 Cube 协议")
            if self._try_cube():
                return

        print(f"[relay] [{self.ip}] 无法连接 (类型检测失败)")

    def _try_cube(self):
        """Try connecting as Cube Lite via sync TCP. Validates the response."""
        try:
            import socket as _sock
            # Test connection by sending activate_fx_mode and checking response
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(3)
            s.setsockopt(_sock.IPPROTO_TCP, _sock.TCP_NODELAY, 1)
            s.connect((self.ip, 55443))

            cmd = json.dumps({"id": 1, "method": "activate_fx_mode",
                            "params": [{"mode": "direct"}]}, separators=(",", ":"))
            s.sendall((cmd + "\r\n").encode("utf8"))

            # Read response and validate
            s.settimeout(1)
            try:
                resp = b""
                for _ in range(10):
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in chunk:
                        break
                resp_data = json.loads(resp.decode("utf8").strip())
                if resp_data.get("error"):
                    print(f"[relay] [{self.ip}] 非 Cube 设备 (response: {resp_data['error'].get('message', 'unknown')})")
                    s.close()
                    return False
            except (_sock.timeout, json.JSONDecodeError, UnicodeDecodeError):
                pass  # No/bad response — could still be Cube if firmware is slow

            s.close()

            # Response was OK or empty — create controller
            ctrl = CubeLiteController(self.ip)
            self.cube = ctrl
            self.detected_type = "cube_lite"
            self.connected = True
            print(f"[relay] [{self.ip}] Cube Lite 已就绪 ({self.name or 'unnamed'})")
            return True
        except Exception as e:
            print(f"[relay] [{self.ip}] Cube 协议探测失败: {e}")
            return False

    def _try_bulb(self):
        """Try connecting as standard Yeelight bulb. Uses raw TCP for detection
        (yeelight library's Bulb() can fail on some firmware versions)."""
        try:
            import socket as _sock
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(3)
            s.connect((self.ip, 55443))

            cmd = json.dumps({"id": 1, "method": "get_prop",
                            "params": ["power", "bright", "name", "model"]},
                           separators=(",", ":"))
            s.sendall((cmd + "\r\n").encode("utf8"))

            s.settimeout(2)
            try:
                resp = b""
                for _ in range(10):
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp += chunk
                    if b"\n" in chunk:
                        break
                resp_data = json.loads(resp.decode("utf8").strip())
                result = resp_data.get("result", [])
                if resp_data.get("error"):
                    s.close()
                    return False
                # result[3] is model — check if it's a Cube
                model = result[3] if len(result) > 3 else ""
                bulb_name = result[2] if len(result) > 2 else ""
                if is_cube_device(model, bulb_name):
                    s.close()
                    return False  # It's a Cube, not a standard bulb
                s.close()
            except (json.JSONDecodeError, UnicodeDecodeError, _sock.timeout, IndexError):
                s.close()
                return False

            # Detection succeeded — now create the persistent Bulb connection
            try:
                bulb = Bulb(self.ip, auto_on=False, effect="sudden")
                bulb.get_properties()
                self.bulb = bulb
            except Exception:
                # yeelight library failed, use raw TCP bulb wrapper
                from yeelight import Bulb as _Bulb
                bulb = _Bulb(self.ip, auto_on=False, effect="sudden")
                self.bulb = bulb

            self.detected_type = "bulb"
            self.connected = True
            print(f"[relay] [{self.ip}] 标准灯泡已就绪 ({self.name or 'unnamed'}, model={model})")
            return True
        except Exception as e:
            print(f"[relay] [{self.ip}] 灯泡连接失败: {e}")
            return False

    def apply_state(self, state_name: str):
        """Apply a state to this device. Called from HTTP handler threads."""
        if not self.connected:
            return {"ip": self.ip, "ok": False, "error": "not connected"}

        if self.detected_type == "cube_lite" and self.cube is not None:
            if state_name == "stop":
                self.cube.stop_effects_sync()
            else:
                self.cube.apply_state_sync(state_name)
            return {"ip": self.ip, "ok": True}

        elif self.detected_type == "bulb" and self.bulb is not None:
            with self.lock:
                try:
                    if state_name == "stop":
                        stop_bulb_effects(self.bulb)
                    else:
                        _apply_bulb(self.bulb, state_name)
                    return {"ip": self.ip, "ok": True}
                except Exception:
                    # Reconnect and retry once
                    try:
                        self.bulb = Bulb(self.ip, auto_on=False, effect="sudden")
                        if state_name == "stop":
                            stop_bulb_effects(self.bulb)
                        else:
                            _apply_bulb(self.bulb, state_name)
                        return {"ip": self.ip, "ok": True}
                    except Exception as e2:
                        self.connected = False
                        return {"ip": self.ip, "ok": False, "error": str(e2)}

        return {"ip": self.ip, "ok": False, "error": f"unknown type: {self.detected_type}"}

    def get_info(self):
        """Return device info for /api/health etc."""
        return {
            "ip": self.ip,
            "name": self.name,
            "type": self.detected_type or self.declared_type,
            "connected": self.connected,
        }


# Device pool
_devices: list[DeviceConnection] = []
_devices_lock = Lock()


def _load_devices():
    """Load device list from bulbs.json and connect to all of them."""
    global _devices
    try:
        with open(BULBS_CONFIG_PATH) as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[relay] 无法读取 bulbs.json: {e}")
        return

    bulbs = cfg.get("bulbs", [])
    if not bulbs:
        print("[relay] bulbs.json 中没有设备配置")
        return

    print(f"[relay] 从 bulbs.json 加载 {len(bulbs)} 个设备")

    def _connect_one(b):
        dev = DeviceConnection(
            ip=b["ip"],
            dev_type=b.get("type", "auto"),
            name=b.get("name", ""),
        )
        dev.detect_and_connect()
        with _devices_lock:
            _devices.append(dev)

    threads = []
    for b in bulbs:
        t = Thread(target=_connect_one, args=(b,), daemon=True)
        t.start()
        threads.append(t)

    for t in threads:
        t.join(timeout=10)

    connected = sum(1 for d in _devices if d.connected)
    print(f"[relay] 设备就绪: {connected}/{len(_devices)}")


def _apply_to_all(state_name: str):
    """Broadcast a state to all connected devices."""
    results = []
    with _devices_lock:
        devices_snapshot = list(_devices)
    for dev in devices_snapshot:
        try:
            r = dev.apply_state(state_name)
            results.append(r)
        except Exception as e:
            results.append({"ip": dev.ip, "ok": False, "error": str(e)})
    return results


def _stop_all():
    """Stop effects on all devices."""
    with _devices_lock:
        devices_snapshot = list(_devices)
    for dev in devices_snapshot:
        try:
            dev.apply_state("stop")
        except Exception:
            pass


def _get_device_summary():
    """Return summary of all devices for API responses."""
    with _devices_lock:
        return [d.get_info() for d in _devices]


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
    now = _time.time()
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


# ═══════════════ Cleanup ═══════════════

def _cleanup():
    _stop_all()


atexit.register(_cleanup)

try:
    signal.signal(signal.SIGTERM, lambda *_: (_cleanup(), sys.exit(0)))
    signal.signal(signal.SIGINT,  lambda *_: (_cleanup(), sys.exit(0)))
except (AttributeError, ValueError):
    pass


# ═══════════════ HTTP Handler ═══════════════

class RelayHandler(BaseHTTPRequestHandler):

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
            devices = _get_device_summary()
            connected = sum(1 for d in devices if d["connected"])
            self._send_json({
                "strategy": data.get("strategy", "priority"),
                "sessions": len(data.get("sessions", {})),
                "yeelight": _BULB_AVAILABLE,
                "devices": devices,
                "devices_total": len(devices),
                "devices_connected": connected,
                "ok": True,
            })
        elif path == "/api/health":
            devices = _get_device_summary()
            self._send_json({
                "ok": True,
                "yeelight_available": _BULB_AVAILABLE,
                "cube_available": _CUBE_AVAILABLE,
                "devices": devices,
            })

        elif path == "/api/bulb-info":
            """查询第一个连接设备的型号/名称"""
            with _devices_lock:
                dev = next((d for d in _devices if d.connected), None)
            if dev is None:
                self._send_json({"ok": False, "error": "没有已连接的设备"})
                return
            if dev.detected_type == "cube_lite":
                self._send_json({
                    "ok": True,
                    "ip": dev.ip,
                    "model": "yeelink.light.cubelite",
                    "name": dev.name or "Cube Smart Lamp Lite",
                    "fw_ver": "",
                    "power": "on",
                    "bright": str(dev.cube._hw_brightness if dev.cube else 0),
                    "device_type": "cube_lite",
                })
                return
            try:
                if dev.bulb:
                    props = dev.bulb.get_properties()
                    self._send_json({
                        "ok": True,
                        "ip": dev.ip,
                        "model": props.get("model", "unknown"),
                        "name": props.get("name", ""),
                        "fw_ver": props.get("fw_ver", ""),
                        "power": props.get("power", ""),
                        "bright": props.get("bright", ""),
                    })
                else:
                    self._send_json({"ok": False, "error": "灯泡未连接"})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if path == "/api/direct":
            raw = body.get("state", "").lower()
            state = raw if raw == "stop" else _ALIASES.get(raw, raw)

            # Validate state against available definitions
            if state != "stop":
                if state not in _STATES:
                    # Also check cube patterns for cube-only states
                    valid = False
                    try:
                        from .cube_patterns import STATE_ALIASES as CUBE_ALIASES
                    except ImportError:
                        try:
                            from cube_patterns import STATE_ALIASES as CUBE_ALIASES
                        except ImportError:
                            CUBE_ALIASES = {}
                    resolved = CUBE_ALIASES.get(state, state)
                    try:
                        from .cube_patterns import STATE_DEFS
                    except ImportError:
                        try:
                            from cube_patterns import STATE_DEFS
                        except ImportError:
                            STATE_DEFS = {}
                    if resolved not in STATE_DEFS and state not in _STATES:
                        self._send_json({"ok": False, "error": f"未知状态: {state}"}, 400)
                        return

            label_text = state
            if state == "stop":
                label_text = "已终止灯效"
            elif state in _STATES:
                label_text = _STATES[state]["label"]
            else:
                try:
                    from .cube_patterns import STATE_DEFS as CUBE_SD
                except ImportError:
                    try:
                        from cube_patterns import STATE_DEFS as CUBE_SD
                    except ImportError:
                        CUBE_SD = {}
                s = CUBE_SD.get(state)
                if s:
                    label_text = s.get("label", state)

            self._send_json({"ok": True, "state": state, "label": label_text})

            # Background: broadcast to all devices
            def _run():
                _apply_to_all(state)
            Thread(target=_run, daemon=True).start()

        elif path == "/api/direct_sync":
            """Same as /api/direct but synchronous — waits for all devices."""
            raw = body.get("state", "").lower()
            state = raw if raw == "stop" else _ALIASES.get(raw, raw)
            if state != "stop" and state not in _STATES:
                # Also check cube patterns
                valid = False
                try:
                    from .cube_patterns import STATE_ALIASES as CUBE_ALIASES
                    from .cube_patterns import STATE_DEFS as CUBE_SD
                except ImportError:
                    try:
                        from cube_patterns import STATE_ALIASES as CUBE_ALIASES
                        from cube_patterns import STATE_DEFS as CUBE_SD
                    except ImportError:
                        CUBE_ALIASES, CUBE_SD = {}, {}
                resolved = CUBE_ALIASES.get(state, state)
                if resolved not in CUBE_SD:
                    self._send_json({"ok": False, "error": f"未知状态: {state}"}, 400)
                    return

            results = _apply_to_all(state)
            label_text = state
            if state in _STATES:
                label_text = _STATES[state]["label"]
            self._send_json({"ok": True, "state": state, "label": label_text,
                             "results": results})

        elif path == "/api/state":
            raw = body.get("state", "").lower()
            state = _ALIASES.get(raw, raw)
            pid = body.get("pid", f"remote_{int(_time.time())}")
            data = read_shared()
            data.setdefault("sessions", {})[pid] = {"state": state, "updatedAt": _time.time()}
            write_shared(data)
            final = aggregate(data)
            label_text = ""
            if final:
                if final in _STATES:
                    label_text = _STATES[final]["label"]
                else:
                    try:
                        from .cube_patterns import STATE_DEFS as CUBE_STATE_DEFS
                    except ImportError:
                        try:
                            from cube_patterns import STATE_DEFS as CUBE_STATE_DEFS
                        except ImportError:
                            CUBE_STATE_DEFS = {}
                    s = CUBE_STATE_DEFS.get(final)
                    label_text = s["label"] if s else final

            if final:
                self._send_json({"ok": True, "state": final, "label": label_text,
                                 "strategy": data.get("strategy", "priority"),
                                 "sessions": len(data.get("sessions", {}))})
                # Background: broadcast to all devices
                def _run():
                    _apply_to_all(final)
                Thread(target=_run, daemon=True).start()

        elif path == "/api/discover":
            try:
                if not _BULB_AVAILABLE:
                    self._send_json({"ok": False, "error": "yeelight 包未安装"})
                    return

                result = []
                seen_ips = set()

                def add_entry(entry):
                    ip = entry.get("ip", "")
                    if ip and ip not in seen_ips:
                        seen_ips.add(ip)
                        result.append(entry)

                # 1. SSDP 多播发现（标准 Yeelight 协议，Cube Lite 也会响应）
                try:
                    bulbs = discover_bulbs(timeout=3)
                    for info in bulbs:
                        model = info.get("model", "unknown")
                        add_entry({
                            "ip": info.get("ip", ""),
                            "port": info.get("port", 55443),
                            "model": model,
                            "name": info.get("name", f"Yeelight-{info.get('ip', '??')}"),
                            "is_cube": any(p in model.lower() for p in ('cube', 'clt', 'cubelite')),
                        })
                except Exception:
                    pass

                # 2. mDNS/Zeroconf 发现 Cube Lite 设备
                try:
                    from zeroconf import ServiceBrowser, Zeroconf, ServiceStateChange

                    class CubeListener:
                        def __init__(self):
                            self.found = []

                        def add_service(self, zc: Zeroconf, service_type: str, name: str):
                            info = zc.get_service_info(service_type, name)
                            if info and info.addresses:
                                ip = socket.inet_ntoa(info.addresses[0])
                                model = "unknown"
                                name_display = name.split(".")[0] if "." in name else name
                                m = __import__('re').search(
                                    r'yeelink-light-([a-z0-9]+)', name.lower()
                                )
                                if m:
                                    model = f"yeelink.light.{m.group(1)}"
                                self.found.append({
                                    "ip": ip,
                                    "port": 55443,
                                    "model": model,
                                    "name": name_display,
                                    "is_cube": True,
                                })

                        def remove_service(self, zc, service_type, name):
                            pass

                        def update_service(self, zc, service_type, name):
                            pass

                    zc = Zeroconf()
                    listener = CubeListener()
                    browser = ServiceBrowser(
                        zc, "_miio._udp.local.", listener=listener,
                    )
                    _time.sleep(2)
                    zc.close()
                    for entry in listener.found:
                        add_entry(entry)
                except ImportError:
                    pass
                except Exception:
                    pass

                # 3. 无结果 → TCP 端口扫描回退
                if not result:
                    from concurrent.futures import ThreadPoolExecutor, as_completed

                    def probe(ip):
                        try:
                            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            s.settimeout(0.2)
                            s.connect((ip, 55443))
                            s.close()
                            return {"ip": ip, "port": 55443, "name": f"Yeelight-{ip}", "model": "unknown"}
                        except Exception:
                            return None

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
                                add_entry(r)

                # 4. 型号充实
                for entry in result:
                    ip = entry.get("ip", "")
                    if not entry.get("name") or entry.get("name", "").startswith("Yeelight-"):
                        try:
                            host = socket.gethostbyaddr(ip)
                            if host and host[0]:
                                entry["name"] = host[0]
                                if entry.get("model") == "unknown" and "yeelink" in host[0].lower():
                                    import re
                                    m = re.search(r'yeelink-light-([a-z0-9]+)', host[0].lower())
                                    if m:
                                        entry["model"] = f"yeelink.light.{m.group(1)}"
                        except Exception:
                            pass

                    if entry.get("model") == "unknown":
                        try:
                            bulb = Bulb(ip, auto_on=False, effect="sudden", duration=0)
                            props = bulb.get_properties()
                            if props:
                                model = props.get("model", "unknown")
                                entry["model"] = model
                                prop_name = props.get("name")
                                if prop_name:
                                    entry["name"] = prop_name
                        except Exception:
                            pass

                    model = entry.get("model", "")
                    entry["is_cube"] = any(
                        p in model.lower() for p in ('cube', 'clt', 'cubelite')
                    )

                self._send_json({"ok": True, "bulbs": result, "count": len(result)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})

        elif path == "/api/stop":
            try:
                _stop_all()
                self._send_json({"ok": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})

        elif path == "/api/debug":
            """同步测试所有设备连接"""
            results = []
            with _devices_lock:
                devices_snapshot = list(_devices)
            for dev in devices_snapshot:
                if dev.detected_type == "cube_lite" and dev.cube:
                    try:
                        dev.cube.apply_state_sync("idle")
                        results.append({"ip": dev.ip, "ok": True, "msg": "Cube Lite 应显示 IDLE 文字"})
                    except Exception as e:
                        results.append({"ip": dev.ip, "ok": False, "error": str(e)})
                elif dev.detected_type == "bulb" and dev.bulb:
                    try:
                        dev.bulb.turn_on()
                        dev.bulb.set_rgb(0, 220, 80, effect="sudden")
                        dev.bulb.set_brightness(80, effect="sudden")
                        results.append({"ip": dev.ip, "ok": True, "msg": "灯泡应变为翠绿"})
                    except Exception as e:
                        try:
                            dev.bulb = Bulb(dev.ip, auto_on=False, effect="sudden")
                            dev.bulb.turn_on()
                            dev.bulb.set_rgb(0, 220, 80, effect="sudden")
                            dev.bulb.set_brightness(80, effect="sudden")
                            results.append({"ip": dev.ip, "ok": True, "msg": "灯泡应变为翠绿 (重连后)"})
                        except Exception as e2:
                            dev.connected = False
                            results.append({"ip": dev.ip, "ok": False, "error": str(e2)})
            self._send_json({"ok": True, "results": results})

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

    if not _BULB_AVAILABLE:
        print("⚠ yeelight 包未安装: pip install yeelight")
    if not _CUBE_AVAILABLE:
        print("⚠ Cube Lite 支持不可用 (缺少 yeelight_cube_lite 模块)")

    # 从 bulbs.json 加载并连接所有设备
    _load_devices()

    server = HTTPServer(("", port), RelayHandler)
    print(f"[relay] 端口 {port}  设备数 {len(_devices)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()
        server.shutdown()


if __name__ == "__main__":
    main()
