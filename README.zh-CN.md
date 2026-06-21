<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/platform-Claude%20Code%20%7C%20Pi%20Agent-orange" alt="Platform">
  <img src="https://img.shields.io/badge/yeelight-lan%20control-brightgreen" alt="Yeelight">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

<p align="center">
  <a href="./README.md">English</a>
</p>

<h1 align="center">Yeelight Vibe Control</h1>
<h3 align="center">让智能灯实时显示 AI 编程助手的工作状态</h3>

---

## 这是什么？

**Yeelight Vibe Control** 让你的 Yeelight 智能灯泡实时反映 AI 编程助手（Claude Code / Pi Agent）的运行状态。基于交通信号灯 + HCI 人机交互色彩理论设计，通过灯光**一眼看出** AI 正在做什么——在思考？在读文件？在等你确认？还是出错了？

```
🟦 蓝呼吸   → 思考中
🟧 橙呼吸   → 执行命令
🟦 青呼吸   → 读取文件
🟪 玫红呼吸 → 写入/编辑
🟦 蓝闪烁   → 访问网络
🟩 绿呼吸   → 查询上下文
🟧 琥珀常亮 → 等待用户确认
🟥 正红常亮 → 出错了
🟩 翠绿常亮 → 任务完成
```

## 支持平台

| 平台 | 集成方式 | 目录 |
|------|---------|------|
| **Claude Code** | 官方 [Hooks 系统](https://code.claude.com/docs/en/hooks) (6 种事件) | [`claude-hook/`](./claude-hook/) |
| **Pi Agent** | TypeScript 扩展 API (10+ 种事件) | [`pi-agent/`](./pi-agent/) |

> 💡 两个版本**共享同一套 relay 守护进程**。灯光颜色映射**完全对齐**——相同语义 = 相同灯光，切换 agent 不困惑。

## 架构

```
Claude Code hooks ──→ hooks.py ─┐
                                 ├──→ HTTP ──→ relay (:9877) ──→ TCP ──→ 💡 灯泡
Pi Agent 事件    ──→ index.ts ──┘
```

- **relay 守护进程**: 保持**单一持久 TCP 连接**到灯泡，所有状态变化通过 HTTP 瞬时完成
- **hooks.py / index.ts**: 将各自 agent 的事件映射为灯光状态，发 HTTP 到 relay
- **颜色对齐**: 两个 agent 的相同语义事件映射到相同灯光效果

## 前提条件

| 要求 | 说明 |
|------|------|
| Python 3.8+ | `pip install yeelight` |
| Yeelight 灯泡 | 在 Yeelight App 中开启「局域网控制」 |
| 同一局域网 | 电脑和灯泡在同一网络 |
| Claude Code 或 Pi Agent | 对应 agent 已安装 |

## 快速开始

### Claude Code

```bash
cd claude-hook
pip install yeelight
python setup.py
# 向导自动完成: 发现灯泡 → 保存配置 → 写入 ~/.claude/settings.json hooks
# 重启 Claude Code 生效
```

### Pi Agent

```bash
cp -r pi-agent ~/.pi/agent/extensions/yeelight-vibe
# 启动 pi，运行 /yeelight-setup 配置灯泡
# 运行 /yeelight-test 测试灯光效果
```

## 状态颜色参考

两种 agent 的**相同语义事件映射到相同灯光效果**。

| 语义 | Pi Agent 事件 | Claude Code 事件 | 灯光效果 | RGB |
|------|--------------|-----------------|---------|-----|
| 开始工作 | `agent_start` | `UserPromptSubmit` | 🟦 蓝呼吸 | (0,68,255) |
| 等用户操作 | `user_bash` | `PreToolUse(permission:ask)` | 🟧 琥珀常亮 | (255,140,0) |
| 读文件 | `tool_call(read)` | `PreToolUse(Read)` | 🟦 青呼吸 | (0,200,255) |
| 写文件 | `tool_call(write)` | `PreToolUse(Write)` | 🟪 玫红呼吸 | (255,50,120) |
| 执行命令 | `tool_call(bash)` | `PreToolUse(Bash)` | 🟧 橙呼吸 | (220,90,0) |
| 访问网络 | `tool_call(web)` | `PreToolUse(WebFetch)` | 🟦 蓝闪烁 | (0,100,255) |
| 查询上下文 | `context` | — | 🟩 绿呼吸 | (0,160,100) |
| 工具成功 | `tool_result(ok)` | `PostToolUse(ok)` | 🟦 蓝呼吸 | (0,68,255) |
| 工具出错 | `tool_result(err)` | `PostToolUse(err)` | 🟥 正红常亮 | (255,30,30) |
| 任务完成 | `agent_end` | `Stop` | 🟩 翠绿常亮 | (0,220,80) |

## 项目结构

```
yeelight-vibe-control-cfgs/
├── .gitignore
├── README.md                     ← 英文版
├── README.zh-CN.md               ← 你在这里
│
├── claude-hook/                  ← Claude Code 版
│   ├── hooks.py                  # Hook 事件处理 (全部 6 种事件)
│   ├── yeelight_relay.py         # HTTP relay 守护进程 (持久 TCP)
│   ├── yeelight_discover.py      # 局域网设备发现
│   ├── setup.py                  # 一键安装向导 (扫描/验证/写入 hooks)
│   ├── settings.json             # Hook 配置模板
│   ├── bulbs.json                # 灯泡配置 (自动生成)
│   └── README.md
│
└── pi-agent/                     ← Pi Agent 版
    ├── index.ts                  # Pi 扩展入口 (TypeScript)
    ├── yeelight_relay.py         # HTTP relay 守护进程 (与 claude-hook 共享)
    ├── yeelight_discover.py      # 局域网设备发现 (与 claude-hook 共享)
    ├── yeelight_ctl.py           # CLI 控制脚本
    ├── bulbs.json                # 灯泡配置 (自动生成)
    └── README.md
```

## 设计笔记

- **颜色体系**: 交通信号灯 + HCI 色彩理论。红色 = 停止/错误，绿色 = 通过/完成，蓝色 = 信息/思考，橙色 = 警告/等待
- **持久连接**: relay 守护进程保持单一 TCP 连接到灯泡，避免频繁握手和连接数竞争
- **多实例安全**: relay 内置优先级协调机制，多个 agent 会话同时运行时不会冲突
- **超时保护**: stdin 读取带 2 秒超时，防止 Claude Code TUI 卡死

## 故障排查

| 问题 | 解决 |
|------|------|
| 扫描不到灯泡 | 检查「局域网控制」是否在 Yeelight App 中开启 |
| 灯不响应 | 确认 IP 正确；尝试给灯泡断电重启 |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` |
| hooks 不触发 | 检查 settings.json 路径；重启 Claude Code |
| relay 启动失败 | 确认 Python 3.8+ 且 yeelight 包已安装 |
| Claude Code TUI 卡死 | 使用最新版 hooks.py（含 stdin 超时保护） |

## License

MIT
