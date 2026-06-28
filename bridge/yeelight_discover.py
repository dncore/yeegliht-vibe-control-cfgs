#!/usr/bin/env python3
"""Yeelight 局域网设备发现 — 输出 JSON（含 Cube Lite 识别）"""

import json
import socket
import sys

result = []
seen_ips = set()


def add_entry(entry):
    ip = entry.get("ip", "")
    if ip and ip not in seen_ips:
        seen_ips.add(ip)
        result.append(entry)


# 1. SSDP 多播发现
try:
    from yeelight import discover_bulbs, Bulb

    bulbs = discover_bulbs(timeout=3)
    for info in bulbs:
        model = info.get("model", "unknown")
        add_entry({
            "ip": info.get("ip", ""),
            "port": info.get("port", 55443),
            "model": model,
            "name": info.get("name", f"Yeelight-{info.get('ip', '??')}"),
            "is_cube": any(p in model.lower() for p in ("cube", "clt", "cubelite")),
        })
except ImportError:
    print(json.dumps({"ok": False, "error": "yeelight 包未安装: pip install yeelight"}))
    sys.exit(1)
except Exception as e:
    pass  # SSDP failed, continue to mDNS / TCP scan

# 2. mDNS/Zeroconf 发现 Cube Lite 设备
try:
    from zeroconf import ServiceBrowser, Zeroconf
    import time as _time

    class CubeListener:
        def __init__(self):
            self.found = []

        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name)
            if info and info.addresses:
                ip = socket.inet_ntoa(info.addresses[0])
                model = "unknown"
                import re
                m = re.search(r"yeelink-light-([a-z0-9]+)", name.lower())
                if m:
                    model = f"yeelink.light.{m.group(1)}"
                name_display = name.split(".")[0] if "." in name else name
                self.found.append({
                    "ip": ip, "port": 55443, "model": model,
                    "name": name_display, "is_cube": True,
                })

        def remove_service(self, zc, service_type, name):
            pass

        def update_service(self, zc, service_type, name):
            pass

    zc = Zeroconf()
    listener = CubeListener()
    browser = ServiceBrowser(zc, "_miio._udp.local.", listener=listener)
    _time.sleep(2)
    zc.close()
    for entry in listener.found:
        add_entry(entry)
except ImportError:
    pass  # zeroconf not installed
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

# 4. 型号充实：对所有 unknown 设备查询 get_properties()
for entry in result:
    ip = entry.get("ip", "")

    # 反向 DNS
    if not entry.get("name") or entry.get("name", "").startswith("Yeelight-"):
        try:
            host = socket.gethostbyaddr(ip)
            if host and host[0]:
                entry["name"] = host[0]
                if entry.get("model") == "unknown" and "yeelink" in host[0].lower():
                    import re
                    m = re.search(r"yeelink-light-([a-z0-9]+)", host[0].lower())
                    if m:
                        entry["model"] = f"yeelink.light.{m.group(1)}"
        except Exception:
            pass

    # 查询型号（所有 unknown 设备）
    if entry.get("model") == "unknown":
        try:
            bulb = Bulb(ip, auto_on=False, effect="sudden", duration=0)
            props = bulb.get_properties()
            if props:
                entry["model"] = props.get("model", "unknown")
                prop_name = props.get("name")
                if prop_name:
                    entry["name"] = prop_name
        except Exception:
            pass

    model = entry.get("model", "")
    entry["is_cube"] = any(p in model.lower() for p in ("cube", "clt", "cubelite"))

print(json.dumps({"ok": True, "bulbs": result, "count": len(result)}, ensure_ascii=False))
