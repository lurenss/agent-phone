#!/usr/bin/env bun
import { parseArgs } from "node:util";
import * as walkie from "./walkie";

const help = `agent-phone devices
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

Use -- before positional text starting with a dash. Set AGENT_PHONE_WP to override wp.py.`;

class UsageError extends Error {}

async function unique(serial: string, selector: string, why: string): Promise<string> {
  const answer = await walkie.call(["ui", serial, "--on", selector, `--why=${why}`]);
  const { elements } = JSON.parse(answer);
  if (!Array.isArray(elements)) throw new Error("Expected an array of screen elements.");
  if (elements.length !== 1) {
    throw new walkie.TransportError(
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
      },
    });
  } catch (error) {
    throw new UsageError(String(error));
  }
  const { why: given, id } = parsed.values;
  const [command, serial, ...words] = parsed.positionals;
  if (command === "devices" && serial === undefined && given === undefined && id === undefined)
    return walkie.call(["phones"]);
  if (!serial || !/^[\w.:-]{1,64}$/.test(serial) || serial.startsWith("-")) throw new UsageError(help);
  if (command === "release" && !words.length && given === undefined && id === undefined)
    return walkie.call(["release", serial]);
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
    return walkie.call([command, ...args, "--", ...words]);
  }

  switch (command) {
    case "lease":
      if (why.length > 80) throw new UsageError("A lease task can contain up to 80 characters.");
      if (words.length === 0 && noId) return walkie.call(["lease", serial, `--task=${why}`]);
      break;
    case "state":
    case "snapshot":
      if (words.length === 0 && noId)
        return walkie.call([command === "snapshot" ? "ui" : "state", ...args]);
      break;
    case "open":
    case "key":
    case "screenshot":
      if (words.length === 1 && first && noId) return walkie.call([command, ...args, "--", first]);
      break;
    case "tap":
    case "find":
    case "wait": {
      const selector =
        id && !words.length ? { id } : noId && words.length === 1 && first ? { text: first } : null;
      if (!selector) break;
      if (command === "wait")
        return walkie.call(["wait", ...args, "--until", JSON.stringify({ see: selector })]);
      const on = JSON.stringify(selector);
      const element = await unique(serial, on, why);
      if (command === "find") return element;
      return walkie.call(["tap", ...args, "--on", on]);
    }
    case "set-text":
      if (words.length !== 1 || first === undefined || id === "") break;
      if (id !== undefined) {
        const on = JSON.stringify({ id });
        await unique(serial, on, why);
        return walkie.call(["set-text", ...args, "--on", on, "--", first]);
      }
      return walkie.call(["set-text", ...args, "--", first]);
  }
  throw new UsageError(help);
}

try {
  process.stdout.write(await run(process.argv.slice(2)));
} catch (error) {
  if (error instanceof walkie.TransportError) {
    console.error(error.output);
    process.exitCode = error.status;
  } else {
    console.error(JSON.stringify({ error: error instanceof Error ? error.message : String(error) }));
    process.exitCode = error instanceof UsageError ? 2 : 1;
  }
}
