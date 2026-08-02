import {
  createAccessibilityAnnouncementOwner,
  createAccessibilityAnnouncer,
} from "../src/shared/accessibility/announcements";

afterEach(() => jest.useRealTimers());

test("announcements suppress identical keyed rerenders but announce changed outcomes", () => {
  let now = 1000;
  const announceNative = jest.fn();
  const announce = createAccessibilityAnnouncer({
    announceNative,
    now: () => now,
    schedule: (callback, delayMs) => setTimeout(callback, delayMs),
    cancelScheduled: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  });

  announce("Food saved", { key: "food-save", priority: "polite" });
  announce("Food saved", { key: "food-save", priority: "polite" });
  announce("Food could not be saved", { key: "food-save", priority: "assertive" });

  expect(announceNative).toHaveBeenCalledTimes(2);
  expect(announceNative).toHaveBeenNthCalledWith(1, "Food saved", "polite");
  expect(announceNative).toHaveBeenNthCalledWith(2, "Food could not be saved", "assertive");

  now += 2000;
  announce("Food saved", { key: "food-save", dedupeMs: 1500 });
  expect(announceNative).toHaveBeenCalledTimes(3);
});

test("a pending delayed announcement can be cancelled as obsolete", () => {
  jest.useFakeTimers();
  const announceNative = jest.fn();
  const announce = createAccessibilityAnnouncer({
    announceNative,
    now: () => 1000,
    schedule: (callback, delayMs) => setTimeout(callback, delayMs),
    cancelScheduled: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  });

  const cancel = announce("Review required", { key: "review", delayMs: 50 });
  cancel();
  jest.advanceTimersByTime(50);

  expect(announceNative).not.toHaveBeenCalled();
});

test("announcement ownership retains only genuinely pending delayed work", () => {
  jest.useFakeTimers();
  const announceNative = jest.fn();
  const announce = createAccessibilityAnnouncer({
    announceNative,
    now: () => 1000,
    schedule: (callback, delayMs) => setTimeout(callback, delayMs),
    cancelScheduled: (timer) => clearTimeout(timer as ReturnType<typeof setTimeout>),
  });
  const owner = createAccessibilityAnnouncementOwner(announce);

  owner.announce("Immediate", { key: "immediate" });
  expect(owner.pendingCount()).toBe(0);

  owner.announce("Delayed", { key: "delayed", delayMs: 50 });
  expect(owner.pendingCount()).toBe(1);
  jest.advanceTimersByTime(50);
  expect(owner.pendingCount()).toBe(0);

  const cancel = owner.announce("Obsolete", { key: "obsolete", delayMs: 50 });
  expect(owner.pendingCount()).toBe(1);
  cancel();
  expect(owner.pendingCount()).toBe(0);
  owner.cancelAll();
  expect(announceNative.mock.calls.map(([message]) => message)).toEqual(["Immediate", "Delayed"]);
});

test("completed repeated announcements do not accumulate owners and dedupe keys are bounded", () => {
  const announceNative = jest.fn();
  const announce = createAccessibilityAnnouncer({
    announceNative,
    now: () => 1000,
    schedule: (callback) => { callback(); return 0; },
    cancelScheduled: jest.fn(),
  });
  const owner = createAccessibilityAnnouncementOwner(announce);
  for (let index = 0; index < 120; index += 1) {
    owner.announce(`Message ${index}`, { key: `key-${index}`, dedupeMs: 10_000 });
  }
  expect(owner.pendingCount()).toBe(0);
  owner.announce("Message 0", { key: "key-0", dedupeMs: 10_000 });
  expect(announceNative).toHaveBeenCalledTimes(121);
});
