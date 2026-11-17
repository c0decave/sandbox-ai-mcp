// Prepares the installed @upstash/context7-mcp 4.5.0 for the image (see PROVENANCE.md): keeps only the packages that
// run on the stdio path with OpenTelemetry off, removes the telemetry modules that would load the rest, and applies
// four patches (two in dist/index.js). Usage: node prepare.mjs NODE_MODULES_DIR (after npm ci --omit=dev --ignore-scripts).
// Every kept package must have its locked version, each patched file must be the reviewed one before and after
// (SHA-256), each replaced text must occur exactly once; anything else stops the build.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// What Node.js loads for `--transport stdio` with OTEL_SDK_DISABLED=true (traced module by module, PROVENANCE.md):
// the server, the MCP SDK, express (imported at the top for the HTTP mode, never listening here), undici (the proxy
// agent), jose, commander and zod. Not kept: OpenTelemetry with require-in-the-middle and import-in-the-middle, hono,
// the @types packages and undici-types - none of them is loaded.
const KEEP = {
  "@hono/node-server": "1.19.17", "@modelcontextprotocol/core": "2.3.1", "@modelcontextprotocol/node": "2.1.1",
  "@modelcontextprotocol/server": "2.3.1", "@upstash/context7-mcp": "4.5.0", "accepts": "2.0.0",
  "body-parser": "2.4.0", "bytes": "3.1.2", "call-bind-apply-helpers": "1.0.2", "call-bound": "1.0.4",
  "commander": "13.1.0", "content-disposition": "2.0.1", "content-type": "2.1.0", "cookie": "0.7.2",
  "cookie-signature": "1.2.2", "debug": "4.4.3", "depd": "2.0.0", "dunder-proto": "1.0.1", "ee-first": "1.1.1",
  "encodeurl": "2.0.1", "es-define-property": "1.0.1", "es-errors": "1.3.0", "es-object-atoms": "1.1.2",
  "escape-html": "1.0.3", "etag": "1.8.1", "express": "5.3.0", "finalhandler": "2.1.1", "forwarded": "0.2.0",
  "fresh": "2.0.0", "function-bind": "1.1.2", "get-intrinsic": "1.3.0", "get-proto": "1.0.1", "gopd": "1.2.0",
  "has-symbols": "1.1.0", "hasown": "2.0.4", "http-errors": "2.0.1", "iconv-lite": "0.7.3", "inherits": "2.0.4",
  "ipaddr.js": "1.9.1", "is-promise": "4.0.0", "jose": "6.2.14", "math-intrinsics": "1.1.0",
  "media-typer": "1.1.1", "merge-descriptors": "2.0.0", "mime-db": "1.54.0", "mime-types": "3.0.2", "ms": "2.1.3",
  "negotiator": "1.1.0", "object-inspect": "1.13.4", "on-finished": "2.4.2", "once": "1.4.0",
  "parseurl": "1.3.3", "path-to-regexp": "8.4.2", "proxy-addr": "2.0.8", "qs": "6.17.1", "range-parser": "1.3.0",
  "raw-body": "3.0.2", "router": "2.2.0", "safer-buffer": "2.1.2", "send": "1.2.1", "serve-static": "2.2.1",
  "setprototypeof": "1.2.0", "side-channel": "1.1.1", "side-channel-list": "1.0.1", "side-channel-map": "1.0.1",
  "side-channel-weakmap": "1.0.2", "statuses": "2.0.2", "toidentifier": "1.0.1", "type-is": "2.1.0",
  "undici": "7.30.1", "unpipe": "1.0.0", "vary": "1.1.2", "wrappy": "1.0.2", "zod": "4.6.7",
};
// The server's telemetry modules: telemetry-runtime.js imports them only when OTEL_SDK_DISABLED is not "true", and
// they import OpenTelemetry. Removed, so that telemetry cannot be switched back on (the server then fails to start).
const TELEMETRY_MODULES = ["mcp-telemetry.js", "mcp-subscription-telemetry.js", "telemetry.js", "telemetry-provider.js",
  "mcp-operation-scope.js", "telemetry-contracts.js", "types.js"];

const PATCHES = [
  {
    // 1. No sign-in nudge: when context7.com answers an anonymous call with X-Context7-Auth-Prompt: 1, the server
    //    asks the human (MCP elicitation) to run an unpinned `npx ctx7 setup ... -y`, which signs in through the
    //    browser and rewrites the MCP client's configuration. Never wanted here: the key comes from sandbox-ai's
    //    secret store (CONTEXT7_API_KEY).
    file: "dist/lib/auth/auth-prompt.js",
    before: "9d6ef90e4a7cb750b6502dba7eb1ba4bd7236379d724bbd164ef70982e696460",
    after: "a2a609e5f65a45435c887030f82d217ca48592f1cf4f61bb98de120fd4c4e5d4",
    replace: [
      [
        "export function maybeElicitAuthSignIn(server, ctx) {\n    if (ctx.apiKey || !ctx.shouldPrompt)\n",
        "export function maybeElicitAuthSignIn(server, ctx) {\n    // sandbox-ai-mcp: no sign-in nudge (it asks to run an unpinned `npx ctx7 setup`).\n    return;\n    if (ctx.apiKey || !ctx.shouldPrompt)\n",
      ],
    ],
  },
  {
    // 2. Only what a lookup needs goes to context7.com: no per-process session id (mcp-session-id) and no name and
    //    version of the MCP client (X-Context7-Client-IDE, X-Context7-Client-Version). The query, the library,
    //    the language, the server's version, the transport and the key (when set) still go.
    file: "dist/lib/encryption.js",
    before: "a55b3b4bce3c1d209d5e7c92d20fa6ae5ba7a50ff15c10c154a40d2c834182fc",
    after: "0ee644ab37da5dd85e9805f9d2df2ae8ace6e0e0657d54a573e4c12f679ef24d",
    replace: [
      [
        '    if (context.sessionId) {\n        headers["mcp-session-id"] = context.sessionId;\n    }\n',
        "    // sandbox-ai-mcp: no session id.\n",
      ],
      [
        '    if (context.clientInfo?.ide) {\n        headers["X-Context7-Client-IDE"] = context.clientInfo.ide;\n    }\n    if (context.clientInfo?.version) {\n        headers["X-Context7-Client-Version"] = context.clientInfo.version;\n    }\n',
        "    // sandbox-ai-mcp: no client name or version.\n",
      ],
    ],
  },
  {
    // 3. Tools only: the server declares the prompts and resources capabilities and has none of either (empty
    //    lists). Agents act on the capability: they offer a model tools for MCP resources (Hermes four more per
    //    server), which local models took for the way to the server's tools (sandbox-ai research round 1).
    // 4. No research preview (4.5.0): --research-preview or CONTEXT7_RESEARCH_PREVIEW=1 would add the tool
    //    submit-docs-feedback, which POSTs agent-written feedback to context7.com, and instructions to call it after
    //    every answer ("No need to mention it to the user"). Fixed off: only the two lookups leave.
    file: "dist/index.js",
    before: "a58aa517ab6defd8780566373a9fde5d1d47845a1cf7b2fb72151ef595740a57",
    after: "5d434be98e6a68ac94bf275608786a09cfd75286d0aab8df16958b7ef53939d7",
    replace: [
      [
        "            prompts: { listChanged: false },\n            resources: { listChanged: false, subscribe: false },\n",
        "            // sandbox-ai-mcp: tools only (no prompts or resources capability: it publishes none).\n",
      ],
      [
        "        stdioResearchPreview =\n            cliOptions.researchPreview === true ||\n                isResearchPreviewValue(process.env.CONTEXT7_RESEARCH_PREVIEW);\n",
        "        // sandbox-ai-mcp: no research preview (submit-docs-feedback would send agent-written feedback).\n        stdioResearchPreview = false;\n",
      ],
    ],
  },
];

const sha256 = (text) => createHash("sha256").update(text).digest("hex");
const fail = (message) => {
  console.error(message);
  process.exit(1);
};
const modules = process.argv[2];
if (!modules) {
  console.error("usage: node prepare.mjs NODE_MODULES_DIR");
  process.exit(2);
}

// 1. Only the kept packages, each at its locked version, none nested.
for (const entry of readdirSync(modules)) {
  const names = entry.startsWith("@") ? readdirSync(join(modules, entry)).map((n) => `${entry}/${n}`) : [entry];
  for (const name of names) {
    if (!(name in KEEP)) rmSync(join(modules, name), { recursive: true, force: true });
  }
  if (entry.startsWith("@") && readdirSync(join(modules, entry)).length === 0) rmSync(join(modules, entry), { recursive: true });
}
rmSync(join(modules, ".bin"), { recursive: true, force: true });
rmSync(join(modules, ".package-lock.json"), { force: true });
for (const [name, version] of Object.entries(KEEP)) {
  const found = JSON.parse(readFileSync(join(modules, name, "package.json"), "utf8")).version;
  if (found !== version) fail(`${name} ${found}, not ${version}`);
  if (existsSync(join(modules, name, "node_modules"))) fail(`${name} has a nested node_modules`);
}
const left = readdirSync(modules).flatMap((e) => (e.startsWith("@") ? readdirSync(join(modules, e)).map((n) => `${e}/${n}`) : [e]));
if (left.sort().join(" ") !== Object.keys(KEEP).sort().join(" ")) fail(`unexpected packages: ${left.join(" ")}`);

// 2. The telemetry modules.
const server = join(modules, "@upstash/context7-mcp");
for (const file of TELEMETRY_MODULES) rmSync(join(server, "dist/lib", file));
rmSync(join(server, "README.md"));

// 3. The patches.
for (const patch of PATCHES) {
  const path = join(server, patch.file);
  let text = readFileSync(path, "utf8");
  if (sha256(text) !== patch.before) fail(`${patch.file}: not the reviewed file (sha256 ${sha256(text)})`);
  for (const [old, replacement] of patch.replace) {
    if (text.split(old).length !== 2) fail(`${patch.file}: the text to replace does not occur exactly once`);
    text = text.replace(old, () => replacement);
  }
  if (sha256(text) !== patch.after) fail(`${patch.file}: the patched file is not the reviewed one (sha256 ${sha256(text)})`);
  writeFileSync(path, text);
  console.log(`patched ${patch.file}`);
}
