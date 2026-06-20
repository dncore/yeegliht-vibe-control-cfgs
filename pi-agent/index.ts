/**
 * Yeelight Vibe Control — Pi Agent 插件
 * =======================================
 * 通过 Yeelight 智能灯显示 pi agent 运行状态。
 *
 * 命令:
 *   /yeelight-setup    → TUI 添加/管理灯泡 (局域网扫描 + 手动输入)
 *   /yeelight-test     → 选择灯泡后进入状态测试 TUI
 *
 * 自动跟踪: session_start 后自动使用已保存的默认灯泡。
 *
 * 架构: TypeScript 扩展 → HTTP → 本地 relay 守护进程 → 持久 TCP → 灯泡
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { matchesKey, Key } from "@earendil-works/pi-tui";
import { exec, execSync, type ChildProcess } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { env, pid, homedir } from "node:process";

// ═══════════════ 常量 ═══════════════

const PLUGIN_DIR = __dirname;
const BULBS_FILE = join(PLUGIN_DIR, "bulbs.json");
const RELAY_SCRIPT = join(PLUGIN_DIR, "yeelight_relay.py");
const DISCOVER_SCRIPT = join(PLUGIN_DIR, "yeelight_discover.py");
function findPython(): string {
  // 辅助：测试 Python 命令是否可用且有 yeelight 包
  const hasYeelight = (cmd: string): boolean => {
    try {
      const r = execSync(`"${cmd}" -c "import yeelight"`, { stdio: "pipe", windowsHide: true, timeout: 3000 });
      return true;
    } catch { return false; }
  };
  // 1. 从 pi settings.json 读取 yeelight.python 配置
  try {
    const settingsPath = join(homedir(), ".pi", "agent", "settings.json");
    if (existsSync(settingsPath)) {
      const settings = JSON.parse(readFileSync(settingsPath, "utf-8"));
      if (settings?.yeelight?.python && hasYeelight(settings.yeelight.python)) {
        return settings.yeelight.python;
      }
    }
  } catch {}
  // 2. 尝试常见命令（必须能 import yeelight）
  for (const cmd of ["python3", "python"]) {
    if (hasYeelight(cmd)) return cmd;
  }
  // 3. 硬编码回退
  const fallbacks = [
    join(homedir(), "AppData", "Local", "Programs", "Python", "Python312", "python.exe"),
    "C:\\Python312\\python.exe",
  ];
  for (const p of fallbacks) {
    if (existsSync(p) && hasYeelight(p)) return p;
  }
  return "python";
}
let pythonCmd = findPython();
const RELAY_PORT = 9877;

// ═══════════════ 数据模型 ═══════════════

interface BulbEntry {
  id: string;
  name: string;
  ip: string;
}

interface BulbsConfig {
  default?: string;
  bulbs: BulbEntry[];
}

interface YeelightConfig {
  bulbIp: string;
  relayPort: number;
}

function loadBulbs(): BulbsConfig {
  try {
    if (existsSync(BULBS_FILE)) {
      return JSON.parse(readFileSync(BULBS_FILE, "utf-8"));
    }
  } catch {}
  return { bulbs: [] };
}

function saveBulbs(cfg: BulbsConfig): void {
  mkdirSync(PLUGIN_DIR, { recursive: true });
  writeFileSync(BULBS_FILE, JSON.stringify(cfg, null, 2), "utf-8");
}

function getDefaultBulb(): BulbEntry | null {
  const cfg = loadBulbs();
  if (cfg.default && cfg.bulbs.find(b => b.id === cfg.default)) {
    return cfg.bulbs.find(b => b.id === cfg.default)!;
  }
  return cfg.bulbs[0] || null;
}

// ═══════════════ Relay 守护进程 ═══════════════

const RELAY_PID_FILE = join(PLUGIN_DIR, "relay.pid");
let relayProcess: ChildProcess | null = null;
let config: YeelightConfig = { bulbIp: "", relayPort: 0 };
let warned = false;

function getRelayUrl(): string {
  return `http://127.0.0.1:${config.relayPort}`;
}

function killAllRelayProcesses(): void {
  // 方法1: 通过 PID 文件杀
  try {
    if (existsSync(RELAY_PID_FILE)) {
      const savedPid = parseInt(readFileSync(RELAY_PID_FILE, "utf-8").trim(), 10);
      if (savedPid) {
        try { process.kill(savedPid, "SIGTERM"); } catch {}
        try { execSync(`taskkill //PID ${savedPid} //F`, { windowsHide: true, timeout: 3000 }); } catch {}
      }
    }
  } catch {}
  // 方法2: 通过 WMIC 查找所有运行 yeelight_relay.py 的 python 进程
  try {
    const out = execSync(
      `wmic process where "name='python.exe'" get processid,commandline /format:csv`,
      { encoding: "utf-8", windowsHide: true, timeout: 5000 }
    );
    for (const line of out.split(/\r?\n/)) {
      if (line.includes("yeelight_relay")) {
        const m = line.match(/,(\d+)\s*$/);
        if (m) {
          const pid = parseInt(m[1], 10);
          if (pid && pid !== process.pid) {
            try { execSync(`taskkill //PID ${pid} //F`, { windowsHide: true }); } catch {}
          }
        }
      }
    }
  } catch {}
  // 方法3: 杀当前跟踪的进程
  if (relayProcess) {
    try { relayProcess.kill(); } catch {}
    relayProcess = null;
  }
  // 清理 PID 文件
  try { if (existsSync(RELAY_PID_FILE)) require("node:fs").unlinkSync(RELAY_PID_FILE); } catch {}
  // 等待端口释放
  try { execSync("timeout /t 1 /nobreak >nul", { windowsHide: true }); } catch {}
}

function startRelay(bulbIp: string): Promise<number> {
  killAllRelayProcesses();
  return new Promise((resolve, reject) => {
    const cmd = `"${pythonCmd}" "${RELAY_SCRIPT}" ${RELAY_PORT} ${bulbIp}`;
    relayProcess = exec(cmd, { windowsHide: true }, (err) => {
      relayProcess = null;
      try { if (existsSync(RELAY_PID_FILE)) require("node:fs").unlinkSync(RELAY_PID_FILE); } catch {}
    });
    // 写入 PID 文件
    if (relayProcess && relayProcess.pid) {
      try { writeFileSync(RELAY_PID_FILE, String(relayProcess.pid), "utf-8"); } catch {}
    }
    const check = (tries: number) => {
      if (!relayProcess) { reject(new Error("relay 未启动")); return; }
      fetch(`http://127.0.0.1:${RELAY_PORT}/api/status`)
        .then(r => r.json())
        .then(d => {
          if (d.ok) {
            // 验证 relay 能否 import yeelight
            if (!d.yeelight) {
              reject(new Error(`relay 的 Python (${pythonCmd}) 未安装 yeelight 包。请在该 Python 中执行: pip install yeelight`));
              return;
            }
            resolve(RELAY_PORT);
          } else {
            reject(new Error("relay 未就绪"));
          }
        })
        .catch(() => tries > 0 ? setTimeout(() => check(tries - 1), 200) : reject(new Error("relay 超时")));
    };
    check(30);
  });
}

function stopRelay(): void {
  killAllRelayProcesses();
}

// ═══════════════ 灯光控制 ═══════════════

let currentState: string | null = null;
let pendingState: string | null = null;
let busy = false;

function setLight(state: string): void {
  if (state === currentState) return;
  if (state === pendingState) return;
  if (busy) { pendingState = state; return; }
  _sendNow(state);
}

function forceLight(state: string): void {
  pendingState = null;
  if (busy) { pendingState = state; return; }
  _sendNow(state);
}

function _sendNow(state: string): void {
  busy = true;
  currentState = state;
  pendingState = null;

  fetch(`${getRelayUrl()}/api/state`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ state, pid: `${pid}` }),
  })
    .then(r => r.json())
    .then(d => { if (!d.ok && !warned) { warned = true; console.error(`[yeelight] ${d.error}`); } })
    .catch(err => { if (!warned) { warned = true; console.error(`[yeelight] relay 不可达`); } })
    .finally(() => { busy = false; if (pendingState) { const n = pendingState; pendingState = null; _sendNow(n); } });
}

// ═══════════════ 工具类型映射 ═══════════════

const READ_TOOLS = new Set(["read", "ls", "grep", "find"]);
const WRITE_TOOLS = new Set(["write", "edit"]);
const WEB_CMDS = ["curl", "wget", "http ", "fetch"];

function toolColor(name: string): string | null {
  if (READ_TOOLS.has(name)) return "reading";
  if (WRITE_TOOLS.has(name)) return "writing";
  if (name === "bash") return "executing";
  return null;
}

// ═══════════════ TUI 状态测试列表 ═══════════════

const STATE_ITEMS = [
  { id: "idle",      icon: "💤", name: "空闲待命",   desc: "冰蓝常亮" },
  { id: "thinking",  icon: "🧠", name: "思考中",     desc: "蓝色呼吸" },
  { id: "executing", icon: "⚙️", name: "执行命令",   desc: "橙呼吸" },
  { id: "reading",   icon: "📖", name: "读取文件",   desc: "青呼吸" },
  { id: "writing",   icon: "✏️", name: "写入/编辑",  desc: "玫红呼吸" },
  { id: "querying",  icon: "🔍", name: "查询上下文", desc: "绿呼吸" },
  { id: "fetching",  icon: "🌐", name: "访问网络",   desc: "蓝闪烁" },
  { id: "waiting",   icon: "🟡", name: "等待用户",   desc: "琥珀常亮" },
  { id: "success",   icon: "✅", name: "完成成功",   desc: "翠绿常亮" },
  { id: "error",     icon: "🔴", name: "出错",       desc: "正红常亮" },
];

const TUI_ITEMS = [...STATE_ITEMS,
  { id: "__sep__", icon: "", name: "", desc: "" },
  { id: "stop",    icon: "🛑", name: "终止效果", desc: "停止所有灯效，恢复日常照明" },
];

async function openStateTester(ctx: any, bulbIp: string): Promise<void> {
  if (ctx.mode !== "tui") return;
  await ctx.ui.custom<string | null>((tui: any, theme: any, _kb: any, done: any) => {
    let selected = 0, lastApplied: string | null = null, applying = false;
    let cW: number | undefined, cL: string[] | undefined;
    const comp = {
      render(w: number): string[] {
        if (cW === w && cL) return cL; cW = w;
        const lines: string[] = []; const mw = Math.min(w - 4, 50);
        lines.push("", `  ${theme.fg("accent", theme.bold("Yeelight 灯光状态测试"))}`, `  ${theme.fg("dim", "─".repeat(mw))}`, "");
        for (let i = 0; i < TUI_ITEMS.length; i++) {
          const it = TUI_ITEMS[i];
          if (it.id === "__sep__") { lines.push(`  ${theme.fg("dim", "─".repeat(mw))}`); continue; }
          const isSel = i === selected, isAp = it.id === lastApplied;
          const arr = isSel ? "▸" : " ", lab = `${it.icon} ${it.name}`, pad = lab.padEnd(18);
          const ck = isAp ? theme.fg("success", " ✓") : "";
          lines.push(`  ${isSel ? theme.fg("accent", `${arr} ${theme.bold(pad)}${it.desc} ${ck}`) : `${arr} ${pad}${theme.fg("dim", it.desc)}${ck}`}`);
        }
        lines.push("", `  ${theme.fg("dim", "─".repeat(mw))}`);
        if (applying) lines.push(`  ${theme.fg("warning", "⏳ 正在应用...")}`);
        else if (lastApplied) lines.push(`  ${theme.fg("success", `✓ 已应用: ${lastApplied}`)}`);
        lines.push(`  ${theme.fg("dim", "↑↓ 选择  Enter 应用  Esc 退出")}`, "");
        return cL = lines;
      },
      handleInput(d: string): void {
        if (matchesKey(d, Key.up)) { let s = selected - 1; while (s >= 0 && TUI_ITEMS[s].id === "__sep__") s--; if (s >= 0) { selected = s; cW = undefined; cL = undefined; tui.requestRender(); } }
        else if (matchesKey(d, Key.down)) { let s = selected + 1; while (s < TUI_ITEMS.length && TUI_ITEMS[s].id === "__sep__") s++; if (s < TUI_ITEMS.length) { selected = s; cW = undefined; cL = undefined; tui.requestRender(); } }
        else if (matchesKey(d, Key.enter)) {
          const it = TUI_ITEMS[selected];
          if (it.id === "__sep__" || applying) return;
          applying = true; cW = undefined; cL = undefined; tui.requestRender();
          fetch(`${getRelayUrl()}/api/direct`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ state: it.id }),
          })
            .then(r => r.json())
            .then(j => { applying = false; lastApplied = j.ok ? it.id : `❌ ${it.name}`; cW = undefined; cL = undefined; tui.requestRender(); })
            .catch(() => { applying = false; lastApplied = `❌ ${it.name}`; cW = undefined; cL = undefined; tui.requestRender(); });
        }
        else if (matchesKey(d, Key.escape)) { forceLight("idle"); done(null); }
      },
      invalidate(): void { cW = undefined; cL = undefined; },
    };
    return comp;
  });
}

// ═══════════════ 安装引导 /yeelight-setup ═══════════════

async function runSetup(_pi: any, ctx: any): Promise<void> {
  const cfg = loadBulbs();

  while (true) {
    // ── 构建菜单选项 ──
    const menuItems: string[] = [];
    for (const b of cfg.bulbs) {
      const prefix = cfg.default === b.id ? "★ " : "  ";
      menuItems.push(`${prefix}${b.name}  (${b.ip})`);
    }
    if (cfg.bulbs.length > 0) menuItems.push("──────────────");
    menuItems.push("➕ 手动添加");
    menuItems.push("🔍 扫描局域网");
    if (cfg.bulbs.length > 0) {
      menuItems.push("✏️ 设置默认");
      menuItems.push("🗑 删除灯泡");
    }
    menuItems.push("✅ 完成退出");

    if (cfg.bulbs.length === 0) {
      ctx.ui.notify("暂无保存的灯泡，请添加或扫描", "info");
    }

    const choice = await ctx.ui.select("Yeelight 灯泡配置", menuItems);
    if (!choice) { saveBulbs(cfg); return; }

    // ── 处理选择 ──

    if (choice === "✅ 完成退出") {
      saveBulbs(cfg);
      ctx.ui.notify("灯泡配置已保存", "info");
      return;
    }

    if (choice === "➕ 手动添加") {
      const ip = await ctx.ui.input("灯泡 IP 地址 (例如 192.168.2.205)");
      if (!ip) continue;
      const name = await ctx.ui.input("灯泡名称 (例如 办公室主灯)");
      if (!name) continue;
      const id = `bulb_${Date.now()}`;
      cfg.bulbs.push({ id, name, ip });
      if (!cfg.default) cfg.default = id;
      ctx.ui.notify(`已添加: ${name} (${ip})`, "info");
      continue;
    }

    if (choice === "🔍 扫描局域网") {
      ctx.ui.setStatus("yeelight", "扫描中...");
      try {
        // 确保 relay 在跑（没有默认灯泡时 relay 不会自动启动）
        if (!config.relayPort) {
          ctx.ui.setStatus("yeelight", "启动 relay...");
          try {
            // 用一个占位 IP 启动 relay，只用于扫描
            config.relayPort = await startRelay("127.0.0.1");
          } catch {
            ctx.ui.notify("relay 启动失败，请检查 Python 配置", "error");
            ctx.ui.setStatus("yeelight", "");
            continue;
          }
        }
        const resp = await fetch(`${getRelayUrl()}/api/discover`, { method: "POST", body: "{}" });
        const data = await resp.json();
        if (!data.ok) { ctx.ui.notify(`扫描失败: ${data.error}`, "error"); continue; }
        if (!data.bulbs || data.bulbs.length === 0) {
          ctx.ui.notify("未发现灯泡，请检查局域网控制是否开启", "warning");
          continue;
        }
        const labels = data.bulbs.map((b: any) => `${b.name || b.model || "未知"} — ${b.ip}`);
        const picked = await ctx.ui.select(`发现 ${data.count} 个设备`, labels);
        if (!picked) continue;
        const idx = labels.indexOf(picked);
        if (idx >= 0) {
          const b = data.bulbs[idx];
          const bName = b.name || b.model || "未命名";
          const bId = `bulb_${Date.now()}`;
          cfg.bulbs.push({ id: bId, name: bName, ip: b.ip });
          if (!cfg.default) cfg.default = bId;
          ctx.ui.notify(`已添加: ${bName} (${b.ip})`, "info");
        }
      } catch (e: any) {
        ctx.ui.notify(`扫描出错: ${e.message}`, "error");
      }
      ctx.ui.setStatus("yeelight", "");
      continue;
    }

    if (choice === "✏️ 设置默认") {
      const labels = cfg.bulbs.map(b => `${b.name} (${b.ip})`);
      const picked = await ctx.ui.select("选择默认灯泡", labels);
      if (!picked) continue;
      const idx = labels.indexOf(picked);
      if (idx >= 0) {
        cfg.default = cfg.bulbs[idx].id;
        ctx.ui.notify(`默认灯泡: ${cfg.bulbs[idx].name}`, "info");
      }
      continue;
    }

    if (choice === "🗑 删除灯泡") {
      const labels = cfg.bulbs.map(b => `${b.name} (${b.ip})`);
      const picked = await ctx.ui.select("选择要删除的灯泡", labels);
      if (!picked) continue;
      const idx = labels.indexOf(picked);
      if (idx >= 0) {
        const removed = cfg.bulbs[idx];
        cfg.bulbs.splice(idx, 1);
        if (cfg.default === removed.id) cfg.default = cfg.bulbs[0]?.id;
        ctx.ui.notify(`已删除: ${removed.name}`, "info");
      }
      continue;
    }
  }
}

// ═══════════════ 扩展入口 ═══════════════

export default function (pi: ExtensionAPI): void {

  // ─── 会话启动：启动 relay ───
  pi.on("session_start", async () => {
    const bulb = getDefaultBulb();
    if (!bulb) return;  // 没配置灯泡，不做任何操作
    config.bulbIp = bulb.ip;
    warned = false;
    try {
      config.relayPort = await startRelay(bulb.ip);
    } catch (e: any) {
      console.error(`[yeelight] relay 启动失败: ${e.message}`);
    }
  });

  // ─── 会话关闭 ───
  pi.on("session_shutdown", (event) => {
    if (event.reason === "quit") forceLight("off");
    stopRelay();
  });

  // ─── Agent 生命周期 ───
  pi.on("before_agent_start", () => setLight("thinking"));
  pi.on("agent_start", () => setLight("thinking"));
  pi.on("agent_end", () => forceLight("success"));
  pi.on("turn_start", () => setLight("thinking"));
  pi.on("context", () => setLight("querying"));

  pi.on("tool_call", (event) => {
    if (isToolCallEventType("bash", event)) {
      const cmd = (event.input.command ?? "").toLowerCase().trim();
      setLight(WEB_CMDS.some(kw => cmd.startsWith(kw)) ? "fetching" : "executing");
      return;
    }
    const c = toolColor(event.toolName);
    if (c) setLight(c);
  });

  pi.on("tool_result", (event) => setLight(event.isError ? "error" : "thinking"));
  pi.on("user_bash", () => setLight("waiting"));

  // ─── /yeelight-setup：配置灯泡 ───
  pi.registerCommand("yeelight-setup", {
    description: "配置 Yeelight 灯泡 (添加/扫描/管理)",
    handler: async (_args: string, ctx: any) => runSetup(pi, ctx),
  });

  // ─── /yeelight-test：选择灯泡 → 状态测试 ───
  pi.registerCommand("yeelight-test", {
    description: "选择灯泡后进行灯光状态测试",
    handler: async (_args: string, ctx: any) => {
      const cfg = loadBulbs();
      if (cfg.bulbs.length === 0) {
        ctx.ui.notify("暂无保存的灯泡，请先运行 /yeelight-setup", "warning");
        return;
      }
      if (ctx.mode !== "tui") {
        ctx.ui.notify(`已保存 ${cfg.bulbs.length} 个灯泡`, "info");
        return;
      }
      // 快速检查 relay 是否可达
      if (!config.relayPort) {
        ctx.ui.notify("relay 未运行，请执行 /reload", "error");
        return;
      }
      try {
        const resp = await fetch(`${getRelayUrl()}/api/health`);
        if (!resp.ok) throw new Error("relay down");
      } catch {
        ctx.ui.notify("relay 无响应，请 /reload 后重试", "error");
        return;
      }

      // 单灯泡直接进入测试
      if (cfg.bulbs.length === 1) {
        await openStateTester(ctx, cfg.bulbs[0].ip);
        return;
      }
      // 多灯泡选择
      const choice = await ctx.ui.select("选择要测试的灯泡",
        cfg.bulbs.map(b => `${b.name} (${b.ip})`));
      if (choice) {
        const bulb = cfg.bulbs.find(b => `${b.name} (${b.ip})` === choice);
        if (bulb) {
          // 如果测试灯泡不是当前 relay 连的，切换 relay
          if (bulb.ip !== config.bulbIp) {
            stopRelay();
            config.bulbIp = bulb.ip;
            try { config.relayPort = await startRelay(bulb.ip); } catch {}
          }
          await openStateTester(ctx, bulb.ip);
        }
      }
    },
  });
}
