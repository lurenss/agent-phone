import { afterAll, beforeAll, expect, test } from "bun:test";
import { chmod, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

let folder: string;
let script: string;
const cli = join(import.meta.dir, "../agent-phone");
beforeAll(async () => {
  folder = await mkdtemp(join(tmpdir(), "agent-phone-"));
  script = join(folder, "wp.py");
  await Bun.write(
    script,
    `
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALL_LOG"], "a") as log:
    print(json.dumps(args), file=log)
if args[0] == os.environ.get("FAIL_CMD"):
    print(json.dumps({"error":"unknown_delivery"}))
    sys.exit(1)
if args[0] == "ui" and "--on" in args:
    target = next(iter(json.loads(args[args.index("--on") + 1]).values()))
    print(json.dumps({"elements": [{"text":target}] * {"missing":0,"twice":2}.get(target,1)}))
else:
    print(json.dumps({"ok":True}))
`,
  );
  const uv = join(folder, "uv");
  await Bun.write(
    uv,
    `#!/usr/bin/env python3
import json, os, sys
with open(os.environ["CALL_LOG"], "a") as log:
    print(json.dumps(sys.argv[1:]), file=log)
if os.environ.get("FAIL_CMD"):
    print(json.dumps({"error": "unknown_delivery"}))
    sys.exit(1)
print(json.dumps({"ok": True}))
`,
  );
  await chmod(uv, 0o755);
});
afterAll(async () => {
  await rm(folder, { recursive: true, force: true });
});

async function call(args: string[], fail = "") {
  const log = join(folder, crypto.randomUUID());
  const child = Bun.spawn([cli, ...args], {
    env: {
      ...process.env,
      PATH: folder + ":" + process.env.PATH,
      CALL_LOG: log,
      AGENT_PHONE_WP: script,
      FAIL_CMD: fail,
    },
    stderr: "pipe",
    stdout: "pipe",
  });
  const [status, out, error] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  const trace = Bun.file(log);
  const calls: string[][] = (await trace.exists())
    ? (await trace.text())
        .trim()
        .split("\n")
        .map((line) => JSON.parse(line))
    : [];
  return { status, out: out.trim(), error: error.trim(), calls };
}

test("one transport call for each direct command", async () => {
  const why = ["--why", "review"];
  const phone = ["emu", "--why=review"];
  const cases: [string[], string[]][] = [
    [["devices"], ["phones"]],
    [
      ["lease", "emu", ...why],
      ["lease", "emu", "--task=review"],
    ],
    [
      ["release", "emu"],
      ["release", "emu"],
    ],
    [
      ["snapshot", "emu", ...why],
      ["ui", ...phone],
    ],
    [
      ["state", "emu", ...why],
      ["state", ...phone],
    ],
    [
      ["screenshot", "emu", "screen.jpg", ...why],
      ["screenshot", ...phone, "--", "screen.jpg"],
    ],
    [
      ["open", "emu", "demo.app", ...why],
      ["open", ...phone, "--", "demo.app"],
    ],
    [
      ["key", "emu", "BACK", ...why],
      ["key", ...phone, "--", "BACK"],
    ],
    [
      ["tap", "emu", "120", "300", ...why],
      ["tap", ...phone, "--", "120", "300"],
    ],
    [
      ["swipe", "emu", "1", "20", "3", "4", ...why],
      ["swipe", ...phone, "--", "1", "20", "3", "4"],
    ],
    [
      ["set-text", "emu", ...why, "--", "--Café menu ☕"],
      ["set-text", ...phone, "--", "--Café menu ☕"],
    ],
    [
      ["set-text", "emu", "", ...why],
      ["set-text", ...phone, "--", ""],
    ],
    [
      ["wait", "emu", "Done 🌅", ...why],
      ["wait", ...phone, "--until", JSON.stringify({ see: { text: "Done 🌅" } })],
    ],
    [
      ["wait", "emu", "--id", "done", ...why],
      ["wait", ...phone, "--until", JSON.stringify({ see: { id: "done" } })],
    ],
  ];
  for (const [args, expected] of cases) {
    const result = await call(args);
    expect(result.status).toBe(0);
    expect(result.calls).toEqual([expected]);
  }
});

test("named tap and targeted text check uniqueness before sending", async () => {
  for (const [args, on, command] of [
    [["tap", "emu", "Confirm"], { text: "Confirm" }, "tap"],
    [["set-text", "emu", "Café menu 🌅", "--id", "name"], { id: "name" }, "set-text"],
    [["tap", "emu", "--id", "finish"], { id: "finish" }, "tap"],
  ] as const) {
    const result = await call([...args, "--why", "review"]);
    expect(result.status).toBe(0);
    expect(result.calls.map((row) => row[0])).toEqual(["ui", command]);
    for (const row of result.calls) expect(row[row.indexOf("--on") + 1]).toBe(JSON.stringify(on));
  }
});

test("missing and duplicate targets send zero inputs", async () => {
  for (const command of ["find", "tap", "set-text"]) {
    for (const [label, error] of [
      ["missing", "not_found"],
      ["twice", "ambiguous"],
    ] as const) {
      const rest = command === "set-text" ? ["new", "--id", label] : [label];
      const result = await call([command, "emu", ...rest, "--why", "review"]);
      expect(result.status).toBe(1);
      expect(JSON.parse(result.error).error).toBe(error);
      expect(result.calls.map((row) => row[0])).toEqual(["ui"]);
    }
  }
  const match = await call(["--why", "review", "find", "emu", "name"]);
  expect(JSON.parse(match.out)).toEqual({ text: "name" });
});

test("a failed action is reported once and never replayed", async () => {
  const result = await call(["tap", "emu", "Done", "--why", "review"], "tap");
  expect(result.status).toBe(1);
  expect(JSON.parse(result.error).error).toBe("unknown_delivery");
  expect(result.calls.map((row) => row[0])).toEqual(["ui", "tap"]);
});

test("usage errors make no transport calls", async () => {
  for (const args of [
    ["devices", "extra"],
    ["snapshot", "emu"],
    ["lease", "emu", "--why", "x".repeat(81)],
    ["tap", "emu", "1", "bad", "--why", "review"],
    ["tap", "emu", "A", "--id", "B", "--why", "review"],
    ["set-text", "emu", "x", "--id", "", "--why", "review"],
    ["swipe", "emu", "1", "2", "--why", "review"],
  ]) {
    const result = await call(args);
    expect(result.status).toBe(2);
    expect(result.calls).toEqual([]);
  }
});

test("--local selects the bundled adapter and sends each input once", async () => {
  const program = ["run", "--no-project", "--script", join(import.meta.dir, "../src/local.py")];
  const devices = await call(["--local", "devices"]);
  expect(devices.status).toBe(0);
  expect(devices.calls).toEqual([[...program, "phones"]]);
  for (const [command, serial] of [
    ["tap", "R58M1234"],
    ["set-text", "emulator-5554"],
  ] as const) {
    const words = command === "set-text" ? ["--", "--café menu"] : [];
    const result = await call(
      [command, serial, "--id", "query", "--why", "test", "--local", ...words],
      command,
    );
    expect(result.status).toBe(1);
    expect(JSON.parse(result.error).error).toBe("unknown_delivery");
    expect(result.calls).toEqual([
      [...program, command, serial, "--why=test", "--on", '{"id":"query"}', ...words],
    ]);
  }
});
