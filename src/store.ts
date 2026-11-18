import { RedisClient } from "bun";
import { createHash, randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import { hostname, homedir, userInfo } from "node:os";
import { join } from "node:path";

type Lease = { owner: string; task: string; since: number; until: number };
type Routine = { steps: string[][]; commands: string[][] };
type Device = { serial: string; state: string; model: string };
type Seen = { model: string; lastSeen: number };
type Details = Record<string, unknown>;
type Update<T> = { command?: [string, ...string[]]; result: T };

const ttl = 600;
const seconds = () => Date.now() / 1000;

export class Store {
  readonly user = userInfo().username;
  readonly owner: string;
  readonly prefix = `agent-phone:${hostname()}:`;
  private readonly url: string;
  private readonly db: RedisClient;
  private ready?: Promise<void>;

  constructor() {
    const label = (process.env.AGENT_PHONE_OWNER ?? "").trim();
    if ([...label].length > 80 || /[\u0000-\u001f]/.test(label)) throw new Error("invalid_owner");
    this.owner = label ? `${this.user}/${label}` : this.user;
    this.url = (process.env.AGENT_PHONE_REDIS_URL ?? "redis://127.0.0.1:6379/0").replace(
      /^unix:/,
      "redis+unix:",
    );
    this.db = this.client();
  }

  private client() {
    try {
      return new RedisClient(this.url, {
        autoReconnect: false,
        enableOfflineQueue: false,
        connectionTimeout: 3000,
      });
    } catch {
      throw new Error("redis_unavailable");
    }
  }

  close() {
    this.db.close();
  }

  private async connect(db: RedisClient) {
    try {
      await db.connect();
    } catch {
      throw new Error("redis_unavailable");
    }
  }

  private async send<T>(command: string, args: string[], db = this.db): Promise<T> {
    const timeout = setTimeout(() => db.close(), 5000);
    try {
      if (db === this.db) await (this.ready ??= this.connect(db));
      return await db.send(command, args);
    } catch {
      throw new Error("redis_unavailable");
    } finally {
      clearTimeout(timeout);
    }
  }

  // WATCH belongs to a connection. Isolate each transaction so concurrent callers cannot share its state.
  private async update<T>(key: string, decide: (value: string | null) => Update<T>): Promise<T> {
    const db = this.client();
    try {
      await this.connect(db);
      for (;;) {
        await this.send("WATCH", [key], db);
        const { command, result } = decide(await this.send<string | null>("GET", [key], db));
        if (!command) return result;
        const [name, ...args] = command;
        await this.send("MULTI", [], db);
        await this.send(name, [key, ...args], db);
        if ((await this.send("EXEC", [], db)) !== null) return result;
      }
    } finally {
      db.close();
    }
  }

  leaseKey(serial: string) {
    return this.prefix + "lease:" + serial;
  }

  async lease(serial: string): Promise<Lease | null> {
    const value = await this.send<string | null>("GET", [this.leaseKey(serial)]);
    return value === null ? null : JSON.parse(value);
  }

  private checkOwner(lease: Lease | null) {
    if (!lease) throw new Error("not_leased");
    if (lease.owner !== this.owner) throw new Error("leased_by_another_owner");
    return lease;
  }

  async requireOwner(serial: string) {
    return this.checkOwner(await this.lease(serial));
  }

  private writeLease(serial: string, task?: string) {
    return this.update(this.leaseKey(serial), (value) => {
      const current: Lease | null = value === null ? null : JSON.parse(value);
      if (current || task === undefined) this.checkOwner(current);
      const now = seconds();
      const lease = {
        owner: this.owner,
        task: task ?? current!.task,
        since: current?.since ?? now,
        until: now + ttl,
      };
      return {
        command: ["SET", JSON.stringify(lease), "EX", String(ttl)],
        result: { lease, renewed: current !== null },
      };
    });
  }

  reserve(serial: string, task: string) {
    return this.writeLease(serial, task);
  }

  renew(serial: string) {
    return this.writeLease(serial);
  }

  release(serial: string) {
    return this.update(this.leaseKey(serial), (value) => {
      if (value === null) return { result: {} };
      this.checkOwner(JSON.parse(value));
      return { command: ["DEL"], result: {} };
    });
  }

  async withLock<T>(serial: string, operation: (extend: () => Promise<void>) => Promise<T>) {
    const key = this.prefix + "operation:" + serial;
    const token = randomUUID();
    if (!(await this.send("SET", [key, token, "EX", String(ttl), "NX"])))
      throw new Error("device_busy");
    const extend = () =>
      this.update(key, (value) => {
        if (value !== token) throw new Error("operation_lock_lost");
        return { command: ["EXPIRE", String(ttl)], result: undefined };
      });
    try {
      return await operation(extend);
    } finally {
      await this.update(key, (value) => ({
        command: value === token ? ["DEL"] : undefined,
        result: undefined,
      }));
    }
  }

  async migrateFileLease(serial: string, locked = false): Promise<void> {
    const root =
      process.env.AGENT_PHONE_LOCAL_STATE ?? join(homedir(), ".agent-phone", "local-leases");
    const path = join(root, createHash("sha256").update(serial).digest("hex"));
    if (!locked) {
      if (!(await Bun.file(path).exists())) return;
      try {
        await this.withLock(serial, () => this.migrateFileLease(serial, true));
      } catch (error) {
        if (!(error instanceof Error && error.message === "device_busy")) throw error;
      }
      return;
    }
    let data: string;
    try {
      data = await readFile(path, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
    const old: { task: string; until: number } = JSON.parse(data);
    if (!Number.isFinite(old.until) || typeof old.task !== "string")
      throw new Error("invalid_legacy_lease");
    const remaining = Math.ceil(old.until - seconds());
    if (remaining > 0) {
      const lease = { ...old, owner: this.user, since: old.until - ttl };
      await this.send("SET", [
        this.leaseKey(serial),
        JSON.stringify(lease),
        "EX",
        String(remaining),
        "NX",
      ]);
    }
    await rm(path);
  }

  async inventory(devices: Device[]) {
    const key = this.prefix + "inventory";
    const now = seconds();
    const live = new Map(devices.map((device) => [device.serial, device.state]));
    if (devices.length) {
      const fields = devices.flatMap(({ serial, model }) => [
        serial,
        JSON.stringify({ model, lastSeen: now }),
      ]);
      await this.send("HSET", [key, ...fields]);
    }
    const seen = await this.send<Record<string, string>>("HGETALL", [key]);
    const serials = Object.keys(seen).sort();
    const leases = serials.length
      ? await this.send<(string | null)[]>(
          "MGET",
          serials.map((s) => this.leaseKey(s)),
        )
      : [];
    const phones = serials.map((serial, index) => {
      const info: Seen = JSON.parse(seen[serial]!);
      const state = live.get(serial) ?? "disconnected";
      const lease: Lease | null = leases[index] ? JSON.parse(leases[index]!) : null;
      return { serial, ...info, state, healthy: state === "device", lease };
    });
    const active = phones.filter((p) => p.healthy).length;
    const busy = phones.filter((p) => p.healthy && p.lease).length;
    return { phones, counts: { known: phones.length, active, busy, available: active - busy } };
  }

  async listRoutines() {
    const names = await this.send<string[]>("HKEYS", [this.prefix + "routines"]);
    return { routines: names.sort() };
  }

  async routine(name: string): Promise<Routine> {
    const value = await this.send<string | null>("HGET", [this.prefix + "routines", name]);
    if (value === null) throw new Error("routine_not_found");
    return JSON.parse(value);
  }

  async save(name: string, definition: Routine) {
    await this.send("HSET", [this.prefix + "routines", name, JSON.stringify(definition)]);
    return { name, steps: definition.steps };
  }

  private record(serial: string, event: Details) {
    return this.send("XADD", [
      this.prefix + "history:" + serial,
      "MAXLEN",
      "2000",
      "*",
      "event",
      JSON.stringify(event),
    ]);
  }

  async audit<T>(
    serial: string,
    action: string,
    why: string,
    operation: () => Promise<T>,
    details: Details = {},
  ) {
    const event = {
      actionId: randomUUID().replaceAll("-", ""),
      owner: this.owner,
      serial,
      action,
      why,
      ...details,
    };
    await this.record(serial, { ...event, status: "started" });
    let result: T;
    try {
      result = await operation();
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      // Driver diagnostics may contain the text supplied to a field.
      const reason =
        /^(ambiguous|not_found|not_reached|target_moved|device_not_ready|device_busy|operation_lock_lost|not_leased|leased_by_another_owner|redis_unavailable|invalid_package|invalid_key)$/.test(
          message,
        )
          ? message
          : "operation_failed";
      await this.record(serial, { ...event, status: "error", error: reason });
      throw error;
    }
    await this.record(serial, { ...event, status: "ok" });
    return result;
  }

  async history(serial: string) {
    const rows = await this.send<[string, [string, string]][]>("XREVRANGE", [
      this.prefix + "history:" + serial,
      "+",
      "-",
      "COUNT",
      "100",
    ]);
    const events = rows.map(([id, [, value]]) => ({
      id,
      at: Number(id.split("-")[0]) / 1000,
      ...JSON.parse(value),
    }));
    return { events };
  }
}
