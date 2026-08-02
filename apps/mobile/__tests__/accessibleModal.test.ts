import React, { createRef } from "react";
import { Modal, Text, View } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import { AccessibleModal } from "../src/shared/accessibility/AccessibleModal";

function modalElement(renderer: TestRenderer.ReactTestRenderer) {
  return renderer.root.findByType(Modal);
}

test("modal entry focus starts at native onShow once per opening", async () => {
  const initial = createRef<object>();
  const returning = createRef<object>();
  initial.current = {};
  returning.current = {};
  const entryCancel = jest.fn();
  const returnCancel = jest.fn();
  const reopenedCancel = jest.fn();
  const requestFocus = jest.fn()
    .mockReturnValueOnce(entryCancel)
    .mockReturnValueOnce(returnCancel)
    .mockReturnValueOnce(reopenedCancel);
  const onShow = jest.fn();
  let renderer!: TestRenderer.ReactTestRenderer;

  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessibleModal, {
      visible: true,
      title: "Select unit",
      busy: true,
      onRequestClose: jest.fn(),
      onShow,
      initialFocusRef: initial,
      returnFocusRef: returning,
      requestFocus,
    }, React.createElement(Text, null, "Modal body")));
  });
  expect(requestFocus).not.toHaveBeenCalled();

  await act(async () => modalElement(renderer).props.onShow());
  await act(async () => modalElement(renderer).props.onShow());
  expect(onShow).toHaveBeenCalledTimes(2);
  expect(requestFocus).toHaveBeenCalledTimes(1);
  expect(requestFocus).toHaveBeenCalledWith(initial.current, expect.objectContaining({ focusKeyboardTarget: false }));

  await act(async () => {
    renderer.update(React.createElement(AccessibleModal, {
      visible: true,
      title: "Select unit",
      busy: true,
      onRequestClose: jest.fn(),
      onShow,
      initialFocusRef: initial,
      returnFocusRef: returning,
      requestFocus,
    }, React.createElement(Text, null, "Updated body")));
  });
  expect(requestFocus).toHaveBeenCalledTimes(1);

  const isolated = renderer.root.findAllByType(View).find((node) => node.props.accessibilityViewIsModal === true);
  expect(isolated?.props.importantForAccessibility).toBe("yes");
  const heading = renderer.root.findAllByType(Text).find((node) => node.props.accessibilityRole === "header");
  expect(heading?.props.accessibilityState).toEqual({ busy: true, disabled: true });

  await act(async () => {
    renderer.update(React.createElement(AccessibleModal, {
      visible: false,
      title: "Select unit",
      onRequestClose: jest.fn(),
      onShow,
      initialFocusRef: initial,
      returnFocusRef: returning,
      requestFocus,
    }));
  });
  expect(entryCancel).toHaveBeenCalledTimes(1);
  expect(requestFocus).toHaveBeenLastCalledWith(returning.current, expect.objectContaining({ focusKeyboardTarget: false }));

  await act(async () => {
    renderer.update(React.createElement(AccessibleModal, {
      visible: true,
      title: "Select unit",
      onRequestClose: jest.fn(),
      onShow,
      initialFocusRef: initial,
      returnFocusRef: returning,
      requestFocus,
    }));
  });
  expect(returnCancel).toHaveBeenCalledTimes(1);
  expect(requestFocus).toHaveBeenCalledTimes(2);
  await act(async () => modalElement(renderer).props.onShow());
  expect(requestFocus).toHaveBeenCalledTimes(3);
  await act(async () => renderer.unmount());
});

test("closing before native onShow causes no stale entry or return focus", async () => {
  const requestFocus = jest.fn(() => jest.fn());
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessibleModal, {
      visible: true,
      title: "Confirm",
      onRequestClose: jest.fn(),
      requestFocus,
    }));
  });
  await act(async () => {
    renderer.update(React.createElement(AccessibleModal, {
      visible: false,
      title: "Confirm",
      onRequestClose: jest.fn(),
      requestFocus,
    }));
  });
  expect(requestFocus).not.toHaveBeenCalled();
  await act(async () => renderer.unmount());
});

test("normal close owns cancellable return focus and does not restore twice on unmount", async () => {
  const initial = createRef<object>();
  const returning = createRef<object>();
  initial.current = {};
  returning.current = {};
  const entryCancel = jest.fn();
  const returnCancel = jest.fn();
  const requestFocus = jest.fn()
    .mockReturnValueOnce(entryCancel)
    .mockReturnValueOnce(returnCancel);
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessibleModal, {
      visible: true,
      title: "Confirm",
      onRequestClose: jest.fn(),
      initialFocusRef: initial,
      returnFocusRef: returning,
      requestFocus,
    }));
  });
  await act(async () => modalElement(renderer).props.onShow());
  await act(async () => {
    renderer.update(React.createElement(AccessibleModal, {
      visible: false,
      title: "Confirm",
      onRequestClose: jest.fn(),
      initialFocusRef: initial,
      returnFocusRef: returning,
      requestFocus,
    }));
  });
  expect(requestFocus).toHaveBeenCalledTimes(2);
  await act(async () => renderer.unmount());
  expect(returnCancel).toHaveBeenCalledTimes(1);
  expect(requestFocus).toHaveBeenCalledTimes(2);
});

test("unmount while presented makes bounded return focus and releases its cancellation", async () => {
  const initial = createRef<object>();
  const fallback = createRef<object>();
  initial.current = {};
  fallback.current = {};
  const entryCancel = jest.fn();
  const unmountReturnCancel = jest.fn();
  const requestFocus = jest.fn()
    .mockReturnValueOnce(entryCancel)
    .mockReturnValueOnce(unmountReturnCancel);
  let renderer!: TestRenderer.ReactTestRenderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(AccessibleModal, {
      visible: true,
      title: "Confirm",
      onRequestClose: jest.fn(),
      initialFocusRef: initial,
      fallbackFocusRef: fallback,
      requestFocus,
    }));
  });
  await act(async () => modalElement(renderer).props.onShow());
  await act(async () => renderer.unmount());

  expect(entryCancel).toHaveBeenCalledTimes(1);
  expect(requestFocus).toHaveBeenLastCalledWith(fallback.current, expect.objectContaining({ delayMs: 0 }));
  expect(unmountReturnCancel).toHaveBeenCalledTimes(1);
});
