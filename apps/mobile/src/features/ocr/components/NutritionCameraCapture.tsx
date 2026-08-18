import { CameraView, type CameraCapturedPicture } from "expo-camera";
import * as FileSystem from "expo-file-system";
import { useEffect, useMemo, useRef, useState } from "react";
import { StyleSheet, Text, View } from "react-native";

import { useAppTheme } from "../../../app/theme/AppTheme";
import { getPreferredBackCameraLensName } from "../../../native/camera/NutritionCamera";
import { AccessiblePressable } from "../../../shared/accessibility/AccessiblePressable";
import { useAccessibilityAnnouncement } from "../../../shared/accessibility/announcements";
import {
  focusAccessibilityElement,
  useAccessibilityScreenFocus,
} from "../../../shared/accessibility/focus";

export type NutritionCameraCaptureResult = Pick<
  CameraCapturedPicture,
  "uri" | "width" | "height"
>;

export function NutritionCameraCapture({
  onCancel,
  onCaptured,
}: {
  onCancel: () => void;
  onCaptured: (capture: NutritionCameraCaptureResult) => void;
}) {
  const theme = useAppTheme();
  const styles = useMemo(() => createStyles(theme), [theme]);
  const selectedLens = useMemo(
    () => getPreferredBackCameraLensName(),
    [],
  );
  const cameraRef = useRef<CameraView>(null);
  const headingRef = useRef<Text>(null);
  const errorRef = useRef<Text>(null);
  const mounted = useRef(true);
  const [ready, setReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const announce = useAccessibilityAnnouncement();

  useAccessibilityScreenFocus({
    active: true,
    routeKey: "nutrition-camera-capture",
    targetRef: headingRef,
  });

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!cameraError) return;

    const cancelAnnouncement = announce(cameraError, {
      key: "nutrition-camera-error",
      kind: "error",
      priority: "assertive",
    });
    const cancelFocus = focusAccessibilityElement(errorRef.current, {
      focusKeyboardTarget: false,
    });

    return () => {
      cancelAnnouncement();
      cancelFocus();
    };
  }, [announce, cameraError]);

  const capture = async () => {
    if (!ready || capturing) return;

    const camera = cameraRef.current;
    if (!camera) {
      setCameraError("The camera is not ready yet. Try again.");
      return;
    }

    setCapturing(true);
    setCameraError(null);

    try {
      const photo = await camera.takePictureAsync({ quality: 1 });
      if (!photo) {
        throw new Error("Camera did not return a photo.");
      }
      if (!mounted.current) {
        await FileSystem.deleteAsync(photo.uri, { idempotent: true }).catch(
          () => undefined,
        );
        return;
      }

      onCaptured({
        uri: photo.uri,
        width: photo.width,
        height: photo.height,
      });
    } catch {
      if (mounted.current) {
        setCapturing(false);
        setCameraError("The photo could not be captured. Try again.");
      }
    }
  };

  return (
    <View style={styles.screen}>
      <View style={styles.header}>
        <Text
          ref={headingRef}
          accessibilityRole="header"
          style={styles.title}
        >
          Photograph Nutrition Facts
        </Text>

        <AccessiblePressable
          accessibilityLabel="Cancel camera capture"
          accessibilityHint="Returns to the nutrition label scan options"
          disabled={capturing}
          onPress={onCancel}
        >
          <Text style={styles.cancelText}>Cancel</Text>
        </AccessiblePressable>
      </View>

      <Text style={styles.instructions}>
        Keep the complete Nutrition Facts panel visible and move close enough
        that it fills most of the view. The corner marks are a guide, not a
        required crop; tall, short, narrow, or curved labels may extend beyond
        them.
      </Text>

      <View
        accessibilityLabel="Nutrition Facts camera preview"
        accessibilityHint="Align the complete Nutrition Facts panel near the corner guides"
        style={styles.cameraStage}
      >
        <CameraView
          ref={cameraRef}
          active
          autofocus="off"
          facing="back"
          mode="picture"
          selectedLens={selectedLens}
          onCameraReady={() => {
            setReady(true);
            setCameraError(null);
          }}
          onMountError={() => {
            setReady(false);
            setCameraError(
              "The camera preview could not start. Cancel and try again.",
            );
          }}
          style={StyleSheet.absoluteFill}
        />

        <View
          accessible={false}
          pointerEvents="none"
          style={styles.guide}
        >
          <View style={[styles.corner, styles.topLeft]} />
          <View style={[styles.corner, styles.topRight]} />
          <View style={[styles.corner, styles.bottomLeft]} />
          <View style={[styles.corner, styles.bottomRight]} />
        </View>
      </View>

      <Text style={styles.guideLabel}>
        Nutrition Facts framing guide
      </Text>

      {cameraError ? (
        <Text
          ref={errorRef}
          accessibilityLiveRegion="none"
          accessibilityRole="alert"
          style={styles.error}
        >
          {cameraError}
        </Text>
      ) : null}

      <AccessiblePressable
        accessibilityLabel="Capture nutrition label photo"
        accessibilityHint="Takes a temporary photo for on-device nutrition label recognition"
        busy={capturing}
        disabled={!ready}
        onPress={() => {
          void capture();
        }}
        style={[
          styles.captureButton,
          (!ready || capturing) && styles.captureButtonDisabled,
        ]}
      >
        <Text style={styles.captureButtonText}>
          {capturing
            ? "Capturing…"
            : ready
              ? "Take photo"
              : "Preparing camera…"}
        </Text>
      </AccessiblePressable>
    </View>
  );
}

function createStyles(theme: ReturnType<typeof useAppTheme>) {
  return StyleSheet.create({
    bottomLeft: {
      borderBottomWidth: 4,
      borderLeftWidth: 4,
      bottom: 0,
      left: 0,
    },
    bottomRight: {
      borderBottomWidth: 4,
      borderRightWidth: 4,
      bottom: 0,
      right: 0,
    },
    cameraStage: {
      backgroundColor: "#000000",
      borderRadius: 14,
      flex: 1,
      minHeight: 360,
      overflow: "hidden",
      position: "relative",
    },
    cancelText: {
      color: theme.colors.accent,
      fontSize: 16,
      fontWeight: "700",
    },
    captureButton: {
      backgroundColor: theme.colors.primaryActionBackground,
      borderRadius: 8,
      minHeight: 52,
    },
    captureButtonDisabled: {
      opacity: 0.55,
    },
    captureButtonText: {
      color: theme.colors.primaryActionForeground,
      fontSize: 17,
      fontWeight: "800",
    },
    corner: {
      borderColor: "#FFFFFF",
      height: 46,
      position: "absolute",
      width: 46,
    },
    error: {
      color: theme.colors.errorText,
    },
    guide: {
      bottom: "10%",
      left: "8%",
      position: "absolute",
      right: "8%",
      top: "10%",
    },
    guideLabel: {
      color: theme.colors.secondaryText,
      fontSize: 13,
      fontWeight: "700",
      textAlign: "center",
    },
    header: {
      alignItems: "center",
      flexDirection: "row",
      flexWrap: "wrap",
      justifyContent: "space-between",
    },
    instructions: {
      color: theme.colors.secondaryText,
      fontSize: 15,
      lineHeight: 21,
    },
    screen: {
      backgroundColor: theme.colors.background,
      flex: 1,
      gap: 12,
      padding: 16,
    },
    title: {
      color: theme.colors.text,
      flexShrink: 1,
      fontSize: 24,
      fontWeight: "800",
    },
    topLeft: {
      borderLeftWidth: 4,
      borderTopWidth: 4,
      left: 0,
      top: 0,
    },
    topRight: {
      borderRightWidth: 4,
      borderTopWidth: 4,
      right: 0,
      top: 0,
    },
  });
}
