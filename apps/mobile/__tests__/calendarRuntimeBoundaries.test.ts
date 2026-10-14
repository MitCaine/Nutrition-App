// Portable synthetic controls from the accepted task-10 audit. Node SQLite and native mocks; no device proof.
import * as Crypto from "expo-crypto";
import { createLocalCalendarRuntime } from "../src/runtime/local/localCalendarRuntime";
import { createLocalDailyLogsRuntime } from "../src/runtime/local/localDailyLogsRuntime";
import { markLocalDailyLogComplete } from "../src/runtime/local/localDailyLogCompleteState";
import { ensureLocalNutrientCatalog } from "../src/runtime/local/localNutrientsRuntime";
import { addCalendarDays } from "../src/features/logging/utils/dailyLogDisplay";
import { LocalSQLiteTestDatabase, seedLocalFood, seedLocalOwner } from "./localSQLiteTestSupport";

const OWNER = "00000000-0000-4000-8000-000000000001";
const FOOD = "00000000-0000-4000-8000-000000000010";
const SERVING = "00000000-0000-4000-8000-000000000011";
let serial = 100;
const uuid = () => `00000000-0000-4000-8000-${String(serial++).padStart(12, "0")}`;
let db: LocalSQLiteTestDatabase;
let instant: string;
const now = () => new Date(instant);
let revision: number;

beforeEach(async () => {
  (Crypto.randomUUID as jest.Mock).mockImplementation(uuid);
  db = new LocalSQLiteTestDatabase();
  await db.initialize();
  await seedLocalOwner(db, OWNER);
  await ensureLocalNutrientCatalog(db.asExpoDatabase());
  await seedLocalFood(db, { id: FOOD, ownerId: OWNER, name: "Synthetic boundary Food", servingId: SERVING, gramWeight: "100.000000" });
  await db.runAsync(`INSERT INTO food_nutrients
    (id, food_item_id, nutrient_id, amount, unit, basis, data_status, source, is_user_confirmed)
    VALUES (?, ?, 'protein', '10.000000', 'g', 'per_serving', 'known', 'manual', 1)`, [uuid(), FOOD]);
});
afterEach(() => db.close());

function adapters() {
  return {
    calendar: createLocalCalendarRuntime(db.asExpoDatabase(), OWNER, { now }),
    logs: createLocalDailyLogsRuntime(db.asExpoDatabase(), OWNER, { now }),
  };
}
const input = (date: string) => ({
  client_request_id: uuid(), calendar_revision: revision, food_item_id: FOOD,
  logged_date: date, amount_quantity: "1", amount_unit: "serving" as const,
  serving_definition_id: SERVING, source_food_updated_at: null,
  source_recipe_publication_revision_id: null, meal_type: "breakfast" as const, notes: "Synthetic",
});
const complete = (date: string, requestId = uuid()) => markLocalDailyLogComplete(db.asExpoDatabase(), OWNER,
  { logged_date: date, calendar_revision: revision, client_request_id: requestId }, now);

test.each([
  ["America/Los_Angeles", "2026-03-08T07:59:59.999Z", "2026-03-08T08:00:00.000Z", "2026-03-07", "2026-03-08"],
  ["America/Los_Angeles", "2026-03-08T09:59:59.999Z", "2026-03-08T10:00:00.000Z", "2026-03-08", "2026-03-08"],
  ["America/Los_Angeles", "2026-11-01T08:59:59.999Z", "2026-11-01T09:00:00.000Z", "2026-11-01", "2026-11-01"],
  ["Europe/Berlin", "2026-03-29T00:59:59.999Z", "2026-03-29T01:00:00.000Z", "2026-03-29", "2026-03-29"],
  ["Australia/Lord_Howe", "2026-04-04T14:59:59.999Z", "2026-04-04T15:00:00.000Z", "2026-04-05", "2026-04-05"],
  ["Pacific/Kiritimati", "2026-12-31T09:59:59.999Z", "2026-12-31T10:00:00.000Z", "2026-12-31", "2027-01-01"],
])("%s at %s: dates, summary, Complete and exact replay survive boundary", async (zone, before, after, dateBefore, dateAfter) => {
  instant = before;
  const { calendar, logs } = adapters();
  const state = await calendar.establishTimeZone(zone);
  revision = state.calendar_revision!;
  expect(state.today).toBe(dateBefore);
  const payload = input(dateBefore);
  const created = await logs.create(payload);
  const snapshots = await db.getAllAsync(`SELECT * FROM daily_log_nutrient_snapshots ORDER BY id`);
  await complete(dateBefore);
  instant = after;
  expect((await calendar.getState()).today).toBe(dateAfter);
  expect(await logs.create(payload)).toEqual(created);
  expect((await logs.list(dateBefore)).map(x => x.id)).toEqual([created.id]);
  expect(await logs.getDailySummary(dateBefore)).toMatchObject({ logged_date: dateBefore, is_complete: true,
    totals: [expect.objectContaining({ nutrientId: "protein", amountKnown: "10.000000" })] });
  expect(await db.getAllAsync(`SELECT * FROM daily_log_nutrient_snapshots ORDER BY id`)).toEqual(snapshots);
  await expect(logs.create(input(addCalendarDays(dateAfter, 1)))).rejects.toMatchObject({ code: "future_dated_mutation_blocked" });
  await logs.update(created.id, { client_request_id: uuid(), calendar_revision: revision, notes: "Metadata after boundary" });
  expect((await logs.getDailySummary(dateBefore)).is_complete).toBe(true);
});

test("reviewed backward timezone change preserves dates and Complete, fences fresh writes, allows explicit move and stable replay", async () => {
  instant = "2026-03-09T06:30:00.000Z";
  const { calendar, logs } = adapters();
  revision = (await calendar.establishTimeZone("UTC")).calendar_revision!;
  const payload = input("2026-03-09");
  const created = await logs.create(payload);
  const destination = await logs.create(input("2026-03-08"));
  const completeRequest = uuid();
  const completion = await complete("2026-03-09", completeRequest);
  await complete("2026-03-08");
  const snapshots = await db.getAllAsync(`SELECT * FROM daily_log_nutrient_snapshots ORDER BY id`);
  const oldRevision = revision;
  const preview = await calendar.previewTimeZoneChange("America/Los_Angeles");
  expect(preview.affected_entries.map(x => x.id)).toEqual([created.id]);
  const next = await calendar.confirmTimeZoneChange({ timeZone: preview.proposed_time_zone, calendarRevision: preview.calendar_revision, previewToken: preview.preview_token });
  revision = next.calendar_revision!;
  expect(next.today).toBe("2026-03-08");
  expect((await logs.listFuture("2026-03-09")).map(x => x.id)).toEqual([created.id]);
  expect(await logs.list("2026-03-09")).toEqual([]);
  expect((await logs.getDailySummary("2026-03-09")).is_complete).toBe(true);
  expect(await logs.create(payload)).toEqual(created);
  await expect(logs.create({ ...payload, client_request_id: uuid() })).rejects.toMatchObject({ code: "calendar_context_changed" });
  await expect(logs.create(input("2026-03-09"))).rejects.toMatchObject({ code: "future_dated_mutation_blocked" });
  await expect(complete("2026-03-09")).rejects.toMatchObject({ code: "future_dated_mutation_blocked" });
  expect(await markLocalDailyLogComplete(db.asExpoDatabase(), OWNER, { logged_date: "2026-03-09", client_request_id: completeRequest, calendar_revision: oldRevision }, now)).toEqual(completion);
  const move = { client_request_id: uuid(), calendar_revision: revision, logged_date: "2026-03-08" };
  const moved = await logs.update(created.id, move);
  expect(moved.created_at).toBe(created.created_at);
  expect(await db.getAllAsync(`SELECT * FROM daily_log_nutrient_snapshots ORDER BY id`)).toEqual(snapshots);
  expect(await logs.getDailySummary("2026-03-09")).toMatchObject({ is_complete: false, totals: [] });
  expect(await logs.getDailySummary("2026-03-08")).toMatchObject({ is_complete: false, totals: [expect.objectContaining({ amountKnown: "20.000000" })] });
  expect((await logs.list("2026-03-08")).map(x => x.id).sort()).toEqual([created.id, destination.id].sort());
  expect(await logs.update(created.id, move)).toEqual(moved);
  expect(await logs.create(payload)).toEqual(created);
  await expect(logs.create({ ...payload, logged_date: "2026-03-08" })).rejects.toMatchObject({ code: "log_idempotency_payload_conflict" });
  expect((await logs.list("2026-03-08"))).toHaveLength(2);
});

test("preview spanning midnight is stale; renewed forward change leaves date-owned evidence intact", async () => {
  instant = "2026-01-01T09:59:59.999Z";
  const { calendar, logs } = adapters();
  revision = (await calendar.establishTimeZone("America/Los_Angeles")).calendar_revision!;
  const created = await logs.create(input("2026-01-01"));
  await complete("2026-01-01");
  const stale = await calendar.previewTimeZoneChange("Pacific/Kiritimati");
  instant = "2026-01-01T10:00:00.000Z";
  await expect(calendar.confirmTimeZoneChange({ timeZone: stale.proposed_time_zone, calendarRevision: stale.calendar_revision, previewToken: stale.preview_token }))
    .rejects.toMatchObject({ code: "stale_calendar_preview" });
  const preview = await calendar.previewTimeZoneChange("Pacific/Kiritimati");
  const next = await calendar.confirmTimeZoneChange({ timeZone: preview.proposed_time_zone, calendarRevision: preview.calendar_revision, previewToken: preview.preview_token });
  expect(next.today).toBe("2026-01-02");
  expect((await logs.list("2026-01-01"))[0].id).toBe(created.id);
  expect((await logs.getDailySummary("2026-01-01")).is_complete).toBe(true);
  expect((await logs.getDailySummary("2026-01-02"))).toMatchObject({ is_complete: false, totals: [] });
});


test("owner UTC calendar accepts the date skipped by device Apia and preserves arithmetic and storage", async () => {
  instant = "2026-07-14T00:00:00.000Z";
  const { calendar, logs } = adapters();
  revision = (await calendar.establishTimeZone("UTC")).calendar_revision!;
  expect(addCalendarDays("2011-12-29", 1)).toBe("2011-12-30");
  const created = await logs.create(input("2011-12-30"));
  expect(created.logged_date).toBe("2011-12-30");
  await complete("2011-12-30");
  expect((await logs.list("2011-12-30"))[0].id).toBe(created.id);
  expect(await logs.getDailySummary("2011-12-30")).toMatchObject({ logged_date: "2011-12-30", is_complete: true,
    totals: [expect.objectContaining({ amountKnown: "10.000000" })] });
});
