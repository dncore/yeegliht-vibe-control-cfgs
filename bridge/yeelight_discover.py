#!/usr/bin/env python3
"""Yeelight 局域网设备发现 — 输出 JSON"""

import json
import sys

try:
    from yeelight import discover_bulbs
    bulbs = discover_bulbs(timeout=3)
    result = []
    for info in bulbs:
        result.append({
            "ip": info.get("ip", ""),
            "port": info.get("port", 55443),
            "name": info.get("name", ""),
            "model": info.get("model", "unknown"),
        })
    print(json.dumps({"ok": True, "bulbs": result, "count": len(result)}))
except ImportError:
    print(json.dumps({"ok": False, "error": "yeelight 包未安装: pip install yeelight"}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}))
    sys.exit(1)
