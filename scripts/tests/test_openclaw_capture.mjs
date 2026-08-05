import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import register from "../../extensions/openclaw-capture/index.js";

function readJsonl(file) {
  return fs
    .readFileSync(file, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function assertRegisterRecord(records) {
  const record = records.find((item) => item.event === "register");
  assert.ok(record);
  assert.equal(record.sessionKey, "");
  assert.equal(record.agentId, "");
  assert.equal(record.content, "");
  assert.ok(!Number.isNaN(Date.parse(record.ts)));
}

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const manifest = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../extensions/openclaw-capture/openclaw.plugin.json"), "utf8"),
);
assert.equal(typeof manifest.activation, "object");
assert.notEqual(manifest.activation, null);
assert.equal(Array.isArray(manifest.activation), false);
assert.equal(manifest.activation.onStartup, true);

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "openclaw-capture-test-"));
const today = new Date().toISOString().slice(0, 10);
const messageTs = "2026-07-07T00:00:00Z";
const spool = path.join(tmp, "spool");
const subscriptions = [];
const api = {
  pluginConfig: { spoolDir: spool },
  on(eventName, handler, options) {
    subscriptions.push({ eventName, handler, options });
  },
};

register(api);

assert.deepEqual(
  subscriptions.map((item) => item.eventName),
  ["message_received", "message_sent"],
);
assert.equal(subscriptions[0].options.priority, 100);
assert.equal(subscriptions[1].options.priority, 100);

subscriptions[0].handler({
  ts: messageTs,
  sessionKey: "session-1",
  agentId: "agent-g",
  content: "hello",
});

const records = readJsonl(path.join(spool, `${today}.jsonl`));
assertRegisterRecord(records);
const messageDay = messageTs.slice(0, 10);
const messageRecords = readJsonl(path.join(spool, `${messageDay}.jsonl`));
assert.deepEqual(messageRecords.find((item) => item.event === "message_received"), {
  ts: messageTs,
  event: "message_received",
  sessionKey: "session-1",
  agentId: "agent-g",
  content: "hello",
});

const fallbackSpool = path.join(tmp, "fallback-spool");
const fallbackSubscriptions = [];
register({
  config: {
    plugins: {
      entries: {
        "openclaw-capture": {
          config: { spoolDir: fallbackSpool },
        },
      },
    },
  },
  on(eventName, handler, options) {
    fallbackSubscriptions.push({ eventName, handler, options });
  },
});
assert.deepEqual(
  fallbackSubscriptions.map((item) => item.eventName),
  ["message_received", "message_sent"],
);
assert.equal(fallbackSubscriptions[0].options.priority, 100);
assert.equal(fallbackSubscriptions[1].options.priority, 100);
assertRegisterRecord(readJsonl(path.join(fallbackSpool, `${today}.jsonl`)));

const badPayload = {};
Object.defineProperty(badPayload, "content", {
  get() {
    throw new Error("content getter failed");
  },
});
assert.doesNotThrow(() => subscriptions[1].handler(badPayload));
assert.equal(fs.existsSync(path.join(spool, "capture-errors.log")), true);

const errors = [];
const originalConsoleError = console.error;
console.error = (...args) => {
  errors.push(args.join(" "));
};
try {
  assert.doesNotThrow(() => register({ config: {} }));
  assert.doesNotThrow(() => register({ config: { spoolDir: "" } }));
} finally {
  console.error = originalConsoleError;
}
assert.equal(errors.length, 2);
assert.match(errors[0], /\[openclaw-capture\].*FATAL.*spoolDir.*DISABLED/);
assert.match(errors[1], /\[openclaw-capture\].*FATAL.*spoolDir.*DISABLED/);

const traversalSpool = path.join(tmp, "traversal-spool");
const traversalSubscriptions = [];
register({
  config: { spoolDir: traversalSpool },
  on(eventName, handler, options) {
    traversalSubscriptions.push({ eventName, handler, options });
  },
});
traversalSubscriptions[0].handler({
  ts: "../../../tmp/evil",
  sessionKey: "session-2",
  agentId: "agent-g",
  content: "safe path",
});

const traversalFiles = fs.readdirSync(traversalSpool);
assert.deepEqual(traversalFiles, [`${today}.jsonl`]);
assert.match(traversalFiles[0], /^\d{4}-\d{2}-\d{2}\.jsonl$/);
assert.equal(fs.existsSync(path.join(traversalSpool, "../../../tmp/evil.jsonl")), false);

fs.rmSync(tmp, { recursive: true, force: true });
