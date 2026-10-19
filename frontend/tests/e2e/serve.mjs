// Copy the built frontend into the backend package and start `papertrail serve`.
import { cpSync, existsSync, rmSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";

const port = process.argv[2] ?? "8765";
const dist = path.resolve("dist");
const staticDir = path.resolve("../backend/papertrail/static");
if (!existsSync(path.join(dist, "index.html"))) {
  console.error("Build the frontend first: npm run build");
  process.exit(1);
}
rmSync(staticDir, { recursive: true, force: true });
cpSync(dist, staticDir, { recursive: true });

const child = spawn(
  "uv",
  ["run", "--project", "../backend", "papertrail", "serve", "--port", port],
  {
    stdio: "inherit",
    env: process.env,
  },
);
const stop = () => child.kill("SIGINT");
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
child.on("exit", (code) => process.exit(code ?? 0));
