package io.github.zhanfg.galleryguard;

import android.content.SharedPreferences;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Visibility policy:
 * 1) explicit folder passthrough;
 * 2) selected-app passthrough (generic Android/media + known compatibility roots);
 * 3) trusted system media roots;
 * 4) everything else hidden while strict isolation is enabled.
 *
 * Explicit passthrough intentionally wins over .nomedia: choosing an app/folder means
 * the user is explicitly asking Gallery/Picker to surface that media.
 */
public final class VisibilityPolicy {
    private static final String STORAGE = "/storage/emulated/0";
    private static final String[] TRUSTED_PREFIXES = {
            STORAGE + "/DCIM/Camera",
            STORAGE + "/DCIM/Screenshots",
            STORAGE + "/Pictures/Screenshots",
            STORAGE + "/Pictures/ColorOS",
            STORAGE + "/Pictures/Edited"
    };

    private static final ConcurrentHashMap<String, Boolean> DIR_CACHE = new ConcurrentHashMap<>();
    private static final AtomicLong GENERATION = new AtomicLong(1);

    private static volatile boolean strictIsolation = true;
    private static volatile Set<String> passthroughDirs = Collections.emptySet();
    private static volatile Set<String> passthroughApps =
            Collections.unmodifiableSet(AppMediaRegistry.defaultCommunicationPackages());
    private static volatile Set<String> appPassthroughRoots =
            Collections.unmodifiableSet(
                    AppMediaRegistry.resolveRoots(AppMediaRegistry.defaultCommunicationPackages()));

    private static volatile SharedPreferences prefs;
    private static volatile Runnable onChanged;

    private static final SharedPreferences.OnSharedPreferenceChangeListener LISTENER = (p, key) -> {
        if (GuardPrefs.KEY_STRICT_ISOLATION.equals(key)
                || GuardPrefs.KEY_PASSTHROUGH_DIRS.equals(key)
                || GuardPrefs.KEY_PASSTHROUGH_APPS.equals(key)
                || GuardPrefs.KEY_POLICY_GENERATION.equals(key)) {
            reload(p);
            Runnable r = onChanged;
            if (r != null) r.run();
        }
    };

    private VisibilityPolicy() {}

    public static synchronized void bind(SharedPreferences p, Runnable changed) {
        if (prefs != null) {
            try {
                prefs.unregisterOnSharedPreferenceChangeListener(LISTENER);
            } catch (Throwable ignored) {}
        }

        prefs = p;
        onChanged = changed;

        if (p != null) {
            reload(p);
            try {
                p.registerOnSharedPreferenceChangeListener(LISTENER);
            } catch (Throwable ignored) {}
        } else {
            strictIsolation = true;
            passthroughDirs = Collections.emptySet();
            passthroughApps = Collections.unmodifiableSet(
                    AppMediaRegistry.defaultCommunicationPackages());
            appPassthroughRoots = Collections.unmodifiableSet(
                    AppMediaRegistry.resolveRoots(passthroughApps));
            invalidate();
        }
    }

    private static void reload(SharedPreferences p) {
        strictIsolation = p.getBoolean(GuardPrefs.KEY_STRICT_ISOLATION, true);

        HashSet<String> dirs = new HashSet<>();
        try {
            Set<String> raw = p.getStringSet(
                    GuardPrefs.KEY_PASSTHROUGH_DIRS, Collections.emptySet());
            if (raw != null) {
                for (String v : raw) {
                    String n = normalize(v);
                    if (n != null) dirs.add(n);
                }
            }
        } catch (Throwable ignored) {}
        passthroughDirs = Collections.unmodifiableSet(dirs);

        Set<String> appSource;
        try {
            if (p.contains(GuardPrefs.KEY_PASSTHROUGH_APPS)) {
                Set<String> saved = p.getStringSet(
                        GuardPrefs.KEY_PASSTHROUGH_APPS, Collections.emptySet());
                appSource = saved == null ? Collections.emptySet() : saved;
            } else {
                // First-run default: communication apps are allowed automatically.
                appSource = AppMediaRegistry.defaultCommunicationPackages();
            }
        } catch (Throwable t) {
            appSource = AppMediaRegistry.defaultCommunicationPackages();
        }

        HashSet<String> apps = new HashSet<>();
        for (String pkg : appSource) {
            if (pkg != null && !pkg.trim().isEmpty()) apps.add(pkg.trim());
        }
        passthroughApps = Collections.unmodifiableSet(apps);

        HashSet<String> roots = new HashSet<>();
        for (String root : AppMediaRegistry.resolveRoots(apps)) {
            String n = normalize(root);
            if (n != null) roots.add(n);
        }
        appPassthroughRoots = Collections.unmodifiableSet(roots);

        invalidate();
    }

    public static void invalidate() {
        GENERATION.incrementAndGet();
        DIR_CACHE.clear();
    }

    public static long generation() {
        return GENERATION.get();
    }

    public static boolean shouldHide(String filePath) {
        String normalized = normalize(filePath);
        if (normalized == null) return false;

        File f = new File(normalized);
        String dir = normalize(f.getParent());
        if (dir == null) return false;

        Boolean cached = DIR_CACHE.get(dir);
        if (cached != null) return cached;

        boolean hidden = computeHidden(dir);
        DIR_CACHE.put(dir, hidden);
        return hidden;
    }

    private static boolean computeHidden(String dir) {
        if (matchesAnyPrefix(dir, passthroughDirs)) return false;
        if (matchesAnyPrefix(dir, appPassthroughRoots)) return false;

        boolean trusted = matchesAnyPrefix(dir, TRUSTED_PREFIXES);
        if (!trusted && strictIsolation) return true;

        File cursor = new File(dir);
        while (cursor != null) {
            String p = normalize(cursor.getAbsolutePath());
            if (p == null) break;
            if (new File(cursor, ".nomedia").isFile()) return true;
            if (STORAGE.equals(p)
                    || "/storage/emulated".equals(p)
                    || "/storage".equals(p)
                    || "/".equals(p)) {
                break;
            }
            cursor = cursor.getParentFile();
        }
        return false;
    }

    private static boolean matchesAnyPrefix(String path, Set<String> prefixes) {
        for (String prefix : prefixes) {
            if (isWithin(path, prefix)) return true;
        }
        return false;
    }

    private static boolean matchesAnyPrefix(String path, String[] prefixes) {
        for (String prefix : prefixes) {
            if (isWithin(path, prefix)) return true;
        }
        return false;
    }

    private static boolean isWithin(String path, String prefix) {
        String p = normalize(prefix);
        if (p == null) return false;
        return path.equals(p) || path.startsWith(p + "/");
    }

    static String normalize(String path) {
        if (path == null) return null;
        String p = path.trim().replace('\\', '/');
        if (p.isEmpty()) return null;
        while (p.contains("//")) p = p.replace("//", "/");
        if (p.length() > 1 && p.endsWith("/")) {
            p = p.substring(0, p.length() - 1);
        }
        return p;
    }

    public static Set<String> passthroughSnapshot() {
        return new HashSet<>(passthroughDirs);
    }

    public static Set<String> passthroughAppsSnapshot() {
        return new HashSet<>(passthroughApps);
    }

    public static ArrayList<String> trustedSnapshot() {
        ArrayList<String> out = new ArrayList<>();
        Collections.addAll(out, TRUSTED_PREFIXES);
        return out;
    }
}
