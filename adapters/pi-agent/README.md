# Yeelight Vibe Bridge — Pi Agent 适配器

Pi Agent 事件 → HTTP → bridge relay。

## 职责

这个适配器**只做一件事**：将 Pi Agent 的事件翻译为 HTTP 请求发送给 bridge relay。

- ✅ 监听 Pi Agent 生命周期/工具事件
- ✅ 映射事件 → 灯光状态
- ✅ POST 到 bridge relay (`/api/state` 或 `/api/direct`)
- ✅ 提供 `/yeelight-setup` 和 `/yeelight-test` 命令

不负责：
- ❌ 启动/停止 relay（bridge 自行管理，适配器只调用 `yeelight_bridge.py ensure`）
- ❌ 灯泡发现（bridge 提供 `/api/discover`）
- ❌ 灯泡配置读写（bridge 提供 `bulbs.json` 作为单一数据源）
- ❌ Python 环境检测（bridge 管理 Python 依赖）

## 两种模式

| 模式 | Bridge 位置 | RELAY_URL | API_KEY |
|------|------------|-----------|---------|
| **本地** | 本机 `127.0.0.1:9877` | 不设（默认） | 不需要 |
| **LAN** | 局域网其他机器 | 必须设置 | 必须设置 |

## 安装

**前提：已安装 bridge 公共核心**
```bash
cd bridge && python setup.py
```

### 本地模式

```bash
cp -r adapters/pi-agent ~/.pi/agent/extensions/yeelight-vibe
# 启动 pi agent 即生效
```

### LAN 模式

设置环境变量后部署：

```bash
export YEELIGHT_RELAY_URL="http://192.168.x.x:9877"
export YEELIGHT_API_KEY="<your-api-key>"

cp -r adapters/pi-agent ~/.pi/agent/extensions/yeelight-vibe
# 启动 pi agent 即生效
```

Pi Agent 是 CLI 进程，继承 shell 环境变量，直接 `export` 或写入 `.zshrc`/`.bashrc` 即可。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `YEELIGHT_RELAY_URL` | `http://127.0.0.1:9877` | Bridge relay 地址 |
| `YEELIGHT_API_KEY` | (空) | API 认证密钥，本地模式不需要 |
