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
⬜ 暖白微光 → 任务完成
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
| Yeelight 灯泡 | 在 Yeelight App 中开启**局域网控制**（Cube Lite：使用 **Yeelight Station** app） |
| 同一网络 | 电脑和灯泡在同一局域网 |
| Cube Lite | 点阵显示请参阅 [Cube Lite 像素艺术参考](docs/cube-lite-pixel-art.md) |

## 快速开始

```bash
# 1. 安装 bridge
pip install .
yeelight-bridge setup
# 交互式向导: 发现灯泡 → 保存配置 → 安装到 ~/.yeelight-vibe-bridge/

# 2. 启动 relay
yeelight-bridge start

# 3. 安装智能体适配器
yeelight-bridge adapter claude-code      # Claude Code: 重启生效
yeelight-bridge adapter pi-agent         # Pi Agent: 显示复制说明
```

### 升级

已有安装如何升级（例如添加 Cube Lite 支持，或拉取新功能）：

```bash
# 1. 拉取最新代码并重装 bridge
cd yeelight-vibe-control-cfgs
git pull
pip install .
yeelight-bridge install       # 复制更新后的模块到 ~/.yeelight-vibe-bridge/

# 2. 重启 relay（自动检测设备类型：标准灯泡或 Cube Lite）
yeelight-bridge stop
yeelight-bridge start         # 使用已保存的默认灯泡 IP
# 或: yeelight-bridge start <ip>

# 3. 验证
yeelight-bridge status        # 显示设备类型 + 连接状态
yeelight-bridge test thinking # 快速冒烟测试
```

> **注意：** Claude Code / Pi Agent 适配器升级后**无需**重新安装。HTTP API 向后兼容 — relay 会自
动检测设备类型（标准灯泡或 Cube Lite）并路由相应指令。

### Arch Linux / PEP 668

Arch Linux 强制执行 [PEP 668](https://peps.python.org/pep-0668/)，直接 `pip install` 会被阻止。选用以下方式之一：

**方式一：pipx（推荐 CLI 工具首选）**
```bash
sudo pacman -S python-pipx          # 安装 pipx（如未安装）
pipx ensurepath                     # 将 ~/.local/bin 加入 PATH
pipx install .                      # 安装 yeelight-vibe-bridge
```

**方式二：venv + 符号链接**
```bash
python -m venv .venv
.venv/bin/pip install .
ln -sf "$(pwd)/.venv/bin/yeelight-bridge" ~/.local/bin/yeelight-bridge
```

然后正常执行 `yeelight-bridge setup`。

## CLI 命令参考

所有命令: `yeelight-bridge <命令> [参数...]`

### 安装与管理

| 命令 | 说明 |
|------|------|
| `setup` | 完整安装向导: 发现灯泡、保存配置、安装 bridge |
| `install` | 仅安装 bridge 文件到 `~/.yeelight-vibe-bridge/` |
| `adapter <名称>` | 安装智能体适配器 (`claude-code` / `pi-agent`) |

### Relay 生命周期

| 命令 | 说明 |
|------|------|
| `start [ip]` | 启动 relay 守护进程（自动从配置读取灯泡 IP） |
| `stop` | 优雅停止 relay，恢复灯泡为暖白光 |
| `status` | 查看 relay 健康、灯泡连接、活跃会话、协调策略 |

### 灯泡发现与配置

| 命令 | 说明 |
|------|------|
| `discover` | 扫描局域网 Yeelight 设备（SSDP + TCP 扫描 + 反向 DNS） |
| `setup-bulbs` | 交互式菜单: 添加、删除、重命名灯泡，设置默认 |
| `test <状态> [ip]` | 直接发送灯光状态测试 |

### 协调策略

| 命令 | 说明 |
|------|------|
| `strategy <名称>` | 切换协调策略: `priority`（优先级）、`active`（活跃优先）、`carousel`（分组轮播） |

### 发现输出示例

```
$ yeelight-bridge discover

  ✅ 发现 1 个设备:
    1. yeelink-light-color8_mibt2EF1.lan (192.168.2.205) [yeelink.light.color8]
```

设备名称获取优先级:
1. SSDP 广播名称
2. 灯泡 `get_properties()` 返回的名称
3. **反向 DNS** 主机名（如 `yeelink-light-color8_mibt2EF1.lan`）
4. 兜底: `Yeelight-{ip}`

型号从 SSDP、`get_properties()` 或主机名正则匹配获取。
# 或: cp -r adapters/pi-agent ~/.pi/agent/extensions/yeelight-vibe
```

## 灯光状态参考

所有 agent 相同语义事件 → 相同灯光效果。

**标准灯泡** — 单色呼吸/闪烁效果。  
**Cube Lite** — 点阵文字显示。所有 10 种状态的 20×5 LED 矩阵 ASCII 图示详见 **[Cube Lite 像素艺术参考](docs/cube-lite-pixel-art.md)**。

| 语义 | 标准灯泡 | Cube Lite 显示 | RGB |
|------|---------|---------------|-----|
| 工作/思考中 | 🟦 蓝色呼吸 | `THINK` 蓝呼吸 | (0,68,255) |
| 等待你确认 | 🟧 琥珀常亮 | `WAIT` 琥珀慢脉冲 | (255,140,0) |
| 读取文件 | 🟦 青色呼吸 | `READ` 青呼吸 | (0,200,255) |
| 写入文件 | 🟪 玫红呼吸 | `WRITE` 玫红呼吸 | (255,50,120) |
| 执行命令 | 🟧 橙色呼吸 | `EXEC` 橙呼吸 | (220,90,0) |
| 访问网络 | 🟦 蓝色闪烁 | `FETCH` 天蓝闪烁 | (0,100,255) |
| 查询上下文 | 🟩 绿色呼吸 | `QUERY` 绿呼吸 | (0,160,100) |
| 出错 | 🟥 正红常亮 | `ERR!` 红闪烁 | (255,30,30) |
| 任务完成 | ⬜ 暖白微光 | `DONE` 暖白 | (255,240,230) |

## 项目结构

```
yeelight-vibe-bridge/
├── .gitignore
├── README.md
├── README.zh-CN.md
│
├── bridge/                         ← 公共桥接层 (先安装)
│   ├── yeelight_relay.py           # HTTP relay 守护进程
│   ├── yeelight_discover.py        # 局域网设备发现
│   ├── yeelight_bridge.py          # bridge 管理 CLI
│   ├── setup.py                    # 一键安装向导
│   └── bulbs.json                  # 灯泡配置模板
│
└── adapters/                       ← 智能体适配器 (可选、可扩展)
    ├── claude-code/
    │   ├── hooks.py                # Claude Code hook → HTTP (薄适配器)
    │   ├── hooks.js                # Node.js 版 (启动更快)
    │   ├── settings.json           # hook 配置模板
    │   ├── setup.py                # Claude Code 适配器安装
    │   └── README.md
    │
    └── pi-agent/
        ├── index.ts                # Pi Agent 扩展 → HTTP (薄适配器)
        └── README.md
```

## 设计说明

- **色彩系统**：交通信号灯 + HCI 色彩理论。红 = 停止/错误，绿 = 完成/通过，蓝 = 信息/思考，橙 = 注意/等待
- **持久连接**：relay 守护进程与灯泡保持单一 TCP 连接，避免频繁握手和连接竞争
- **多实例安全**：relay 内置优先级协调。多个 session/agent 不冲突 — 高优先级状态胜出（error > executing > writing > reading > thinking > waiting > idle）
- **生命周期**：relay 守护进程跨 session 存活，无 session 独占。过期条目 30 秒自动淘汰
- **可扩展**：添加新智能体只需写一个 ~100 行的薄适配器，映射事件到 HTTP 调用
- **跨平台**：支持 Windows、macOS、Linux。进程管理、网络发现、Python 检测均有平台特定适配

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| 无法发现灯泡 | 检查 Yeelight App 中是否开启局域网控制 |
| 灯泡不响应 | 确认 IP；重启灯泡和 relay: `yeelight-bridge stop && yeelight-bridge start` |
| `ModuleNotFoundError: yeelight` | `pip install yeelight`（需在 relay 使用的 Python 中安装） |
| Hooks 不触发 | 检查 `~/.claude/settings.json`；重启 Claude Code |
| `yeelight-bridge` 命令找不到 | 重新运行 `pip install .` 重建入口点 |
| `externally-managed-environment` (Arch) | 用 `pipx install .` 或虚拟环境安装 — 见 [Arch Linux](#arch-linux--pep-668) 章节 |
| Discover 显示旧名称 | 灯泡改名后重启 relay: `yeelight-bridge stop && yeelight-bridge start` |
| Discover 超时 | 杀掉僵尸 relay 进程后重启: `yeelight-bridge stop && yeelight-bridge start` |
| 多个 relay 进程 (Windows) | `yeelight-bridge stop` 只杀一个；需手动杀端口 9877 上所有进程 |
| 灯泡型号显示 "unknown" | 灯泡固件不返回型号；可通过 DNS 主机名推断 |
| Claude Code hook 延迟数秒 | Node.js 版适配器最快 (~150ms)；确保用的 hooks.js |
| 确认对话框时灯不变 | Claude Code 不发送权限确认的 hook 事件；灯显示工具状态（如橙色呼吸） |

## 许可证

MIT
