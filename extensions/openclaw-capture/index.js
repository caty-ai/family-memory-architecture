import fs from "node:fs";
import path from "node:path";

const EVENTS = ["message_received", "message_sent"];
const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function utcDay() {
  return new Date().toISOString().slice(0, 10);
}

function safeDayFromTimestamp(ts) {
  const candidate = typeof ts === "string" ? ts.slice(0, 10) : "";
  return DAY_RE.test(candidate) ? candidate : utcDay();
}

function configFrom(api) {
  if (api && api.pluginConfig && typeof api.pluginConfig === "object") {
    return api.pluginConfig;
  }
  if (api && typeof api.getConfig === "function") {
    const value = api.getConfig();
    if (value && typeof value === "object") {
      return value;
    }
  }
  const entryConfig = api?.config?.plugins?.entries?.["openclaw-capture"]?.config;
  if (entryConfig && typeof entryConfig === "object") {
    return entryConfig;
  }
  return (api && (api.config || api.options || api.settings)) || {};
}

function pickString(source, names) {
  if (!source || typeof source !== "object") {
    return "";
  }
  for (const name of names) {
    const value = source[name];
    if (typeof value === "string" && value) {
      return value;
    }
  }
  return "";
}

function extractContent(payload) {
  const direct = pickString(payload, ["content", "text", "message"]);
  if (direct) {
    return direct;
  }
  const message = payload && payload.message;
  if (typeof message === "string") {
    return message;
  }
  if (message && typeof message === "object") {
    const nested = pickString(message, ["content", "text"]);
    if (nested) {
      return nested;
    }
  }
  return "";
}

function extractRecord(eventName, payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  return {
    ts: pickString(source, ["ts", "timestamp", "createdAt"]) || new Date().toISOString(),
    event: pickString(source, ["event", "type"]) || eventName,
    sessionKey: pickString(source, ["sessionKey", "sessionId", "conversationId"]),
    agentId: pickString(source, ["agentId", "agent", "provider"]),
    content: extractContent(source),
  };
}

function ensureSpool(spoolDir) {
  fs.mkdirSync(spoolDir, { recursive: true, mode: 0o700 });
  fs.chmodSync(spoolDir, 0o700);
}

function appendError(spoolDir, error) {
  try {
    ensureSpool(spoolDir);
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      error: error && error.message ? error.message : String(error),
    });
    const file = path.join(spoolDir, "capture-errors.log");
    const fd = fs.openSync(file, "a", 0o600);
    try {
      fs.writeSync(fd, `${line}\n`);
    } finally {
      fs.closeSync(fd);
    }
    fs.chmodSync(file, 0o600);
  } catch (_ignored) {
    // Capture failures must never break an agent turn.
  }
}

function appendRecord(spoolDir, eventName, payload) {
  try {
    ensureSpool(spoolDir);
    const record = extractRecord(eventName, payload);
    const day = safeDayFromTimestamp(record.ts);
    const file = path.join(spoolDir, `${day}.jsonl`);
    const fd = fs.openSync(file, "a", 0o600);
    try {
      fs.writeSync(fd, `${JSON.stringify(record)}\n`);
    } finally {
      fs.closeSync(fd);
    }
    fs.chmodSync(file, 0o600);
  } catch (error) {
    appendError(spoolDir, error);
  }
}

function subscribe(api, eventName, handler) {
  if (api && typeof api.on === "function") {
    api.on(eventName, handler, { priority: 100 });
    return true;
  }
  if (api && typeof api.subscribe === "function") {
    api.subscribe(eventName, handler, { priority: 100 });
    return true;
  }
  return false;
}

export default function register(api) {
  const config = configFrom(api);
  const spoolDir = config.spoolDir;
  if (typeof spoolDir !== "string" || !spoolDir) {
    console.error("[openclaw-capture] FATAL: spoolDir is missing/empty in plugin config; capture is DISABLED");
    return;
  }
  for (const eventName of EVENTS) {
    if (!subscribe(api, eventName, (payload) => appendRecord(spoolDir, eventName, payload))) {
      return;
    }
  }
  appendRecord(spoolDir, "register", {
    ts: new Date().toISOString(),
    event: "register",
    sessionKey: "",
    agentId: "",
    content: "",
  });
}
