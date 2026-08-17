import React from "react";
import { Text } from "react-native";
import TestRenderer, {
  act,
} from "react-test-renderer";

import {
  LocalFirstStartRuntimeBootstrap,
} from "../src/transfer/e2_15/LocalFirstStartGate";
import type {
  LocalFirstStartCoordinator,
} from "../src/transfer/e2_15/localFirstStartCoordinator";
import type {
  OpenLocalRuntimeHandle,
} from "../src/runtime/local/localRuntimeFoundation";

function runtimeHandle(): OpenLocalRuntimeHandle {
  return {
    authority: {
      kind: "local",
      recoveryScope:
        "local:00000000-0000-4000-8000-000000000001",
    },
    calendar: {},
    nutrients: {},
    foods: {},
    recipes: {},
    dailyLogs: {},
    targets: {},
    ocr: {},
    usda: {},
    close: jest.fn(
      async () => undefined,
    ),
  } as unknown as OpenLocalRuntimeHandle;
}

async function flushEffects(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function textContent(
  node: TestRenderer.ReactTestInstance,
): string {
  return node.children
    .map((child) =>
      typeof child === "string"
        ? child
        : textContent(child),
    )
    .join("");
}

test(
  "pending restore activation completes before the local coordinator opens SQLite",
  async () => {
    const events: string[] = [];
    const handle = runtimeHandle();

    const coordinator = {
      state: "existing_data",
      continueExisting: jest.fn(
        async () => {
          events.push("continue");
          return handle;
        },
      ),
      close: jest.fn(
        async () => undefined,
      ),
    } as unknown as LocalFirstStartCoordinator;

    const dependencies = {
      activatePendingLocalRestore:
        jest.fn(async () => {
          events.push("restore");
        }),

      prepare: jest.fn(
        async () => {
          events.push("prepare");
          return coordinator;
        },
      ),

      pickCachedTransfer:
        jest.fn(async () => null),
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(async () => {
      renderer = TestRenderer.create(
        React.createElement(
          LocalFirstStartRuntimeBootstrap,
          {
            dependencies,
            children: () =>
              React.createElement(
                Text,
                null,
                "ready",
              ),
          },
        ),
      );
    });

    await flushEffects();

    expect(events).toEqual([
      "restore",
      "prepare",
      "continue",
    ]);

    expect(
      dependencies
        .activatePendingLocalRestore,
    ).toHaveBeenCalledTimes(1);

    expect(
      dependencies.prepare,
    ).toHaveBeenCalledTimes(1);

    await act(async () => {
      renderer.unmount();
    });
  },
);

test(
  "restore activation failure prevents any local database startup",
  async () => {
    const prepare = jest.fn();

    const dependencies = {
      activatePendingLocalRestore:
        jest.fn(async () => {
          throw new Error(
            "restore activation failed",
          );
        }),

      prepare,

      pickCachedTransfer:
        jest.fn(async () => null),
    };

    let renderer!:
      TestRenderer.ReactTestRenderer;

    await act(async () => {
      renderer = TestRenderer.create(
        React.createElement(
          LocalFirstStartRuntimeBootstrap,
          {
            dependencies,
            children: () =>
              React.createElement(
                Text,
                null,
                "ready",
              ),
          },
        ),
      );
    });

    await flushEffects();

    expect(
      dependencies
        .activatePendingLocalRestore,
    ).toHaveBeenCalledTimes(1);

    expect(prepare).not.toHaveBeenCalled();

    const renderedText = renderer.root
      .findAllByType(Text)
      .map(textContent)
      .join(" ");

    expect(renderedText).toContain(
      "restore activation failed",
    );

    await act(async () => {
      renderer.unmount();
    });
  },
);
