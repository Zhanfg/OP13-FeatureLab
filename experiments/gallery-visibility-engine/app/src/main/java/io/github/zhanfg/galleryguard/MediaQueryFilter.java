package io.github.zhanfg.galleryguard;

import android.content.ContentResolver;
import android.content.Context;
import android.database.Cursor;
import android.database.CursorWrapper;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.provider.MediaStore;

import java.io.File;
import java.util.ArrayList;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import io.github.libxposed.api.XposedInterface;

/**
 * 查询层过滤（v1.1）：让相册"打开即隐藏"含 .nomedia 目录的已入库旧记录。
 * <p>
 * 原理：不删文件、不删 MediaStore 记录，只在【相册进程读取媒体库】时，把
 *       "位于含 .nomedia 目录（或其子目录）" 的行从返回 Cursor 中剔除。
 *       → 相册展示层看不到它们，磁盘文件与系统记录完好，移走 .nomedia 即恢复。
 * <p>
 * v1.1 优化"一闪而过"：相册首帧常用【不带 _data 的轻量查询】（如 proj=[_id]）先渲染，
 * 旧版只能过滤带 _data 的查询 → 首帧先闪出再消失。新版：
 *   - 模块启动后异步【预索引】：查一次媒体库 (_id,_data)，把 .nomedia 目录条目的
 *     _id 记入内存集合 sHiddenIds；
 *   - 查询过滤分两模式：
 *       MODE_DATA：投影含 _data → 按路径判断（命中行顺手把 _id 喂进集合，实时增量）；
 *       MODE_ID：投影无 _data 但含 _id，且索引非空 → 按 sHiddenIds 判断。
 *   → 第一帧的 [_id] 查询也能被过滤，不再闪。
 * <p>
 * ⚠️ 安全：
 *   - 只处理 content://media/...（媒体库）uri，其它 provider 查询原样放行；
 *   - 查询层只做"展示层隐藏"，不删文件、不删 MediaStore 记录。
 * <p>
 * v1.3.0【删行实时隐藏】（2026-09-03 黑盒验证闭环）：
 * 纯查询过滤不能让"开着相册时加 .nomedia"实时生效——UI 时间线数据源 = 相册自建
 * gallery.db local_media 表（ContentProvider 暴露），画面持旧 Cursor 不重查。
 * 黑盒实验结论：
 *   - 加 .nomedia → 直接走相册自己 provider.delete 删 local_media 对应行 →
 *     provider 自 notify → ContentObserverManager 分发 → UI 重查 → 图实时消失；✅
 *     且 .nomedia 在 → 模块查询过滤把 MediaStore 源里的行挡掉 → FullSync 补不回 → 稳定。
 *   - 删 .nomedia → 模块过滤失效 → 相册周期 FullSync 从 MediaStore 自动补回
 *     local_media → UI 自动恢复（无需模块动作）。✅
 * 因此本类新增删除能力：只删相册自建 local_media 的【索引行】（对应 .nomedia 目录
 * 文件，本就该在相册不可见）；磁盘文件与系统 MediaStore 记录不动，.nomedia 移除后
 * FullSync 自动重建，零数据破坏。
 * <p>
 * v1.3.1【删 .nomedia 重扫补全】：新照片在 .nomedia 存在时复制进目录 → 从未进
 * MediaStore → 删 .nomedia 后旧照片自动恢复、新照片不显示。修复：watcher 捕获
 * .nomedia DELETE/MOVED_FROM → rescanMediaAfterNomediaRemoved 主动系统重扫该目录
 * 媒体文件 → MediaStore 入库 → 相册 FullSync 自动补回 → 显示。
 */
public class MediaQueryFilter {

    public static final String TAG = "GalleryNomediaGuard";

    /** 已知"位于 .nomedia 目录"的媒体 _id（预索引 + 实时增量），线程安全 */
    private static final Set<Long> sHiddenIds = ConcurrentHashMap.newKeySet();

    /**
     * 最近一次触发"驱动相册 MediaSync 对账"的时间戳（节流用，避免每次 resume 狂驱动）。
     * 加/删 .nomedia 不产生 MediaStore 通知，相册不会自动重查 →
     * 模块在相册 Activity onResume / watcher 事件时反射驱动相册自身同步链对账刷新。
     */
    private static final java.util.concurrent.atomic.AtomicLong sLastNotifyTs =
            new java.util.concurrent.atomic.AtomicLong(0L);

    /** 只有可见性/nomedia 规则变化才需要额外驱动 ColorOS FullSync。 */
    private static final java.util.concurrent.atomic.AtomicLong sSyncDirtyGeneration =
            new java.util.concurrent.atomic.AtomicLong(1L);
    private static final java.util.concurrent.atomic.AtomicLong sSyncConsumedGeneration =
            new java.util.concurrent.atomic.AtomicLong(0L);

    /** 合并连续的设置变更，避免每勾选一个 App 都全库扫描 + purge + FullSync。 */
    private static final java.util.concurrent.atomic.AtomicLong sPolicyRefreshSerial =
            new java.util.concurrent.atomic.AtomicLong(0L);

    /** Application 引用（预索引/resume 通知用），由 MainHook 启动时注入 */
    static volatile android.content.Context sAppContext;

    /** 相册 App ClassLoader（反射驱动相册自身 MediaSync 用），由 MainHook 注入 */
    static volatile ClassLoader sAppClassLoader;

    /** 预索引是否已跑过（进程内只建一次） */
    private static volatile boolean sIndexBuilt;

    /** 预索引/purge 线程标记：我们自己发起的查询要直接 proceed，避免递归过滤（包可见，MainHook hooker 用） */
    static final ThreadLocal<Boolean> sIndexing = ThreadLocal.withInitial(() -> Boolean.FALSE);

    /**
     * Prevents duplicate SQL injection when ContentResolver.query() calls the in-process
     * GalleryProvider.query() on the same thread.
     */
    static final ThreadLocal<Boolean> sPushdownActive =
            ThreadLocal.withInitial(() -> Boolean.FALSE);

    private MediaQueryFilter() {}

    // ===== uri / 列判断 =====

    /** 是否媒体库查询（只过滤 content://media/...，其它放行） */
    static boolean isMediaUri(Uri uri) {
        if (uri == null || !"media".equals(uri.getAuthority())) return false;
        String path = uri.getPath();
        if (path == null) return false;
        String p = path.toLowerCase(java.util.Locale.ROOT);

        // Only collections that actually expose MediaStore._data. Do not touch PhotoPicker,
        // cloud-media or other internal MediaProvider tables.
        return p.contains("/images/media")
                || p.contains("/video/media")
                || p.endsWith("/file")
                || p.contains("/file/");
    }

    /**
     * 是否相册自建库(local_media)查询（v1.4 第二通道）：
     * uri = content://com.oplus.gallery.database.provider.gallery/local_media_internal 等。
     * 相册时间线/相册列表首帧数据源 = 自建 gallery.db local_media（非 content://media），
     * 旧 ContentResolver hook 只拦 content://media → 首帧旧列表完全盲区 → 闪烁。
     * 这里按 authority + 表名识别；raw_query/SQL 直查不改（太复杂易误伤）。
     */
    static boolean isGalleryLocalMediaUri(Uri uri) {
        if (uri == null) return false;

        // ColorOS 17 compatibility: do not hard-code one provider authority.
        // This hook only runs inside the Gallery process, so matching a Gallery-ish authority
        // plus known local media table path is substantially safer than binding to one class name.
        String authority = uri.getAuthority();
        String path = uri.getPath();
        if (authority == null || path == null) return false;

        String a = authority.toLowerCase(java.util.Locale.ROOT);
        String p = path.toLowerCase(java.util.Locale.ROOT);

        boolean galleryAuthority = a.contains("gallery") || a.contains("photos");
        boolean localMediaPath = p.contains("/local_media_internal")
                || p.contains("/local_media")
                || p.contains("/gallery_media");

        return galleryAuthority && localMediaPath;
    }

    /** projection 是否包含指定列（大小写不敏感） */
    private static boolean hasColumn(String[] projection, String column) {
        if (projection == null) return false;
        for (String c : projection) {
            if (c != null && c.equalsIgnoreCase(column)) return true;
        }
        return false;
    }

    static boolean hasDataColumn(String[] projection) { return hasColumn(projection, "_data"); }

    static boolean hasIdColumn(String[] projection) { return hasColumn(projection, "_id"); }

    // ===== 预索引：把 .nomedia 目录条目的 _id 记入内存 =====

    /**
     * 预扫描一次外部媒体库（image+video），把 .nomedia 目录下条目的 _id 记入 sHiddenIds。
     * 应在本模块进程早期（onPackageReady 后）由后台线程调用一次。
     * 查询走系统 MediaProvider，相册进程有读权限；用 sIndexing 防递归。
     */
    public static void buildHiddenIdIndex(Context ctx) {
        if (sIndexBuilt) return;
        sIndexBuilt = true;
        sIndexing.set(Boolean.TRUE);
        Cursor c = null;
        try {
            ContentResolver cr = ctx.getContentResolver();
            c = cr.query(
                    MediaStore.Files.getContentUri("external"),
                    new String[] { "_id", "_data", "owner_package_name" },
                    MediaStore.Files.FileColumns.MEDIA_TYPE + " IN (?,?)",
                    new String[] {
                        String.valueOf(MediaStore.Files.FileColumns.MEDIA_TYPE_IMAGE),
                        String.valueOf(MediaStore.Files.FileColumns.MEDIA_TYPE_VIDEO)
                    },
                    null);
            int added = 0;
            if (c != null && c.moveToFirst()) {
                int idCol = c.getColumnIndex("_id");
                int dataCol = c.getColumnIndex("_data");
                int ownerCol = c.getColumnIndex("owner_package_name");
                if (idCol >= 0 && dataCol >= 0) {
                    do {
                        String data;
                        String owner = null;
                        try { data = c.getString(dataCol); } catch (Throwable t) { data = null; }
                        if (ownerCol >= 0) {
                            try { owner = c.getString(ownerCol); } catch (Throwable ignored) {}
                        }
                        if (data != null && !data.isEmpty()) {
                            VisibilityPolicy.rememberOwnerAllowedPath(data, owner);
                            if (isHiddenPath(data)) {
                                sHiddenIds.add(c.getLong(idCol));
                                added++;
                            }
                        }
                    } while (c.moveToNext());
                }
            }
            // #ifdef DEBUG
            if (BuildConfig.DEBUG) {
                Debug.d(TAG, "ID-INDEX 预索引完成: 扫描命中隐藏 " + added + " 条, 累计集合 " + sHiddenIds.size());
            }
            // #endif
        } catch (Throwable t) {
            // #ifdef DEBUG
            if (BuildConfig.DEBUG) {
                Debug.d(TAG, "ID-INDEX 预索引失败: " + t);
            }
            // #endif
        } finally {
            if (c != null) c.close();
            sIndexing.remove();
        }
    }

    /** 隐藏 _id 是否已知（供 ID 模式过滤） */
    static boolean isHiddenId(long id) {
        return sHiddenIds.contains(id);
    }

    /** 有隐藏 id 才值得做 ID 模式过滤（避免空索引时每个查询都包 cursor） */
    static boolean hasHiddenIdIndex() {
        return !sHiddenIds.isEmpty();
    }

    // ===== .nomedia 目录判断（实时 stat，不缓存） =====

    /**
     * 判断一个媒体文件路径是否位于"含 .nomedia 的目录（或其子目录）"下。
     * 沿父目录逐级向上查，任何一级存在 .nomedia 即视为隐藏。
     * <p>
     * ⚠️ 刻意【不缓存】目录检查结果：加/删 .nomedia 必须实时反映（v1.2 修复——
     * 旧版永久缓存 true 导致"删除 .nomedia 后进程内仍隐藏、必须冷启动才恢复"）。
     * 每次 stat 目录链（典型 2-4 级，~微秒级），一次几百行查询约几十 ms，可接受。
     */
    static boolean isHiddenPath(String path) {
        return VisibilityPolicy.shouldHide(path);
    }

    // ===== v1.3.0 删行实时隐藏（黑盒验证闭环，2026-09-03） =====
    // 根因：UI 时间线数据源 = 相册自建 gallery.db local_media，画面持旧 Cursor 不重查；
    //       纯查询过滤只挡\"新查询\"，加 .nomedia 时旧画面不消失。
    // 解法：加 .nomedia → 走相册自己 provider.delete 删 local_media 对应行 →
    //       provider 自 notify → ContentObserverManager 分发 → UI 实时消失。
    // 恢复：删 .nomedia → 过滤失效 → 相册周期 FullSync 自动补回（无需模块动作）。
    // ⚠️ 只删相册自建索引行，磁盘/MediaStore 不动；.nomedia 移除后自动重建。

    /** 相册自建 local_media 表 uri（v11 实测 delete 有效 + 触发 UI 刷新） */
    private static final Uri GALLERY_LOCAL_MEDIA_URI =
            Uri.parse("content://com.oplus.gallery.database.provider.gallery/local_media");

    /**
     * 删除相册 local_media 中位于 dirPath 目录（含子目录）下的行。
     * 必须在 .nomedia 存在（要隐藏）时调用；删除经相册自己 ContentProvider →
     * provider 自 notify → UI 实时刷新（v11 黑盒验证）。
     *
     * @return 删除行数（0 = 无匹配/调用失败；幂等安全）
     */
    static int deleteLocalMediaRowsUnder(Context ctx, String dirPath) {
        if (ctx == null || dirPath == null || dirPath.isEmpty()) return 0;
        try {
            String prefix = dirPath.endsWith("/") ? dirPath : dirPath + "/";
            // 参数化 _data LIKE 前缀，避免误匹配兄弟目录（如 Plus2）
            ContentResolver cr = ctx.getContentResolver();
            int n = cr.delete(GALLERY_LOCAL_MEDIA_URI, "_data LIKE ?", new String[] { prefix + "%" });
            if (n > 0) {
                logMark("LOCALMEDIA-DEL: 删除 " + dirPath + " 下 local_media 行 " + n
                        + " (.nomedia 实时隐藏生效)");
            }
            return n;
        } catch (Throwable t) {
            logMark("LOCALMEDIA-DEL fail: dir=" + dirPath + " e=" + t);
            return 0;
        }
    }

    /**
     * 启动兜底清洗：把 local_media 中所有\"位于含 .nomedia 目录（或其子目录）\"的行删掉。
     * 场景：模块冷启动（升级/重启相册）时，之前已存在的 .nomedia 目录可能还在
     *       local_media 残留旧行 → 不重开相册也能隐藏。配合 watcher 增量删除互补：
     *       watcher 管\"之后新增的 .nomedia\"，purge 管\"启动前已有的\"。
     * 与预索引同思路：全表扫 _data 实时 stat 判断（local_media 行量级几百~几千，可接受），
     * 命中行收集其父目录去重后逐个删。只删真隐藏目录，零误伤。
     */
    static void purgeLocalMediaForHiddenDirs(Context ctx) {
        if (ctx == null) return;
        Cursor c = null;
        sIndexing.set(Boolean.TRUE);   // 防 GalleryProvider.query hook 递归过滤
        try {
            ContentResolver cr = ctx.getContentResolver();
            c = cr.query(GALLERY_LOCAL_MEDIA_URI, new String[] { "_id", "_data" },
                    null, null, null);
            if (c == null) return;
            java.util.LinkedHashSet<String> dirs = new java.util.LinkedHashSet<>();
            int idCol = c.getColumnIndex("_id");
            int dataCol = c.getColumnIndex("_data");
            if (c.moveToFirst() && idCol >= 0 && dataCol >= 0) {
                do {
                    String data;
                    try { data = c.getString(dataCol); } catch (Throwable t) { data = null; }
                    if (data == null || data.isEmpty()) continue;
                    if (!isHiddenPath(data)) continue;
                    File parent = new File(data).getParentFile();
                    if (parent != null) dirs.add(parent.getAbsolutePath());
                } while (c.moveToNext());
            }
            if (dirs.isEmpty()) {
                // #ifdef DEBUG
                if (BuildConfig.DEBUG) {
                    Debug.d(TAG, "LOCALMEDIA-PURGE: 无隐藏目录残留, 跳过");
                }
                // #endif
                return;
            }
            int total = 0;
            for (String dir : dirs) {
                total += deleteLocalMediaRowsUnder(ctx, dir);
            }
            logMark("LOCALMEDIA-PURGE: 清洗 " + dirs.size() + " 个隐藏目录, 共删 " + total + " 行");
        } catch (Throwable t) {
            logMark("LOCALMEDIA-PURGE fail: " + t);
        } finally {
            if (c != null) c.close();
            sIndexing.remove();
        }
    }

    // ===== 主动驱动相册刷新（加/删 .nomedia 后相册不会自己重查） =====
    // ⚠️ v1.1.9 方案 A：不再 notifyChange，改为反射驱动相册自身 MediaSync。
    //    根因（mt 静态全链路确认）：相册媒体观察者 qia$a/loo$d deliverSelfNotifications=false，
    //    模块 notifyChange = 同 uid 自通知 → ContentService 不投递 → v1.2~1.1.8 的
    //    "resume notify 驱动刷新"实际全部无效，只有冷启动（进程重建自查）才生效。

    /** 标记：只有规则真的变化时，下一次才需要额外对账。 */
    public static void markGallerySyncDirty() {
        sSyncDirtyGeneration.incrementAndGet();
    }

    /**
     * Gallery Activity resume 的轻量路径：
     * 没有 .nomedia/透传策略变化时直接 O(1) 返回，不再每次 resume 触发 FullSync。
     */
    public static void driveGallerySyncOnResumeIfDirty() {
        if (sAppContext == null) return;

        long dirty = sSyncDirtyGeneration.get();
        long consumed = sSyncConsumedGeneration.get();
        if (dirty == consumed) return;

        if (!sSyncConsumedGeneration.compareAndSet(consumed, dirty)) return;

        long now = System.currentTimeMillis();
        sLastNotifyTs.set(now);
        driveGalleryMediaSync();

        // #ifdef DEBUG
        if (BuildConfig.DEBUG) {
            Debug.d(TAG, "SYNC-DRIVE[dirty-resume]: generation=" + dirty);
        }
        // #endif
    }

    /** 节流版（watcher/后台事件用）：只对真实规则变化触发，3s 内不重复驱动。 */
    public static void driveGallerySyncIfNeeded() {
        android.content.Context ctx = sAppContext;
        if (ctx == null) return;

        long dirty = sSyncDirtyGeneration.get();
        long consumed = sSyncConsumedGeneration.get();
        if (dirty == consumed) return;

        long now = System.currentTimeMillis();
        long last = sLastNotifyTs.get();
        if (now - last < 3000) return;
        if (!sLastNotifyTs.compareAndSet(last, now)) return;

        driveGalleryMediaSync();
        sSyncConsumedGeneration.set(dirty);

        // #ifdef DEBUG
        if (BuildConfig.DEBUG) {
            Debug.d(TAG, "SYNC-DRIVE[dirty]: generation=" + dirty);
        }
        // #endif
    }

    /**
     * v1.1.9 方案 A：反射调用相册自己的 onMediaChange 静态入口，走相册原生同步链。
     * <p>
     * 目标：com.oplus.aiunit.vision.loo（MediaSyncManager 单例）的静态方法
     *   {@code loo.a(loo实例, boolean selfChange, Uri uri)}。
     * 传 selfChange=false（非自通知）+ images/video 根 uri → 与系统 MediaProvider
     * 跨进程通知走同一条路：
     *   loo.a → UriMatcher 白名单校验 → handleRecvUris → 根 uri 无 id → 排队 10s
     *   MSG_FULL_SYNC → FullSyncTask(u1h) 全量对账：
     *   重查 MediaStore（此时被模块查询层过滤，.nomedia 行不可见）→
     *   发现相册本地库多出这些行 → 删除 → 通知 UI 刷新 → 图消失（磁盘文件不动）。
     * 节流/队列/线程全由相册自己管理，安全。
     */
    private static void driveGalleryMediaSync() {
        ClassLoader cl = sAppClassLoader;
        if (cl == null) return;

        // ColorOS 17 / Gallery 17.10.6: fgq is the MediaSyncManager implementation.
        // ColorOS 16: loo served the same role. Both expose:
        //   static f() -> singleton
        //   static a(Self, boolean, Uri) -> onMediaChange
        final String[] candidates = {
                "com.oplus.aiunit.vision.fgq",
                "com.oplus.aiunit.vision.loo"
        };

        Throwable last = null;

        for (String className : candidates) {
            try {
                Class<?> syncCls = Class.forName(className, false, cl);

                java.lang.reflect.Method getter = null;
                for (java.lang.reflect.Method m : syncCls.getDeclaredMethods()) {
                    if ("f".equals(m.getName())
                            && m.getParameterCount() == 0
                            && m.getReturnType() == syncCls) {
                        getter = m;
                        break;
                    }
                }
                if (getter == null) continue;

                getter.setAccessible(true);
                Object inst = getter.invoke(null);
                if (inst == null) continue;

                java.lang.reflect.Method onChange = null;
                for (java.lang.reflect.Method m : syncCls.getDeclaredMethods()) {
                    Class<?>[] p = m.getParameterTypes();
                    if ("a".equals(m.getName())
                            && p.length == 3
                            && p[0] == syncCls
                            && p[1] == boolean.class
                            && p[2] == android.net.Uri.class
                            && m.getReturnType() == void.class) {
                        onChange = m;
                        break;
                    }
                }
                if (onChange == null) continue;

                onChange.setAccessible(true);
                onChange.invoke(null, inst, Boolean.FALSE,
                        MediaStore.Images.Media.getContentUri("external"));
                onChange.invoke(null, inst, Boolean.FALSE,
                        MediaStore.Video.Media.getContentUri("external"));

                if (BuildConfig.DEBUG) {
                    Debug.d(TAG, "SYNC-DRIVE: matched " + className);
                }
                return;
            } catch (Throwable t) {
                last = t;
            }
        }

        if (BuildConfig.DEBUG) {
            Debug.d(TAG, "SYNC-DRIVE: no compatible MediaSyncManager"
                    + (last != null ? " / " + last : ""));
        }
    }

    /**
     * 策略变化后的增量重建。RemotePreferences 监听线程只负责发信号，
     * 真正扫描放后台，避免阻塞 Binder / UI。
     */
    public static void onVisibilityPolicyChanged() {
        // SQL predicate snapshots are generation-based and rebuild lazily on the next query.
        // Do not scan MediaStore or local_media here; those full scans were the main source of
        // UI stalls on large ColorOS 17 libraries.
        final Context ctx = sAppContext;
        markGallerySyncDirty();
        if (ctx == null) return;

        final long serial = sPolicyRefreshSerial.incrementAndGet();
        Thread t = new Thread(() -> {
            try {
                Thread.sleep(300);
            } catch (InterruptedException e) {
                return;
            }
            if (serial != sPolicyRefreshSerial.get()) return;
            driveGallerySyncIfNeeded();
        }, "gallery-policy-refresh");
        t.setDaemon(true);
        t.start();
    }

    /** 测试/调试用：清空策略缓存。 */
    static void clearCache() {
        VisibilityPolicy.invalidate();
    }

    // ===== .nomedia 文件变化实时监听（v1.6：消除"切回相册闪一帧"） =====

    /** watcher 引用（防 GC），进程内只建一次 */
    private static volatile java.util.ArrayList<android.os.FileObserver> sWatchers;

    /** v1.3.1: 目录重扫防抖表（删 .nomedia 后 1.5s 内不重复扫同目录） */
    private static final java.util.concurrent.ConcurrentHashMap<String, Long> sLastDirScan =
            new java.util.concurrent.ConcurrentHashMap<>();

    /** v1.3.1: 常见媒体扩展名（删 .nomedia 后重扫用） */
    private static final java.util.Set<String> sMediaExts = new java.util.HashSet<>(
            java.util.Arrays.asList(
                "jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "mpo",
                "mp4", "m4v", "3gp", "webm", "mov", "avi", "mkv"));

    /**
     * v1.3.1 恢复方向补全：.nomedia 被删除 → 触发该目录（含子目录）系统 MediaScanner 重扫。
     * <p>
     * 背景：新照片在 .nomedia 存在时复制进目录 → MediaScanner 忽略该目录 →
     *       新照片从未进 MediaStore → 相册 FullSync 只同步 MediaStore → 删 .nomedia
     *       后旧照片恢复、新照片仍不显示。
     * 解法：.nomedia 移除后主动请求系统重扫该目录媒体文件（MediaScannerConnection.scanFile
     *       ——官方 API，Android 8+ 通用）→ 新照片进 MediaStore → MediaStore notify →
     *       相册 FullSync 自动补回 local_media → 显示。旧文件重复扫幂等无害。
     * 实现：收集目录树媒体文件（限扩展名 + 深度/总量）→ 延迟 600ms(等文件系统稳定)
     *       → 分批 scanFile（200/批，防一次过多）→ 驱动相册同步兜底。
     */
    static void rescanMediaAfterNomediaRemoved(Context ctx, String dirPath) {
        if (ctx == null || dirPath == null || dirPath.isEmpty()) return;
        long now = System.currentTimeMillis();
        String key = "scan:" + dirPath;
        Long last = sLastDirScan.get(key);
        if (last != null && now - last < 1500) return;          // 防抖：1.5s
        sLastDirScan.put(key, now);
        new Thread(() -> {
            try { Thread.sleep(600); } catch (InterruptedException e) { return; }
            try {
                java.util.ArrayList<String> files = new java.util.ArrayList<>();
                collectMediaFiles(new File(dirPath), files, 0);
                if (files.isEmpty()) {
                    logMark("SCAN-DIR: " + dirPath + " 无可扫媒体文件(仅目录/非媒体)");
                    return;
                }
                final int BATCH = 200;
                for (int i = 0; i < files.size(); i += BATCH) {
                    int end = Math.min(i + BATCH, files.size());
                    String[] batch = files.subList(i, end).toArray(new String[0]);
                    MediaScannerConnection.scanFile(ctx, batch, null, null);
                }
                logMark("SCAN-DIR: .nomedia 已移除, 重扫 " + dirPath + " 下 "
                        + files.size() + " 个媒体文件 → MediaStore 入库");
                // scan 后 MediaStore notify 通常自动触发；仅 nomedia 规则变化时兜底对账。
                markGallerySyncDirty();
                driveGallerySyncIfNeeded();
            } catch (Throwable t) {
                logMark("SCAN-DIR fail: " + dirPath + " e=" + t);
            }
        }, "nomedia-rescan").start();
    }

    /** 收集 dir 树下的媒体文件路径（限扩展名/深度/总量，防失控） */
    private static void collectMediaFiles(File dir, java.util.ArrayList<String> out, int depth) {
        if (dir == null || depth > 4 || out.size() >= 1000) return;
        File[] children;
        try { children = dir.listFiles(); } catch (Throwable t) { return; }
        if (children == null) return;
        for (File f : children) {
            try {
                String n = f.getName();
                if (n.startsWith(".")) continue;                 // 隐藏项跳过
                if (f.isDirectory()) {
                    collectMediaFiles(f, out, depth + 1);
                } else {
                    int dot = n.lastIndexOf('.');
                    if (dot >= 0 && sMediaExts.contains(n.substring(dot + 1).toLowerCase())) {
                        out.add(f.getAbsolutePath());
                    }
                }
            } catch (Throwable ignored) {}
        }
    }

    /**
     * v1.6+：监控媒体目录树内 .nomedia 的增删（自实现递归 watch）。
     * 背景：加/删 .nomedia 不产生任何系统通知；相册在后台时不会重查，切回前台
     *       resume 先画旧内存列表一帧，随后驱动对账才刷新 → "一闪"。
     * 方案：.nomedia 一变化就立刻驱动相册 MediaSync（v1.1.9 起为反射驱动 loo.a，
     *       之前 notifyChange 因 self-notification 限制实际无效），相册在后台就完成
     *       对账 → resume 画帧时已是新数据 → 零闪。
     * 实现：Android FileObserver 官方无递归构造 → 对目录树【每个目录】各建一个
     *       watch（inotify）。只监听 Pictures/DCIM 两个媒体根（覆盖相册绝大多数
     *       来源与测试目录 /Pictures/Plus），控制 watch 数量，见性能注释。
     * 新目录（启动后才创建）：不在本批 watch 内 → 由 onResume 驱动兜底
     *       （媒体目录几乎都预存在，代价可接受）。
     */
    public static void startNomediaWatcher(Context ctx) {
        if (ctx == null) {
            logMark("WATCHER: skip ctx=null");
            return;
        }
        synchronized (MediaQueryFilter.class) {
            if (sWatchers != null) {
                logMark("WATCHER: skip already-started (" + sWatchers.size() + ")");
                return;
            }
            sWatchers = new java.util.ArrayList<>();   // 先占位，防并发重复启动
        }
        final String[] roots = {
            "/storage/emulated/0/Pictures",
            "/storage/emulated/0/DCIM",
        };
        logMark("WATCHER: start collecting under Pictures/DCIM");
        // 目录树收集 + 建 watch 可能涉及几百~几千目录，放后台线程，不卡 hook/UI
        new Thread(() -> {
            final int mask = android.os.FileObserver.CREATE
                | android.os.FileObserver.DELETE
                | android.os.FileObserver.MOVED_TO
                | android.os.FileObserver.MOVED_FROM
                | android.os.FileObserver.CLOSE_WRITE;
            java.util.ArrayList<android.os.FileObserver> list = new java.util.ArrayList<>();
            int skipped = 0;
            for (String root : roots) {
                File rf = new File(root);
                if (!rf.isDirectory()) { skipped++; continue; }
                java.util.ArrayDeque<File> queue = new java.util.ArrayDeque<>();
                queue.add(rf);
                while (!queue.isEmpty()) {
                    File dir = queue.poll();
                    // 深目录树一次性全建 watch 可能太多；限制单根深度避免失控
                    if (list.size() >= 600) { skipped++; break; }
                    try {
                        // v1.3.0: 捕获本 watch 目录绝对路径（.nomedia 事件精确删行用）
                        final String watchDirAbs = dir.getAbsolutePath();
                        android.os.FileObserver w = new android.os.FileObserver(dir.getAbsolutePath(), mask) {
                            @Override public void onEvent(int event, String path) {
                                if (path != null
                                    && (path.equals(".nomedia") || path.endsWith("/.nomedia"))) {
                                    logMark("WATCHER-EVT: .nomedia changed: " + path
                                            + " in " + watchDirAbs);
                                    // v1.3.0: 加 .nomedia(CREATE/MOVED_TO) → 立刻删该目录
                                    // local_media 行 → provider 自 notify → UI 实时消失
                                    boolean created = (event & (android.os.FileObserver.CREATE
                                            | android.os.FileObserver.MOVED_TO)) != 0;
                                    // v1.3.1: 删 .nomedia(DELETE/MOVED_FROM) → 触发系统重扫
                                    // 该目录媒体(新照片复制时被忽略, 从未进 MediaStore →
                                    // 不重扫则删 .nomedia 后仍不显示)
                                    boolean removed = (event & (android.os.FileObserver.DELETE
                                            | android.os.FileObserver.MOVED_FROM)) != 0;
                                    if (created) {
                                        deleteLocalMediaRowsUnder(sAppContext, watchDirAbs);
                                    } else if (removed) {
                                        rescanMediaAfterNomediaRemoved(sAppContext, watchDirAbs);
                                    }
                                    markGallerySyncDirty();
                                    driveGallerySyncIfNeeded();  // 仅真实 .nomedia 变化才驱动
                                }
                            }
                        };
                        w.startWatching();
                        list.add(w);
                    } catch (Throwable t) {
                        skipped++;
                        // 单个目录建 watch 失败（如配额满/无权限）→ 记录首例后跳过
                        if (skipped == 1) logMark("WATCHER: first watch fail: " + t);
                    }
                    // 子目录入队（仅下一层目录）
                    File[] children;
                    try { children = dir.listFiles(); } catch (Throwable t) { children = null; }
                    if (children != null) {
                        for (File c : children) {
                            try {
                                if (c.isDirectory() && !c.getName().startsWith(".")) queue.add(c);
                            } catch (Throwable ignored) {}
                        }
                    }
                }
            }
            synchronized (MediaQueryFilter.class) {
                if (list.isEmpty()) {
                    sWatchers = null;
                    logMark("WATCHER: empty, nothing watched (skipped=" + skipped + ")");
                    return;
                }
                sWatchers = list;
            }
            logMark("WATCHER: started " + list.size() + " watches (skipped=" + skipped + ") Pictures/DCIM");
        }, "nomedia-watcher").start();
    }

    /** watcher 阶段标记：走 Debug.d 双通道（debug 构建才打）——排查 watcher 是否真跑/跑到哪 */
    private static void logMark(String s) {
        Debug.d(TAG, s);
    }

    // ===== 过滤 Cursor（双模式） =====

    /**
     * 过滤 Cursor：预扫描底层 cursor，把隐藏行剔除，对外呈现"干净"的列表。
     * 所有位置类方法基于可见行映射，getXxx 由 CursorWrapper 透传底层（已定位到可见行）。
     * <p>
     * MODE_DATA = 按 _data 路径判断（命中行顺手把 _id 喂入 sHiddenIds 增量）；
     * MODE_ID   = 按 _id ∈ sHiddenIds 判断（用于投影无 _data 的首帧轻量查询）。
     */
    static class FilteringCursor extends CursorWrapper {

        static final int MODE_DATA = 1;
        static final int MODE_ID = 2;

        private final Cursor mInner;
        private final int mMode;
        private final boolean mFeedIdIndex; // MODE_DATA 命中时是否顺手把 _id 喂入 sHiddenIds
        private final int mDataCol;   // MODE_DATA 用（可能 -1）
        private final int mIdCol;     // MODE_ID 用（可能 -1）
        private final int mOwnerCol;  // owner_package_name（可能 -1）
        private final ArrayList<Integer> mVisible = new ArrayList<>();
        private int mPos = -1;          // 逻辑当前位置（-1 = beforeFirst）
        private int mHiddenCount;       // 被过滤掉的行数（调试用）
        private String mHiddenSample;   // 首个被隐藏的行样例（调试用，仅 debug 打印）

        FilteringCursor(Cursor inner, int mode) {
            this(inner, mode, true);
        }

        FilteringCursor(Cursor inner, int mode, boolean feedIdIndex) {
            super(inner);
            mInner = inner;
            mMode = mode;
            mFeedIdIndex = feedIdIndex;
            mDataCol = inner.getColumnIndex("_data");
            mIdCol = inner.getColumnIndex("_id");
            mOwnerCol = inner.getColumnIndex("owner_package_name");
            build();
        }

        /** 预扫描：遍历底层 cursor，只保留非隐藏行 */
        private void build() {
            if (mMode == MODE_DATA && mDataCol < 0) {
                // 期望按路径但无 _data 列：无法判断 → 全部保留
                keepAll();
                return;
            }
            if (mMode == MODE_ID && mIdCol < 0) {
                keepAll();
                return;
            }
            if (!mInner.moveToFirst()) return;
            do {
                if (isRowHidden()) {
                    mHiddenCount++;
                } else {
                    mVisible.add(mInner.getPosition());
                }
            } while (mInner.moveToNext());
        }

        private void keepAll() {
            if (mInner.moveToFirst()) {
                do { mVisible.add(mInner.getPosition()); } while (mInner.moveToNext());
            }
        }

        private boolean isRowHidden() {
            if (mMode == MODE_DATA) {
                String data;
                try { data = mInner.getString(mDataCol); } catch (Throwable t) { data = null; }
                if (data == null || data.isEmpty()) return false;
                if (mOwnerCol >= 0) {
                    try {
                        VisibilityPolicy.rememberOwnerAllowedPath(data, mInner.getString(mOwnerCol));
                    } catch (Throwable ignored) {}
                }
                if (!isHiddenPath(data)) return false;
                if (mHiddenSample == null) mHiddenSample = data;
                // 顺手把 _id 喂进集合（实时增量，让后续无 _data 查询也能过滤）。
                // ⚠️ 仅 content://media 查询可喂（_id = MediaStore._id）；
                //    GalleryProvider local_media 查询 _id ≠ MediaStore._id，禁止喂（feedIdIndex=false）。
                if (mFeedIdIndex && mIdCol >= 0) {
                    try { sHiddenIds.add(mInner.getLong(mIdCol)); } catch (Throwable ignored) {}
                }
                return true;
            } else { // MODE_ID
                long id;
                try { id = mInner.getLong(mIdCol); } catch (Throwable t) { return false; }
                if (!isHiddenId(id)) return false;
                if (mHiddenSample == null) mHiddenSample = String.valueOf(id);
                return true;
            }
        }

        int hiddenCount() { return mHiddenCount; }
        String hiddenSample() { return mHiddenSample; }

        // ---- 位置类方法（全部基于可见行映射）----

        @Override public int getCount() { return mVisible.size(); }

        @Override public boolean moveToPosition(int position) {
            if (position < 0 || position >= mVisible.size()) {
                mPos = position < 0 ? -1 : mVisible.size();
                return false;
            }
            mInner.moveToPosition(mVisible.get(position));
            mPos = position;
            return true;
        }

        @Override public boolean moveToFirst() { return moveToPosition(0); }

        @Override public boolean moveToLast() { return moveToPosition(mVisible.size() - 1); }

        @Override public boolean moveToNext() { return moveToPosition(mPos + 1); }

        @Override public boolean moveToPrevious() { return moveToPosition(mPos - 1); }

        @Override public boolean move(int offset) { return moveToPosition(mPos + offset); }

        @Override public boolean isFirst() { return mPos == 0 && mVisible.size() > 0; }

        @Override public boolean isLast() { return mPos == mVisible.size() - 1 && mVisible.size() > 0; }

        @Override public boolean isBeforeFirst() { return mVisible.isEmpty() || mPos < 0; }

        @Override public boolean isAfterLast() { return mVisible.isEmpty() || mPos >= mVisible.size(); }

        @Override public int getPosition() { return mPos; }
    }

    // ===== ContentResolver.query 拦截器 =====

    /**
     * ContentResolver.query 拦截器：
     *   - 非媒体 uri / 预索引自身查询 → 直接 proceed（原样）
     *   - 媒体 uri 且投影含 _data → MODE_DATA 路径过滤（命中顺手喂 _id）
     *   - 媒体 uri 投影无 _data 但含 _id 且索引非空 → MODE_ID 过滤（覆盖首帧轻量查询）
     *   - 其余 → 原样放行（无可判列）
     * 功能（过滤）release/debug 都生效；路径/统计日志仅 debug（if BuildConfig.DEBUG）。
     */
    static Object proceedWithVisibilityPushdown(
            XposedInterface.Chain chain) throws Throwable {
        if (Boolean.TRUE.equals(sPushdownActive.get())) {
            return chain.proceed();
        }

        Object[] modified = VisibilityQueryPushdown.inject(chain);
        if (modified == null) {
            return chain.proceed();
        }

        sPushdownActive.set(Boolean.TRUE);
        try {
            return chain.proceed(modified);
        } finally {
            sPushdownActive.remove();
        }
    }

    public static class QueryHooker implements XposedInterface.Hooker {
        private static int sQueryCount;
        private static int sOtherUriCount;

        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            if (Boolean.TRUE.equals(sIndexing.get())) return chain.proceed();

            Object o0 = chain.getArg(0);
            if (!(o0 instanceof Uri)) return chain.proceed();

            Uri uri = (Uri) o0;
            boolean mediaStoreQuery = isMediaUri(uri);
            boolean galleryLocalQuery = isGalleryLocalMediaUri(uri);

            if (!mediaStoreQuery && !galleryLocalQuery) {
                if (BuildConfig.DEBUG && uri.toString().startsWith("content://")) {
                    sOtherUriCount++;
                    if (sOtherUriCount <= 20 || sOtherUriCount % 250 == 0) {
                        Debug.d(TAG, "QUERY-PUSHDOWN[OTHER] #" + sOtherUriCount
                                + " uri=" + uri);
                    }
                }
                return chain.proceed();
            }

            sQueryCount++;
            if (BuildConfig.DEBUG && (sQueryCount <= 20 || sQueryCount % 100 == 0)) {
                Debug.d(TAG, "QUERY-PUSHDOWN #" + sQueryCount
                        + " uri=" + uri
                        + " generation=" + VisibilityPolicy.generation());
            }

            // Critical fast path: filtering happens in provider SQL before a Cursor exists.
            // No getCount(), no full Cursor iteration, no frozen visible-position table.
            return proceedWithVisibilityPushdown(chain);
        }
    }}
