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

final class PassthroughScanner {
    private static final Set<String> EXT = new HashSet<>(Arrays.asList(
            "jpg","jpeg","png","gif","webp","heic","heif","bmp","mpo",
            "mp4","m4v","3gp","webm","mov","avi","mkv"
    ));
    private static final int MAX_FILES = 5000;

    private PassthroughScanner() {}

    static void scanAsync(Context context, String dir) {
        final Context app = context.getApplicationContext();
        new Thread(() -> scan(app, dir), "gallery-passthrough-scan").start();
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
            try { children = current.listFiles(); } catch (Throwable t) { continue; }
            if (children == null) continue;

            for (File f : children) {
                if (media.size() >= MAX_FILES) break;
                try {
                    if (f.isDirectory()) {
                        queue.addLast(f);
                    } else {
                        String n = f.getName();
                        int dot = n.lastIndexOf('.');
                        if (dot >= 0 && EXT.contains(n.substring(dot + 1).toLowerCase(Locale.ROOT))) {
                            media.add(f.getAbsolutePath());
                        }
                    }
                } catch (Throwable ignored) {}
            }
        }

        for (int i = 0; i < media.size(); i += 256) {
            int end = Math.min(i + 256, media.size());
            MediaScannerConnection.scanFile(
                    context,
                    media.subList(i, end).toArray(new String[0]),
                    null,
                    null
            );
        }
    }
}
