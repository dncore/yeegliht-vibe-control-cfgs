# Yeelight Vibe Control — Claude Code Hook 版

> [项目主页 / Project Home](../README.md)

让 Yeelight 智能灯实时显示 Claude Code 的运行状态。基于交通信号灯 + HCI 色彩理论设计。

## 与 pi-agent 版的区别

| 特性 | pi-agent 版 | claude-hook 版 |
|------|-----------|---------------|
| 运行平台 | Pi Coding Agent | Claude Code |
| 集成方式 | TypeScript 扩展 API | 官方 Hooks 系统 |
| 配置入口 | `/yeelight-setup` TUI | `python setup.py` CLI |
| 事件系统 | `pi.on("tool_call")` | `PreToolUse` / `PostToolUse` / `Stop` |
| 架构 | TS 扩展 → HTTP → relay | Python hooks → HTTP → relay |
| relay | 共享相同的 yeelight_relay.py | 共享相同的 yeelight_relay.py |

## 环境准备

### 1. Python 环境

需要 Python 3.8+。确认 Python 已安装：

```bash
python --version
# 或
python3 --version
```

### 2. 安装 yeelight Python 包

```bash
pip install yeelight
```

验证安装：

```bash
python -c "import yeelight; print('OK')"
# 输出 OK 表示安装成功
```

### 3. Yeelight 灯泡准备

在 **Yeelight App** 中打开灯泡的「局域网控制」功能：

1. 打开 Yeelight App → 选择灯泡
2. 右上角设置 → **局域网控制** → 开启

## 工作原理

```
Claude Code hooks → hooks.py → HTTP → relay 守护进程(9877) → 持久 TCP → 灯泡
```

每次 Claude Code 会话中触发 hook 时，`hooks.py` 自动管理 relay 生命周期：
- `UserPromptSubmit` → 标记 Claude 开始工作 (🟦 thinking)
- `PreToolUse` → 工具类型映射灯光 / 权限等待 (🟧 waiting)
- `PostToolUse` → 成功继续工作 / 检测错误 (🟥 error)
- `SubagentStop` → 子任务结束，恢复工作状态
- `Notification` → 保持 relay 活跃，不改变状态
- `Stop` → 会话结束，任务完成 (🟩 success)

relay 守护进程保持**单一 TCP 连接**到灯泡，所有状态变化通过 HTTP 瞬时完成。

## 安装步骤

### 一键安装

```bash
cd claude-hook
python setup.py
```

安装向导会自动完成 **全部三步**：

| 步骤 | 自动完成 |
|------|---------|
| 🔍 发现灯泡 | SSDP 多播 (秒级) → TCP 端口 55443 扫描 (仅主网段，~30s) |
| 💾 保存配置 | 写入 `bulbs.json`，验证灯泡连通性 |
| 📦 安装脚本 | 复制运行文件到 `~/.claude/hooks/yeelight-vibe/`（删除仓库不影响） |
| ⚙️ 写入 hooks | 自动合并到 `~/.claude/settings.json`，无需手动编辑 |

> 💡 如果之前已配置过灯泡，向导会提示复用已有配置，跳过扫描步骤。

**交互式管理**（可选）：

| 操作 | 说明 |
|------|------|
| ➕ 手动添加 | 输入灯泡 IP 和名称 |
| 🔍 扫描局域网 | 重新发现网络中的 Yeelight 设备 |
| ✏️ 设置默认 | 标记默认灯泡 |
| 🗑 删除 | 移除已保存的灯泡 |

### 手动写入 Hooks（仅当自动写入失败时）

手动合并到 `~/.claude/settings.json`（全局）或 `.claude/settings.local.json`（项目级）：

```json
{
  "hooks": {
    "UserPromptSubmit": [{
      "hooks": [{"type": "command", "command": "python \"/path/to/claude-hook/hooks.py\" user_prompt"}]
    }],
    "PreToolUse": [{
      "hooks": [{"type": "command", "command": "python \"/path/to/claude-hook/hooks.py\" pre_tool"}]
    }],
    "PostToolUse": [{
      "hooks": [{"type": "command", "command": "python \"/path/to/claude-hook/hooks.py\" post_tool"}]
    }],
    "Stop": [{
      "hooks": [{"type": "command", "command": "python \"/path/to/claude-hook/hooks.py\" stop"}]
    }],
    "SubagentStop": [{
      "hooks": [{"type": "command", "command": "python \"/path/to/claude-hook/hooks.py\" subagent_stop"}]
    }],
    "Notification": [{
      "hooks": [{"type": "command", "command": "python \"/path/to/claude-hook/hooks.py\" notification"}]
    }]
  }
}
```

> ⚠️ 将 `/path/to/claude-hook` 替换为项目实际路径。推荐使用 `~/.claude/hooks/yeelight-vibe/`。

### 测试

```bash
# 测试灯光效果
python hooks.py direct thinking   # 蓝呼吸
python hooks.py direct executing  # 橙呼吸
python hooks.py direct success    # 翠绿
python hooks.py direct stop       # 终止灯效
```

## 状态颜色映射

基于 Claude Code 全部 **6 种** hook 事件重新设计:

| Claude Code 事件 | 条件 | 灯光状态 | 含义 |
|-----------------|------|---------|------|
| `UserPromptSubmit` | — | 🟦 蓝 呼吸 (thinking) | Claude 开始工作，用户等待 |
| `PreToolUse` | 需授权 (Do you want to proceed?) | 🟧 琥珀 常亮 (waiting) | Claude 等待用户确认 |
| `PreToolUse` | Bash 命令执行 | 🟧 橙 呼吸 (executing) | 正在执行命令 |
| `PreToolUse` | Bash (curl/wget/npm/pip) | 🟦 蓝 闪烁 (fetching) | 下载/安装/网络请求 |
| `PreToolUse` | Read / Grep / Glob | 🟦 青 呼吸 (reading) | 正在读取文件 |
| `PreToolUse` | Write / Edit | 🟪 玫红 呼吸 (writing) | 正在写入/编辑文件 |
| `PreToolUse` | WebSearch / WebFetch | 🟦 蓝 闪烁 (fetching) | 正在访问网络 |
| `PreToolUse` | 其他工具 | 🟦 蓝 呼吸 (thinking) | 通用工作状态 |
| `PostToolUse` | 正常返回 | 🟦 蓝 呼吸 (thinking) | 继续下一个任务 |
| `PostToolUse` | 出错 | 🟥 正红 常亮 (error) | 工具执行失败 |
| `SubagentStop` | — | 🟦 蓝 呼吸 (thinking) | 子任务完成，继续 |
| `Notification` | — | (保持当前状态) | 系统通知，不改变灯光 |
| `Stop` | — | 🟩 翠绿 常亮 (success) | 会话成功结束，任务完成 |

> **设计原则**: "thinking" = Claude 在工作（你等着），"waiting" = Claude 在等你操作（快响应）。
> 状态映射与 Pi Agent 版对齐：相同语义 → 相同灯光，切换 agent 不困惑。

完整状态列表：

| 状态 | 效果 | 颜色 | 含义 |
|------|------|------|------|
| idle | 常亮 | 🟦 冰蓝 (68,136,255) | 空闲待命 |
| thinking | 呼吸 | 🟦 蓝 (0,68,255) | 思考中 |
| executing | 呼吸 | 🟧 橙 (220,90,0) | 执行命令 |
| reading | 呼吸 | 🟦 青 (0,200,255) | 读取文件 |
| writing | 呼吸 | 🟪 玫红 (255,50,120) | 写入/编辑 |
| querying | 呼吸 | 🟩 绿 (0,160,100) | 查询上下文 |
| fetching | 闪烁 | 🟦 蓝 (0,100,255) | 访问网络 |
| waiting | 常亮 | 🟧 琥珀 (255,140,0) | 等待用户 |
| success | 常亮 | 🟩 翠绿 (0,220,80) | 完成成功 |
| error | 常亮 | 🟥 正红 (255,30,30) | 出错停止 |

## 文件结构

```
claude-hook/
├── hooks.py              # Hook 事件处理入口
├── yeelight_relay.py     # HTTP relay 守护进程 (持久 TCP)
├── yeelight_discover.py  # 局域网设备发现
├── setup.py              # 安装配置向导
├── settings.json         # Claude Code hook 配置示例
├── bulbs.json            # 灯泡配置
└── README.md
```

## 手动控制

```bash
# 启动 relay
python hooks.py setup

# 直接控制灯光
python hooks.py direct thinking    # 思考中
python hooks.py direct executing   # 执行中
python hooks.py direct success     # 完成
python hooks.py direct idle        # 空闲
python hooks.py direct stop        # 终止灯效恢复白光

# 关闭 relay
python hooks.py shutdown
```

## 故障排查

| 问题 | 解决 |
|------|------|
| setup.py 扫描不到设备 | 检查灯泡「局域网控制」是否已开启 |
| 灯不响应 | 检查 IP 是否正确；灯泡断电重启 |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` |
| hooks 不触发 | 检查 settings.json 路径是否正确；确认 hooks 配置已生效 |
| relay 启动失败 | 检查 Python 路径；确认 yeelight 包已安装 |

## 设计笔记

这个版本与 pi-agent 版共享同一个 `yeelight_relay.py` 和 `yeelight_discover.py`，核心控制逻辑完全相同。区别仅在于：

- **事件系统适配**：将 pi agent 的 TypeScript 事件监听（`pi.on("tool_call")`）替换为 Claude Code 的 JSON hook 机制（`PreToolUse` / `PostToolUse`）
- **工具名映射**：pi agent 工具名 (`read`, `write`, `edit`, `bash`) → Claude Code 工具名 (`Read`, `Write`, `Edit`, `Bash`)
- **配置方式**：从 pi TUI 面板转为 CLI 向导 + JSON 配置文件
