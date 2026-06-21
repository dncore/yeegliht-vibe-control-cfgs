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

## 安装

**前提：已安装 bridge 公共核心**
```bash
cd bridge && python setup.py
```

**安装此适配器：**
```bash
cd adapters/claude-code
python setup.py
# 自动将 hooks.py 复制到 ~/.yeelight-vibe-bridge/
# 写入 hooks 配置到 ~/.claude/settings.json
# 重启 Claude Code 生效
```
