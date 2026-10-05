package io.github.zhanfg.galleryguard;

import android.content.ContentResolver;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;

import java.lang.reflect.Method;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicLong;

import io.github.libxposed.api.XposedInterface;

/**
 * Safe Photo Picker acceleration hotfix.
 *
 * Alpha1 made two mistakes:
 * 1) copied live provider cursors into MatrixCursor and cached them, which broke freshness/
 *    observer semantics and made newly captured media stale for up to several seconds;
 * 2) swallowed picker_media_init / ensure_providers_call bursts and synchronously walked
 *    result cursors + warmed many thumbnails, which introduced visible jank.
 *
 * Hotfix policy:
 * - NEVER replace or cache the current cursor;
 * - NEVER suppress native provider initialization/refresh calls;
 * - NEVER change the requested page size;
 * - only inspect lightweight cursor extras after the real query returns;
 * - best-effort prefetch one next page on a single background worker;
 * - prefetch is heavily throttled/deduplicated and its cursor is immediately closed.
 *
 * This preserves Android Photo Picker's native invalidation pipeline while still warming the
 * provider/SQLite page cache ahead of a scroll.
 */
final class PhotoPickerAccelerator {
    private static final String TAG = "GalleryPickerAccel";

    private static final long PREFETCH_MIN_INTERVAL_MS = 1_500L;
    private static final long PREFETCH_KEY_TTL_MS = 12_000L;
    private static final int MAX_RECENT_KEYS = 6;

    private static final ThreadLocal<Boolean> PREFETCHING =
            ThreadLocal.withInitial(() -> Boolean.FALSE);

    private static final ExecutorService IO = Executors.newSingleThreadExecutor(new ThreadFactory() {
        @Override public Thread newThread(Runnable r) {
            Thread t = new Thread(r, "picker-prefetch");
            t.setDaemon(true);
            return t;
        }
    });

    private static final AtomicLong LAST_PREFETCH_TS = new AtomicLong(0L);

    private static final Map<String, Long> RECENT_PREFETCH_KEYS =
            Collections.synchronizedMap(new LinkedHashMap<String, Long>(8, 0.75f, true) {
                @Override protected boolean removeEldestEntry(Map.Entry<String, Long> eldest) {
                    return size() > MAX_RECENT_KEYS;
                }
            });

    private static volatile SharedPreferences prefs;

    private PhotoPickerAccelerator() {}

    static boolean isPickerPackage(String pkg) {
        return "com.android.providers.media.module".equals(pkg)
                || "com.google.android.providers.media.module".equals(pkg)
                || "com.android.photopicker".equals(pkg)
                || "com.google.android.photopicker".equals(pkg);
    }

    static boolean shouldInstallInProcess(String pkg, String processName) {
        if ("com.android.photopicker".equals(pkg)
                || "com.google.android.photopicker".equals(pkg)) return true;
        return processName != null && processName.endsWith(":PhotoPicker");
    }

    static void install(MainHook owner, SharedPreferences remotePrefs) {
        prefs = remotePrefs;

        // Android 17 Photo Picker already has native paging/prefetch in its own app process.
        // Extra query prefetch competes for MediaProvider I/O and measurably hurts first paint.
        if (Build.VERSION.SDK_INT >= 37) {
            MainHook.info(TAG, "Android 17+ native fast path: no extra Picker hooks installed");
            return;
        }

        int ok = 0;
        int fail = 0;

        try {
            Method q = ContentResolver.class.getDeclaredMethod(
                    "query",
                    Uri.class,
                    String[].class,
                    Bundle.class,
                    CancellationSignal.class);
            owner.installExternalHook(q, new QueryHooker());
            ok++;
        } catch (Throwable t) {
            fail++;
            MainHook.info(TAG, "query hook unavailable: " + t);
        }

        try {
            Method call = ContentResolver.class.getDeclaredMethod(
                    "call",
                    String.class,
                    String.class,
                    String.class,
                    Bundle.class);
            owner.installExternalHook(call, new CallHooker());
            ok++;
        } catch (Throwable t) {
            fail++;
            MainHook.info(TAG, "call hook unavailable: " + t);
        }

        MainHook.info(TAG, "safe hotfix installed: " + ok + " OK / " + fail + " FAIL");
    }

    private static boolean enabled() {
        SharedPreferences p = prefs;
        if (p == null) return true;
        try {
            return p.getBoolean(GuardPrefs.KEY_PICKER_ACCEL, true);
        } catch (Throwable t) {
            return true;
        }
    }

    /**
     * Current query is always executed natively and returned untouched.
     * We only use cursor extras to discover the next page token.
     */
    private static final class QueryHooker implements XposedInterface.Hooker {
        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            if (!enabled() || Boolean.TRUE.equals(PREFETCHING.get())) {
                return chain.proceed();
            }

            Object uriObj = chain.getArg(0);
            Object projectionObj = chain.getArg(1);
            Object bundleObj = chain.getArg(2);

            Object result = chain.proceed();

            if (!(uriObj instanceof Uri)
                    || !(bundleObj instanceof Bundle)
                    || !(result instanceof Cursor)) {
                return result;
            }

            Uri uri = (Uri) uriObj;
            if (!isPickerQuery(uri)) return result;

            String[] projection = projectionObj instanceof String[]
                    ? ((String[]) projectionObj).clone()
                    : null;

            maybePrefetchNextPage(
                    (ContentResolver) chain.getThisObject(),
                    uri,
                    projection,
                    (Bundle) bundleObj,
                    (Cursor) result);

            return result;
        }
    }

    /**
     * Native provider init/refresh must always run.
     * We only drop our own prefetch bookkeeping when the picker tells the provider to refresh.
     */
    private static final class CallHooker implements XposedInterface.Hooker {
        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            String authority = safeString(chain.getArg(0));
            String method = safeString(chain.getArg(1));

            if ("media".equals(authority)
                    && ("picker_media_init".equals(method)
                    || "ensure_providers_call".equals(method))) {
                clearPrefetchState();
            }

            // Never swallow or replace the system call.
            return chain.proceed();
        }
    }

    private static void maybePrefetchNextPage(
            ContentResolver resolver,
            Uri uri,
            String[] projection,
            Bundle currentArgs,
            Cursor current) {

        if (resolver == null || !isPrefetchable(uri, currentArgs)) return;

        Bundle extras;
        try {
            extras = current.getExtras();
        } catch (Throwable t) {
            return;
        }
        if (extras == null) return;

        long nextDate = extras.getLong("next_page_date_taken", Long.MIN_VALUE);
        if (nextDate == Long.MIN_VALUE) return;

        long nextId = extras.getLong("next_page_picker_id", Long.MIN_VALUE);

        Bundle next = new Bundle(currentArgs);
        next.putLong("date_taken_millis", nextDate);
        next.putLong("picker_id", nextId);

        String key = prefetchKey(uri, next);

        long now = android.os.SystemClock.elapsedRealtime();
        long last = LAST_PREFETCH_TS.get();
        if (now - last < PREFETCH_MIN_INTERVAL_MS) return;

        synchronized (RECENT_PREFETCH_KEYS) {
            Long seen = RECENT_PREFETCH_KEYS.get(key);
            if (seen != null && now - seen < PREFETCH_KEY_TTL_MS) return;
            RECENT_PREFETCH_KEYS.put(key, now);
        }

        if (!LAST_PREFETCH_TS.compareAndSet(last, now)) return;

        IO.execute(() -> {
            Cursor c = null;
            try {
                PREFETCHING.set(Boolean.TRUE);
                c = resolver.query(uri, projection, next, null);

                // Intentionally do not touch rows/count. Executing the query is enough to warm
                // provider/SQLite state; close immediately to keep memory and Binder work tiny.
            } catch (Throwable ignored) {
                synchronized (RECENT_PREFETCH_KEYS) {
                    RECENT_PREFETCH_KEYS.remove(key);
                }
            } finally {
                if (c != null) {
                    try { c.close(); } catch (Throwable ignored) {}
                }
                PREFETCHING.remove();
            }
        });
    }

    private static boolean isPickerQuery(Uri uri) {
        if (uri == null) return false;
        String s = uri.toString();
        return s.startsWith("content://media/picker")
                || s.startsWith("content://com.android.providers.media.photopicker/")
                || s.contains("/picker_internal/");
    }

    private static boolean isPrefetchable(Uri uri, Bundle args) {
        if (uri == null || args == null || !args.containsKey("page_size")) return false;

        String s = uri.toString();
        if (s.contains("search")
                || s.contains("preview")
                || s.contains("pre_selection")
                || s.contains("album")) {
            return false;
        }

        return s.contains("/media") || s.endsWith("/media");
    }

    private static String prefetchKey(Uri uri, Bundle args) {
        return uri + "|date=" + args.getLong("date_taken_millis", Long.MIN_VALUE)
                + "|id=" + args.getLong("picker_id", Long.MIN_VALUE)
                + "|size=" + args.getInt("page_size", -1);
    }

    private static void clearPrefetchState() {
        synchronized (RECENT_PREFETCH_KEYS) {
            RECENT_PREFETCH_KEYS.clear();
        }
        LAST_PREFETCH_TS.set(0L);
    }

    private static String safeString(Object o) {
        return o instanceof String ? (String) o : null;
    }
}
