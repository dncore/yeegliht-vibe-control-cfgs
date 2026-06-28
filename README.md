<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/platform-Claude%20Code%20%7C%20Pi%20Agent-orange" alt="Platform">
  <img src="https://img.shields.io/badge/yeelight-lan%20control-brightgreen" alt="Yeelight">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

<p align="center">
  <a href="./README.zh-CN.md">中文</a>
</p>

<h1 align="center">Yeelight Vibe Bridge</h1>
<h3 align="center">Real-time AI agent status lighting for Yeelight smart bulbs</h3>

---

## What is this?

**Yeelight Vibe Bridge** turns your Yeelight smart bulb into a real-time status indicator for AI coding agents. Designed around traffic-light color theory and HCI principles, the bulb lets you know **at a glance** what the AI is doing — thinking, reading files, waiting for your input, or hitting an error.

```
🟦 blue breathe   → thinking
🟧 orange breathe → executing commands
🟦 cyan breathe   → reading files
🟪 magenta breathe → writing/editing
🟦 blue flash    → fetching web
🟩 green breathe  → querying context
🟧 amber solid   → waiting for you
🟥 red solid     → error
⬜ warm white    → task done
```

## Architecture

```
                      ┌─────────────────────────────────┐
                      │  ~/.yeelight-vibe-bridge/        │  ← bridge core
                      │  ├── yeelight_relay.py           │     (install once)
                      │  ├── yeelight_bridge.py          │
                      │  ├── yeelight_discover.py        │
                      │  └── bulbs.json                  │
                      └──────────┬──────────────────────┘
                                 │ HTTP (:9877)
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Claude   │ │ Pi Agent │ │  (future │  ← adapters
              │ Code     │ │          │ │  agents) │     (optional)
              └──────────┘ └──────────┘ └──────────┘
```

### Design Principles

| Layer | Role | Location |
|-------|------|----------|
| **Bridge** (core platform) | Relay daemon, bulb discovery, multi-session coordination, HTTP API | `~/.yeelight-vibe-bridge/` |
| **Adapters** (agent plugins) | Thin translation layer: agent events → HTTP → bridge | Per-agent config dirs |

### Key Features

- **Single relay daemon**: one persistent TCP connection to bulb, shared by all agents
- **Multi-session & cross-agent coordination**: relay's `/api/state` uses priority aggregation (`yeelight-shared.json`). Stale sessions auto-expire after 30s.
- **Decoupled**: bridge core installed once. Adapters are optional, lightweight, and extensible — ready for future agents.
- **Aligned colors**: same semantic events across all agents map to the same light effect

## Supported Adapters

| Adapter | Integration | Directory |
|---------|------------|-----------|
| **Claude Code** | Official [Hooks system](https://code.claude.com/docs/en/hooks) (6 events) | [`adapters/claude-code/`](./adapters/claude-code/) |
| **Pi Agent** | TypeScript Extension API (10+ events) | [`adapters/pi-agent/`](./adapters/pi-agent/) |

## Requirements

| Requirement | Details |
|-------------|---------|
| Python 3.8+ | `pip install yeelight` |
| Yeelight bulb | Enable **LAN Control** in the Yeelight App (Cube Lite: use **Yeelight Station** app) |
| Same network | Computer and bulb on the same LAN |
| Cube Lite | See [Cube Lite Pixel Art Reference](docs/cube-lite-pixel-art.md) for matrix display details |

## Quick Start

```bash
# 1. Install bridge
pip install .
yeelight-bridge setup
# Interactive wizard: discovers bulbs → saves config → installs to ~/.yeelight-vibe-bridge/

# 2. Start relay
yeelight-bridge start

# 3. Install adapter for your agent
yeelight-bridge adapter claude-code      # Claude Code: restart to apply
yeelight-bridge adapter pi-agent         # Pi Agent: shows copy instructions
```

### Arch Linux / PEP 668

Arch Linux enforces [PEP 668](https://peps.python.org/pep-0668/) — direct `pip install` is blocked. Use one of:

**Option 1: pipx (recommended for CLI tools)**
```bash
sudo pacman -S python-pipx          # install pipx if needed
pipx ensurepath                     # add ~/.local/bin to PATH
pipx install .                      # install yeelight-vibe-bridge
```

**Option 2: venv + symlink**
```bash
python -m venv .venv
.venv/bin/pip install .
ln -sf "$(pwd)/.venv/bin/yeelight-bridge" ~/.local/bin/yeelight-bridge
```

Then proceed with `yeelight-bridge setup` as normal.

## CLI Reference

All commands via `yeelight-bridge <command> [args...]`.

### Setup & Management

| Command | Description |
|---------|-------------|
| `setup` | Full setup wizard: discover bulbs, save config, install bridge |
| `install` | Install bridge files to `~/.yeelight-vibe-bridge/` only |
| `adapter <name>` | Install agent adapter (`claude-code` / `pi-agent`) |

### Relay Lifecycle

| Command | Description |
|---------|-------------|
| `start [ip]` | Start relay daemon (auto-detects bulb from config) |
| `stop` | Gracefully stop relay and restore bulb to warm white |
| `status` | Show relay health, bulb connection, active sessions, strategy |

### Bulb Discovery & Config

| Command | Description |
|---------|-------------|
| `discover` | Scan LAN for Yeelight bulbs (SSDP + TCP scan + reverse DNS) |
| `setup-bulbs` | Interactive menu: add, remove, rename bulbs, set default |
| `test <state> [ip]` | Send a light state directly to the bulb for testing |

### Coordination

| Command | Description |
|---------|-------------|
| `strategy <name>` | Switch coordination strategy: `priority`, `active`, or `carousel` |

### Discovery Output

```
$ yeelight-bridge discover

  ✅ Found 1 device:
    1. yeelink-light-color8_mibt2EF1.lan (192.168.2.205) [yeelink.light.color8]
```

Device names are resolved via:
1. SSDP broadcast name
2. Bulb `get_properties()` name
3. **Reverse DNS** hostname (e.g. `yeelink-light-color8_mibt2EF1.lan`)
4. Fallback: `Yeelight-{ip}`

Model is extracted from SSDP, `get_properties()`, or hostname pattern matching.

## State Color Reference

All agents map **same semantic events to same light effects**.

**Standard Bulb** — single-color breathing/flashing effects.  
**Cube Lite** — dot matrix text display. See **[Cube Lite Pixel Art Reference](docs/cube-lite-pixel-art.md)** for ASCII renderings of all 10 states on the 20×5 LED matrix.

| Semantic | Standard Bulb Effect | Cube Lite Display | RGB |
|----------|---------------------|-------------------|-----|
| Working / Thinking | 🟦 blue breathe | `THINK` blue breathe | (0,68,255) |
| Waiting for you | 🟧 amber solid | `WAIT` amber pulse | (255,140,0) |
| Reading files | 🟦 cyan breathe | `READ` cyan breathe | (0,200,255) |
| Writing files | 🟪 magenta breathe | `WRITE` magenta breathe | (255,50,120) |
| Running commands | 🟧 orange breathe | `EXEC` orange breathe | (220,90,0) |
| Fetching web | 🟦 blue flash | `FETCH` sky blue flash | (0,100,255) |
| Querying context | 🟩 green breathe | `QUERY` green breathe | (0,160,100) |
| Error | 🟥 red solid | `ERR!` red blink | (255,30,30) |
| Task done | ⬜ warm white solid | `DONE` warm white | (255,240,230) | bri=30% |

## Project Structure

```
yeelight-vibe-bridge/
├── .gitignore
├── README.md
├── README.zh-CN.md
│
├── bridge/                         ← core platform (install first)
│   ├── yeelight_relay.py           # HTTP relay daemon
│   ├── yeelight_discover.py        # LAN device discovery
│   ├── yeelight_bridge.py          # bridge management CLI
│   ├── setup.py                    # one-click installer
│   └── bulbs.json                  # bulb config template
│
└── adapters/                       ← agent adapters (optional, extensible)
    ├── claude-code/
    │   ├── hooks.py                # Claude Code hook → HTTP (Python)
    │   ├── hooks.js                # Claude Code hook → HTTP (Node.js, faster)
    │   ├── settings.json           # hook config template
    │   ├── setup.py                # Claude Code adapter installer
    │   └── README.md
    │
    └── pi-agent/
        ├── index.ts                # Pi Agent extension → HTTP (thin)
        └── README.md
```

## Design Notes

- **Color system**: traffic light + HCI color theory. Red = stop/error, Green = go/done, Blue = info/thinking, Orange = caution/waiting
- **Persistent connection**: the relay daemon holds a single TCP connection to the bulb, avoiding frequent handshakes and connection races
- **Multi-instance safe**: relay has built-in priority coordination. Multiple sessions/agents don't conflict — higher-priority state wins (error > executing > writing > reading > thinking > waiting > idle)
- **Bridge lifetime**: relay daemon stays alive across sessions. No session "owns" it. Stale entries expire after 30s.
- **Extensible**: to add a new agent, just write a thin adapter (~100 lines) that maps its events to HTTP calls
- **Cross-platform**: tested on Windows, macOS, and Linux. Platform-specific code paths for process management, network discovery, and Python detection

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't discover bulb | Check LAN Control is enabled in Yeelight App |
| Bulb not responding | Verify the IP; restart bulb and relay: `yeelight-bridge stop && yeelight-bridge start` |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` in the Python used by the relay |
| Hooks not firing | Check `~/.claude/settings.json`; restart Claude Code |
| `yeelight-bridge` command not found | Re-run `pip install .` to rebuild the entry point |
| `externally-managed-environment` (Arch) | Use `pipx install .` or a venv — see [Arch Linux](#arch-linux--pep-668) section |
| Discover shows wrong/old name | Restart relay after bulb rename: `yeelight-bridge stop && yeelight-bridge start` |
| Discover times out | Kill zombie relay processes and restart: `yeelight-bridge stop && yeelight-bridge start` |
| Multiple relay processes (Windows) | `yeelight-bridge stop` kills one; use `python -c "import subprocess; ..."` to kill all on port 9877 |
| Bulb model shows "unknown" | Bulb firmware doesn't report model via `get_properties()`; model extracted from DNS hostname if available |
| Claude Code hook takes seconds | Node.js adapter is fastest (~150ms); ensure hooks.js is used, not hooks.py |
| Light doesn't change on permission dialog | Claude Code doesn't send hook events for permission dialogs; light shows tool state (e.g. orange breathe for executing) |

## License

MIT
