import { scheduleBannerExpiration, SUCCESS_BANNER_DURATION_MS } from "../src/shared/components/TransientSuccessBanner";

afterEach(() => jest.useRealTimers());

test("success banner expires after approximately five seconds", () => {
  jest.useFakeTimers();
  const expired = jest.fn();
  scheduleBannerExpiration(expired);
  jest.advanceTimersByTime(SUCCESS_BANNER_DURATION_MS - 1);
  expect(expired).not.toHaveBeenCalled();
  jest.advanceTimersByTime(1);
  expect(expired).toHaveBeenCalledTimes(1);
});

test("replacing a banner can cancel the old expiration", () => {
  jest.useFakeTimers();
  const oldExpired = jest.fn();
  const cancel = scheduleBannerExpiration(oldExpired);
  cancel();
  jest.advanceTimersByTime(SUCCESS_BANNER_DURATION_MS);
  expect(oldExpired).not.toHaveBeenCalled();
});
