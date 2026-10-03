package io.github.zhanfg.galleryguard;

import android.content.Context;
import android.media.MediaScannerConnection;

import java.io.File;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Manual-folder scanner only.
 *
 * Application passthrough no longer calls this automatically. Folder scans are serialized and
 * deduplicated so adding several folders cannot create a burst of recursive I/O threads.
 */
final class PassthroughScanner {
    private static final Set<String> EXT = new HashSet<>(Arrays.asList(
            "jpg","jpeg","png","gif","webp","heic","heif","bmp","mpo",
            "mp4","m4v","3gp","webm","mov","avi","mkv"
    ));

    private static final int MAX_FILES = 1500;

    private static final ExecutorService EXECUTOR =
            Executors.newSingleThreadExecutor(r -> {
                Thread t = new Thread(r, "gallery-manual-folder-scan");
                t.setDaemon(true);
                return t;
            });

    private static final Set<String> QUEUED = ConcurrentHashMap.newKeySet();

    private PassthroughScanner() {}

    static void scanAsync(Context context, String dir) {
        final Context app = context.getApplicationContext();
        final String normalized = VisibilityPolicy.normalize(dir);
        if (normalized == null || !QUEUED.add(normalized)) return;

        EXECUTOR.execute(() -> {
            try {
                scan(app, normalized);
            } finally {
                QUEUED.remove(normalized);
            }
        });
    }

    private static void scan(Context context, String dir) {
        File root = new File(dir);
        if (!root.isDirectory()) return;

        ArrayList<String> media = new ArrayList<>();
        ArrayDeque<File> queue = new ArrayDeque<>();
        queue.add(root);

        while (!queue.isEmpty() && media.size() < MAX_FILES) {
            File current = queue.removeFirst();
            File[] children;
            try {
                children = current.listFiles();
            } catch (Throwable t) {
                continue;
            }
            if (children == null) continue;

            for (File f : children) {
                if (media.size() >= MAX_FILES) break;
                try {
                    if (f.isDirectory()) {
                        queue.addLast(f);
                    } else {
                        String n = f.getName();
                        int dot = n.lastIndexOf('.');
                        if (dot >= 0
                                && EXT.contains(n.substring(dot + 1).toLowerCase(Locale.ROOT))) {
                            media.add(f.getAbsolutePath());
                        }
                    }
                } catch (Throwable ignored) {}
            }
        }

        // Smaller batches reduce Binder and MediaScanner bursts on large folders.
        final int BATCH = 128;
        for (int i = 0; i < media.size(); i += BATCH) {
            int end = Math.min(i + BATCH, media.size());
            MediaScannerConnection.scanFile(
                    context,
                    media.subList(i, end).toArray(new String[0]),
                    null,
                    null
            );
        }
    }
}
