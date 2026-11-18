import { afterEach, expect, mock, spyOn, test } from "bun:test";
import { Android } from "../src/android";
import { UiAutomator } from "../src/uiautomator";

const screen = `<hierarchy>
  <node text="Café &amp; .." bounds="[2,4][12,16]" resource-id="demo:id/name"
        class="android.widget.EditText" focused="true" clickable="true" />
  <node text="Repeat" bounds="[20,20][40,40]" />
  <node text="Repeat" bounds="[40,20][60,40]" />
  <node text="Hidden" bounds="[0,0][0,0]" />
</hierarchy>`;
const phone = new Android("test");
const beforeInput = mock(async () => {});
function fakeRpc(reply: (method: string, params: unknown[]) => unknown) {
  return spyOn(UiAutomator.prototype, "call").mockImplementation(
    async <T>(method: string, params: unknown[] = []) => reply(method, params) as T,
  );
}

afterEach(() => {
  mock.restore();
  beforeInput.mockClear();
});

test("an exact label maps Android's emoji representation and XML entities to a unique control", async () => {
  fakeRpc(() => screen);
  const match = {
    text: "Café & ..",
    desc: "",
    id: "name",
    center: [7, 10],
    clickable: true,
    focused: true,
  };
  for (const selector of [{ text: "Café & 🌅" }, { id: "name" }, { id: "demo:id/name" }]) {
    expect(await phone.drive("find", [], selector, beforeInput)).toEqual(match);
  }
  for (const [label, message, count] of [
    ["Repeat", "ambiguous", 2],
    ["Hidden", "not_found", 0],
  ] as const) {
    await expect(phone.drive("tap", [], { text: label }, beforeInput)).rejects.toMatchObject({
      message,
      matches: count,
    });
  }
  expect(beforeInput).not.toHaveBeenCalled();
});

test("text input checks the live field bounds and sends Unicode exactly once", async () => {
  let moved = true;
  const rpc = fakeRpc((method) => {
    if (method === "dumpWindowHierarchy") return screen;
    if (method === "count") return 1;
    if (method === "objInfo")
      return { bounds: { left: moved ? 0 : 2, top: 4, right: 12, bottom: 16 } };
    if (method === "setText") throw new Error("unknown_delivery");
    throw new Error("Unexpected RPC: " + method);
  });
  const input = "--Café 🌅";
  await expect(phone.drive("set-text", [input], undefined, beforeInput)).rejects.toThrow(
    "target_moved",
  );
  expect(beforeInput).not.toHaveBeenCalled();
  moved = false;
  await expect(phone.drive("set-text", [input], { id: "name" }, beforeInput)).rejects.toThrow(
    "unknown_delivery",
  );
  expect(beforeInput).toHaveBeenCalledTimes(1);
  const attempts = rpc.mock.calls.filter(([method]) => method === "setText");
  expect(attempts).toEqual([
    ["setText", [expect.objectContaining({ resourceId: "demo:id/name", instance: 0 }), input]],
  ]);
});

test("wait succeeds when a matching control appears in a later hierarchy", async () => {
  let scans = 0;
  fakeRpc(() => (++scans === 1 ? "<hierarchy/>" : screen));
  expect(await phone.drive("wait", [], { id: "name" }, beforeInput)).toMatchObject({
    ms: expect.any(Number),
  });
  expect(scans).toBe(2);
  expect(beforeInput).not.toHaveBeenCalled();
});
