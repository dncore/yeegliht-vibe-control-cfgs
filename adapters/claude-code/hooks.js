#!/usr/bin/env node
/**
 * Yeelight Vibe Bridge — Claude Code adapter (Node.js)
 */
const fs = require("fs");
const path = require("path");
const os = require("os");
const http = require("http");
const BRIDGE = "http://127.0.0.1:9877";
const LOG = path.join(os.homedir(), ".yeelight-vibe-bridge", "hook-debug.log");
const READ_TOOLS = new Set(["Read","LS","Grep","Glob","Task","TodoRead","NotebookRead"]);
const WRITE_TOOLS = new Set(["Write","Edit","NotebookEdit"]);
const EXEC_TOOLS = new Set(["Bash","PowerShell"]);  // command execution tools
const WEB_TOOLS = new Set(["WebSearch","WebFetch"]);
const WEB_KW = ["curl","wget","http ","fetch","npx ","npm ","pip "];

function log(msg) {
  try { fs.appendFileSync(LOG, new Date().toISOString() + " " + msg + "\n"); } catch(_) {}
}

function post(path, data) {
  log("POST " + path + " " + JSON.stringify(data));
  try {
    http.request(BRIDGE + path, {
      method: "POST", headers: { "Content-Type": "application/json" }, timeout: 300
    }).end(JSON.stringify(data));
  } catch (_) {}
}

function readStdin() {
  return new Promise((resolve) => {
    let resolved = false, timer = null;
    const done = (v) => {
      if (resolved) return;
      resolved = true;
      if (timer) clearTimeout(timer);
      resolve(v);
    };
    let data = "";
    process.stdin.on("readable", () => {
      let chunk;
      while ((chunk = process.stdin.read()) !== null) data += chunk;
      try { done(JSON.parse(data.trim())); return; } catch (_) {}
    });
    process.stdin.on("end", () => {
      try { done(JSON.parse(data.trim())); } catch (_) { done(null); }
    });
    process.stdin.on("error", () => done(null));
    timer = setTimeout(() => { try { done(JSON.parse(data.trim())); } catch (_) { done(null); } }, 1000);
    process.stdin.resume();
  });
}

function toolState(name, input) {
  if (READ_TOOLS.has(name)) return "reading";
  if (WRITE_TOOLS.has(name)) return "writing";
  if (EXEC_TOOLS.has(name)) {
    const cmd = (typeof input?.command === "string" ? input.command : "").toLowerCase();
    return WEB_KW.some(kw => cmd.startsWith(kw)) ? "fetching" : "executing";
  }
  if (WEB_TOOLS.has(name)) return "fetching";
  return "thinking";
}

async function main() {
  const mode = process.argv[2]?.toLowerCase();
  if (!mode) return;
  const base = { pid: "claude-hook" };

  log("=== " + mode + " ===");

  switch (mode) {
    case "user_prompt":
      post("/api/state", { ...base, state: "thinking" });
      break;
    case "pre_tool": {
      const ev = await readStdin();
      if (!ev) { log("  ev=null → thinking"); post("/api/state", { ...base, state: "thinking" }); break; }
      log("  ev=" + JSON.stringify(ev));
      // Check ALL possible permission-related fields
      const perm = ev.permissionDecision || ev.permission_decision
                || ev.permission_required || ev.requires_permission
                || ev.permission || ev.decision || "";
      log("  perm=" + (perm || "(none)"));
      if (perm === "ask") { log("  → waiting"); post("/api/state", { ...base, state: "waiting" }); break; }
      const tn = ev.tool_name || ev.toolName || "";
      const ti = ev.tool_input || ev.toolInput || {};
      const st = toolState(tn, ti);
      log("  tool=" + tn + " → " + st);
      post("/api/state", { ...base, state: st });
      break;
    }
    case "post_tool": {
      const ev = await readStdin();
      if (!ev) { post("/api/state", { ...base, state: "thinking" }); break; }
      const tr = ev.tool_response || ev.toolResponse || {};
      const err = typeof tr === "object" ? (tr.isError || tr.is_error) : false;
      post("/api/state", { ...base, state: err ? "error" : "thinking" });
      break;
    }
    case "stop":
      post("/api/direct", { state: "success" });
      break;
    case "subagent_stop":
      post("/api/state", { ...base, state: "thinking" });
      break;
    case "notification":
      break;
  }
}

main();
