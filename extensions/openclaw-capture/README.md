# openclaw-capture

Local OpenClaw capture plugin for the Issue #46 pilot. It subscribes to the dispatch/deliver-layer `message_received` and `message_sent` hooks and appends minimal JSONL records to a local spool directory. It does not read or carry the Supermemory API key.

## Pilot Install

1. Copy or keep this directory on the pilot host.
2. Add the plugin id to OpenClaw config:

   ```json
   {
     "plugins": {
       "allow": ["openclaw-capture"],
       "load": {
         "paths": ["/absolute/path/to/extensions/openclaw-capture"]
       },
       "entries": {
         "openclaw-capture": {
           "enabled": true,
           "config": {
             "spoolDir": "~/.openclaw/capture-spool"
           }
         }
       }
     }
   }
   ```

3. Reload the OpenClaw gateway.
4. Run `scripts/capture-shipper` out-of-process on a launchd cadence (macOS) — or a systemd user timer / cron entry on Linux — with a separate `0600` env file containing the Supermemory key. On WSL2/Linux keep that env file on ext4, never under `/mnt/c`, or the fail-closed `0600` check stops the shipper.

The plugin intentionally uses only `message_received` and `message_sent`. Per the Issue #46 claude-cli verification, those hooks fire at the provider-independent dispatch/deliver layer, so this capture path works under claude-cli. Tool-layer hooks do not fire under claude-cli and are not used here.

## Local Storage Semantics

Spool and quarantine files hold unredacted content by design. Per the family-memory-architecture Issue #46 decision 4, redaction happens at the egress side in `scripts/capture-shipper`, not at capture time. The local files are protected with `0700` directory and `0600` file permissions and also serve as a lossless local backup when shipping is delayed or fails.

`capture-shipper` uses at-least-once retry semantics. A quarantined line can therefore appear more than once across runs, for example if a send succeeds but recording the offset or moving the sent file fails before completion. Quarantine consumers should treat duplicate lines as accepted behavior rather than data corruption.
