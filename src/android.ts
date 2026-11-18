import { resolve } from "node:path";
import { SaxesParser } from "saxes";
import { adb, UiAutomator } from "./uiautomator";

export type Selector = { text?: string; id?: string };
type Control = {
  text: string;
  desc: string;
  id: string;
  fullId: string;
  klass: string;
  bounds: number[];
  center: number[];
  clickable: boolean;
  focused: boolean;
};

export async function listDevices(): Promise<
  Array<{ serial: string; state: string; model: string }>
> {
  const output = await adb(["devices", "-l"]);
  const devices = [];
  for (const line of output.split("\n").slice(1)) {
    const match = /^(\S+)\s+(no permissions|\S+)/.exec(line.trim());
    if (match?.[1] && match[2]) {
      devices.push({
        serial: match[1],
        state: match[2],
        model: /\bmodel:(\S+)/.exec(line)?.[1] ?? "",
      });
    }
  }
  return devices;
}

function elements(xml: string, on?: Selector): Control[] {
  const controls: Control[] = [];
  // The Android dump replaces each surrogate half with a period.
  const label = on?.text?.trim().replace(/[\u{10000}-\u{10ffff}]/gu, "..");
  const parser = new SaxesParser();
  parser.on("opentag", ({ name, attributes }) => {
    if (name !== "node") return;
    const [x1, y1, x2, y2] = (attributes.bounds?.match(/-?\d+/g) ?? []).map(Number);
    if (
      x1 === undefined ||
      x2 === undefined ||
      y1 === undefined ||
      y2 === undefined ||
      x1 >= x2 ||
      y1 >= y2
    )
      return;
    const text = attributes.text ?? "";
    const fullId = attributes["resource-id"] ?? "";
    const id = fullId.split("/").at(-1) ?? "";
    if (label !== undefined && text.trim() !== label) return;
    if (on?.id !== undefined && on.id !== fullId && on.id !== id) return;
    controls.push({
      text,
      desc: attributes["content-desc"] ?? "",
      id,
      fullId,
      klass: attributes.class ?? "",
      bounds: [x1, y1, x2, y2],
      center: [Math.floor((x1 + x2) / 2), Math.floor((y1 + y2) / 2)],
      clickable: attributes.clickable === "true",
      focused: attributes.focused === "true",
    });
  });
  parser.write(xml).close();
  return controls;
}

function visible({ text, desc, id, center, clickable, focused }: Control) {
  return { text, desc, id, center, clickable, focused };
}

function one(controls: Control[]): Control {
  if (controls.length !== 1) {
    throw Object.assign(new Error(controls.length ? "ambiguous" : "not_found"), {
      matches: controls.length,
    });
  }
  return controls[0]!;
}

type Bounds = { left: number; top: number; right: number; bottom: number };

export class Android {
  private readonly helper: UiAutomator;

  constructor(private readonly serial: string) {
    this.helper = new UiAutomator(serial);
  }

  close(): Promise<void> {
    return this.helper.close();
  }

  private async controls(on?: Selector) {
    return elements(await this.helper.call<string>("dumpWindowHierarchy", [false, 50]), on);
  }

  private async textField(target: Control) {
    // UIAutomator setText takes its own selector. Identify the instance by its live bounds.
    const fields = {
      className: target.klass,
      ...(target.fullId ? { resourceId: target.fullId } : {}),
      mask: 0x10 | (target.fullId ? 0x200000 : 0),
      childOrSibling: [],
      childOrSiblingSelector: [],
    };
    const count = await this.helper.call<number>("count", [fields]);
    for (let instance = 0; instance < count; instance++) {
      const field = { ...fields, instance, mask: fields.mask | 0x01000000 };
      const info = await this.helper.call<{ bounds?: Bounds; visibleBounds?: Bounds }>("objInfo", [
        field,
      ]);
      if (
        [info.bounds, info.visibleBounds].some(
          (rect) =>
            rect &&
            rect.left === target.bounds[0] &&
            rect.top === target.bounds[1] &&
            rect.right === target.bounds[2] &&
            rect.bottom === target.bounds[3],
        )
      )
        return field;
    }
    throw new Error("target_moved");
  }

  async drive(
    command: string,
    words: string[],
    selector: Selector | undefined,
    beforeInput: () => Promise<void>,
  ): Promise<unknown> {
    const base = ["-s", this.serial, "shell"];
    if (
      command === "open" ||
      command === "key" ||
      command === "swipe" ||
      (command === "tap" && !selector)
    ) {
      let shell: string[];
      if (command === "open") {
        const pkg = words[0] ?? "";
        if (!/^[a-zA-Z]\w*(\.\w+)+$/.test(pkg)) throw new Error("invalid_package");
        shell = ["monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"];
      } else if (command === "key") {
        const key = words[0]?.toUpperCase() ?? "";
        if (!/^[A-Z0-9_]+$/.test(key)) throw new Error("invalid_key");
        shell = ["input", "keyevent", key];
      } else {
        if (words.length !== (command === "swipe" ? 4 : 2) || words.some((w) => !/^\d+$/.test(w))) {
          throw new Error("invalid_coordinates");
        }
        shell = ["input", command, ...words];
        if (command === "swipe") shell.push("300");
      }
      await beforeInput();
      const result = await adb([...base, ...shell]);
      if (command === "open" && !result.includes("Events injected: 1"))
        throw new Error("Android refused open");
      return null;
    }
    if (command === "state") {
      const [info, ime] = await Promise.all([
        this.helper.call<{ screenOn: boolean; currentPackageName: string }>("deviceInfo"),
        adb([...base, "dumpsys", "input_method"]),
      ]);
      const shown = /\b(?:mInputShown|inputShown)=(true|false)/.exec(ime)?.[1];
      return {
        screenOn: info.screenOn,
        app: info.currentPackageName,
        keyboard: shown ? shown === "true" : null,
      };
    }
    if (command === "screenshot") {
      const encoded = await this.helper.call<string>("takeScreenshot", [1, 90]);
      const jpeg = Buffer.from(encoded, "base64");
      if (jpeg[0] !== 0xff || jpeg[1] !== 0xd8 || jpeg.at(-2) !== 0xff || jpeg.at(-1) !== 0xd9) {
        throw new Error("Android returned an invalid screenshot.");
      }
      const path = resolve(words[0]!);
      const bytes = await Bun.write(path, jpeg);
      return { path, bytes };
    }
    if (command === "wait") {
      const start = performance.now();
      while (!(await this.controls(selector)).length) {
        const left = 10_000 - (performance.now() - start);
        if (left <= 0) throw new Error("not_reached");
        await Bun.sleep(Math.min(200, left));
      }
      return { ms: Math.round(performance.now() - start) };
    }
    const controls = await this.controls(selector);
    if (command === "ui") {
      return {
        elements: controls.filter((c) => selector || c.text || c.desc || c.clickable).map(visible),
      };
    }
    if (command === "find") return visible(one(controls));
    if (command === "tap") {
      const target = one(controls);
      await beforeInput();
      if ((await this.helper.call("click", target.center)) !== true)
        throw new Error("Android refused click");
      return visible(target);
    }
    if (command === "set-text") {
      const target = one(
        selector ? controls : controls.filter((c) => c.focused && c.klass.endsWith("EditText")),
      );
      const field = await this.textField(target);
      await beforeInput();
      if ((await this.helper.call("setText", [field, words[0]])) !== true)
        throw new Error("Android refused setText");
      return null;
    }
    throw new Error("unknown command");
  }
}
