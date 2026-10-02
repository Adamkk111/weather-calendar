#!/usr/bin/env python3
from pathlib import Path

p = Path("upstream/extensions/shared/src/main/java/app/morphe/extension/youtube/patches/general/ChangeFormFactorPatch.java")
s = p.read_text(encoding="utf-8")

def must_replace(old, new, count=1):
    global s
    if old not in s:
        raise SystemExit("Expected upstream block not found:\n" + old[:300])
    s = s.replace(old, new, count)

must_replace(
"""import androidx.annotation.Nullable;
""",
"""import android.content.Context;
import android.content.res.Configuration;
import android.os.Build;
import android.view.Display;
import android.view.WindowManager;

import androidx.annotation.Nullable;
"""
)

must_replace(
"""import app.morphe.extension.shared.utils.PackageUtils;
""",
"""import app.morphe.extension.shared.utils.PackageUtils;
import app.morphe.extension.shared.utils.Utils;
"""
)

must_replace(
"""    private static final int smallestScreenWidthDp = PackageUtils.getSmallestScreenWidthDp();
    private static int clientFormFactorOrdinal = -1;

    private static int getClientFormFactorOrdinal() {
        if (clientFormFactorOrdinal == -1) {
            if (IS_WATCH) {
                clientFormFactorOrdinal = 4; // WEARABLE_FORM_FACTOR
            } else if (IS_AUTOMOTIVE) {
                clientFormFactorOrdinal = 3; // AUTOMOTIVE_FORM_FACTOR
            } else {
                if (smallestScreenWidthDp >= 600) {
                    clientFormFactorOrdinal = 2; // LARGE_FORM_FACTOR
                } else if (smallestScreenWidthDp > 0) {
                    clientFormFactorOrdinal = 1; // SMALL_FORM_FACTOR
                } else {
                    clientFormFactorOrdinal = 0; // UNKNOWN_FORM_FACTOR
                }
            }
        }

        return clientFormFactorOrdinal;
    }
""",
"""    // Fold8 Ultra cover and inner displays are cleanly separated by physical short-side pixels.
    private static final int FOLD8_UNFOLDED_SHORT_SIDE_PX = 1600;

    private static boolean isTargetFold8Ultra() {
        final String model = Build.MODEL;
        return model != null && model.startsWith("SM-F976");
    }

    private static boolean isLandscape() {
        try {
            return Utils.getResources().getConfiguration().orientation
                    == Configuration.ORIENTATION_LANDSCAPE;
        } catch (Throwable t) {
            Logger.printDebug(() -> "Fold8 auto layout: failed to read orientation", t);
            return false;
        }
    }

    private static boolean isUnfolded() {
        if (!isTargetFold8Ultra()) return false;

        try {
            Context context = Utils.getContext();
            if (context == null) return false;

            WindowManager windowManager =
                    (WindowManager) context.getSystemService(Context.WINDOW_SERVICE);
            if (windowManager != null) {
                Display display = windowManager.getDefaultDisplay();
                Display.Mode mode = display.getMode();
                int shortSidePx = Math.min(mode.getPhysicalWidth(), mode.getPhysicalHeight());
                return shortSidePx >= FOLD8_UNFOLDED_SHORT_SIDE_PX;
            }

            int widthPx = context.getResources().getDisplayMetrics().widthPixels;
            int heightPx = context.getResources().getDisplayMetrics().heightPixels;
            return Math.min(widthPx, heightPx) >= FOLD8_UNFOLDED_SHORT_SIDE_PX;
        } catch (Throwable t) {
            Logger.printDebug(() -> "Fold8 auto layout: failed to detect fold state", t);
            return false;
        }
    }

    private static boolean fold8AutoLayoutActive() {
        return FORM_FACTOR == FormFactor.DEFAULT && isUnfolded();
    }

    private static int getClientFormFactorOrdinal() {
        if (IS_WATCH) return 4; // WEARABLE_FORM_FACTOR
        if (IS_AUTOMOTIVE) return 3; // AUTOMOTIVE_FORM_FACTOR

        // Do not cache: fold/unfold can change configuration while the app stays alive.
        int currentSmallestScreenWidthDp = PackageUtils.getSmallestScreenWidthDp();
        if (currentSmallestScreenWidthDp >= 600) return 2; // LARGE_FORM_FACTOR
        if (currentSmallestScreenWidthDp > 0) return 1; // SMALL_FORM_FACTOR
        return 0; // UNKNOWN_FORM_FACTOR
    }
"""
)

must_replace(
"""    public static int getFormFactor() {
        int original = getClientFormFactorOrdinal();

        return FORM_FACTOR_TYPE == null || USING_AUTOMOTIVE_TYPE
                // When 'USING_AUTOMOTIVE_TYPE' is true, the 'Shorts' button in the navigation bar is replaced with the 'Explore' button.
                // To prevent this, the original clientFormFactorOrdinal is used when 'USING_AUTOMOTIVE_TYPE' is true.
                ? original
                : FORM_FACTOR_TYPE;
    }
""",
"""    public static int getFormFactor() {
        int original = getClientFormFactorOrdinal();

        if (fold8AutoLayoutActive()) {
            return isLandscape()
                    ? Objects.requireNonNull(FormFactor.LARGE.formFactorType)
                    : Objects.requireNonNull(FormFactor.SMALL.formFactorType);
        }

        return FORM_FACTOR_TYPE == null || USING_AUTOMOTIVE_TYPE
                ? original
                : FORM_FACTOR_TYPE;
    }
"""
)

must_replace(
"""    public static int getFormFactor(int original) {
        if (TABLET_LAYOUT_IN_PLAYER) {
""",
"""    public static int getFormFactor(int original) {
        // Fold8 dynamic rule takes priority over the generic tablet-in-player option.
        if (fold8AutoLayoutActive()) {
            return isLandscape()
                    ? Objects.requireNonNull(FormFactor.LARGE.formFactorType)
                    : Objects.requireNonNull(FormFactor.SMALL.formFactorType);
        }

        if (TABLET_LAYOUT_IN_PLAYER) {
"""
)

must_replace(
"""    public static int getWidthDp(int original) {
        if (FORM_FACTOR_TYPE == null) return original;
        Integer widthDp = FORM_FACTOR.widthDp;
        if (widthDp == null) {
            return original;
        }
        if (smallestScreenWidthDp == 0) {
            return original;
        }
        return FORM_FACTOR.setMinimumDp()
                ? Math.min(smallestScreenWidthDp, widthDp)
                : Math.max(smallestScreenWidthDp, widthDp);
    }

    public static boolean phoneLayoutEnabled() {
        return Objects.equals(FORM_FACTOR.formFactorType, 1);
    }

    public static boolean tabletLayoutEnabled() {
        return Objects.equals(FORM_FACTOR.formFactorType, 2);
    }
""",
"""    public static int getWidthDp(int original) {
        if (fold8AutoLayoutActive()) {
            return isLandscape()
                    ? Math.max(original, 600)
                    : Math.min(original, 480);
        }

        if (FORM_FACTOR_TYPE == null) return original;
        Integer widthDp = FORM_FACTOR.widthDp;
        if (widthDp == null) {
            return original;
        }

        int currentSmallestScreenWidthDp = PackageUtils.getSmallestScreenWidthDp();
        if (currentSmallestScreenWidthDp == 0) {
            return original;
        }
        return FORM_FACTOR.setMinimumDp()
                ? Math.min(currentSmallestScreenWidthDp, widthDp)
                : Math.max(currentSmallestScreenWidthDp, widthDp);
    }

    public static boolean phoneLayoutEnabled() {
        if (fold8AutoLayoutActive()) {
            return !isLandscape();
        }
        return Objects.equals(FORM_FACTOR.formFactorType, 1);
    }

    public static boolean tabletLayoutEnabled() {
        if (fold8AutoLayoutActive()) {
            return isLandscape();
        }
        return Objects.equals(FORM_FACTOR.formFactorType, 2);
    }
"""
)

# Mark derivative modification while preserving upstream notices.
s = s.replace(
    "package app.morphe.extension.youtube.patches.general;",
    "/* Modified for Galaxy Fold8 Ultra (SM-F976*) fold-aware form-factor switching. */\n\npackage app.morphe.extension.youtube.patches.general;",
    1,
)

p.write_text(s, encoding="utf-8")
print("Applied Fold8 Ultra auto-layout modification to", p)
