package io.github.zhanfg.galleryguard;

import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Tiny in-memory index of directories that currently contain .nomedia.
 * It is populated during the existing watcher traversal, so there is no second filesystem scan.
 */
final class NomediaIndex {
    private static final Set<String> HIDDEN_DIRS = ConcurrentHashMap.newKeySet();
    private static final AtomicLong GENERATION = new AtomicLong(1L);

    private NomediaIndex() {}

    static void add(String dir) {
        String n = VisibilityPolicy.normalize(dir);
        if (n != null && HIDDEN_DIRS.add(n)) GENERATION.incrementAndGet();
    }

    static void remove(String dir) {
        String n = VisibilityPolicy.normalize(dir);
        if (n != null && HIDDEN_DIRS.remove(n)) GENERATION.incrementAndGet();
    }

    static long generation() {
        return GENERATION.get();
    }

    static Set<String> snapshot() {
        return new HashSet<>(HIDDEN_DIRS);
    }
}
