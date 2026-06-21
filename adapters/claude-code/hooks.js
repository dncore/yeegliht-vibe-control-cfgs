#!/usr/bin/env node
/**
 * Yeelight Vibe Bridge — Claude Code adapter (Node.js)
 * Much faster startup than Python on Windows (~100ms vs ~1.5s)
 */
const BRIDGE = "http://127.0.0.1:9877";
const READ_TOOLS = new Set(["Read","LS","Grep","Glob","Task","TodoRead","NotebookRead"]);
const WRITE_TOOLS = new Set(["Write","Edit","NotebookEdit"]);
const WEB_TOOLS = new Set(["WebSearch","WebFetch"]);
const WEB_KW = ["curl","wget","http ","fetch","npx ","npm ","pip "];

function post(path, data) {
  try {
    require("http").request(`${BRIDGE}${path}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      timeout: 300
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
  if (name === "Bash") {
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

  switch (mode) {
    case "user_prompt":
      post("/api/state", { ...base, state: "thinking" });
      break;
    case "pre_tool": {
      const ev = await readStdin();
      if (!ev) { post("/api/state", { ...base, state: "thinking" }); break; }
      const perm = ev.permissionDecision || ev.permission_decision || "";
      if (perm === "ask") { post("/api/state", { ...base, state: "waiting" }); break; }
      const tn = ev.tool_name || ev.toolName || "";
      const ti = ev.tool_input || ev.toolInput || {};
      post("/api/state", { ...base, state: toolState(tn, ti) });
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
      // no-op; relay auto-expires stale sessions
      break;
  }
}

main();
