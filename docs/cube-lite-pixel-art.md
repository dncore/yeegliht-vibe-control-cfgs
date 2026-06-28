# Yeelight Cube Smart Lamp Lite — Pixel Art State Reference

> 20×5 LED matrix (100 individually addressable pixels)  
> Protocol: TCP 55443, JSON commands (activate_fx_mode → update_leds)  
> Font: 3×5 "basic" bitmap, centered on display

---

## Matrix Coordinate System

```
        Column  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19
              ┌────────────────────────────────────────────────────────────────┐
Row 4 (top)   │ 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 96 97 98 99 │
Row 3         │ 60 61 62 63 64 65 66 67 68 69 70 71 72 73 74 75 76 77 78 79 │
Row 2         │ 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 │
Row 1         │ 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 │
Row 0 (bottom)│  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 │
              └────────────────────────────────────────────────────────────────┘
```

Pixel index = `row × 20 + column`

---

## State Overview

| State | Text | Color | Animation | HW Brightness | Anim Spec | Meaning |
|-------|------|-------|-----------|--------------|-----------|---------|
| `idle` | `IDLE` | `( 68,136,255)` | solid | 15% | — | Ice blue idle |
| `thinking` | `THINK` | `(  0, 68,255)` | breathe | 50% | 10 frames / 2.0s | AI generating response |
| `reading` | `READ` | `(  0,200,255)` | breathe | 50% | 10 frames / 2.0s | Reading files |
| `writing` | `WRITE` | `(255, 50,120)` | breathe | 50% | 10 frames / 2.0s | Editing/writing files |
| `executing` | `EXEC` | `(220, 90,  0)` | breathe | 50% | 10 frames / 2.0s | Running shell commands |
| `querying` | `QUERY` | `(  0,160,100)` | breathe | 50% | 10 frames / 2.0s | Querying context |
| `fetching` | `FETCH` | `(  0,100,255)` | flash | 40% | 6 frames / 0.9s | Accessing network |
| `waiting` | `WAIT` | `(255,140,  0)` | pulse_slow | 40% | 10 frames / 3.0s | Waiting for user input |
| `success` | `DONE` | `(255,240,230)` | solid | 25% | — | Task complete |
| `error` | `ERR!` | `(255, 30, 30)` | blink | 50% | 4 frames / 1.2s | Error encountered |

---

## Pixel Patterns

Each grid shows the 20×5 matrix. `█` = lit pixel, `·` = dark pixel.

### idle — `IDLE` — Ice Blue — Solid

```
  ··███·██··█···███···
  ···█··█·█·█···█·····
  ···█··█·█·█···██····
  ···█··█·█·█···█·····
  ··███·██··███·███···
```

**Lit pixels:** 36/100  
**RGB:** `(68, 136, 255)` — `#4488ff`  
**Animation:** Solid, no animation. Dim brightness (15%) — low-key resting state.  
**When:** Agent is idle, no task running. Relay has no active sessions.

---

### thinking — `THINK` — Blue — Breathe

```
  ███·█·█·███·██··█·█·
  ·█··█·█··█··█·█·█·█·
  ·█··███··█··█·█·██··
  ·█··█·█··█··█·█·█·█·
  ·█··█·█·███·█·█·█·█·
```

**Lit pixels:** 47/100  
**RGB:** `(0, 68, 255)` — `#0044ff`  
**Animation:** Breathe — brightness oscillates 100%→20%→100% over 2 seconds (10 pre-computed frames).  
**When:** LLM is generating a response (most frequent active state).

---

### reading — `READ` — Cyan — Breathe

```
  ··██··███··█··██····
  ··█·█·█···█·█·█·█···
  ··██··██··███·█·█···
  ··█·█·█···█·█·█·█···
  ··█·█·███·█·█·██····
```

**Lit pixels:** 40/100  
**RGB:** `(0, 200, 255)` — `#00c8ff`  
**Animation:** Breathe — 2.0s cycle.  
**When:** Agent reads files from disk.

---

### writing — `WRITE` — Magenta — Breathe

```
  █·█·█·██··███·███·██
  █·█·█·█·█··█···█··█·
  █·█·█·██···█···█··██
  █·█·█·█·█··█···█··█·
  ·█·██·█·█·███··█··██
```

**Lit pixels:** 49/100  
**RGB:** `(255, 50, 120)` — `#ff3278`  
**Animation:** Breathe — 2.0s cycle.  
**When:** Agent edits or writes files.

---

### executing — `EXEC` — Orange — Breathe

```
  ··███·█·█·███··██···
  ··█···█·█·█···█·····
  ··██···█··██··█·····
  ··█···█·█·█···█·····
  ··███·█·█·███··██···
```

**Lit pixels:** 36/100  
**RGB:** `(220, 90, 0)` — `#dc5a00`  
**Animation:** Breathe — 2.0s cycle.  
**When:** Agent executes shell commands.

---

### querying — `QUERY` — Green — Breathe

```
  ·█··█·█·███·██··█·█·
  █·█·█·█·█···█·█·█·█·
  █·█·█·█·██··██···█··
  █·█·█·█·█···█·█··█··
  ·██··██·███·█·█··█··
```

**Lit pixels:** 46/100  
**RGB:** `(0, 160, 100)` — `#00a064`  
**Animation:** Breathe — 2.0s cycle.  
**When:** Agent queries context, searches codebase.

---

### fetching — `FETCH` — Sky Blue — Flash

```
  ███·███·███··██·█·█·
  █···█····█··█···█·█·
  ██··██···█··█···███·
  █···█····█··█···█·█·
  █···███··█···██·█·█·
```

**Lit pixels:** 43/100  
**RGB:** `(0, 100, 255)` — `#0064ff`  
**Animation:** Flash — rapid 150ms bright/dim alternation, 6 frames over 0.9s.  
**When:** Agent accesses network (fetch API, download, web search).

---

### waiting — `WAIT` — Amber — Slow Pulse

```
  ·█·█·█··█··███·███··
  ·█·█·█·█·█··█···█···
  ·█·█·█·███··█···█···
  ·█·█·█·█·█··█···█···
  ··█·██·█·█·███··█···
```

**Lit pixels:** 41/100  
**RGB:** `(255, 140, 0)` — `#ff8c00`  
**Animation:** Slow pulse — gentle 3.0s brightness cycle (100%→60%→100%).  
**When:** Agent is waiting for user input/permission.

---

### success — `DONE` — Warm White — Solid

```
  ··██··███·██··███···
  ··█·█·█·█·█·█·█·····
  ··█·█·█·█·█·█·██····
  ··█·█·█·█·█·█·█·····
  ··██··███·█·█·███···
```

**Lit pixels:** 42/100  
**RGB:** `(255, 240, 230)` — `#fff0e6`  
**Animation:** Solid. Warm white low brightness (25%) — gentle completion signal.  
**When:** Task completed successfully.

---

### error — `ERR!` — Red — Blink

```
  ···███·██··██··█····
  ···█···█·█·█·█·█····
  ···██··██··██··█····
  ···█···█·█·█·█······
  ···███·█·█·█·█·█····
```

**Lit pixels:** 34/100  
**RGB:** `(255, 30, 30)` — `#ff1e1e`  
**Animation:** Blink — 600ms on / 600ms off, 4 frames over 1.2s.  
**When:** Agent encounters an error.

---

## Animation Details

Animations are implemented entirely in software (the Cube Lite has no native flow engine). Pre-computed pixel frames are sent sequentially with rate-limited TCP commands (100ms minimum interval).

### breathe (thinking, reading, writing, executing, querying)

```
Brightness
  100%  ████
   90%  ████
   70%  ████
   50%  ████
   30%  ████
   20%  ████              ████
   20%  ████              ████
   30%  ████
   50%  ████
   70%  ████
   90%  ████
        └──── 2000ms cycle ────┘
```

10 frames per cycle, 200ms per frame. Smooth inhale/exhale rhythm.

### flash (fetching)

```
Brightness
  100%  ██
   60%    ██
  100%  ██
   60%    ██
  100%  ██
   60%    ██
        └── 900ms cycle ──┘
```

6 frames, 150ms per frame. Quick staccato blink — unmistakably "network activity."

### blink (error)

```
Brightness
  100%  ██████
    0%          ██████
  100%  ██████
    0%          ██████
        └── 1200ms cycle ──┘
```

4 frames, 300ms per frame. 600ms on / 600ms off. Hard stop signal.

### pulse_slow (waiting)

```
Brightness
  100%  ██████████
   90%  ██████████
   80%  ██████████
   70%  ██████████
   60%  ██████████
   60%  ██████████
   70%  ██████████
   80%  ██████████
   90%  ██████████
  100%  ██████████
        └──── 3000ms cycle ────┘
```

10 frames, 300ms per frame. Gentle breathing — says "I'm still here, waiting for you."

---

## Color Palette

```
  idle      ■ #4488ff  Ice Blue
  thinking  ■ #0044ff  Deep Blue
  reading   ■ #00c8ff  Cyan
  writing   ■ #ff3278  Magenta
  executing ■ #dc5a00  Orange
  querying  ■ #00a064  Green
  fetching  ■ #0064ff  Sky Blue
  waiting   ■ #ff8c00  Amber
  success   ■ #fff0e6  Warm White
  error     ■ #ff1e1e  Red
```

Color semantics follow HCI / traffic-light color theory:
- **Blue family** (thinking/reading/writing/fetching): active cognitive work
- **Green** (querying): gathering, searching, exploring
- **Orange/Amber** (executing/waiting): caution, side effects, blocking
- **Red** (error): stop, attention required
- **Warm White** (success): task resolved

---

## Protocol Reference

The Cube Lite uses a **superset** of the standard Yeelight LAN protocol on TCP port 55443:

### Initialization

```json
{"id":1,"method":"activate_fx_mode","params":[{"mode":"direct"}]}
{"id":1,"method":"set_bright","params":[50]}
```

### Pixel Data Format

```json
{"id":1,"method":"update_leds","params":["<400-character base64>"]}
```

Each of the 100 pixels is 3 bytes (RGB) → base64 encoded → 4 ASCII characters. Total: `100 × 4 = 400` characters.

### Encoding Example

```
Pixel #0: RGB(255, 128, 64) → bytes ff 80 40 → base64 "/4BA"
Pixel #1: RGB(0, 0, 0)      → bytes 00 00 00 → base64 "AAAA"
...
Full array: "/4BAAAAAAAAAA..." (400 chars)
```

### Key Constraints

| Constraint | Value | Reason |
|-----------|-------|--------|
| TCP connections | **1 at a time** | Cube firmware crashes on concurrent connections |
| Min command interval | **100ms** | TCP stack is fragile on embedded device |
| FX mode timeout | **~25 seconds** | Must re-send `activate_fx_mode` before expiry |
| Socket close | **RST (SO_LINGER 0)** | Avoids TIME_WAIT exhaustion |
| Discovery | **Zeroconf/mDNS** | Model: `yeelink.light.clt6pro`, `cubelite` |

---

## Setup for Cube Lite

1. Install the **Yeelight Station app** (NOT the standard Yeelight app)
2. Pair the Cube Lite and connect it to your 2.4GHz WiFi
3. Enable **LAN Control** in the device settings
4. Note the device IP address
5. Run: `yeelight-bridge discover` — the Cube Lite will show as 🧊

```bash
yeelight-bridge setup      # discover + configure
yeelight-bridge start <ip> # auto-detects Cube Lite
yeelight-bridge test thinking  # verify: should show blue "THINK"
```

---

## Additional States

### off

All pixels dark. `set_bright(0)`. Used when relay shuts down or `yeelight-bridge stop` is called.

### stop (relay shutdown)

Restores the Cube Lite to a neutral state:
1. Cancels any running animation
2. Sends `set_bright(0)` (backlight off)
3. Closes TCP connection with RST

---

## State Aliases

For backward compatibility with existing Claude Code / Pi Agent hooks:

| Alias | Resolves To |
|-------|-------------|
| `green` | `idle` |
| `orange` | `waiting` |
| `flash` | `thinking` |
| `context` | `querying` |
| `bash` | `executing` |
| `web` | `fetching` |
| `read` | `reading` |
| `write` | `writing` |
| `purple` | `writing` |
| `cyan` | `reading` |

---

## Multi-Session Coordination

The Cube Lite relay supports the same three coordination strategies as the standard bulb relay:

| Strategy | Behavior |
|----------|----------|
| `priority` | Highest-priority state wins (error > executing > writing > ... > idle) |
| `active` | Only active (non-idle) sessions considered; highest-priority wins |
| `carousel` | Cycles through session groups every 3 seconds |

Switch via: `yeelight-bridge strategy <name>`

Priority ordering: `error(0) > fetching(1) > executing(2) > writing(3) > reading(4) > querying(5) > thinking(6) > waiting(7) > idle(8) > success(9)`
