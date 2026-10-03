package io.github.zhanfg.galleryguard;

import android.content.ContentResolver;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.CancellationSignal;
import android.util.Size;

import java.lang.reflect.Method;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.atomic.AtomicLong;

import io.github.libxposed.api.XposedInterface;

/**
 * Lightweight accelerator for Android 16 Photo Picker.
 *
 * Design goals:
 * - never hook the MediaProvider database process itself;
 * - operate only in the :PhotoPicker/UI process;
 * - enlarge small paging requests moderately;
 * - prefetch exactly one next page and keep a tiny short-lived cursor snapshot cache;
 * - warm only local thumbnails (never trigger cloud-network downloads);
 * - coalesce duplicate picker refresh calls fired in the same short burst.
 */
final class PhotoPickerAccelerator {
    private static final String TAG = "GalleryPickerAccel";

    private static final int MIN_PAGE_SIZE = 64;
    private static final int MAX_PAGE_SIZE = 96;
    private static final int MAX_SNAPSHOT_ROWS = 128;
    private static final int MAX_CACHE_ENTRIES = 8;
    private static final long CACHE_TTL_MS = 5_000L;
    private static final long REFRESH_DEBOUNCE_MS = 600L;
    private static final int THUMB_WARM_COUNT = 18;

    private static final ThreadLocal<Boolean> PREFETCHING =
            ThreadLocal.withInitial(() -> Boolean.FALSE);

    private static final ExecutorService IO = Executors.newFixedThreadPool(2, new ThreadFactory() {
        private int index;
        @Override public synchronized Thread newThread(Runnable r) {
            Thread t = new Thread(r, "picker-accel-" + (++index));
            t.setDaemon(true);
            return t;
        }
    });

    private static final Map<String, CacheEntry> CACHE =
            Collections.synchronizedMap(new LinkedHashMap<String, CacheEntry>(16, 0.75f, true) {
                @Override protected boolean removeEldestEntry(Map.Entry<String, CacheEntry> eldest) {
                    return size() > MAX_CACHE_ENTRIES;
                }
            });

    private static final AtomicLong LAST_REFRESH_TS = new AtomicLong(0L);
    private static volatile SharedPreferences prefs;

    private PhotoPickerAccelerator() {}

    static boolean isPickerPackage(String pkg) {
        return "com.android.providers.media.module".equals(pkg)
                || "com.google.android.providers.media.module".equals(pkg)
                || "com.google.android.photopicker".equals(pkg);
    }

    static boolean shouldInstallInProcess(String pkg, String processName) {
        if ("com.google.android.photopicker".equals(pkg)) return true;
        return processName != null && processName.endsWith(":PhotoPicker");
    }

    static void install(MainHook owner, SharedPreferences remotePrefs) {
        prefs = remotePrefs;

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

        MainHook.info(TAG, "installed: " + ok + " OK / " + fail + " FAIL");
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

    private static final class QueryHooker implements XposedInterface.Hooker {
        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            if (!enabled() || Boolean.TRUE.equals(PREFETCHING.get())) {
                return chain.proceed();
            }

            Object uriObj = chain.getArg(0);
            Object bundleObj = chain.getArg(2);
            if (!(uriObj instanceof Uri) || !(bundleObj instanceof Bundle)) {
                return chain.proceed();
            }

            Uri uri = (Uri) uriObj;
            if (!isPickerQuery(uri)) return chain.proceed();

            Bundle tuned = tuneQueryArgs((Bundle) bundleObj);
            String key = keyFor(uri, tuned);

            CursorSnapshot cached = getFreshSnapshot(key);
            if (cached != null) {
                return cached.newCursor();
            }

            Object[] args = chain.getArgs().toArray(new Object[0]);
            args[2] = tuned;

            Object result = chain.proceed(args);
            if (!(result instanceof Cursor)) return result;

            Cursor raw = (Cursor) result;
            CursorSnapshot snapshot = CursorSnapshot.capture(raw);
            if (snapshot != null) {
                putSnapshot(key, snapshot);
                warmLocalThumbnails((ContentResolver) chain.getThisObject(), snapshot);
                prefetchNextPage((ContentResolver) chain.getThisObject(), uri, tuned, snapshot);
            }
            return raw;
        }
    }

    private static final class CallHooker implements XposedInterface.Hooker {
        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            if (!enabled()) return chain.proceed();

            String authority = safeString(chain.getArg(0));
            String method = safeString(chain.getArg(1));
            if (!"media".equals(authority)
                    || (!"picker_media_init".equals(method)
                    && !"ensure_providers_call".equals(method))) {
                return chain.proceed();
            }

            long now = android.os.SystemClock.elapsedRealtime();
            long last = LAST_REFRESH_TS.get();
            if (now - last < REFRESH_DEBOUNCE_MS) {
                return Bundle.EMPTY;
            }
            LAST_REFRESH_TS.set(now);
            return chain.proceed();
        }
    }

    private static Bundle tuneQueryArgs(Bundle original) {
        Bundle out = new Bundle(original);
        int pageSize = out.getInt("page_size", 0);
        if (pageSize > 0 && pageSize < MIN_PAGE_SIZE) {
            int tuned = Math.min(MAX_PAGE_SIZE, Math.max(MIN_PAGE_SIZE, pageSize * 2));
            out.putInt("page_size", tuned);
        }
        return out;
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
        if (s.contains("search") || s.contains("preview") || s.contains("pre_selection")) {
            return false;
        }
        return s.contains("/media") || s.endsWith("/media");
    }

    private static void prefetchNextPage(
            ContentResolver resolver,
            Uri uri,
            Bundle currentArgs,
            CursorSnapshot current) {
        if (resolver == null || !isPrefetchable(uri, currentArgs)) return;

        long nextDate = current.extras.getLong(
                "next_page_date_taken", Long.MIN_VALUE);
        if (nextDate == Long.MIN_VALUE) return;

        long nextId = current.extras.getLong(
                "next_page_picker_id", Long.MIN_VALUE);

        Bundle next = new Bundle(currentArgs);
        next.putLong("date_taken_millis", nextDate);
        next.putLong("picker_id", nextId);

        String key = keyFor(uri, next);
        if (getFreshSnapshot(key) != null) return;

        IO.execute(() -> {
            if (getFreshSnapshot(key) != null) return;
            Cursor c = null;
            try {
                PREFETCHING.set(Boolean.TRUE);
                c = resolver.query(uri, null, next, null);
                if (c == null) return;

                CursorSnapshot snapshot = CursorSnapshot.capture(c);
                if (snapshot != null) {
                    putSnapshot(key, snapshot);
                    warmLocalThumbnails(resolver, snapshot);
                }
            } catch (Throwable ignored) {
                // Acceleration is strictly best-effort.
            } finally {
                if (c != null) {
                    try { c.close(); } catch (Throwable ignored) {}
                }
                PREFETCHING.remove();
            }
        });
    }

    private static void warmLocalThumbnails(ContentResolver resolver, CursorSnapshot snapshot) {
        if (resolver == null || snapshot == null || Build.VERSION.SDK_INT < 29) return;

        final List<Uri> uris = snapshot.firstLocalMediaUris(THUMB_WARM_COUNT);
        if (uris.isEmpty()) return;

        IO.execute(() -> {
            CancellationSignal signal = new CancellationSignal();
            for (Uri uri : uris) {
                try {
                    resolver.loadThumbnail(uri, new Size(256, 256), signal);
                } catch (Throwable ignored) {
                    // Ignore unsupported or stale items.
                }
            }
        });
    }

    private static String keyFor(Uri uri, Bundle b) {
        StringBuilder sb = new StringBuilder(uri.toString());
        ArrayList<String> keys = new ArrayList<>(b.keySet());
        Collections.sort(keys);
        for (String k : keys) {
            sb.append('|').append(k).append('=').append(stableValue(b.get(k)));
        }
        return sb.toString();
    }

    private static String stableValue(Object value) {
        if (value == null) return "null";
        if (value instanceof String[]) return Arrays.toString((String[]) value);
        if (value instanceof long[]) return Arrays.toString((long[]) value);
        if (value instanceof int[]) return Arrays.toString((int[]) value);
        if (value instanceof Object[]) return Arrays.deepToString((Object[]) value);
        return String.valueOf(value);
    }

    private static CursorSnapshot getFreshSnapshot(String key) {
        CacheEntry entry = CACHE.get(key);
        if (entry == null) return null;
        if (android.os.SystemClock.elapsedRealtime() - entry.when > CACHE_TTL_MS) {
            CACHE.remove(key);
            return null;
        }
        return entry.snapshot;
    }

    private static void putSnapshot(String key, CursorSnapshot snapshot) {
        CACHE.put(key, new CacheEntry(android.os.SystemClock.elapsedRealtime(), snapshot));
    }

    private static String safeString(Object o) {
        return o instanceof String ? (String) o : null;
    }

    private static final class CacheEntry {
        final long when;
        final CursorSnapshot snapshot;
        CacheEntry(long when, CursorSnapshot snapshot) {
            this.when = when;
            this.snapshot = snapshot;
        }
    }

    private static final class CursorSnapshot {
        final String[] columns;
        final ArrayList<Object[]> rows;
        final Bundle extras;

        CursorSnapshot(String[] columns, ArrayList<Object[]> rows, Bundle extras) {
            this.columns = columns;
            this.rows = rows;
            this.extras = extras;
        }

        static CursorSnapshot capture(Cursor cursor) {
            if (cursor == null) return null;
            int count;
            try {
                count = cursor.getCount();
            } catch (Throwable t) {
                return null;
            }
            if (count < 0 || count > MAX_SNAPSHOT_ROWS) return null;

            String[] columns;
            try {
                columns = cursor.getColumnNames();
            } catch (Throwable t) {
                return null;
            }

            Bundle extras;
            try {
                extras = new Bundle(cursor.getExtras());
            } catch (Throwable t) {
                extras = Bundle.EMPTY;
            }

            int original = cursor.getPosition();
            ArrayList<Object[]> rows = new ArrayList<>(count);

            try {
                if (cursor.moveToFirst()) {
                    do {
                        Object[] row = new Object[columns.length];
                        for (int i = 0; i < columns.length; i++) {
                            if (cursor.isNull(i)) {
                                row[i] = null;
                                continue;
                            }
                            switch (cursor.getType(i)) {
                                case Cursor.FIELD_TYPE_INTEGER:
                                    row[i] = cursor.getLong(i);
                                    break;
                                case Cursor.FIELD_TYPE_FLOAT:
                                    row[i] = cursor.getDouble(i);
                                    break;
                                case Cursor.FIELD_TYPE_BLOB:
                                    row[i] = cursor.getBlob(i);
                                    break;
                                case Cursor.FIELD_TYPE_STRING:
                                default:
                                    row[i] = cursor.getString(i);
                                    break;
                            }
                        }
                        rows.add(row);
                    } while (cursor.moveToNext());
                }
            } catch (Throwable t) {
                return null;
            } finally {
                try { cursor.moveToPosition(original); } catch (Throwable ignored) {}
            }

            return new CursorSnapshot(columns.clone(), rows, extras);
        }

        Cursor newCursor() {
            MatrixCursor c = new MatrixCursor(columns, rows.size());
            for (Object[] row : rows) c.addRow(row);
            try { c.setExtras(new Bundle(extras)); } catch (Throwable ignored) {}
            return c;
        }

        List<Uri> firstLocalMediaUris(int max) {
            int uriColumn = indexOf("unwrapped_uri");
            if (uriColumn < 0) uriColumn = indexOf("wrapped_uri");
            if (uriColumn < 0) return Collections.emptyList();

            ArrayList<Uri> out = new ArrayList<>();
            for (Object[] row : rows) {
                if (out.size() >= max) break;
                Object raw = row[uriColumn];
                if (!(raw instanceof String)) continue;

                try {
                    Uri uri = Uri.parse((String) raw);
                    String authority = uri.getAuthority();
                    if ("media".equals(authority)
                            || "com.android.providers.media.photopicker".equals(authority)) {
                        out.add(uri);
                    }
                } catch (Throwable ignored) {}
            }
            return out;
        }

        private int indexOf(String name) {
            for (int i = 0; i < columns.length; i++) {
                if (name.equals(columns[i])) return i;
            }
            return -1;
        }
    }
}
