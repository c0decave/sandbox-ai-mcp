// sandbox-ai-mcp (MIT): the entry point of the official MCP filesystem server
// (@modelcontextprotocol/server-filesystem 2.1.0) in this image, in place of upstream's dist/index.js.
//
// It serves upstream's own createServer() over stdio the way dist/index.js does (serveStdio, both protocol eras),
// with two differences, both narrowing what the server may reach:
//
// 1. The allowed directories are the folders sandbox-ai mounted into the container, nothing else. Of the targets on
//    the command line (fixed by the image's ENTRYPOINT: /work /ref1 /ref2 /ref3; sandbox-ai and axross pass no
//    arguments), only those listed as mount points in /proc/self/mountinfo are allowed. A target the image has as an
//    empty folder but nobody mounted is left out. With none mounted (only a start that lists the tools, such as CI's;
//    sandbox-ai always mounts /work) every path is refused; an unreadable mount table stops the server.
// 2. MCP Roots are never used. In 2.1.0 a 2025-era client's roots REPLACE the allowed directories (server.js,
//    updateAllowedDirectoriesFromRoots), so a client advertising file:/// would widen them to the whole container.
//    Here the server never asks for roots: listRoots refuses, the post-initialize roots request is not made, and
//    notifications/roots/list_changed is ignored.
import { readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { serveStdio, StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { resolveAllowedDirectories } from "@modelcontextprotocol/server-filesystem/dist/index.js";
import { createServer } from "@modelcontextprotocol/server-filesystem/dist/server.js";

export const ROOTS_REFUSED =
  "MCP Roots are not used by this server: its allowed directories are the folders mounted into its container";

/** The mount points of a /proc/self/mountinfo text (its fifth field, with the kernel's octal escapes decoded). */
export function mountPoints(mountinfo) {
  const points = new Set();
  for (const line of mountinfo.split("\n")) {
    const fields = line.split(" ");
    if (fields.length >= 5 && fields[4]) {
      points.add(fields[4].replace(/\\([0-7]{3})/g, (_, octal) => String.fromCharCode(parseInt(octal, 8))));
    }
  }
  return points;
}

/** The TARGETS (absolute, normalized, not "/") that are mount points in POINTS, in the order given. */
export function mountedTargets(targets, points) {
  return targets.filter(
    (target) =>
      typeof target === "string" &&
      path.isAbsolute(target) &&
      path.normalize(target) === target &&
      target !== "/" &&
      points.has(target),
  );
}

/** Upstream's server for one connection, allowed DIRECTORIES only: it never asks the client for roots. */
export function confinedServer(directories, era) {
  const server = createServer(directories, { era, onCannotOperate: () => process.exit(1) });
  const protocol = server.server;
  // Every roots/list the server could send goes through this method (the post-initialize load, the
  // roots/list_changed refresh and the SDK's legacy input-required shim): refused before anything is sent.
  protocol.listRoots = async () => {
    throw new Error(ROOTS_REFUSED);
  };
  protocol.oninitialized = () => {};
  protocol.setNotificationHandler("notifications/roots/list_changed", () => {});
  return server;
}

/**
 * Serve on STDIN/STDOUT with the TARGETS that MOUNTINFO lists as mount points. None mounted: served with no allowed
 * directory, so every path is refused (upstream's check admits nothing against an empty list). Exits 1 when
 * upstream's resolution yields a directory that is not one of them (it adds a target's realpath when that differs:
 * a mount point never does).
 */
export async function main(targets, mountinfo, stdin = process.stdin, stdout = process.stdout) {
  const mounted = mountedTargets(targets, mountPoints(mountinfo));
  if (mounted.length === 0) {
    console.error(
      `Warning: no folder is mounted at ${targets.join(", ")}: every path is refused; mount the folder this server ` +
        "may use (sandbox-ai mcp add filesystem --mount /work=HOST)",
    );
  }
  const allowed = mounted.length === 0 ? [] : await resolveAllowedDirectories(mounted);
  const extra = allowed.filter((directory) => !mounted.includes(directory));
  if (allowed.length !== mounted.length || extra.length > 0) {
    console.error(`Error: the allowed directories would be ${allowed.join(", ")}, not the mounted ${mounted.join(", ")}`);
    process.exit(1);
  }
  const handle = serveStdio(({ era }) => confinedServer(allowed, era), {
    transport: new StdioServerTransport(stdin, stdout),
    onerror: (error) => {
      console.error("Transport error:", error);
      process.exitCode = 1;
    },
  });
  console.error(`Secure MCP Filesystem Server running on stdio; allowed (the mounted folders): ${allowed.join(", ")}`);
  return handle;
}

function isEntryPoint() {
  try {
    return realpathSync(process.argv[1] ?? "") === realpathSync(fileURLToPath(import.meta.url));
  } catch {
    return false;
  }
}

if (isEntryPoint()) {
  try {
    await main(process.argv.slice(2), readFileSync("/proc/self/mountinfo", "utf8"));
  } catch (error) {
    console.error("Fatal error running server:", error);
    process.exit(1);
  }
}
