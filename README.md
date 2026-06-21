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
🟩 green solid   → task done
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
| Yeelight bulb | Enable **LAN Control** in the Yeelight App |
| Same network | Computer and bulb on the same LAN |

## Quick Start

### 1. Install Bridge (required — once for all agents)

```bash
cd bridge
pip install yeelight
python setup.py
# Interactive wizard: discovers bulbs → saves config → installs to ~/.yeelight-vibe-bridge/
```

### 2. Install Agent Adapter (optional — pick your agent)

**Claude Code:**
```bash
cd adapters/claude-code
python setup.py
# Writes hooks config to ~/.claude/settings.json → restart Claude Code
```

**Pi Agent:**
```bash
cp -r adapters/pi-agent ~/.pi/agent/extensions/yeelight-vibe
# Start pi, all bulbs/config managed by bridge
```

## State Color Reference

All agents map **same semantic events to same light effects**.

| Semantic | Light Effect | RGB |
|----------|-------------|-----|
| Working / Thinking | 🟦 blue breathe | (0,68,255) |
| Waiting for you | 🟧 amber solid | (255,140,0) |
| Reading files | 🟦 cyan breathe | (0,200,255) |
| Writing files | 🟪 magenta breathe | (255,50,120) |
| Running commands | 🟧 orange breathe | (220,90,0) |
| Fetching web | 🟦 blue flash | (0,100,255) |
| Querying context | 🟩 green breathe | (0,160,100) |
| Error | 🟥 red solid | (255,30,30) |
| Task done | 🟩 green solid | (0,220,80) |

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
    │   ├── hooks.py                # Claude Code hook → HTTP (thin)
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

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't discover bulb | Check LAN Control is enabled in Yeelight App |
| Bulb not responding | Verify the IP; power-cycle the bulb |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` |
| Hooks not firing | Check `~/.claude/settings.json`; restart Claude Code |
| Bridge relay not running | `python ~/.yeelight-vibe-bridge/yeelight_bridge.py start` |
| Pi Agent bridge unreachable | Run bridge setup first: `python bridge/setup.py` |
| Claude Code TUI freeze | Hooks use readline() with timeout; should not freeze |
| Multiple agents clashing | All sessions use same relay on port 9877; priority aggregation handles it |

## License

MIT
