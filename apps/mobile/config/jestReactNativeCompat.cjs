/*
 * React Native 0.81 exports Pressable through React.memo.
 *
 * Existing react-test-renderer tests intentionally locate interactive controls
 * by the public React Native Pressable component type. Unwrap only that export
 * in Jest so those semantic test selectors remain stable across the RN upgrade.
 *
 * This affects the test environment only; production React Native behavior is
 * unchanged.
 */
jest.mock("react-native", () => {
  const actual = jest.requireActual("react-native");
  const pressable = actual.Pressable;

  const descriptors = Object.getOwnPropertyDescriptors(actual);
  delete descriptors.Pressable;

  const mocked = Object.defineProperties({}, descriptors);

  Object.defineProperty(mocked, "Pressable", {
    configurable: true,
    enumerable: true,
    value: pressable?.type ?? pressable,
  });

  return mocked;
});
