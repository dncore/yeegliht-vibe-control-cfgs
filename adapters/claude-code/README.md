# Yeelight Vibe Bridge — Claude Code 适配器

Claude Code 事件 → HTTP → bridge relay。

## 职责

这个适配器**只做一件事**：将 Claude Code 的 hook 事件翻译为 HTTP 请求发送给 bridge relay。

- ✅ 读取 stdin 事件 JSON
- ✅ 映射 hook 模式 → 灯光状态
- ✅ POST 到 bridge relay (`/api/state` 或 `/api/direct`)

不负责：
- ❌ 启动/停止 relay（bridge 自行管理）
- ❌ 灯泡发现（bridge 提供 `/api/discover`）
- ❌ 灯泡配置读写（bridge 提供 `bulbs.json`）

## 两种模式

| 模式 | Bridge 位置 | RELAY_URL | API_KEY |
|------|------------|-----------|---------|
| **本地** | 本机 `127.0.0.1:9877` | 不设（默认） | 不需要 |
| **LAN** | 局域网其他机器 | 必须设置 | 必须设置 |

本地模式下 hook 直接 POST 到本机 bridge。LAN 模式下 hook POST 到远程 bridge，bridge 统一控制灯。

## 安装

**前提：已安装 bridge 公共核心**
```bash
cd bridge && python setup.py
```

### 本地模式

```bash
cd adapters/claude-code
python setup.py
# 自动将 hooks.py 复制到 ~/.yeelight-vibe-bridge/
# 写入 hooks 配置到 ~/.claude/settings.json
# 重启 Claude Code 生效
```

### LAN 模式

Bridge 已在局域网其他机器上运行，本机只需配置 hook 指向它。

**第一步：设置环境变量**

在 `~/.claude/settings.json` 的 `env` 段添加：

```json
{
  "env": {
    "YEELIGHT_RELAY_URL": "http://192.168.x.x:9877",
    "YEELIGHT_API_KEY": "<your-api-key>"
  }
}
```

> **macOS 注意**：Claude Code 是 GUI 应用，不继承 shell 的 `.zshrc` 环境变量。必须把变量写在 `settings.json` 的 `env` 段，Claude Code 才会注入到 hook 子进程。

**第二步：安装 hook**

```bash
cd adapters/claude-code
python setup.py
# 重启 Claude Code 生效
```

## 验证

```bash
# 带 env 手动测试 hook
YEELIGHT_RELAY_URL="http://192.168.x.x:9877" \
YEELIGHT_API_KEY="<your-api-key>" \
python3 ~/.yeelight-vibe-bridge/hooks.py user_prompt

# 查看日志确认 OK
tail ~/.yeelight-vibe-bridge/hook_debug.log
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `YEELIGHT_RELAY_URL` | `http://127.0.0.1:9877` | Bridge relay 地址 |
| `YEELIGHT_API_KEY` | (空) | API 认证密钥，本地模式不需要 |
