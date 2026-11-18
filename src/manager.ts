import { Android, listDevices } from "./android";
import { Store } from "./store";

interface Devices {
  listDevices(): Promise<{ serial: string; model: string; state: string }[]>;
  android(serial: string): Pick<Android, "drive" | "close">;
}

const local: Devices = { listDevices, android: (serial) => new Android(serial) };

// Saved routines use these same argument arrays. Text after "--" is always literal.
function actionOptions(options: string[]) {
  const split = options.indexOf("--");
  const flags = split < 0 ? options : options.slice(0, split);
  const words = split < 0 ? [] : options.slice(split + 1);
  let selector: { id?: string; text?: string } | undefined;
  if (flags[0] === "--on") selector = JSON.parse(flags[1]!);
  if (flags[0] === "--until") selector = JSON.parse(flags[1]!).see;
  return { words, selector };
}

async function runRoutine(
  store: Store,
  serial: string,
  name: string,
  why: string,
  extend: () => Promise<void>,
  drive: (command: string, flags: string[], details: Record<string, unknown>) => Promise<unknown>,
) {
  const routine = await store.routine(name);
  const runId = crypto.randomUUID().replaceAll("-", "");
  return await store.audit(
    serial,
    "routine-run",
    why,
    async () => {
      await store.requireOwner(serial);
      let completed = 0;
      let lastResult: unknown;
      for (const [action, ...flags] of routine.commands) {
        const step = completed + 1;
        try {
          await extend();
          await store.renew(serial);
          lastResult = await drive(action!, flags, { runId, routine: name, step });
          completed++;
        } catch (error) {
          throw Object.assign(new Error(error instanceof Error ? error.message : String(error)), {
            runId,
            failedStep: step,
            completed,
          });
        }
      }
      return { runId, routine: name, completed, lastResult };
    },
    { runId, routine: name },
  );
}

export async function execute(
  args: string[],
  input?: string,
  devices: Devices = local,
): Promise<unknown> {
  const [command, serial = "", reason = "", ...options] = args;
  const store = new Store();
  try {
    switch (command) {
      case "history":
        return await store.history(serial);
      case "routine-list":
        return await store.listRoutines();
      case "routine-show":
        return { name: serial, steps: (await store.routine(serial)).steps };
      case "routine-save":
        return await store.save(serial, JSON.parse(input!));
      case "phones": {
        const phones = await devices.listDevices();
        for (const phone of phones) await store.migrateFileLease(phone.serial);
        return await store.inventory(phones);
      }
    }

    const why = reason.slice(reason.indexOf("=") + 1);
    const checkReady = async () => {
      const phones = await devices.listDevices();
      if (!phones.some((p) => p.serial === serial && p.state === "device"))
        throw new Error("device_not_ready");
    };

    return await store.withLock(serial, async (extend) => {
      await store.migrateFileLease(serial, true);
      if (command === "release")
        return store.audit(serial, "release", "", () => store.release(serial));
      if (command === "lease") {
        return store.audit(serial, "lease", why, async () => {
          await checkReady();
          return store.reserve(serial, why);
        });
      }

      const android = devices.android(serial);
      const beforeInput = async () => {
        await extend();
        await store.requireOwner(serial);
      };
      const drive = (action: string, flags: string[], details: Record<string, unknown> = {}) => {
        const { selector, words } = actionOptions(flags);
        if (["open", "key", "swipe"].includes(action) || (action === "tap" && !selector))
          details.arguments = words;
        if (action !== "wait" && selector?.id) details.targetId = selector.id;
        return store.audit(
          serial,
          action === "ui" ? "snapshot" : action,
          why,
          async () => {
            await store.requireOwner(serial);
            await checkReady();
            return android.drive(action, words, selector, beforeInput);
          },
          details,
        );
      };

      try {
        if (command === "routine-run") {
          const name = actionOptions(options).words[0]!;
          return await runRoutine(store, serial, name, why, extend, drive);
        }
        const answer = await drive(command!, options);
        return ["ui", "find", "screenshot"].includes(command!)
          ? answer
          : { action: command, answer };
      } finally {
        await android.close();
      }
    });
  } finally {
    store.close();
  }
}
