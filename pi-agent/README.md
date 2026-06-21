# Yeelight Vibe Control — Pi Agent 插件

> [项目主页 / Project Home](../README.md)

让 Yeelight 智能灯实时显示 pi agent 的运行状态。基于交通信号灯 + HCI 色彩理论设计。

## 环境准备

### 1. Python 环境

需要 Python 3.8+。确认 Python 已安装并可执行：

```bash
python3 --version
# 或
python --version
```

> 如果同时有多个 Python 版本，插件默认使用 `python3` 命令。如需要指定路径，在 pi 的 `settings.json` 中设置：
>
> ```json
> {
>   "yeelight": {
>     "python": "C:\\Users\\你的用户名\\AppData\\Local\\Programs\\Python\\Python312\\python.exe"
>   }
> }
> ```

### 2. 安装 yeelight Python 包

```bash
pip install yeelight
```

如果遇到权限问题：

```bash
# macOS / Linux
pip3 install --user yeelight

# Windows (以管理员运行终端)
pip install yeelight
```

验证安装：

```bash
python3 -c "import yeelight; print('OK')"
# 输出 OK 表示安装成功
```

### 3. Yeelight 灯泡准备

在 **Yeelight App** 中打开灯泡的「局域网控制」功能：

1. 打开 Yeelight App → 选择灯泡
2. 右上角设置 → **局域网控制** → 开启

> 部分旧款灯泡需要先固件升级才能开启局域网控制。

## 工作原理

```
pi agent 事件队列 → HTTP → 本地 relay(9877) → 持久TCP连接 → 灯泡
```

每次 pi session 启动时，自动启动一个本地 relay 守护进程，保持**单一 TCP 连接**到灯泡。所有状态变化通过 HTTP 发到 relay，无进程创建开销，零连接数竞争。

## 安装插件

```bash
# 克隆或复制插件到 pi 扩展目录
cp -r pi-agent ~/.pi/agent/extensions/yeelight-vibe
```

## 使用

### 首次配置

启动 pi，运行：

```
/yeelight-setup
```

进入 TUI 配置面板：

| 操作 | 说明 |
|------|------|
| **➕ 手动添加** | 输入灯泡 IP 和名称。IP 可在路由器后台或 Yeelight App 中查看 |
| **🔍 扫描局域网** | 自动发现网络中的 Yeelight 设备，从列表中选择添加 |
| **★ 编辑默认** | 标记默认灯泡，auto-tracking 将使用它 |
| **🗑 删除** | 移除已保存的灯泡 |

配置保存在插件目录的 `bulbs.json` 中，可随时用 `/yeelight-setup` 维护。

### 测试状态

```
/yeelight-test
```

- 如有多个灯泡，先选择要测试的
- ↑↓ 选择状态 → **Enter** 应用
- 🛑 终止效果 — 停止所有灯效
- **Esc** 退出（自动恢复待命）

### 自动跟踪

无需手动操作。扩展在每次 pi session 中自动运行，映射如下：

| Agent 事件 | 灯光状态 |
|-----------|---------|
| 会话启动 | 🟦 冰蓝 空闲待命 |
| 开始处理 | 🟦 蓝 呼吸 |
| 读取文件 | 🟦 青 呼吸 |
| 写入/编辑 | 🟪 玫红 呼吸 |
| 执行命令 | 🟧 橙 呼吸 |
| 查询上下文 | 🟩 绿 呼吸 |
| 访问网络 | 🟦 蓝 闪烁 |
| 等待用户 | 🟧 琥珀 常亮 |
| 完成成功 | 🟩 翠绿 常亮 |
| 出错 | 🟥 正红 常亮 |

## 状态颜色含义

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

设计依据：交通信号灯颜色体系（🟢 通行 / 🟡 注意 / 🔴 停止）+ HCI 人机交互色彩理论。
状态映射与 Claude Code Hook 版对齐：相同语义 → 相同灯光效果。

## 文件结构

```
~/.pi/agent/extensions/yeelight-vibe/
├── index.ts              # Pi 扩展入口
├── yeelight_relay.py     # HTTP relay (持久TCP连接)
├── yeelight_discover.py  # 局域网设备发现
├── yeelight_ctl.py       # CLI 控制脚本 (可选备用)
├── bulbs.json            # 灯泡配置 (首次运行时生成)
└── README.md
```

## 故障排查

| 问题 | 解决 |
|------|------|
| `/yeelight-setup` 扫描不到设备 | 检查灯泡「局域网控制」是否已开启 |
| 灯不响应 | 检查 IP 是否正确；尝试给灯泡断电重启 |
| `ModuleNotFoundError: yeelight` | `pip install yeelight` |
| `python3: command not found` | 安装 Python 3.8+，或配置 `settings.json` 中的 `python` 路径 |
