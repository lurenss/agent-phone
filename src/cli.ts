#!/usr/bin/env bun
import { parseArgs } from "node:util";
import { join } from "node:path";

const help = `Control an Android USB phone or emulator through ADB on this Mac.
agent-phone devices
agent-phone lease SERIAL --why TASK
agent-phone release SERIAL

Commands below take SERIAL and --why TASK.
  state                        active app, screen and keyboard
  snapshot                     visible Android elements
  screenshot FILE.jpg          save the screen
  find LABEL | --id ID         show one matching element
  wait LABEL | --id ID         wait for a match (10 seconds)
  open PACKAGE                 launch an app
  tap LABEL | --id ID | X Y    tap an element or a point
  set-text TEXT [--id ID]      replace text in the selected or focused field
  swipe X1 Y1 X2 Y2            swipe between two points (300 ms)
  key KEY                      send one Android key, e.g. BACK or HOME

Use -- before positional text starting with a dash.`;

class UsageError extends Error {}

class AndroidError extends Error {
  constructor(
    readonly output: string,
    readonly status: number,
  ) {
    super(output);
  }
}

async function call(args: string[]): Promise<string> {
  if (!Bun.which("uv")) throw new Error("Install uv to run Agent Phone.");
  const program = ["uv", "run", "--no-project", "--script", join(import.meta.dir, "local.py")];
  const child = Bun.spawn([...program, ...args], { stdout: "pipe", stderr: "pipe" });
  const [output, diagnostic, status] = await Promise.all([
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
    child.exited,
  ]);
  if (status !== 0) {
    throw new AndroidError(
      output.trim() || JSON.stringify({ error: diagnostic.trim() || "Android transport stopped" }),
      status,
    );
  }
  return output;
}

async function unique(serial: string, selector: string, why: string): Promise<string> {
  const answer = await call(["ui", serial, "--on", selector, `--why=${why}`]);
  const { elements } = JSON.parse(answer);
  if (!Array.isArray(elements)) throw new Error("Expected an array of screen elements.");
  if (elements.length !== 1) {
    throw new AndroidError(
      JSON.stringify({
        error: elements.length ? "ambiguous" : "not_found",
        matches: elements.length,
      }),
      1,
    );
  }
  return JSON.stringify(elements[0]) + "\n";
}

async function run(argv: string[]): Promise<string> {
  if (argv.length === 0 || (argv.length === 1 && argv[0] === "--help")) return help + "\n";
  let parsed;
  try {
    parsed = parseArgs({
      args: argv,
      allowPositionals: true,
      options: {
        why: { type: "string" },
        id: { type: "string" },
        local: { type: "boolean" }, // Accepted by existing USB and emulator scripts.
      },
    });
  } catch (error) {
    throw new UsageError(String(error));
  }
  const { why: given, id } = parsed.values;
  const [command, serial, ...words] = parsed.positionals;
  if (command === "devices" && serial === undefined && given === undefined && id === undefined)
    return call(["phones"]);
  if (!serial || !/^[\w.:-]{1,64}$/.test(serial) || serial.startsWith("-"))
    throw new UsageError(help);
  if (command === "release" && !words.length && given === undefined && id === undefined)
    return call(["release", serial]);
  const why = given?.trim();
  if (!why || why.length > 200) throw new UsageError("Give --why with 1 to 200 characters.");
  const args = [serial, `--why=${why}`];
  const first = words[0];
  const noId = id === undefined;

  if (command === "swipe" || (command === "tap" && words.length === 2)) {
    const count = command === "swipe" ? 4 : 2;
    if (
      !noId ||
      words.length !== count ||
      !words.every((value) => /^\d+$/.test(value) && Number(value) <= 10000)
    )
      throw new UsageError(`Give ${count} coordinates, each an integer from 0 to 10000.`);
    return call([command, ...args, "--", ...words]);
  }

  switch (command) {
    case "lease":
      if (why.length > 80) throw new UsageError("A lease task can contain up to 80 characters.");
      if (words.length === 0 && noId) return call(["lease", serial, `--task=${why}`]);
      break;
    case "state":
    case "snapshot":
      if (words.length === 0 && noId)
        return call([command === "snapshot" ? "ui" : "state", ...args]);
      break;
    case "open":
    case "key":
    case "screenshot":
      if (words.length === 1 && first && noId) return call([command, ...args, "--", first]);
      break;
    case "tap":
    case "find":
    case "wait": {
      const selector =
        id && !words.length ? { id } : noId && words.length === 1 && first ? { text: first } : null;
      if (!selector) break;
      if (command === "wait")
        return call(["wait", ...args, "--until", JSON.stringify({ see: selector })]);
      const on = JSON.stringify(selector);
      if (command === "find") return unique(serial, on, why);
      return call(["tap", ...args, "--on", on]);
    }
    case "set-text":
      if (words.length !== 1 || first === undefined || id === "") break;
      if (id !== undefined) {
        const on = JSON.stringify({ id });
        return call(["set-text", ...args, "--on", on, "--", first]);
      }
      return call(["set-text", ...args, "--", first]);
  }
  throw new UsageError(help);
}

try {
  process.stdout.write(await run(process.argv.slice(2)));
} catch (error) {
  if (error instanceof AndroidError) {
    console.error(error.output);
    process.exitCode = error.status;
  } else {
    console.error(
      JSON.stringify({ error: error instanceof Error ? error.message : String(error) }),
    );
    process.exitCode = error instanceof UsageError ? 2 : 1;
  }
}
