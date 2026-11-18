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

export async function call(args: string[]): Promise<string> {
  const script =
    process.env.AGENT_PHONE_WP ??
    join(homedir(), ".claude/skills/driving-phones-via-walkie-api/scripts/wp.py");
  if (!(await Bun.file(script).exists())) {
    throw new Error("Set AGENT_PHONE_WP to the installed wp.py path.");
  }
  const child = Bun.spawn(["python3", script, ...args], { stdout: "pipe", stderr: "pipe" });
  const [output, diagnostic, status] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (status !== 0) {
    throw new TransportError(
      output.trim() || JSON.stringify({ error: diagnostic.trim() || "wp.py stopped" }),
      status,
    );
  }
  return output;
}
