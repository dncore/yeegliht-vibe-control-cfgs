<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/platform-Claude%20Code%20%7C%20Pi%20Agent-orange" alt="Platform">
  <img src="https://img.shields.io/badge/yeelight-lan%20control-brightgreen" alt="Yeelight">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

<p align="center">
  <a href="./README.zh-CN.md">中文</a>
</p>

<h1 align="center">Yeelight Vibe Control</h1>
<h3 align="center">Real-time AI agent status lighting for Yeelight smart bulbs</h3>

---

## What is this?

**Yeelight Vibe Control** turns your Yeelight smart bulb into a real-time status indicator for AI coding agents (Claude Code / Pi Agent). Designed around traffic-light color theory and HCI principles, the bulb lets you know **at a glance** what the AI is doing — thinking, reading files, waiting for your input, or hitting an error.

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

## Supported Platforms

| Platform | Integration | Directory |
|----------|------------|-----------|
| **Claude Code** | Official [Hooks system](https://code.claude.com/docs/en/hooks) (6 events) | [`claude-hook/`](./claude-hook/) |
| **Pi Agent** | TypeScript Extension API (10+ events) | [`pi-agent/`](./pi-agent/) |

> 💡 Both versions share the **same relay daemon**. Color mappings are **fully aligned** — same semantic → same light effect, no confusion when switching agents.

## Architecture

```
Claude Code hooks ──→ hooks.py ─┐
                                 ├──→ HTTP ──→ relay (:9877) ──→ TCP ──→ 💡 Bulb
Pi Agent events  ──→ index.ts ──┘
```

- **Relay daemon**: maintains a **single persistent TCP connection** to the bulb; all state changes via HTTP are instant
- **hooks.py / index.ts**: translate each agent's events into light states, send HTTP to relay
- **Aligned colors**: same semantic events across both agents map to the same light effect

## Requirements

| Requirement | Details |
|-------------|---------|
| Python 3.8+ | `pip install yeelight` |
| Yeelight bulb | Enable **LAN Control** in the Yeelight App |
| Same network | Computer and bulb on the same LAN |
| Claude Code or Pi Agent | Respective agent installed |

## Quick Start

### Claude Code

```bash
cd claude-hook
pip install yeelight
python setup.py
# The wizard auto: discovers bulbs → saves config → writes hooks to ~/.claude/settings.json
# Restart Claude Code to apply
```

### Pi Agent

```bash
cp -r pi-agent ~/.pi/agent/extensions/yeelight-vibe
# Start pi, run /yeelight-setup to configure bulbs
# Run /yeelight-test to preview light effects
```

## State Color Reference

Both agents map **same semantic events to same light effects**.

| Semantic | Pi Agent Event | Claude Code Event | Light Effect | RGB |
|----------|---------------|-------------------|-------------|-----|
| Working | `agent_start` | `UserPromptSubmit` | 🟦 blue breathe | (0,68,255) |
| Waiting for you | `user_bash` | `PreToolUse(permission:ask)` | 🟧 amber solid | (255,140,0) |
| Reading files | `tool_call(read)` | `PreToolUse(Read)` | 🟦 cyan breathe | (0,200,255) |
| Writing files | `tool_call(write)` | `PreToolUse(Write)` | 🟪 magenta breathe | (255,50,120) |
| Running commands | `tool_call(bash)` | `PreToolUse(Bash)` | 🟧 orange breathe | (220,90,0) |
| Fetching web | `tool_call(web)` | `PreToolUse(WebFetch)` | 🟦 blue flash | (0,100,255) |
| Querying context | `context` | — | 🟩 green breathe | (0,160,100) |
| Tool OK | `tool_result(ok)` | `PostToolUse(ok)` | 🟦 blue breathe | (0,68,255) |
| Tool error | `tool_result(err)` | `PostToolUse(err)` | 🟥 red solid | (255,30,30) |
| Task done | `agent_end` | `Stop` | 🟩 green solid | (0,220,80) |

## Project Structure

```
yeelight-vibe-control-cfgs/
├── .gitignore
├── README.md                     ← you are here
├── README.zh-CN.md               ← 中文版
│
├── claude-hook/                  ← Claude Code version
│   ├── hooks.py                  # Hook event handler (6 events)
│   ├── yeelight_relay.py         # HTTP relay daemon (persistent TCP)
│   ├── yeelight_discover.py      # LAN device discovery
│   ├── setup.py                  # One-click setup wizard
│   ├── settings.json             # Hook config template
│   ├── bulbs.json                # Bulb config (auto-generated)
│   └── README.md
│
└── pi-agent/                     ← Pi Agent version
    ├── index.ts                  # Pi extension entry (TypeScript)
    ├── yeelight_relay.py         # HTTP relay daemon (shared with claude-hook)
    ├── yeelight_discover.py      # LAN device discovery (shared with claude-hook)
    ├── yeelight_ctl.py           # CLI control script
    ├── bulbs.json                # Bulb config (auto-generated)
    └── README.md
```

## Design Notes

- **Color system**: traffic light + HCI color theory. Red = stop/error, Green = go/done, Blue = info/thinking, Orange = caution/waiting
- **Persistent connection**: the relay daemon holds a single TCP connection to the bulb, avoiding frequent handshakes and connection races
- **Multi-instance safe**: relay has built-in priority coordination; multiple agent sessions don't conflict
- **Timeout protection**: stdin reads have a 2-second timeout to prevent Claude Code TUI freeze

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Can't discover bulb | Check LAN Control is enabled in Yeelight App |
| Bulb not responding | Verify the IP; power-cycle the bulb |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` |
| Hooks not firing | Check settings.json path; restart Claude Code |
| Relay fails to start | Ensure Python 3.8+ and yeelight package installed |
| Claude Code TUI freeze | Use latest hooks.py (includes stdin timeout fix) |

## License

MIT
