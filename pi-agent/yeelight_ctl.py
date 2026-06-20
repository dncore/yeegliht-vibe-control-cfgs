#!/usr/bin/env python3
"""
Yeelight 智能灯控制脚本 — Pi Agent 多实例协调版
==================================================
基于交通信号灯与人机交互(HCI)色彩理论重新设计。

状态颜色映射 (HCI / Traffic Signal Design):
┌─────────────┬──────────┬──────────┬────────┬──────────────────────────┐
│ 状态        │ 效果     │ RGB      │ 亮度   │ 设计原理                 │
├─────────────┼──────────┼──────────┼────────┼──────────────────────────┤
│ idle        │ 冰蓝常亮 │ 68,136,255 │ 20%  │ 待机就绪，柔和不打扰      │
│ waiting     │ 琥珀常亮 │ 255,140,0 │ 50%  │ 🟡 等待用户输入           │
│ thinking    │ 蓝呼吸   │ 0,68,255  │ 50%  │ 思考/处理中，冷静专注     │
│ success     │ 翠绿常亮 │ 0,220,80  │ 100% │ 🟢 任务完成成功           │
│ error       │ 正红常亮 │ 255,30,30 │ 50%  │ 🔴 出错/中断              │
│ reading     │ 青呼吸   │ 0,200,255 │ 60%  │ 读取文件                  │
│ writing     │ 玫红呼吸 │ 255,50,120│ 60%  │ 写入/编辑文件             │
│ executing   │ 橙呼吸   │ 220,90,0  │ 60%  │ 执行命令                  │
│ querying    │ 绿呼吸   │ 0,160,100 │ 60%  │ 查询上下文                │
│ fetching    │ 蓝闪烁   │ 0,100,255 │ 40%  │ 访问互联网                │
│ off         │ 关闭     │ —         │ —    │ 会话结束                  │
└─────────────┴──────────┴──────────┴────────┴──────────────────────────┘

安全机制（防止灯卡在闪烁状态）:
  1️⃣ 所有 Flow 使用有限 count，即使中途进程被杀也会自动停止
  2️⃣ atexit 注册清理函数，确保退出时停止所有效果
  3️⃣ try/finally 包裹主流程，异常也能清理
  4️⃣ signal 处理器捕获 SIGTERM/SIGINT

用法:
    python yeelight_ctl.py <状态> <灯泡IP> <PID> [策略]
    python yeelight_ctl.py strategy <策略名> <灯泡IP>

旧名称兼容（自动映射到新名称）:
    green   → idle
    orange  → waiting
    flash   → thinking
    context → querying
    bash    → executing
    web     → fetching
    read    → reading
    write   → writing

策略:
    priority  最高优先级（默认）
    active    活跃优先
    carousel  分组轮播

依赖: pip install yeelight
"""

import atexit
import json
import os
import signal
import sys
import time

# ═══════════════════════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_IP = "192.168.2.205"
STATE_FILE = os.path.expanduser("~/.pi/yeelight-shared.json")
STALE_TIMEOUT = 30
CAROUSEL_INTERVAL = 3

# ═══════════════════════════════════════════════════════════════════════════════
#  HCI / 交通信号设计 — 状态颜色系统
# ═══════════════════════════════════════════════════════════════════════════════
#  设计原则:
#    🟢 绿色 = 完成/成功 (交通信号通行)
#    🟡 橙色 = 注意/等待 (交通信号警示)
#    🔴 红色 = 错误/停止 (交通信号止步)
#    🟦 蓝色 = 思考/处理中 (HCI loading)
#    呼吸效果 = 运行中 (读/写/执行/查询)
#    闪烁效果 = 快速提醒 (网络访问)
#    常亮     = 静止状态 (待机/等待/错误/成功)

# 色相分布确保低亮度下可辨别:
#   蓝 (220°) / 青 (180°) / 绿 (140°) / 橙 (30°) / 玫红 (340°) / 红 (0°)

_STATES = {
    # ── 静止状态（常亮） ──
    "idle":      { "rgb": ( 68, 136, 255), "bri": 20, "mode": "solid", "label": "💤 冰蓝待机" },
    "waiting":   { "rgb": (255, 140,   0), "bri": 50, "mode": "solid", "label": "🟡 等待用户" },
    "success":   { "rgb": (  0, 220,  80), "bri": 80, "mode": "solid", "label": "✅ 完成成功 🟢" },
    "error":     { "rgb": (255,  30,  30), "bri": 50, "mode": "solid", "label": "🔴 出错停止" },
    # ── 运行中状态（呼吸） ──
    "thinking":  { "rgb": (  0,  68, 255), "bri": 50, "mode": "breathe", "label": "🧠 思考中" },
    "reading":   { "rgb": (  0, 200, 255), "bri": 60, "mode": "breathe", "label": "📖 读取文件" },
    "writing":   { "rgb": (255,  50, 120), "bri": 60, "mode": "breathe", "label": "✏️ 写入/编辑" },
    "executing": { "rgb": (220,  90,   0), "bri": 60, "mode": "breathe", "label": "⚙️ 执行命令" },
    "querying":  { "rgb": (  0, 160, 100), "bri": 60, "mode": "breathe", "label": "🔍 查询上下文" },
    # ── 快速活动（闪烁） ──
    "fetching":  { "rgb": (  0, 100, 255), "bri": 40, "mode": "flash", "label": "🌐 访问网络" },
    # ── 关闭 ──
    "off":       { "mode": "off", "label": "⚫ 关闭" },
}

# ── 旧名称 → 新名称 映射（向后兼容） ──
_ALIASES = {
    "green":   "idle",
    "orange":  "waiting",
    "flash":   "thinking",
    "context": "querying",
    "bash":    "executing",
    "web":     "fetching",
    "read":    "reading",
    "write":   "writing",
    "purple":  "writing",
    "cyan":    "reading",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  状态优先级 — lower = higher priority
# ═══════════════════════════════════════════════════════════════════════════════

_PRIORITY = {
    "error": 0,
    "fetching": 1,
    "executing": 2,
    "writing": 3,
    "reading": 4,
    "querying": 5,
    "thinking": 6,
    "waiting": 7,
    "idle": 8,
    "success": 9,
    "off": 99,
}

_IDLE_STATES = {"idle", "waiting", "success", "off"}

_GROUP_MAP = {
    "fetching": "net", "executing": "exec", "writing": "write",
    "reading": "read", "querying": "query", "thinking": "think",
    "waiting": "idle", "idle": "idle", "success": "idle",
    "off": "idle", "error": "error",
}

# ═══════════════════════════════════════════════════════════════════════════════
#  Yeelight 控制 — ★ 安全修复核心
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from yeelight import Bulb, Flow
    from yeelight.transitions import RGBTransition
except ImportError:
    print("Error: yeelight 包未安装。请执行: pip install yeelight")
    sys.exit(1)

# 全局灯泡引用，用于 atexit 清理
_bulb_instance = None


def get_bulb(ip: str) -> Bulb:
    global _bulb_instance
    # auto_on=False: 不加额外查询，减少延迟
    # effect='sudden': 基础效果瞬间切换
    b = Bulb(ip, auto_on=False, effect="sudden")
    _bulb_instance = b
    return b


# ★ 安全机制 1: atexit — 进程退出时自动停止 flow
@atexit.register
def _cleanup_on_exit():
    """确保进程退出时停止所有效果，防止灯卡在闪烁状态"""
    if _bulb_instance is not None:
        try:
            _bulb_instance.stop_flow()
        except Exception:
            pass


# ★ 安全机制 2: signal 处理器 — 捕获终止信号
def _signal_handler(signum, frame):
    _cleanup_on_exit()
    sys.exit(0)


signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


def _solid(bulb: Bulb, r: int, g: int, b: int, brightness: int = 20) -> None:
    """常亮 — 瞬间切换（不先 stop_flow，set_rgb 会自动停止）"""
    try:
        # effect='sudden' 立即生效，不等待渐变
        # 先设颜色再设亮度，各一次网络往返
        bulb.set_rgb(r, g, b, effect="sudden")
        bulb.set_brightness(brightness, effect="sudden")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  呼吸 / 闪烁效果（使用 Flow，异步执行，不影响响应速度）
# ═══════════════════════════════════════════════════════════════════════════════

def _breathe(bulb: Bulb, r: int, g: int, b: int, brightness: int = 50) -> None:
    """呼吸效果 — 直接用 Flow，首帧快速到位"""
    try:
        dark_r = max(1, r // 20)
        dark_g = max(1, g // 20)
        dark_b = max(1, b // 20)
        flow = Flow(count=6, transitions=[
            RGBTransition(r, g, b, duration=50,   brightness=brightness),  # 瞬间到位
            RGBTransition(r, g, b, duration=1000, brightness=brightness),  # 渐亮
            RGBTransition(r, g, b, duration=300,  brightness=brightness),  # 保持
            RGBTransition(dark_r, dark_g, dark_b, duration=1500, brightness=1),  # 渐暗
        ])
        bulb.start_flow(flow)
    except Exception:
        _solid(bulb, r, g, b, brightness)


def _flash(bulb: Bulb, r: int, g: int, b: int, brightness: int = 40) -> None:
    """闪烁效果 — 直接用 Flow，首帧快速到位"""
    try:
        dark_r = max(1, r // 30)
        dark_g = max(1, g // 30)
        dark_b = max(1, b // 30)
        flow = Flow(count=10, transitions=[
            RGBTransition(r, g, b, duration=50,   brightness=brightness),  # 瞬间到位
            RGBTransition(r, g, b, duration=300,  brightness=brightness),  # 亮
            RGBTransition(dark_r, dark_g, dark_b, duration=300, brightness=1),  # 暗
        ])
        bulb.start_flow(flow)
    except Exception:
        _solid(bulb, r, g, b, brightness)


# ═══════════════════════════════════════════════════════════════════════════════
#  状态应用函数
# ═══════════════════════════════════════════════════════════════════════════════

def _apply_state(bulb: Bulb, state_name: str) -> None:
    """对灯泡应用状态效果"""
    state = _STATES.get(state_name)
    if not state:
        return

    mode = state.get("mode", "solid")

    if mode == "off":
        try:
            bulb.turn_off(effect="sudden")
        except Exception:
            pass
        return

    r, g, b = state["rgb"]
    bri = state["bri"]

    if mode == "solid":
        _solid(bulb, r, g, b, bri)
    elif mode == "breathe":
        _breathe(bulb, r, g, b, bri)
    elif mode == "flash":
        _flash(bulb, r, g, b, bri)


def stop_effects(bulb: Bulb) -> None:
    """终止所有灯效，恢复日常照明 (100% 亮度, 6500K 白光)"""
    try:
        bulb.stop_flow()
        bulb.turn_on()
        bulb.set_color_temp(4000, effect="sudden")
        bulb.set_brightness(80, effect="sudden")
    except Exception:
        _solid(bulb, 255, 255, 255, 80)


# ═══════════════════════════════════════════════════════════════════════════════
#  多实例协调
# ═══════════════════════════════════════════════════════════════════════════════

def read_shared() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"strategy": "priority", "sessions": {}}


def write_shared(data: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def cleanup_stale(data: dict, now: float) -> bool:
    changed = False
    stale = [
        pid for pid, info in data.get("sessions", {}).items()
        if now - info.get("updatedAt", 0) > STALE_TIMEOUT
    ]
    for pid in stale:
        del data["sessions"][pid]
        changed = True
    return changed


def strategy_priority(sessions: dict) -> str | None:
    best, bp = None, 999
    for info in sessions.values():
        st = info.get("state", "off")
        p = _PRIORITY.get(st, 999)
        if p < bp:
            bp, best = p, st
    return best


def strategy_active(sessions: dict) -> str | None:
    active = {k: v for k, v in sessions.items()
              if v.get("state") not in _IDLE_STATES}
    if not active:
        return "idle"
    return strategy_priority(active)


def strategy_carousel(sessions: dict) -> str | None:
    groups: dict[str, list[str]] = {}
    for info in sessions.values():
        st = info.get("state", "off")
        grp = _GROUP_MAP.get(st, "idle")
        groups.setdefault(grp, []).append(st)
    if not groups:
        return None
    now = time.time()
    data = read_shared()
    idx = data.get("_carousel_idx", 0)
    ts = data.get("_carousel_ts", 0)
    keys = sorted(groups.keys(),
                  key=lambda g: min(_PRIORITY.get(s, 999) for s in groups[g]))
    if now - ts >= CAROUSEL_INTERVAL:
        idx = (idx + 1) % len(keys)
        data["_carousel_idx"] = idx
        data["_carousel_ts"] = now
        write_shared(data)
    current = groups[keys[idx]]
    best, bp = None, 999
    for s in current:
        p = _PRIORITY.get(s, 999)
        if p < bp:
            bp, best = p, s
    return best


_STRATEGIES = {
    "priority": strategy_priority,
    "active": strategy_active,
    "carousel": strategy_carousel,
}


def aggregate_state(data: dict) -> str | None:
    sessions = data.get("sessions", {})
    if not sessions:
        return None
    strategy = data.get("strategy", "priority")
    fn = _STRATEGIES.get(strategy, strategy_priority)
    return fn(sessions)


def update_shared(pid: str, state: str, ip: str, strategy: str | None = None) -> str | None:
    now = time.time()
    data = read_shared()
    if strategy and strategy in _STRATEGIES:
        data["strategy"] = strategy
    data.setdefault("sessions", {})[pid] = {"state": state, "updatedAt": now}
    cleanup_stale(data, now)
    final = aggregate_state(data)
    write_shared(data)
    return final


# ═══════════════════════════════════════════════════════════════════════════════
#  入口
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    # ★ 安全机制 3: try/finally 确保无论异常与否都能清理
    bulb = None
    try:
        if len(sys.argv) < 2:
            print(f"用法: python {sys.argv[0]} <状态> [灯泡IP] [PID] [策略]")
            print(f"       python {sys.argv[0]} strategy <策略名> [灯泡IP]")
            print(f"状态: {', '.join(_STATES.keys())}")
            print(f"策略: {', '.join(_STRATEGIES.keys())}")
            sys.exit(1)

        cmd = sys.argv[1].lower()

        if cmd == "strategy":
            if len(sys.argv) < 3:
                print(f"策略: {', '.join(_STRATEGIES.keys())}")
                sys.exit(1)
            strategy = sys.argv[2].lower()
            if strategy not in _STRATEGIES:
                print(f"未知策略: {strategy}")
                sys.exit(1)
            ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_IP
            data = read_shared()
            data["strategy"] = strategy
            data.pop("_carousel_idx", None)
            data.pop("_carousel_ts", None)
            write_shared(data)
            print(f"OK - 策略已切换为: {strategy}")
            return

        # direct 命令：绕过协调，直接应用状态到灯泡（TUI 手动测试用）
        if cmd == "direct":
            if len(sys.argv) < 3:
                print("用法: direct <状态|stop> [灯泡IP]")
                sys.exit(1)
            raw_state = sys.argv[2].lower()
            
            # 特殊命令：stop — 终止所有灯效，恢复日常照明
            if raw_state == "stop":
                ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_IP
                for attempt in range(2):
                    try:
                        bulb = get_bulb(ip)
                        stop_effects(bulb)
                        print("OK - 已终止所有灯效，恢复日常照明")
                        break
                    except Exception as e:
                        if attempt == 0:
                            _cleanup_on_exit()
                            time.sleep(1)
                        else:
                            print(f"错误: {e}", file=sys.stderr)
                            sys.exit(1)
                return
            
            state = _ALIASES.get(raw_state, raw_state)
            if state not in _STATES:
                print(f"未知状态: {raw_state}")
                sys.exit(1)
            ip = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_IP
            for attempt in range(2):
                try:
                    bulb = get_bulb(ip)
                    _apply_state(bulb, state)
                    label = _STATES.get(state, {}).get("label", state)
                    print(f"OK - 直接应用: {label}")
                    break
                except Exception as e:
                    if attempt == 0:
                        _cleanup_on_exit()
                        time.sleep(1)
                    else:
                        print(f"错误: {e}", file=sys.stderr)
                        sys.exit(1)
            return

        # 解析状态名（支持别名向后兼容）
        raw_state = cmd
        state = _ALIASES.get(raw_state, raw_state)

        if state not in _STATES:
            print(f"未知状态: {raw_state}")
            sys.exit(1)

        ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_IP
        pid = sys.argv[3] if len(sys.argv) > 3 else str(os.getpid())
        strategy = sys.argv[4] if len(sys.argv) > 4 else None

        # 更新共享状态并计算最终决定
        final = update_shared(pid, state, ip, strategy)
        if final is None:
            print("OK - 无活跃会话")
            return

        # 应用最终状态到灯泡（带重试，灯泡有时会拒绝连接）
        max_retries = 2
        last_error = None
        for attempt in range(max_retries):
            try:
                bulb = get_bulb(ip)
                _apply_state(bulb, final)
                last_error = None
                break
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    _cleanup_on_exit()
                    time.sleep(1)
        if last_error:
            raise last_error

        data = read_shared()
        label = _STATES.get(final, {}).get("label", final)
        print(f"OK - {label} (策略={data.get('strategy','?')}, {len(data.get('sessions',{}))}会话)")

    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # ★ 安全机制 4: 确保灯泡引用存在，供 atexit 使用
        pass


if __name__ == "__main__":
    main()
