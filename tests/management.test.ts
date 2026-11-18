import { afterAll, afterEach, beforeAll, beforeEach, expect, test } from "bun:test";
import { RedisClient } from "bun";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { hostname, tmpdir, userInfo } from "node:os";
import { join } from "node:path";
import { execute } from "../src/manager";

const prefix = `agent-phone:${hostname()}:`;
const owner = `${userInfo().username}/alice`;
const keys = ["AGENT_PHONE_REDIS_URL", "AGENT_PHONE_LOCAL_STATE", "AGENT_PHONE_OWNER"] as const;
const savedEnv = keys.map((key) => process.env[key]);
let folder: string;
let socket: string;
let server: Bun.Subprocess | undefined;
let redis: RedisClient;
type Phone = { serial: string; state: string; model: string };
let online: Phone[];
type Selector = { text?: string; id?: string };
type Input = { command: string; words: string[]; selector?: Selector };
let actions: Input[];
let drive: (input: Input, beforeInput: () => Promise<void>) => Promise<unknown>;
const devices = {
  listDevices: async () => online,
  android: (_serial: string) => ({
    drive: (
      command: string,
      words: string[],
      selector: Selector | undefined,
      beforeInput: () => Promise<void>,
    ) => {
      const input = { command, words, selector };
      actions.push(input);
      return drive(input, beforeInput);
    },
    close: async () => {},
  }),
};
const run = (args: string[], input?: string) => execute(args, input, devices);
const reserve = (serial = "one") => run(["lease", serial, "--task=test"]);

beforeAll(async () => {
  folder = await mkdtemp(join(tmpdir(), "agent-phone-"));
  socket = join(folder, "r.sock");
  server = Bun.spawn(
    [
      "redis-server",
      "--port",
      "0",
      "--unixsocket",
      socket,
      "--save",
      "",
      "--appendonly",
      "no",
      "--dir",
      folder,
    ],
    { stdout: "ignore", stderr: "inherit" },
  );
  for (let attempt = 0; attempt < 100 && server.exitCode === null; attempt++) {
    const probe = new RedisClient(`redis+unix://${socket}`, { autoReconnect: false });
    try {
      if ((await probe.ping()) === "PONG") return;
    } catch {
      // Redis has not yet opened its temporary socket.
    } finally {
      probe.close();
    }
    await Bun.sleep(20);
  }
  throw new Error("The temporary Redis server did not start");
});

beforeEach(async () => {
  process.env.AGENT_PHONE_REDIS_URL = `unix://${socket}`;
  process.env.AGENT_PHONE_LOCAL_STATE = folder;
  process.env.AGENT_PHONE_OWNER = "alice";
  redis = new RedisClient(`redis+unix://${socket}`);
  await redis.send("FLUSHDB", []);
  online = [{ serial: "one", state: "device", model: "test" }];
  actions = [];
  drive = async (_action, beforeInput) => {
    await beforeInput();
    return null;
  };
});

afterEach(() => {
  redis.close();
  keys.forEach((key, index) => {
    if (savedEnv[index] === undefined) delete process.env[key];
    else process.env[key] = savedEnv[index];
  });
});

afterAll(async () => {
  if (server) {
    server.kill();
    await server.exited;
  }
  if (folder) await rm(folder, { recursive: true, force: true });
});

test("inventory keeps disconnected devices and counts only ready ones", async () => {
  online.push(
    { serial: "two", state: "device", model: "test" },
    { serial: "three", state: "unauthorized", model: "test" },
  );
  await reserve();
  const initial = await run(["phones"]);
  expect(initial).toMatchObject({
    counts: { known: 3, active: 2, available: 1, busy: 1 },
    phones: expect.arrayContaining([
      expect.objectContaining({ serial: "one", lease: expect.objectContaining({ owner }) }),
    ]),
  });
  online = [{ serial: "two", state: "offline", model: "test" }];
  expect(await run(["phones"])).toMatchObject({
    counts: { known: 3, active: 0, available: 0, busy: 0 },
    phones: [
      { serial: "one", state: "disconnected" },
      { serial: "three", state: "disconnected" },
      { serial: "two", state: "offline" },
    ],
  });
  await expect(reserve("two")).rejects.toThrow("device_not_ready");
});

test("two CLI processes race for one lease and only the winner can act", async () => {
  const script = `
    import { execute } from "./src/manager";
    const devices = {
      listDevices: async () => [{ serial: "one", state: "device", model: "test" }],
      android: () => ({ close: async () => {} }),
    };
    try { console.log(JSON.stringify(await execute(["lease", "one", "--task=race"], undefined, devices))); }
    catch (error) { console.error(error.message); process.exitCode = 1; }
  `;
  async function claim(label: string) {
    const child = Bun.spawn([process.execPath, "-e", script], {
      cwd: join(import.meta.dir, ".."),
      env: { ...process.env, AGENT_PHONE_OWNER: label },
      stdout: "pipe",
      stderr: "pipe",
    });
    const [code, out, error] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ]);
    return { label, code, out, error };
  }
  const entrants = await Promise.all([claim("alice"), claim("bob")]);
  const winners = entrants.filter((entry) => entry.code === 0);
  expect(winners).toHaveLength(1);
  const loser = entrants.find((entry) => entry.code !== 0)!;
  expect(loser.error).toMatch(/device_busy|leased_by_another_owner/);
  expect(JSON.parse(winners[0]!.out).lease.owner).toBe(
    `${userInfo().username}/${winners[0]!.label}`,
  );
  process.env.AGENT_PHONE_OWNER = loser.label;
  await expect(run(["key", "one", "--why=test", "--", "BACK"])).rejects.toThrow(
    "leased_by_another_owner",
  );
  await expect(run(["release", "one"])).rejects.toThrow("leased_by_another_owner");
  expect(actions).toHaveLength(0);
  await redis.send("PEXPIRE", [prefix + "lease:one", "1"]);
  await Bun.sleep(20);
  expect(await reserve()).toMatchObject({
    lease: { owner: `${userInfo().username}/${loser.label}` },
    renewed: false,
  });
});

test("imported file leases retain their original owner and expiry", async () => {
  const path = join(folder, createHash("sha256").update("one").digest("hex"));
  const until = Date.now() / 1000 + 35;
  await Bun.write(path, JSON.stringify({ task: "existing", until }));
  await expect(run(["release", "one"])).rejects.toThrow("leased_by_another_owner");
  const lease = JSON.parse((await redis.get(prefix + "lease:one"))!);
  expect(lease).toMatchObject({ owner: userInfo().username, task: "existing", until });
  expect(await Bun.file(path).exists()).toBe(false);
});

test("failed routine stops at the failed step and preserves correlated history", async () => {
  const steps = [["state"], ["key", "BACK"], ["key", "HOME"]];
  const commands = [["state"], ["key", "--", "BACK"], ["key", "--", "HOME"]];
  // Seed the existing on-disk format to exercise compatibility across upgrades.
  await redis.hset(prefix + "routines", { sample: JSON.stringify({ steps, commands }) });
  await reserve();
  drive = async ({ command }) => {
    if (command === "key") throw new Error("not_found");
    return { app: "demo.app" };
  };
  const failure = await run(["routine-run", "one", "--why=review", "--", "sample"]).catch(
    (error: Error) => error,
  );
  expect(failure).toMatchObject({
    message: "not_found",
    failedStep: 2,
    completed: 1,
    runId: expect.any(String),
  });
  expect(actions.map(({ command, words }) => [command, ...words])).toEqual([
    ["state"],
    ["key", "BACK"],
  ]);
  const history = (await run(["history", "one"])) as {
    events: { step?: number; status: string; runId?: string; owner: string }[];
  };
  const attempts = history.events.filter((row) => row.step !== undefined).reverse();
  expect(attempts.map(({ step, status }) => [step, status])).toEqual([
    [1, "started"],
    [1, "ok"],
    [2, "started"],
    [2, "error"],
  ]);
  expect(new Set(attempts.map((row) => row.runId)).size).toBe(1);
  expect(attempts[0]!.runId).toBeString();
  expect(history.events.every((row) => row.owner === owner)).toBe(true);
});

test("a running routine blocks simultaneous inputs from the same owner", async () => {
  const steps = [["state"]];
  expect(
    await run(["routine-save", "inspect"], JSON.stringify({ steps, commands: steps })),
  ).toMatchObject({
    name: "inspect",
    steps,
  });
  expect(await run(["routine-list"])).toMatchObject({ routines: ["inspect"] });
  expect(await run(["routine-show", "inspect"])).toMatchObject({ name: "inspect", steps });
  await reserve();
  drive = async () => {
    await expect(run(["key", "one", "--why=interrupt", "--", "HOME"])).rejects.toThrow(
      "device_busy",
    );
    return { app: "demo.app" };
  };
  expect(await run(["routine-run", "one", "--why=inspect", "--", "inspect"])).toMatchObject({
    completed: 1,
    lastResult: { app: "demo.app" },
  });
  expect(actions).toHaveLength(1);
});

test("verify ownership again before delivering input and keep user text out of history", async () => {
  await reserve();
  let delivered = 0;
  drive = async (_action, beforeInput) => {
    await redis.del(prefix + "lease:one");
    await beforeInput();
    delivered++;
  };
  await expect(
    run(["set-text", "one", "--why=form", "--on", '{"id":"name"}', "--", "Private words 🌅"]),
  ).rejects.toThrow("not_leased");
  expect(delivered).toBe(0);
  expect(actions).toHaveLength(1);
  const history = JSON.stringify(await run(["history", "one"]));
  expect(history).toContain("not_leased");
  expect(history).toContain("targetId");
  expect(history).not.toContain("Private words");
});

test("direct find passes the selector and returns the raw match", async () => {
  await reserve();
  drive = async ({ selector }) => {
    if (selector?.text === "missing") throw new Error("not_found");
    if (selector?.text === "twice") throw new Error("ambiguous");
    return { text: selector?.text, id: "name" };
  };
  const find = (text: string) =>
    run(["find", "one", "--why=review", "--on", JSON.stringify({ text })]);
  expect(await find("Name")).toEqual({ text: "Name", id: "name" });
  await expect(find("missing")).rejects.toThrow("not_found");
  await expect(find("twice")).rejects.toThrow("ambiguous");
  expect(actions.map(({ selector }) => selector)).toEqual([
    { text: "Name" },
    { text: "missing" },
    { text: "twice" },
  ]);
});

test("Redis outage blocks input before Android is called", async () => {
  process.env.AGENT_PHONE_REDIS_URL = `unix://${join(folder, "missing.sock")}`;
  await expect(run(["key", "one", "--why=test", "--", "BACK"])).rejects.toThrow();
  expect(actions).toHaveLength(0);
});

test("an expired operation lock cannot send input or delete its successor's lock", async () => {
  await reserve();
  const key = prefix + "operation:one";
  let delivered = false;
  drive = async (_action, beforeInput) => {
    await redis.send("SET", [key, "successor", "EX", "60", "XX"]);
    await beforeInput();
    delivered = true;
  };
  await expect(run(["key", "one", "--why=review", "--", "BACK"])).rejects.toThrow();
  expect(delivered).toBe(false);
  expect(await redis.get(key)).toBe("successor");
});

test("CLI preserves a saved routine when a replacement contains an invalid step", async () => {
  const path = join(folder, "replacement.json");
  const cli = join(import.meta.dir, "../agent-phone");
  async function routine(...args: string[]) {
    const process = Bun.spawn([cli, "routine", ...args], { stdout: "pipe", stderr: "pipe" });
    const [status, stdout, stderr] = await Promise.all([
      process.exited,
      new Response(process.stdout).text(),
      new Response(process.stderr).text(),
    ]);
    return { status, result: JSON.parse(status === 0 ? stdout : stderr) };
  }
  const steps = [["set-text", "--id", "name", "--", "--Café 🌅"], ["state"]];
  await Bun.write(path, JSON.stringify(steps));
  expect(await routine("save", "editing", path)).toEqual({
    status: 0,
    result: { ok: true, name: "editing", steps },
  });
  await Bun.write(path, JSON.stringify([["state"], ["lease", "another-phone"]]));
  const failed = await routine("save", "editing", path);
  expect(failed.status).toBe(2);
  expect(failed.result.error).toContain("Step 2");
  expect(await routine("show", "editing")).toEqual({
    status: 0,
    result: { ok: true, name: "editing", steps },
  });
});
