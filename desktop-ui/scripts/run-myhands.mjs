import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const child = spawn(
  python,
  [
    "-m", "uvicorn", "server:app",
    "--app-dir", path.join(projectRoot, "myhands-sidecar"),
    "--host", "127.0.0.1",
    "--port", "8795",
  ],
  { cwd: projectRoot, stdio: "inherit", env: process.env },
);

child.on("error", (error) => {
  console.error(`Could not start the My Hands service with '${python}': ${error.message}`);
  console.error("Install the sidecar dependencies in that Python environment, or set PYTHON to its interpreter path.");
  process.exitCode = 1;
});
child.on("exit", (code, signal) => {
  if (signal) {
    console.error(`My Hands service stopped by ${signal}.`);
    process.exitCode = 1;
  } else {
    process.exitCode = code ?? 1;
  }
});
