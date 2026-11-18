import { expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { plan } from "../src/cli";

const cli = join(import.meta.dir, "../agent-phone");

async function call(...args: string[]) {
  const child = Bun.spawn([cli, ...args], {
    env: { ...process.env, AGENT_PHONE_REDIS_URL: "redis://127.0.0.1:1" },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [status, output, error] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  return { status, output, error };
}

test("public command arguments preserve IDs, Unicode, empty fields and literal dashes", () => {
  const why = "--why=review";
  const phone = ["emu", why];
  const cases: [string[], string[]][] = [
    [["devices"], ["phones"]],
    [["--local", "devices"], ["phones"]],
    [
      ["lease", ...phone],
      ["lease", "emu", "--task=review"],
    ],
    [
      ["release", "emu"],
      ["release", "emu"],
    ],
    [
      ["history", "emu"],
      ["history", "emu"],
    ],
    [
      ["snapshot", ...phone],
      ["ui", ...phone],
    ],
    [
      ["state", ...phone],
      ["state", ...phone],
    ],
    [
      ["screenshot", ...phone, "screen.jpg"],
      ["screenshot", ...phone, "--", "screen.jpg"],
    ],
    [
      ["open", ...phone, "demo.app"],
      ["open", ...phone, "--", "demo.app"],
    ],
    [
      ["key", ...phone, "BACK"],
      ["key", ...phone, "--", "BACK"],
    ],
    [
      ["tap", ...phone, "120", "300"],
      ["tap", ...phone, "--", "120", "300"],
    ],
    [
      ["swipe", ...phone, "1", "20", "3", "4"],
      ["swipe", ...phone, "--", "1", "20", "3", "4"],
    ],
    [
      ["tap", ...phone, "Confirm"],
      ["tap", ...phone, "--on", JSON.stringify({ text: "Confirm" })],
    ],
    [
      ["tap", ...phone, "--id", "done"],
      ["tap", ...phone, "--on", JSON.stringify({ id: "done" })],
    ],
    [
      ["find", ...phone, "--id", "name"],
      ["find", ...phone, "--on", JSON.stringify({ id: "name" })],
    ],
    [
      ["set-text", ...phone, "--", "--Café 🌅"],
      ["set-text", ...phone, "--", "--Café 🌅"],
    ],
    [
      ["set-text", ...phone, ""],
      ["set-text", ...phone, "--", ""],
    ],
    [
      ["set-text", ...phone, "Café 🌅", "--id", "name"],
      ["set-text", ...phone, "--on", JSON.stringify({ id: "name" }), "--", "Café 🌅"],
    ],
    [
      ["wait", ...phone, "Done 🌅"],
      ["wait", ...phone, "--until", JSON.stringify({ see: { text: "Done 🌅" } })],
    ],
    [
      ["wait", ...phone, "--id", "done"],
      ["wait", ...phone, "--until", JSON.stringify({ see: { id: "done" } })],
    ],
  ];
  for (const [args, expected] of cases) expect(plan(args)).toEqual(expected);
});

test("the executable shows help without Redis or a phone", async () => {
  const result = await call("--help");
  expect(result.status).toBe(0);
  expect(result.output).toContain("agent-phone routine run");
  expect(result.error).toBe("");
});

test("invalid commands exit with a JSON usage error before accessing Redis", async () => {
  for (const args of [
    ["devices", "extra"],
    ["snapshot", "emu"],
    ["lease", "emu", "--why", "x".repeat(81)],
    ["tap", "emu", "1", "bad", "--why", "review"],
    ["tap", "emu", "A", "--id", "B", "--why", "review"],
    ["set-text", "emu", "x", "--id", "", "--why", "review"],
    ["swipe", "emu", "1", "2", "--why", "review"],
  ]) {
    const result = await call(...args);
    expect(result.status).toBe(2);
    expect(result.output).toBe("");
    expect(JSON.parse(result.error).error).toBeString();
  }
});

test("a malformed later step prevents saving a routine", async () => {
  const folder = await mkdtemp(join(tmpdir(), "agent-phone-cli-"));
  try {
    const path = join(folder, "invalid.json");
    await Bun.write(
      path,
      JSON.stringify([
        ["open", "com.android.settings"],
        ["lease", "another-phone"],
      ]),
    );
    const result = await call("routine", "save", "example", path);
    expect(result.status).toBe(2);
    expect(JSON.parse(result.error).error).toContain("Step 2");
  } finally {
    await rm(folder, { recursive: true, force: true });
  }
});
