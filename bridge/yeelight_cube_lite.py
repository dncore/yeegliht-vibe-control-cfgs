#!/usr/bin/env python3
"""
Yeelight Cube Smart Lamp Lite Controller
=========================================
TCP protocol handler for the Yeelight Cube Smart Lamp Lite (20×5 LED matrix).

Protocol (based on yeelight-cube-lite Home Assistant integration):
  1. TCP connect to port 55443
  2. activate_fx_mode {"mode": "direct"}  → enter direct pixel control mode
  3. set_bright [0-100]                   → hardware brightness
  4. update_leds [rgb_data]               → send 100-pixel frame (400-char base64)

FX mode expires ~25s after activation. Must be refreshed periodically.
Only ONE TCP connection at a time — Cube firmware crashes on concurrent connections.

Usage:
    controller = CubeLiteController("192.168.2.205")
    await controller.connect()
    await controller.apply_state("thinking")
    await controller.close()
"""

import asyncio
import base64
import json
import logging
import socket
import struct
import threading
import time
from typing import Optional, List, Tuple

try:
    from .cube_fonts import TOTAL_COLUMNS, TOTAL_ROWS, TOTAL_PIXELS, layout_text_centered
    from .cube_patterns import (
        STATE_DEFS,
        STATE_ALIASES,
        ANIMATION_CONFIG,
    )
except ImportError:
    from cube_fonts import TOTAL_COLUMNS, TOTAL_ROWS, TOTAL_PIXELS, layout_text_centered
    from cube_patterns import (
        STATE_DEFS,
        STATE_ALIASES,
        ANIMATION_CONFIG,
    )

logger = logging.getLogger(__name__)

# ═══════════════ Constants ═══════════════

CUBE_PORT = 55443
CONNECT_TIMEOUT = 1.5       # seconds
COMMAND_TIMEOUT = 1.0       # seconds
FX_REFRESH_INTERVAL = 20    # seconds — re-activate FX mode before it expires (~25s)
MIN_COMMAND_INTERVAL = 0.1  # seconds between TCP commands (Cube TCP stack is fragile)
RECONNECT_COOLDOWN = 2.0    # seconds to wait before reconnecting after failure


# ═══════════════ Model Detection ═══════════════

CUBE_MODEL_PATTERNS = [
    "cube", "cubelite", "cube_lite", "cube-lite",
    "clt",    # CubeLite model prefix (clt6pro, clt4, etc.)
    "panel", "matrix",
]


def is_cube_device(model: str, name: str = "") -> bool:
    """Detect if a Yeelight device is a Cube Smart Lamp Lite based on model/name."""
    combined = f"{model} {name}".lower()
    return any(pattern in combined for pattern in CUBE_MODEL_PATTERNS)


# ═══════════════ Pixel Encoding ═══════════════

def encode_hex_color(hex_color: str) -> str:
    """Encode a hex color (#RRGGBB) as base64(3-byte RGB).

    Each pixel is 3 bytes → 4 chars base64. 100 pixels = 400 chars total.
    """
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return base64.b64encode(bytes([r, g, b])).decode("ascii")


def encode_pixel_array(pixels: list) -> str:
    """Encode 100 RGB tuples into a 400-character base64 string for update_leds.

    Args:
        pixels: List of 100 (r, g, b) tuples, index = row * 20 + col

    Returns:
        400-character base64-encoded string
    """
    if len(pixels) != TOTAL_PIXELS:
        raise ValueError(f"Expected {TOTAL_PIXELS} pixels, got {len(pixels)}")

    result = []
    for r, g, b in pixels:
        result.append(base64.b64encode(bytes([r, g, b])).decode("ascii"))
    return "".join(result)


def build_pixel_array(lit_indices: list, color: tuple, brightness_pct: int = 100) -> list:
    """Build a full 100-pixel array with given LED indices lit in the specified color.

    Args:
        lit_indices: List of pixel indices (0-99) to light up
        color: (r, g, b) base color
        brightness_pct: Brightness percentage (0-100), applied to color

    Returns:
        List of 100 (r, g, b) tuples
    """
    r, g, b = color
    factor = brightness_pct / 100.0
    lit = (int(r * factor), int(g * factor), int(b * factor))
    dark = (0, 0, 0)

    lit_set = set(lit_indices)
    return [lit if i in lit_set else dark for i in range(TOTAL_PIXELS)]


# ═══════════════ CubeLiteController ═══════════════

class CubeLiteController:
    """Manages TCP connection and pixel rendering for Cube Smart Lamp Lite."""

    def __init__(self, ip: str, port: int = CUBE_PORT):
        self._ip = ip
        self._port = port
        self._socket: Optional[socket.socket] = None
        self._last_command_time = 0.0
        self._fx_activated = False
        self._last_fx_time = 0.0
        self._hw_brightness = 50
        self._command_lock: Optional[asyncio.Lock] = None

        # Animation state
        self._anim_task: Optional[asyncio.Task] = None
        self._current_state: Optional[str] = None
        self._current_pixels: Optional[list] = None

    def _get_lock(self) -> asyncio.Lock:
        """Lazily create the command lock (needs an event loop)."""
        if self._command_lock is None:
            self._command_lock = asyncio.Lock()
        return self._command_lock

    # ── Connection Management ──────────────────────────────

    async def connect(self) -> bool:
        """Establish TCP connection and activate FX mode.

        Returns True on success, False on failure.
        """
        try:
            await self._raw_connect()
            await self._activate_fx()
            return True
        except Exception as e:
            logger.warning(f"[CubeLite] [{self._ip}] Connect failed: {e}")
            await self._close_socket()
            return False

    async def _raw_connect(self):
        """Raw TCP connect with SO_LINGER RST close."""
        self._close_socket()

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        # SO_LINGER with 0 timeout: RST on close, avoids TIME_WAIT
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))

        await asyncio.to_thread(sock.connect, (self._ip, self._port))
        self._socket = sock
        self._fx_activated = False
        logger.debug(f"[CubeLite] [{self._ip}] TCP connected")

    def _close_socket(self):
        """Close socket with RST (abortive close)."""
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
            self._fx_activated = False

    async def close(self):
        """Graceful shutdown: turn off display, close socket."""
        self._stop_animation()
        try:
            await self._send_command("set_bright", [0])
        except Exception:
            pass
        self._close_socket()

    # ── Command Sending ───────────────────────────────────

    async def _send_command(self, method: str, params: list, retry=True) -> None:
        """Send a JSON command over TCP with rate limiting and reconnection."""
        async with self._get_lock():
            # Rate limiting
            elapsed = time.time() - self._last_command_time
            if elapsed < MIN_COMMAND_INTERVAL:
                await asyncio.sleep(MIN_COMMAND_INTERVAL - elapsed)

            # Reconnect if needed
            if self._socket is None:
                await self._raw_connect()

            cmd = json.dumps({"id": 1, "method": method, "params": params},
                             separators=(",", ":"))
            request = (cmd + "\r\n").encode("utf8")

            try:
                await asyncio.to_thread(self._socket.sendall, request)
                self._last_command_time = time.time()
            except (socket.error, OSError, BrokenPipeError, ConnectionResetError) as e:
                logger.warning(f"[CubeLite] [{self._ip}] Send failed ({type(e).__name__}): {e}")
                self._close_socket()
                if not retry:
                    raise
                # Reconnect and retry once
                for attempt in range(2):
                    try:
                        await asyncio.sleep(0.1)
                        await self._raw_connect()
                        await self._activate_fx()
                        await asyncio.to_thread(self._socket.sendall, request)
                        self._last_command_time = time.time()
                        return
                    except Exception as e2:
                        if attempt == 1:
                            logger.warning(f"[CubeLite] [{self._ip}] Retry failed: {e2}")
                            raise

    async def _activate_fx(self):
        """Enter direct FX mode + set brightness. Called on connect and periodically."""
        await self._send_command("activate_fx_mode", [{"mode": "direct"}])
        await asyncio.sleep(0.05)  # 50ms settle for firmware
        await self._send_command("set_bright", [self._hw_brightness])
        self._fx_activated = True
        self._last_fx_time = time.time()

    async def _ensure_fx(self):
        """Re-activate FX mode if it's been more than FX_REFRESH_INTERVAL seconds."""
        if not self._fx_activated or (time.time() - self._last_fx_time) > FX_REFRESH_INTERVAL:
            logger.debug(f"[CubeLite] [{self._ip}] Refreshing FX mode")
            await self._activate_fx()

    async def set_brightness(self, pct: int):
        """Set hardware brightness (0-100)."""
        pct = max(0, min(100, pct))
        self._hw_brightness = pct
        try:
            await self._send_command("set_bright", [pct])
        except Exception:
            pass

    # ── Pixel Rendering ───────────────────────────────────

    async def send_pixels(self, pixels: list, brightness_pct: Optional[int] = None):
        """Encode and send a 100-pixel array to the Cube Lite.

        Args:
            pixels: List of 100 (r, g, b) tuples
            brightness_pct: Optional hardware brightness override (0-100)
        """
        await self._ensure_fx()

        if brightness_pct is not None and brightness_pct != self._hw_brightness:
            self._hw_brightness = brightness_pct
            await self._send_command("set_bright", [brightness_pct])

        rgb_data = encode_pixel_array(pixels)
        await self._send_command("update_leds", [rgb_data])
        self._current_pixels = pixels

    async def send_text(self, text: str, color: tuple, visual_brightness: int = 100,
                        hw_brightness: int = 30):
        """Render centered text and send to Cube Lite.

        Args:
            text: Text to display (will be uppercased)
            color: (r, g, b) base color
            visual_brightness: Color brightness multiplier (0-100), applied to RGB values
            hw_brightness: Hardware brightness sent via set_bright (0-100)
        """
        lit_indices = layout_text_centered(text) if text else []
        pixels = build_pixel_array(lit_indices, color, visual_brightness)
        await self.send_pixels(pixels, hw_brightness)

    # ── Synchronous State Application ─────────────────
    # Follows the same pattern as bulb's _get_bulb + _apply_locked:
    #   - One persistent TCP socket, reused
    #   - One lock serializes all commands
    #   - Sync blocking, no background thread or asyncio
    #   - Auto-reconnect on socket failure

    _persistent_sock: socket.socket = None
    _persistent_lock = None  # created lazily
    _fx_last = 0.0           # last FX activation timestamp

    def _get_cube_lock(self):
        if self.__class__._persistent_lock is None:
            self.__class__._persistent_lock = threading.Lock()
        return self.__class__._persistent_lock

    def _drain(self):
        """Drain pending response data from Cube's TCP receive buffer.
        Cube firmware stops processing commands when RX buffer fills up
        (~20-30 unread responses). Must drain after every send."""
        import socket as _sock
        sock = self.__class__._persistent_sock
        if sock is None:
            return
        sock.settimeout(0.01)
        try:
            for _ in range(10):
                r = sock.recv(4096)
                if not r:
                    break
        except (_sock.timeout, BlockingIOError, OSError):
            pass
        finally:
            sock.settimeout(3)

    def _cube_send(self, cmd_dict: dict):
        """Send one JSON command on persistent socket with reconnect + drain."""
        import socket as _sock

        # Retry up to 2 times on connection errors
        for attempt in range(2):
            try:
                if self.__class__._persistent_sock is None:
                    s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
                    s.settimeout(3)
                    s.setsockopt(_sock.IPPROTO_TCP, _sock.TCP_NODELAY, 1)
                    s.setsockopt(_sock.SOL_SOCKET, _sock.SO_LINGER, struct.pack('ii', 1, 0))
                    s.connect((self._ip, self._port))
                    self.__class__._persistent_sock = s

                payload = (json.dumps(cmd_dict, separators=(",", ":")) + "\r\n").encode("utf8")
                self.__class__._persistent_sock.sendall(payload)
                self._drain()  # prevent Cube RX buffer from filling up
                return  # success
            except (_sock.error, OSError, BrokenPipeError, ConnectionResetError, AttributeError):
                # Close stale socket
                try:
                    if self.__class__._persistent_sock is not None:
                        self.__class__._persistent_sock.close()
                except Exception:
                    pass
                self.__class__._persistent_sock = None

    def _cube_apply(self, state_name: str):
        """Synchronous state apply: activate FX (throttled) → set bright → update LEDs.
        FX mode only re-activated at most once per 20s (~25s duration)."""
        resolved = STATE_ALIASES.get(state_name, state_name)
        state_def = STATE_DEFS.get(resolved)
        if not state_def:
            return

        text = state_def["text"]
        lit = layout_text_centered(text) if text else []
        pixels = build_pixel_array(lit, state_def["rgb"], state_def["brightness"])
        brightness = state_def["brightness"]
        rgb_data = encode_pixel_array(pixels)

        with self._get_cube_lock():
            now = time.time()
            # FX mode lasts ~25s — only re-activate every 20s
            if now - self.__class__._fx_last > 20:
                self._cube_send({"id": 1, "method": "activate_fx_mode", "params": [{"mode": "direct"}]})
                time.sleep(0.05)
                self.__class__._fx_last = now
            self._cube_send({"id": 2, "method": "set_bright", "params": [brightness]})
            time.sleep(0.05)
            self._cube_send({"id": 3, "method": "update_leds", "params": [rgb_data]})

    def apply_state_sync(self, state_name: str):
        """Called from relay thread — sync, blocking, single-connection.
        Enforces a minimum display time per state so rapid transitions
        don't skip visible frames (e.g. success/error must be seen)."""
        self._cube_apply(state_name)

    def stop_effects_sync(self):
        """Turn off display."""
        with self._get_cube_lock():
            try:
                self._cube_send({"id": 1, "method": "activate_fx_mode", "params": [{"mode": "direct"}]})
                time.sleep(0.05)
                self._cube_send({"id": 2, "method": "set_bright", "params": [0]})
                time.sleep(0.05)
                rgb_data = encode_pixel_array(build_pixel_array([], (0, 0, 0), 0))
                self._cube_send({"id": 3, "method": "update_leds", "params": [rgb_data]})
            except Exception:
                pass

    # ── Animation Engine (kept for backward compatibility) ──

    # ── Animation Engine (kept for backward compatibility) ──

    async def apply_state(self, state_name: str, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Apply an AI agent state to the Cube Lite display.

        Handles:
          - State lookup (with alias resolution)
          - Animation start/stop
          - Pixel rendering
          - Unknown state fallback

        Args:
            state_name: State key (e.g., "thinking", "waiting", "green" alias)
            loop: Event loop for animation tasks; required when no running loop.
        """
        # Resolve alias
        resolved = STATE_ALIASES.get(state_name, state_name)

        state_def = STATE_DEFS.get(resolved)
        if not state_def:
            logger.warning(f"[CubeLite] [{self._ip}] Unknown state: {state_name}")
            return

        text = state_def["text"]
        color = state_def["rgb"]
        animation = state_def["animation"]
        brightness = state_def["brightness"]

        # Stop any running animation
        self._stop_animation()

        try:
            if animation == "solid" or not text:
                # Static display — one frame
                await self.send_text(text, color, hw_brightness=brightness)
            else:
                # Start animation loop
                animation_brightness = state_def["brightness"]
                self._start_animation(text, color, animation, animation_brightness, loop)

        except Exception as e:
            logger.warning(f"[CubeLite] [{self._ip}] apply_state({state_name}) failed: {e}")
            # Try reconnect once
            try:
                await self._raw_connect()
                await self._activate_fx()
                await self.send_text(text, color, hw_brightness=brightness)
            except Exception:
                pass

    async def stop_effects(self):
        """Stop all effects — turn off display and restore to soft white glow."""
        self._stop_animation()
        try:
            await self.send_text("", (0, 0, 0), hw_brightness=0)
        except Exception:
            pass

    # ── Animation Engine ──────────────────────────────────

    def _start_animation(self, text: str, color: tuple, animation: str, base_brightness: int, loop: Optional[asyncio.AbstractEventLoop] = None):
        """Start async animation loop for breathing/flashing effects.

        Pre-computes pixel frames at different brightness levels and sends them
        at controlled intervals. Runs until _stop_animation() is called or
        state changes.

        Args:
            loop: Optional event loop to create the task in. If not provided,
                  uses get_running_loop(). Must be provided when called from
                  a thread without a running loop.
        """
        anim_cfg = ANIMATION_CONFIG.get(animation)
        if not anim_cfg:
            return

        frames = anim_cfg["frames"]
        cycle_ms = anim_cfg["cycle_ms"]
        curve = anim_cfg["brightness_curve"]

        if not text:
            return

        lit_indices = layout_text_centered(text)

        # Pre-compute all frames
        pixel_frames = []
        for b in curve:
            pixels = build_pixel_array(lit_indices, color, b)
            pixel_frames.append(pixels)

        frame_delay = (cycle_ms / 1000.0) / len(curve)

        async def _anim_loop():
            idx = 0
            try:
                while True:
                    await self.send_pixels(pixel_frames[idx], base_brightness)
                    idx = (idx + 1) % len(pixel_frames)
                    await asyncio.sleep(frame_delay)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"[CubeLite] [{self._ip}] Animation stopped: {e}")

        self._anim_task = asyncio.ensure_future(_anim_loop(), loop=loop) if loop else asyncio.ensure_future(_anim_loop())

    def _stop_animation(self):
        """Cancel the running animation task."""
        if self._anim_task is not None and not self._anim_task.done():
            self._anim_task.cancel()
        self._anim_task = None
        self._current_state = None


# ═══════════════ CLI Test ═══════════════

async def _cli_test():
    """Quick test when run directly: python -m bridge.yeelight_cube_lite <ip> <state>"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: python yeelight_cube_lite.py <ip> [state]")
        print("States: idle, waiting, success, error, thinking, reading, writing, executing, querying, fetching")
        sys.exit(1)

    ip = sys.argv[1]
    state = sys.argv[2] if len(sys.argv) > 2 else "idle"

    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")

    ctrl = CubeLiteController(ip)
    print(f"Connecting to Cube Lite at {ip}...")
    ok = await ctrl.connect()
    if not ok:
        print("Connection failed!")
        sys.exit(1)

    print(f"Connected. Applying state: {state}")
    await ctrl.apply_state(state)

    try:
        await asyncio.sleep(30)  # Keep alive to see FX refresh
    except KeyboardInterrupt:
        pass
    finally:
        await ctrl.stop_effects()
        await ctrl.close()
        print("Done.")


if __name__ == "__main__":
    asyncio.run(_cli_test())
