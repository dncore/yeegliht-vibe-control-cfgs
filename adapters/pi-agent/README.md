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

## 安装

**前提：已安装 bridge 公共核心**
```bash
cd bridge && python setup.py
```

**部署此适配器：**
```bash
cp -r adapters/pi-agent ~/.pi/agent/extensions/yeelight-vibe
# 启动 pi agent 即生效
```
