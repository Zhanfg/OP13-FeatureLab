package io.github.zhanfg.galleryguard;

import android.app.Activity;
import android.view.View;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;

/**
 * One source of truth for Android 16 edge-to-edge page insets.
 * Keeps content clear of status/navigation bars and gives every page the same horizontal grid.
 */
final class EdgeToEdgeInsets {
    private EdgeToEdgeInsets() {}

    static void apply(Activity activity, View root,
                      int horizontalDp, int topDp, int bottomDp) {
        WindowCompat.setDecorFitsSystemWindows(activity.getWindow(), false);

        final float density = root.getResources().getDisplayMetrics().density;
        final int horizontal = Math.round(horizontalDp * density);
        final int top = Math.round(topDp * density);
        final int bottom = Math.round(bottomDp * density);

        ViewCompat.setOnApplyWindowInsetsListener(root, (view, windowInsets) -> {
            Insets bars = windowInsets.getInsets(
                    WindowInsetsCompat.Type.systemBars()
                            | WindowInsetsCompat.Type.displayCutout());
            Insets ime = windowInsets.getInsets(WindowInsetsCompat.Type.ime());

            view.setPadding(
                    horizontal + bars.left,
                    top + bars.top,
                    horizontal + bars.right,
                    bottom + Math.max(bars.bottom, ime.bottom)
            );
            return windowInsets;
        });

        ViewCompat.requestApplyInsets(root);
    }
}
