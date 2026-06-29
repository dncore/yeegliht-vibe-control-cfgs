/**
 * Yeelight Vibe Bridge — Pi Agent 适配器
 * ========================================
 * 薄适配器: Pi Agent 事件 → HTTP → bridge relay (9877)
 *
 * 职责: 仅负责事件转换和 TUI 命令。
 *       不启动/停止 relay，不管理灯泡连接。
 *       所有底层功能由 ~/.yeelight-vibe-bridge/ 提供。
 *
 * 前提: 已安装 bridge 公共核心 (python bridge/setup.py)
 *
 * 命令:
 *   /yeelight-setup    → 通过 bridge API 配置灯泡
 *   /yeelight-test     → 灯光状态测试 TUI
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { isToolCallEventType } from "@earendil-works/pi-coding-agent";
import { matchesKey, Key } from "@earendil-works/pi-tui";
import { execSync } from "node:child_process";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { pid } from "node:process";
import { homedir } from "node:os";

// ═══════════════ 常量 ═══════════════

const BRIDGE_DIR = join(homedir(), ".yeelight-vibe-bridge");
const RELAY_PORT = 9877;
const RELAY_URL = process.env.YEELIGHT_RELAY_URL || `http://127.0.0.1:${RELAY_PORT}`;
const API_KEY = process.env.YEELIGHT_API_KEY || "";

function authHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) h["Authorization"] = `Bearer ${API_KEY}`;
  return h;
}

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

function loadBulbs(): BulbsConfig {
  try {
    const bulbsFile = join(BRIDGE_DIR, "bulbs.json");
    if (existsSync(bulbsFile)) {
      return JSON.parse(readFileSync(bulbsFile, "utf-8"));
    }
  } catch {}
  return { bulbs: [] };
}

function saveBulbs(cfg: BulbsConfig): void {
  mkdirSync(BRIDGE_DIR, { recursive: true });
  writeFileSync(join(BRIDGE_DIR, "bulbs.json"), JSON.stringify(cfg, null, 2), "utf-8");
}

function getDefaultBulb(): BulbEntry | null {
  const cfg = loadBulbs();
  if (cfg.default && cfg.bulbs.find(b => b.id === cfg.default)) {
    return cfg.bulbs.find(b => b.id === cfg.default)!;
  }
  return cfg.bulbs[0] || null;
}

// ═══════════════ Bridge 通信 ═══════════════

let warned = false;

async function bridgePost(path: string, data: Record<string, unknown>): Promise<boolean> {
  try {
    const resp = await fetch(`${RELAY_URL}${path}`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(data),
    });
    const d = await resp.json();
    if (!d.ok && !warned) {
      warned = true;
      console.error(`[yeelight] bridge: ${d.error}`);
    }
    return d.ok;
  } catch {
    if (!warned) {
      warned = true;
      console.error("[yeelight] bridge 不可达，请确保 relay 已启动");
    }
    return false;
  }
}

async function bridgeGet(path: string): Promise<any> {
  try {
    const resp = await fetch(`${RELAY_URL}${path}`);
    return await resp.json();
  } catch {
    return { ok: false };
  }
}

async function ensureBridge(): Promise<boolean> {
  const health = await bridgeGet("/api/health");
  if (health.ok) return true;
  // 尝试启动 bridge relay
  const bridgeCli = join(BRIDGE_DIR, "yeelight_bridge.py");
  if (!existsSync(bridgeCli)) return false;
  try {
    execSync(`python "${bridgeCli}" ensure`, { windowsHide: true, timeout: 10000 });
    return true;
  } catch {
    return false;
  }
}

// ═══════════════ 灯光控制 ═══════════════

let currentState: string | null = null;
let pendingState: string | null = null;
let busy = false;

function setLight(state: string): void {
  if (state === currentState || state === pendingState) return;
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
  bridgePost("/api/state", { state, pid: `${pid}` }).finally(() => {
    busy = false;
    if (pendingState) {
      const n = pendingState;
      pendingState = null;
      _sendNow(n);
    }
  });
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

// ═══════════════ TUI 状态测试 ═══════════════

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

async function openStateTester(ctx: any): Promise<void> {
  if (ctx.mode !== "tui") return;
  await ctx.ui.custom<string | null>((tui: any, theme: any, _kb: any, done: any) => {
    let selected = 0, lastApplied: string | null = null, applying = false;
    let cW: number | undefined, cL: string[] | undefined;
    const comp = {
      render(w: number): string[] {
        if (cW === w && cL) return cL; cW = w;
        const lines: string[] = [];
        const mw = Math.min(w - 4, 50);
        lines.push("", `  ${theme.fg("accent", theme.bold("Yeelight 灯光状态测试"))}`,
          `  ${theme.fg("dim", "─".repeat(mw))}`, "");
        for (let i = 0; i < TUI_ITEMS.length; i++) {
          const it = TUI_ITEMS[i];
          if (it.id === "__sep__") { lines.push(`  ${theme.fg("dim", "─".repeat(mw))}`); continue; }
          const isSel = i === selected, isAp = it.id === lastApplied;
          const arr = isSel ? "▸" : " ";
          const lab = `${it.icon} ${it.name}`;
          const pad = lab.padEnd(18);
          const ck = isAp ? theme.fg("success", " ✓") : "";
          lines.push(`  ${isSel ? theme.fg("accent", `${arr} ${theme.bold(pad)}${it.desc} ${ck}`)
            : `${arr} ${pad}${theme.fg("dim", it.desc)}${ck}`}`);
        }
        lines.push("", `  ${theme.fg("dim", "─".repeat(mw))}`);
        if (applying) lines.push(`  ${theme.fg("warning", "⏳ 正在应用...")}`);
        else if (lastApplied) lines.push(`  ${theme.fg("success", `✓ 已应用: ${lastApplied}`)}`);
        lines.push(`  ${theme.fg("dim", "↑↓ 选择  Enter 应用  Esc 退出")}`, "");
        return cL = lines;
      },
      handleInput(d: string): void {
        if (matchesKey(d, Key.up)) {
          let s = selected - 1;
          while (s >= 0 && TUI_ITEMS[s].id === "__sep__") s--;
          if (s >= 0) { selected = s; cW = undefined; cL = undefined; tui.requestRender(); }
        } else if (matchesKey(d, Key.down)) {
          let s = selected + 1;
          while (s < TUI_ITEMS.length && TUI_ITEMS[s].id === "__sep__") s++;
          if (s < TUI_ITEMS.length) { selected = s; cW = undefined; cL = undefined; tui.requestRender(); }
        } else if (matchesKey(d, Key.enter)) {
          const it = TUI_ITEMS[selected];
          if (it.id === "__sep__" || applying) return;
          applying = true; cW = undefined; cL = undefined; tui.requestRender();
          fetch(`${RELAY_URL}/api/direct`, {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({ state: it.id }),
          })
            .then(r => r.json())
            .then(j => {
              applying = false;
              lastApplied = j.ok ? it.id : `❌ ${it.name}`;
              cW = undefined; cL = undefined; tui.requestRender();
            })
            .catch(() => {
              applying = false;
              lastApplied = `❌ ${it.name}`;
              cW = undefined; cL = undefined; tui.requestRender();
            });
        } else if (matchesKey(d, Key.escape)) {
          forceLight("idle"); done(null);
        }
      },
      invalidate(): void { cW = undefined; cL = undefined; },
    };
    return comp;
  });
}

// ═══════════════ /yeelight-setup — 通过 bridge API ═══════════════

async function runSetup(ctx: any): Promise<void> {
  // 确保 bridge relay 在运行（setup 需要它做发现）
  const bridgeOk = await ensureBridge();

  const cfg = loadBulbs();

  while (true) {
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
      if (!bridgeOk) {
        ctx.ui.notify("bridge relay 未运行，无法扫描", "warning");
        continue;
      }
      ctx.ui.setStatus("yeelight", "扫描中...");
      try {
        const resp = await fetch(`${RELAY_URL}/api/discover`, { method: "POST", headers: authHeaders(), body: "{}" });
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
          const bId = `bulb_${Date.now()}`;
          cfg.bulbs.push({ id: bId, name: b.name || b.model || "未命名", ip: b.ip });
          if (!cfg.default) cfg.default = bId;
          ctx.ui.notify(`已添加: ${b.name || b.ip}`, "info");
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

  // ─── 会话启动：确保 bridge relay 在运行 ───
  pi.on("session_start", async () => {
    const bulb = getDefaultBulb();
    if (!bulb) return;
    warned = false;
    const ok = await ensureBridge();
    if (!ok) {
      console.error("[yeelight] bridge relay 启动失败。请手动运行:");
      console.error(`  python ${join(BRIDGE_DIR, "yeelight_bridge.py")} start`);
    }
  });

  // ─── 会话关闭 ───
  // 不停止 relay！relay 是独立守护进程，可能被其他 session/agent 使用
  pi.on("session_shutdown", (event) => {
    if (event.reason === "quit") forceLight("off");
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

  // ─── /yeelight-setup：配置灯泡（通过 bridge API）───
  pi.registerCommand("yeelight-setup", {
    description: "配置 Yeelight 灯泡 (添加/扫描/管理)",
    handler: async (_args: string, ctx: any) => runSetup(ctx),
  });

  // ─── /yeelight-test：灯光状态测试 ───
  pi.registerCommand("yeelight-test", {
    description: "灯光状态测试",
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
      // 检查 relay
      const health = await bridgeGet("/api/health");
      if (!health.ok) {
        ctx.ui.notify("bridge relay 未运行，正在启动...", "warning");
        const ok = await ensureBridge();
        if (!ok) {
          ctx.ui.notify("bridge relay 启动失败", "error");
          return;
        }
      }
      await openStateTester(ctx);
    },
  });
}
