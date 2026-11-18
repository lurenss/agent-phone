import { homedir } from "node:os";
import { join } from "node:path";

export class TransportError extends Error {
  constructor(
    readonly output: string,
    readonly status: number,
  ) {
    super(output);
  }
}

export async function call(local: boolean, args: string[]): Promise<string> {
  const script =
    process.env.AGENT_PHONE_WP ??
    join(homedir(), ".claude/skills/driving-phones-via-walkie-api/scripts/wp.py");
  if (!local && !(await Bun.file(script).exists())) {
    throw new Error("Set AGENT_PHONE_WP to the installed wp.py path.");
  }
  const program = local
    ? ["uv", "run", "--no-project", "--script", join(import.meta.dir, "local.py")]
    : ["python3", script];
  if (local && !Bun.which("uv"))
    throw new Error("Local Android requires uv. Install it with brew install uv.");
  const child = Bun.spawn([...program, ...args], { stdout: "pipe", stderr: "pipe" });
  const [output, diagnostic, status] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (status !== 0) {
    throw new TransportError(
      output.trim() || JSON.stringify({ error: diagnostic.trim() || "Android transport stopped" }),
      status,
    );
  }
  return output;
}
