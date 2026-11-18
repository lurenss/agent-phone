import { mkdir, rename, rm, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const version = "0.4.1";
const digest = "87c8ac9505970d42aa5922baa90114808fda6f47f9e5fbd4caa0f621c2c8d30d";
const deviceJar = "/data/local/tmp/u2.jar";
const release = `https://github.com/openatx/android-uiautomator-server-jar/releases/download/${version}/u2.jar`;

// A device can be ready on USB while a caller's shell still points adb at a remote server.
function adbProcess(args: string[], timeout?: number) {
  const exe = Bun.which("adb") ?? join(homedir(), "Library/Android/sdk/platform-tools/adb");
  if (!existsSync(exe)) throw new Error("Install Android SDK Platform-Tools or add adb to PATH.");
  const env = { ...process.env };
  delete env.ADB_SERVER_SOCKET;
  delete env.ANDROID_ADB_SERVER_ADDRESS;
  delete env.ANDROID_ADB_SERVER_PORT;
  return Bun.spawn([exe, "-P", "5037", ...args], {
    env,
    stdin: "ignore",
    stdout: "pipe",
    stderr: "pipe",
    timeout,
  });
}

export async function adb(args: string[], timeout = 15_000): Promise<string> {
  const process = adbProcess(args, timeout);
  const [stdout, stderr, code] = await Promise.all([
    new Response(process.stdout).text(),
    new Response(process.stderr).text(),
    process.exited,
  ]);
  if (code !== 0) throw new Error(stderr.trim() || "ADB command failed");
  return stdout.trim();
}

async function cachedJar(): Promise<string> {
  const folder = join(homedir(), ".cache/agent-phone");
  const path = join(folder, `uiautomator-${version}.jar`);
  const hash = (bytes: Uint8Array) => new Bun.CryptoHasher("sha256").update(bytes).digest("hex");
  const file = Bun.file(path);
  if ((await file.exists()) && hash(await file.bytes()) === digest) return path;
  const reply = await fetch(release, { signal: AbortSignal.timeout(45_000) });
  if (!reply.ok) throw new Error(`Cannot download UIAutomator: HTTP ${reply.status}.`);
  const bytes = await reply.bytes();
  if (hash(bytes) !== digest) throw new Error("UIAutomator download checksum mismatch.");
  await mkdir(folder, { recursive: true });
  const part = path + "." + crypto.randomUUID();
  try {
    await writeFile(part, bytes, { flag: "wx" });
    await rename(part, path);
  } finally {
    await rm(part, { force: true });
  }
  return path;
}

export class UiAutomator {
  private endpoint = "";
  private process?: ReturnType<typeof adbProcess>;

  constructor(private readonly serial: string) {}

  private async alive(): Promise<boolean> {
    try {
      const response = await fetch(this.endpoint + "/ping", {
        signal: AbortSignal.timeout(500),
        keepalive: false,
        redirect: "error",
      });
      return response.ok && (await response.text()) === "pong";
    } catch {
      return false;
    }
  }

  private async start(): Promise<void> {
    const device = ["-s", this.serial];
    const port = await adb([...device, "forward", "tcp:0", "tcp:9008"]);
    if (!/^\d+$/.test(port)) throw new Error("ADB did not allocate a forward.");
    this.endpoint = "http://127.0.0.1:" + port;
    const ready = await this.alive();
    const installedDigest = async () => {
      // A missing jar is the expected first run. Leave a transport failure distinguishable.
      const result = await adb([
        ...device,
        "shell",
        `if test -f ${deviceJar}; then toybox sha256sum ${deviceJar}; fi`,
      ]);
      return result.split(/\s+/)[0];
    };
    if ((await installedDigest()) !== digest) {
      if (ready) throw new Error("Another UIAutomator version is running on this device.");
      const local = await cachedJar();
      await adb([...device, "push", local, deviceJar], 60_000);
      if ((await installedDigest()) !== digest)
        throw new Error("UIAutomator device checksum mismatch.");
    }
    if (ready) return;
    // Keep ADB's shell connection open. Closing it ends only the process this instance started.
    this.process = adbProcess([
      ...device,
      "shell",
      "-T",
      `CLASSPATH=${deviceJar} exec app_process / com.wetest.uia2.Main -p 9008`,
    ]);
    void new Response(this.process.stdout).arrayBuffer();
    void new Response(this.process.stderr).arrayBuffer();
    const deadline = Date.now() + 30_000;
    while (Date.now() < deadline && this.process.exitCode === null) {
      if (await this.alive()) return;
      await Bun.sleep(100);
    }
    throw new Error("Android UIAutomator did not start.");
  }

  async call<T>(method: string, params: unknown[] = []): Promise<T> {
    if (!this.endpoint) await this.start();
    // Escape non-ASCII UTF-16 units as the upstream client does. Never resend an input.
    const body = JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }).replace(
      /[^\x00-\x7f]/g,
      (unit) => "\\u" + unit.charCodeAt(0).toString(16).padStart(4, "0"),
    );
    const response = await fetch(this.endpoint + "/jsonrpc/0", {
      method: "POST",
      body,
      headers: { "content-type": "application/json", "accept-encoding": "identity" },
      keepalive: false,
      redirect: "error",
      signal: AbortSignal.timeout(12_000),
    });
    if (!response.ok) throw new Error(`Android refused ${method}: HTTP ${response.status}.`);
    const message = (await response.json()) as { error?: unknown; result?: T };
    if (message.error || !("result" in message)) throw new Error(`Android refused ${method}.`);
    return message.result as T;
  }

  async close(): Promise<void> {
    if (!this.endpoint) return;
    try {
      if (this.process) {
        this.process.kill();
        await this.process.exited;
        const deadline = Date.now() + 5_000;
        while (await this.alive()) {
          if (Date.now() >= deadline) throw new Error("Android UIAutomator did not stop.");
          await Bun.sleep(100);
        }
      }
    } finally {
      const port = new URL(this.endpoint).port;
      this.endpoint = "";
      this.process = undefined;
      await adb(["-s", this.serial, "forward", "--remove", "tcp:" + port]);
    }
  }
}
