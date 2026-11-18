#!/usr/bin/env bun
import { parseArgs } from "node:util";
import { join } from "node:path";

const help = `Control an Android USB phone or emulator through ADB on this Mac.
agent-phone devices
agent-phone lease SERIAL --why TASK
agent-phone release SERIAL
agent-phone history SERIAL
agent-phone routine save NAME FILE.json | list | show NAME
agent-phone routine run NAME SERIAL --why TASK

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

async function call(args: string[], input?: string): Promise<string> {
  if (!Bun.which("uv")) throw new Error("Install uv to run Agent Phone.");
  const program = [
    "uv",
    "run",
    "--no-project",
    "--python",
    ">=3.11,<3.15",
    "--with-requirements",
    join(import.meta.dir, "../requirements.txt"),
    "python",
    join(import.meta.dir, "local.py"),
  ];
  const child = Bun.spawn([...program, ...args], {
    stdin: input === undefined ? "ignore" : new Blob([input]),
    stdout: "pipe",
    stderr: "pipe",
  });
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

function plan(argv: string[], routine?: string): string[] {
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
    return ["phones"];
  if (!serial || !/^[\w.:-]{1,64}$/.test(serial) || serial.startsWith("-"))
    throw new UsageError(help);
  if (
    (command === "release" || command === "history") &&
    !words.length &&
    given === undefined &&
    id === undefined
  )
    return [command, serial];
  const why = given?.trim();
  if (!why || why.length > 200) throw new UsageError("Give --why with 1 to 200 characters.");
  if (routine !== undefined) {
    if (words.length || id !== undefined) throw new UsageError(help);
    return ["routine-run", serial, `--why=${why}`, "--", routine];
  }
  if (command === "lease") {
    if (why.length > 80) throw new UsageError("A lease task can contain up to 80 characters.");
    if (words.length || id !== undefined) throw new UsageError(help);
    return ["lease", serial, `--task=${why}`];
  }
  if (!command) throw new UsageError(help);
  const [action, ...options] = actionArgs(command, words, id);
  return [action, serial, `--why=${why}`, ...options];
}

function actionArgs(command: string, words: string[], id?: string): [string, ...string[]] {
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
    return [command, "--", ...words];
  }

  switch (command) {
    case "state":
    case "snapshot":
      if (words.length === 0 && noId) return [command === "snapshot" ? "ui" : "state"];
      break;
    case "open":
      if (!first || !/^[A-Za-z]\w*(\.\w+)+$/.test(first))
        throw new UsageError("Invalid Android package.");
      if (words.length === 1 && noId) return [command, "--", first];
      break;
    case "key":
      if (!first || !/^[A-Za-z0-9_]+$/.test(first)) throw new UsageError("Invalid Android key.");
      if (words.length === 1 && noId) return [command, "--", first];
      break;
    case "screenshot":
      if (words.length === 1 && first && noId) return [command, "--", first];
      break;
    case "tap":
    case "find":
    case "wait": {
      const selector =
        id && !words.length ? { id } : noId && words.length === 1 && first ? { text: first } : null;
      if (!selector) break;
      if (command === "wait") return ["wait", "--until", JSON.stringify({ see: selector })];
      return [command, "--on", JSON.stringify(selector)];
    }
    case "set-text":
      if (words.length !== 1 || first === undefined || id === "") break;
      if (id !== undefined) {
        const on = JSON.stringify({ id });
        return ["set-text", "--on", on, "--", first];
      }
      return ["set-text", "--", first];
  }
  throw new UsageError(help);
}

async function run(argv: string[]): Promise<string> {
  if (!argv.length || (argv.length === 1 && argv[0] === "--help")) return help + "\n";
  if (argv[0] !== "routine") return call(plan(argv));
  const [, verb, name, ...rest] = argv;
  if (verb === "list" && name === undefined) return call(["routine-list"]);
  if (!name || !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(name)) {
    throw new UsageError(
      "Give the routine a name of 1 to 64 letters, digits, hyphens or underscores.",
    );
  }
  if (verb === "show" && !rest.length) return call(["routine-show", name]);
  if (verb === "run") return call(plan(["run", ...rest], name));
  if (verb !== "save" || rest.length !== 1) throw new UsageError(help);
  const steps: unknown = await Bun.file(rest[0]!).json();
  if (!Array.isArray(steps) || !steps.length || steps.length > 100) {
    throw new UsageError("A routine is a JSON array of 1 to 100 steps.");
  }
  const commands = steps.map((step, index) => {
    try {
      if (!Array.isArray(step) || !step.every((v) => typeof v === "string") || !step[0]) {
        throw new Error("Expected a command and string arguments.");
      }
      if (step[0] === "screenshot")
        throw new Error("Use screenshot directly to choose a local file.");
      const { values, positionals } = parseArgs({
        args: step.slice(1),
        allowPositionals: true,
        options: { id: { type: "string" } },
      });
      return actionArgs(step[0], positionals, values.id);
    } catch (error) {
      throw new UsageError(`Step ${index + 1}: ${error instanceof Error ? error.message : error}`);
    }
  });
  return call(["routine-save", name], JSON.stringify({ steps, commands }));
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
