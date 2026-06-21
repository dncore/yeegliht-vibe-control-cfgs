<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/platform-Claude%20Code%20%7C%20Pi%20Agent-orange" alt="Platform">
  <img src="https://img.shields.io/badge/yeelight-lan%20control-brightgreen" alt="Yeelight">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

<h1 align="center">Yeelight Vibe Bridge</h1>
<h3 align="center">AI 智能体实时状态灯光 — Yeelight 智能灯泡</h3>

---

## 这是什么？

**Yeelight Vibe Bridge** 让你的 Yeelight 智能灯泡变成 AI 编程助手的实时状态指示灯。基于交通信号灯色彩理论和人机交互 (HCI) 原则设计，一眼就知道 AI 在做什么 — 思考、读文件、等你输入、还是出错了。

```
🟦 蓝色呼吸 → 思考中
🟧 橙色呼吸 → 执行命令
🟦 青色呼吸 → 读取文件
🟪 玫红呼吸 → 写入/编辑
🟦 蓝色闪烁 → 访问网络
🟩 绿色呼吸 → 查询上下文
🟧 琥珀常亮 → 等待你确认
🟥 正红常亮 → 出错了
🟩 翠绿常亮 → 任务完成
```

## 架构

```
                      ┌─────────────────────────────────┐
                      │  ~/.yeelight-vibe-bridge/        │  ← 公共桥接层
                      │  ├── yeelight_relay.py           │     (独立安装)
                      │  ├── yeelight_bridge.py          │
                      │  ├── yeelight_discover.py        │
                      │  └── bulbs.json                  │
                      └──────────┬──────────────────────┘
                                 │ HTTP (:9877)
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ Claude   │ │ Pi Agent │ │  未来    │  ← 可选适配器
              │ Code     │ │          │ │  智能体  │     (各自安装)
              └──────────┘ └──────────┘ └──────────┘
```

### 设计原则

| 层 | 职责 | 位置 |
|----|------|------|
| **Bridge** (公共核心) | Relay 守护进程、灯泡发现、多 session 协调、HTTP API | `~/.yeelight-vibe-bridge/` |
| **Adapters** (智能体适配器) | 极薄的事件翻译：agent 事件 → HTTP → bridge | 各 agent 配置目录 |

### 关键特性

- **单一 relay 守护进程**：与灯泡保持一条持久 TCP 连接，所有 agent 共享
- **多 session / 跨 agent 协调**：relay 的 `/api/state` 使用优先级聚合（`yeelight-shared.json`），过期 session 30 秒自动淘汰
- **解耦设计**：bridge 核心安装一次；适配器可选、轻量、可扩展 — 随时添加新智能体
- **颜色对齐**：所有 agent 相同语义事件 → 相同灯光效果

## 支持的适配器

| 适配器 | 集成方式 | 目录 |
|--------|---------|------|
| **Claude Code** | 官方 [Hooks 系统](https://code.claude.com/docs/en/hooks)（6 种事件） | [`adapters/claude-code/`](./adapters/claude-code/) |
| **Pi Agent** | TypeScript 扩展 API（10+ 事件） | [`adapters/pi-agent/`](./adapters/pi-agent/) |

## 环境要求

| 要求 | 说明 |
|------|------|
| Python 3.8+ | `pip install yeelight` |
| Yeelight 灯泡 | 在 Yeelight App 中开启**局域网控制** |
| 同一网络 | 电脑和灯泡在同一局域网 |

## 快速开始

```bash
# 1. 安装 bridge（一条命令）
pip install .
yeelight-bridge setup
# 交互式: 发现灯泡 → 保存配置 → 安装到 ~/.yeelight-vibe-bridge/

# 2. 安装智能体适配器

# Claude Code:
yeelight-bridge adapter claude-code
# 重启 Claude Code 生效

# Pi Agent:
yeelight-bridge adapter pi-agent  # 显示安装说明
# 或: cp -r adapters/pi-agent ~/.pi/agent/extensions/yeelight-vibe
```

## 灯光状态参考

所有 agent 相同语义事件 → 相同灯光效果。

| 语义 | 灯光效果 | RGB |
|------|---------|-----|
| 工作/思考中 | 🟦 蓝色呼吸 | (0,68,255) |
| 等待你确认 | 🟧 琥珀常亮 | (255,140,0) |
| 读取文件 | 🟦 青色呼吸 | (0,200,255) |
| 写入文件 | 🟪 玫红呼吸 | (255,50,120) |
| 执行命令 | 🟧 橙色呼吸 | (220,90,0) |
| 访问网络 | 🟦 蓝色闪烁 | (0,100,255) |
| 查询上下文 | 🟩 绿色呼吸 | (0,160,100) |
| 出错 | 🟥 正红常亮 | (255,30,30) |
| 任务完成 | 🟩 翠绿常亮 | (0,220,80) |

## 项目结构

```
yeelight-vibe-bridge/
├── .gitignore
├── README.md
├── README.zh-CN.md
│
├── bridge/                         ← 公共桥接层（必须先安装）
│   ├── yeelight_relay.py           # HTTP relay 守护进程
│   ├── yeelight_discover.py        # 局域网设备发现
│   ├── yeelight_bridge.py          # bridge 管理 CLI
│   ├── setup.py                    # bridge 一键安装向导
│   └── bulbs.json                  # 灯泡配置模板
│
└── adapters/                       ← 智能体适配器（可选、可扩展）
    ├── claude-code/
    │   ├── hooks.py                # Claude Code hook → HTTP (极薄)
    │   ├── settings.json           # hook 配置模板
    │   ├── setup.py                # Claude Code 适配器安装
    │   └── README.md
    │
    └── pi-agent/
        ├── index.ts                # Pi Agent 扩展 → HTTP (极薄)
        └── README.md
```

## 设计说明

- **色彩系统**：交通信号灯 + HCI 色彩理论。红 = 停止/错误，绿 = 完成/通过，蓝 = 信息/思考，橙 = 注意/等待
- **持久连接**：relay 守护进程与灯泡保持单一 TCP 连接，避免频繁握手和连接竞争
- **多实例安全**：relay 内置优先级协调。多个 session/agent 不冲突 — 高优先级状态胜出（error > executing > writing > reading > thinking > waiting > idle）
- **生命周期**：relay 守护进程跨 session 存活，无 session 独占。过期条目 30 秒自动淘汰
- **可扩展**：添加新智能体只需写一个 ~100 行的薄适配器，映射事件到 HTTP 调用

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| 无法发现灯泡 | 检查 Yeelight App 中是否开启局域网控制 |
| 灯泡不响应 | 确认 IP 正确；重启灯泡 |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` |
| Hooks 不触发 | 检查 `~/.claude/settings.json`；重启 Claude Code |
| Bridge relay 未运行 | `python ~/.yeelight-vibe-bridge/yeelight_bridge.py start` |
| Pi Agent 连不上 bridge | 先安装 bridge: `python bridge/setup.py` |
| Claude Code TUI 冻结 | hooks 使用 readline() + 超时，不会冻结 |
| 多个 agent 抢灯 | 所有 session 走同一 relay 端口 9877；优先级聚合处理 |

## 许可证

MIT
