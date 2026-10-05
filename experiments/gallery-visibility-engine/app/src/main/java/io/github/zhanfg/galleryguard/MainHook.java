package io.github.zhanfg.galleryguard;

import static android.util.Log.DEBUG;
import static android.util.Log.INFO;

import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.os.CancellationSignal;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.HashSet;

import io.github.libxposed.api.XposedInterface;
import io.github.libxposed.api.XposedModule;
import io.github.libxposed.api.XposedModuleInterface;

/**
 * ColorOS Gallery Nomedia Guard —— 入口（java_init.list 声明）。
 * <p>
 * 目标：让 ColorOS 相册（com.coloros.gallery3d）遵循 Android .nomedia 标准，两重防线：
 * <ol>
 *   <li>破坏链阻断（原有）：相册内置 NomediaScanner 会把"保护名单"目录里的 .nomedia
 *       自动改名/删除再重扫 → 本模块短路其入口/任务/判定，使 .nomedia 不被破坏；</li>
 *   <li>查询层过滤（v1.1）：hook ContentResolver.query（相册进程），把"已入库但在含
 *       .nomedia 目录下"的旧记录从返回 Cursor 剔除 → 打开相册即自动隐藏，不删文件不删记录。</li>
 * </ol>
 * 生命周期：onModuleLoaded → onPackageReady → installHooks
 * 热重载：  onHotReloading(返回true) → unhook 旧 handle → installHooks 重装
 */
public class MainHook extends XposedModule implements HookLogger {

    public static final String TAG = "GalleryNomediaGuard";

    private ClassLoader mAppClassLoader;
    private String mProcessName;
    private String mPackageName;
    private SharedPreferences mPrefs;

    private static int sHookOk;
    private static int sHookFail;
    private static StringBuilder sHookDetail;

    public MainHook() { super(); }

    /** 静态实例引用（static 内部类 hooker 通过它调实例 log(INFO) 等） */
    private static volatile MainHook sInstance;

    // ===== 生命周期 =====

    @Override
    public void onModuleLoaded(XposedModuleInterface.ModuleLoadedParam param) {
        sInstance = this;
        Debug.sLogger = this;
        mProcessName = param.getProcessName();
        try {
            mPrefs = getRemotePreferences(GuardPrefs.GROUP);
            VisibilityPolicy.bind(mPrefs, MediaQueryFilter::onVisibilityPolicyChanged);
            log(INFO, TAG, "module loaded, process=" + mProcessName + ", prefs=remote");
        } catch (Throwable t) {
            mPrefs = null;
            VisibilityPolicy.bind(null, null);
            log(INFO, TAG, "remote prefs unavailable, using safe defaults: " + t);
        }
    }

    @Override
    public void onPackageReady(XposedModuleInterface.PackageReadyParam param) {
        ClassLoader cl = param.getClassLoader();
        mAppClassLoader = cl;
        mPackageName = param.getPackageName();

        log(INFO, TAG, "[pkg] ready package=" + mPackageName
                + " process=" + mProcessName
                + " classLoader=" + (cl != null ? "non-null" : "NULL!"));

        if ("com.coloros.gallery3d".equals(mPackageName)) {
            // Gallery-only hooks and state.
            MediaQueryFilter.sAppClassLoader = cl;
            installGalleryHooks(cl);
            startHiddenIdIndexer(cl);
            return;
        }

        if (PhotoPickerAccelerator.isPickerPackage(mPackageName)
                && PhotoPickerAccelerator.shouldInstallInProcess(mPackageName, mProcessName)) {
            PhotoPickerAccelerator.install(this, mPrefs);
        }
    }

    @Override
    public boolean onHotReloading(XposedModuleInterface.HotReloadingParam param) {
        return true;
    }

    @Override
    public void onHotReloaded(XposedModuleInterface.HotReloadedParam param) {
        // unhook 旧 handle
        ClassLoader cl = null;
        if (param.getOldHookHandles() != null) {
            for (XposedInterface.HookHandle h : param.getOldHookHandles()) {
                try {
                    if (cl == null) cl = h.getExecutable().getDeclaringClass().getClassLoader();
                } catch (Throwable ignored) {}
                try { h.unhook(); } catch (Throwable ignored) {}
            }
        }
        if (cl == null) cl = mAppClassLoader;
        if (cl == null) return;

        if ("com.coloros.gallery3d".equals(mPackageName)) {
            installGalleryHooks(cl);
        } else if (PhotoPickerAccelerator.isPickerPackage(mPackageName)
                && PhotoPickerAccelerator.shouldInstallInProcess(mPackageName, mProcessName)) {
            PhotoPickerAccelerator.install(this, mPrefs);
        }

        restoreModuleState();
        log(INFO, TAG, "hot reloaded, hooks reinstalled for " + mPackageName);
    }

    // ===== 静态日志桥（供 static hooker 用）=====

    /** INFO 级框架日志（正式版保留）。hooker 在相册进程调用, 每实例每方法仅首次触发。 */
    static void info(String tag, String msg) {
        MainHook i = sInstance;
        if (i != null) {
            i.log(INFO, tag, msg);
        } else {
            android.util.Log.i(tag, msg); // 极端兜底: 框架实例未就绪也尽量留痕
        }
    }

    // ===== Gallery hooks =====

    private void installGalleryHooks(ClassLoader cl) {
        sHookDetail = new StringBuilder();
        sHookOk = sHookFail = 0;

        /*
         * ColorOS 17 (Gallery 17.10.6) moved the nomedia chain:
         *   MediaDBSyncDM.i() -> uks.run() -> wks.a(String,String,HashMap,HashMap)
         * ColorOS 16 used:
         *   MediaDBSyncDM.j() -> gyq.run() -> iyq.a(...)
         *
         * Try structural/version candidates in order and hook only the first valid one in each
         * role. This keeps one APK compatible with both generations without relying on OS version.
         */
        hookFirstNoArgVoid(cl,
                new String[][] {
                        {"com.oplus.gallery.framework.abilities.mediadbsync.MediaDBSyncDM", "i",
                                "ColorOS17 entry(i=startNomediaCheckTask)"},
                        {"com.oplus.gallery.framework.abilities.mediadbsync.MediaDBSyncDM", "j",
                                "ColorOS16 entry(j=startNomediaCheckTask)"}
                },
                "nomedia-entry");

        hookFirstNoArgVoid(cl,
                new String[][] {
                        {"com.oplus.aiunit.vision.uks", "run", "ColorOS17 NomediaScanner task"},
                        {"com.oplus.aiunit.vision.gyq", "run", "ColorOS16 NomediaScanner task"}
                },
                "nomedia-task");

        // ③ 兜底：判定函数恒 false，确保即便其它入口启动 scanner，也不会改名/删除 .nomedia。
        hookNomediaCheck(cl);

        // ④ 查询层过滤（v1）：hook ContentResolver.query —— 相册读媒体库时剔除 .nomedia 目录旧记录
        hookContentResolverQuery(cl);

        // ⑤ 主动刷新（v1.2→v1.1.9 演进）：hook Activity.onResume → 反射驱动相册自身
        //    MediaSync(loo.a onMediaChange) 对账。旧 notifyChange 因 self-notification 无效。
        hookActivityResume(cl);

        // ⑥ 第二通道（v1.4）：hook 相册自建库 GalleryProvider.query —— 首帧时间线数据源
        //    = 自建 gallery.db local_media（非 content://media，旧 ContentResolver hook 盲区）。
        //    对 local_media 且带 _data 的查询做 .nomedia 路径过滤（同 ContentResolver 逻辑），
        //    从源头掐掉"旧列表先渲染再对账"的闪烁。
        hookGalleryProviderQuery(cl);

        log(INFO, TAG, "installGalleryHooks done: " + sHookOk + " OK / " + sHookFail + " FAIL / \n" + sHookDetail);
        sHookOk = sHookFail = 0;
        sHookDetail.setLength(0);
    }

    /**
     * Package-private bridge for isolated helper components such as PhotoPickerAccelerator.
     * Keeps access to XposedModule#hook inside this module entry point.
     */
    void installExternalHook(Method method, XposedInterface.Hooker hooker) {
        hook(method).intercept(hooker);
    }

    // ===== hook 辅助 =====

    /** Hook the first existing no-arg void candidate for one semantic role. */
    private void hookFirstNoArgVoid(ClassLoader cl, String[][] candidates, String role) {
        Throwable last = null;
        for (String[] candidate : candidates) {
            String clsName = candidate[0];
            String methodName = candidate[1];
            String desc = candidate[2];
            try {
                Class<?> cls = cl.loadClass(clsName);
                Method m = cls.getDeclaredMethod(methodName);
                if (m.getReturnType() != void.class || m.getParameterCount() != 0) {
                    continue;
                }
                hook(m).intercept(new BlockHooker(cls.getSimpleName() + "." + methodName));
                sHookOk++;
                sHookDetail.append("[OK] ").append(role).append(" -> ")
                        .append(clsName).append("#").append(methodName)
                        .append(" (").append(desc).append(")\n");
                return;
            } catch (Throwable e) {
                last = e;
            }
        }
        sHookFail++;
        sHookDetail.append("[FAIL] ").append(role).append(": no compatible candidate")
                .append(last != null ? " / " + last : "").append("\n");
    }

    /** ColorOS 17=wks.a(...), ColorOS 16=iyq.a(...). Same structural signature. */
    private void hookNomediaCheck(ClassLoader cl) {
        String[] classes = {
                "com.oplus.aiunit.vision.wks",
                "com.oplus.aiunit.vision.iyq"
        };
        Throwable last = null;
        for (String clsName : classes) {
            try {
                Class<?> cls = cl.loadClass(clsName);
                Method m = cls.getDeclaredMethod("a", String.class, String.class,
                        HashMap.class, HashMap.class);
                if (m.getReturnType() != boolean.class) continue;
                hook(m).intercept(new NomediaCheckHooker());
                sHookOk++;
                sHookDetail.append("[OK] nomedia-check -> ").append(clsName)
                        .append("#a(String,String,HashMap,HashMap)Z\n");
                return;
            } catch (Throwable e) {
                last = e;
            }
        }
        sHookFail++;
        sHookDetail.append("[FAIL] nomedia-check: no compatible candidate")
                .append(last != null ? " / " + last : "").append("\n");
    }

    /**
     * hook ContentResolver.query（框架类，在相册进程执行）三个重载。
     * 过滤逻辑见 MediaQueryFilter.QueryHooker；hook 失败不影响前 3 组（仅记 FAIL）。
     */
    private void hookContentResolverQuery(ClassLoader cl) {
        String clsName = "android.content.ContentResolver";
        hookQueryMethod(cl, clsName, "query",
            new Class<?>[] { Uri.class, String[].class, String.class, String[].class, String.class },
            "query(Uri,String[],String,String[],String)",
            new MediaQueryFilter.QueryHooker());
        hookQueryMethod(cl, clsName, "query",
            new Class<?>[] { Uri.class, String[].class, String.class, String[].class,
                String.class, CancellationSignal.class },
            "query(Uri,String[],String,String[],String,CancellationSignal)",
            new MediaQueryFilter.QueryHooker());
        hookQueryMethod(cl, clsName, "query",
            new Class<?>[] { Uri.class, String[].class, Bundle.class, CancellationSignal.class },
            "query(Uri,String[],Bundle,CancellationSignal)",
            new MediaQueryFilter.QueryHooker());
    }

    /** hook 任意签名方法（泛化 helper），成功记 OK / 失败记 FAIL */
    private void hookQueryMethod(ClassLoader cl, String clsName, String methodName,
                                 Class<?>[] paramTypes, String desc,
                                 XposedInterface.Hooker hooker) {
        try {
            Class<?> cls = cl.loadClass(clsName);
            Method m = cls.getDeclaredMethod(methodName, paramTypes);
            hook(m).intercept(hooker);
            sHookOk++;
            sHookDetail.append("[OK] ").append(clsName).append("#").append(methodName)
                .append(" (").append(desc).append(")\n");
        } catch (Throwable e) {
            sHookFail++;
            sHookDetail.append("[FAIL] ").append(clsName).append("#").append(methodName)
                .append(" (").append(desc).append("): ").append(e).append("\n");
            Debug.d(TAG, "hook fail: " + clsName + "#" + methodName, e);
        }
    }

    /**
     * hook Activity.onResume（框架类，相册进程所有 Activity resume 都会触发）：
     * proceed 后调 MediaQueryFilter.driveGallerySyncForce() 反射驱动相册自身 MediaSync，
     * 走相册原生 FullSyncTask 全量对账 → 加/删 .nomedia 实时反映。节流在 filter 内部。
     */
    private void hookActivityResume(ClassLoader cl) {
        try {
            Class<?> cls = cl.loadClass("android.app.Activity");
            Method m = cls.getDeclaredMethod("onResume");
            hook(m).intercept(new ResumeHooker());
            sHookOk++;
            sHookDetail.append("[OK] android.app.Activity#onResume (主动刷新)\n");
        } catch (Throwable e) {
            sHookFail++;
            sHookDetail.append("[FAIL] android.app.Activity#onResume: ").append(e).append("\n");
            Debug.d(TAG, "hook fail: Activity.onResume", e);
        }
    }

    // ===== 预索引启动 =====

    /**
     * hook 相册自建库 GalleryProvider.query（v1.4 第二通道过滤）：
     * 相册时间线/列表首帧数据源 = 自建 gallery.db 的 local_media（content://...gallery/local_media_internal），
     * 非 content://media —— 旧 ContentResolver hook 盲区 → 首帧"旧列表闪烁"。
     * 本组 hook：local_media 且投影含 _data → MODE_DATA 过滤（.nomedia 目录行剔除）；
     *           其余 gallery 查询 → 探针观察不过滤。三个标准重载都尝试。
     */
    private void hookGalleryProviderQuery(ClassLoader cl) {
        final String clsName = "com.oplus.gallery.foundation.database.provider.GalleryProvider";
        try {
            Class<?> cls = cl.loadClass(clsName);
            int matched = 0;

            // ColorOS 16 exposed three query overloads; ColorOS 17.10.6 exposes two.
            // Match by semantic shape instead of an exact overload list.
            for (Method m : cls.getDeclaredMethods()) {
                if (!"query".equals(m.getName())) continue;
                if (!android.database.Cursor.class.isAssignableFrom(m.getReturnType())) continue;

                Class<?>[] p = m.getParameterTypes();
                if (p.length < 2
                        || p[0] != android.net.Uri.class
                        || p[1] != String[].class) {
                    continue;
                }

                hook(m).intercept(new GalleryQueryHooker(
                        "GalleryProvider#" + m.getName() + "/" + p.length));
                matched++;
            }

            if (matched > 0) {
                sHookOk++;
                sHookDetail.append("[OK] GalleryProvider query family -> ")
                        .append(matched).append(" overload(s)\n");
            } else {
                sHookFail++;
                sHookDetail.append("[FAIL] GalleryProvider query family: no compatible overload\n");
            }
        } catch (Throwable e) {
            // ContentResolver URI-level filtering is the mandatory fallback on ColorOS 17,
            // so a renamed provider class no longer makes the feature unusable.
            sHookDetail.append("[OPTIONAL] GalleryProvider class hook unavailable: ")
                    .append(e).append(" (URI fallback active)\n");
        }
    }

    /**
     * 后台线程轮询 ActivityThread.currentApplication() 拿到 Application，
     * 交给 MediaQueryFilter.buildHiddenIdIndex 预扫描媒体库，建立"隐藏 _id"索引。
     * 目的：相册首帧若用不带 _data 的轻量查询（[_id]）也能被过滤 → 消除"一闪而过"。
     * 轮询最多 ~5s；拿不到 Application 则跳过（后续带 _data 查询仍会实时增量过滤）。
     */
    private void startHiddenIdIndexer(ClassLoader cl) {
        Thread t = new Thread(() -> {
            Object app = null;
            for (int i = 0; i < 100 && app == null; i++) {
                try {
                    // ⚠️ 用模块自己的 loader 加载 ActivityThread（boot classpath 类），
                    //    别用 cl（被 hook 进程 loader）——曾出现 cl 代理不到 boot 类导致
                    //    5s 轮询全失败、ID-INDEX/WATCHER 永不执行（1.1.4+ 实测缺失）。
                    ClassLoader bootish = MediaQueryFilter.class.getClassLoader();
                    if (bootish == null) bootish = cl;
                    Class<?> at = Class.forName("android.app.ActivityThread", false, bootish);
                    java.lang.reflect.Method m = at.getMethod("currentApplication");
                    app = m.invoke(null);
                } catch (Throwable ignored) {
                    // 进程启动早期 framework 未就绪，正常，继续轮询
                }
                if (app == null) {
                    try { Thread.sleep(50); } catch (InterruptedException e) { return; }
                }
            }
            if (app instanceof android.content.Context) {
                MediaQueryFilter.sAppContext = (android.content.Context) app;
                MediaQueryFilter.buildHiddenIdIndex((android.content.Context) app);
                MediaQueryFilter.startNomediaWatcher((android.content.Context) app);   // v1.6
                // v1.3.0: 启动兜底清洗——冷启动时把已存在 .nomedia 目录的 local_media
                //         残留行删掉(不重开相册也隐藏)；watcher 管后续新增。同一后台线程。
                MediaQueryFilter.purgeLocalMediaForHiddenDirs((android.content.Context) app);
                MediaQueryFilter.markGallerySyncDirty();
                MediaQueryFilter.driveGallerySyncIfNeeded();
            } else {
                // #ifdef DEBUG
                if (BuildConfig.DEBUG) {
                    Debug.d(TAG, "ID-INDEX: 未拿到 Application, 跳过预索引(仅靠实时增量)");
                }
                // #endif
            }
        }, "nomedia-id-indexer");
        t.setDaemon(true);
        t.start();
    }

    // ===== HookLogger =====

    @Override
    public void logD(String tag, String msg) {
        log(DEBUG, tag, msg);
    }

    @Override
    public void logD(String tag, String msg, Throwable tr) {
        log(DEBUG, tag, msg, tr);
    }

    // ===== restoreModuleState =====

    private void restoreModuleState() {
        sInstance = this;
        Debug.sLogger = this;
    }

    // ===== Hooker 内部类 =====
    // ⚠️ 本段所有 Debug.d 输出走「debug 渠道」：
    //   - LSPosed 框架日志（DEBUG 级, Debug.sLogger→MainHook.log(DEBUG,...)）
    //   - app 进程 logcat（tag=GalleryNomediaGuard）
    //   debug 构建（BuildConfig.DEBUG=true）才生效; release 构建自动折叠为空, 零副作用。
    // 验证方法: 装 debug 版 → LSPosed 日志过滤 GalleryNomediaGuard →
    //   应看到 ① installHooks done: 6 OK/0 FAIL（4 组 hook 注册成败, ContentResolver×3）
    //          ② 🏁 HOOK-生效[...] 第1次被调用（证明相册真的调用了被 hook 方法）
    //          ③ ID-INDEX 预索引完成（隐藏 _id 集合建立, 消除首帧一闪而过）

    /**
     * Activity.onResume 拦截器：先 proceed（不干扰相册正常生命周期），
     * 随后触发相册自身 MediaSync 对账（反射驱动 loo.a onMediaChange，替代 1.1.8 的
     * notifyChange —— notify 是模块同 uid 自通知，相册观察者 deliverSelfNotifications=false
     * 收不到，实际无效；驱动相册自身入口 selfChange=false 走原生链，10s 后 FullSyncTask
     * 全量对账 → 被模块过滤的 .nomedia 行从相册本地库删除 → UI 刷新）。
     * 后台 watcher 刚驱动过（<3s）时，resume 走 force 版不被节流吞掉。
     */
    static class ResumeHooker implements XposedInterface.Hooker {
        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            Object result = chain.proceed();
            try {
                MediaQueryFilter.driveGallerySyncOnResumeIfDirty();
            } catch (Throwable ignored) {
                // 驱动失败不影响相册生命周期
            }
            return result;
        }
    }

    /**
     * GalleryProvider.query 探针（v1.3 诊断）：proceed 后打 debug 日志，
     * 观察相册自建库查询的 uri/投影/行数（是否 local_media/gallery_media、有无 _data 列）。
     * 纯观察不过滤，防止干扰相册；release 构建日志折叠为空。
     */
    static class GalleryQueryHooker implements XposedInterface.Hooker {
        private final String name;
        private int count;
        private static int sFiltered;
        GalleryQueryHooker(String name) { this.name = name; }

        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            // 预索引/purge 线程自己的查询：直接放行，避免递归过滤(否则 purge 看不到要删的隐藏行)
            if (Boolean.TRUE.equals(MediaQueryFilter.sIndexing.get())) return chain.proceed();

            // ① 先看 uri 是否相册自建 local_media（v1.4 第二通道过滤目标）
            Object o0 = chain.getArg(0);
            boolean isLocalMedia = o0 instanceof Uri
                && MediaQueryFilter.isGalleryLocalMediaUri((Uri) o0);
            Object o1 = chain.getArg(1);
            String[] projection = (o1 instanceof String[]) ? (String[]) o1 : null;
            boolean hasData = MediaQueryFilter.hasDataColumn(projection);

            Object result = chain.proceed();

            // ② 是 local_media 且投影含 _data → 真正过滤（.nomedia 目录行剔除）
            //    注意 feedIdIndex=false：local_media._id 不是 MediaStore._id，禁止喂入 sHiddenIds
            if (isLocalMedia && hasData && result instanceof android.database.Cursor) {
                android.database.Cursor raw = (android.database.Cursor) result;
                long t0 = System.currentTimeMillis();
                int before = raw.getCount();
                MediaQueryFilter.FilteringCursor filtered =
                    new MediaQueryFilter.FilteringCursor(raw, MediaQueryFilter.FilteringCursor.MODE_DATA, false);
                int after = filtered.getCount();
                long cost = System.currentTimeMillis() - t0;
                // #ifdef DEBUG
                if (BuildConfig.DEBUG) {
                    if (filtered.hiddenCount() > 0) {
                        sFiltered++;
                        Debug.d(TAG, "GPQ-FILTER[生效] #" + (++count) + " " + name
                            + " uri=" + o0 + " 行数 " + before + "→" + after
                            + " 隐藏 " + filtered.hiddenCount() + " 例: " + filtered.hiddenSample()
                            + " (" + cost + "ms)");
                    } else if (count <= 60 || count % 200 == 0) {
                        Debug.d(TAG, "GPQ-FILTER[无隐藏] #" + (++count) + " " + name
                            + " uri=" + o0 + " 行数=" + before + " (" + cost + "ms)");
                    }
                }
                // #endif
                return filtered;
            }

            // ③ 其它 gallery 查询：纯探针日志（仅 debug），原样放行
            // #ifdef DEBUG
            if (BuildConfig.DEBUG) {
                count++;
                if (count <= 60 || count % 200 == 0) {
                    try {
                        String proj = "";
                        if (o1 instanceof String[]) {
                            String[] arr = (String[]) o1;
                            StringBuilder sb = new StringBuilder("[");
                            int max = Math.min(arr.length, 12);
                            for (int i = 0; i < max; i++) {
                                if (i > 0) sb.append(",");
                                sb.append(arr[i]);
                            }
                            if (arr.length > max) sb.append(",...").append(arr.length);
                            proj = sb.append("]").toString();
                        }
                        String rows = "?";
                        if (result instanceof android.database.Cursor) {
                            rows = String.valueOf(((android.database.Cursor) result).getCount());
                        }
                        Debug.d(TAG, "GPQ[probe] #" + count + " " + name
                            + " uri=" + o0 + " proj=" + proj + " rows=" + rows);
                    } catch (Throwable ignored) {}
                }
            }
            // #endif
            return result;
        }
    }

    /**
     * 短路 void 方法：不 proceed（方法体变空）。
     * 日志策略（折中）：
     *   第 1 次被调用 → INFO 级（正式版保留, 框架日志可见, 证明 hook 真的生效）
     *   后续每 50 次  → Debug.d（仅 debug 版, 防刷屏）
     */
    static class BlockHooker implements XposedInterface.Hooker {
        private final String name;
        private int count;
        BlockHooker(String name) { this.name = name; }

        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            count++;
            if (count == 1) {
                MainHook.info(TAG, "🏁 HOOK-生效[" + name + "] 第1次被调用 → 已短路(.nomedia 保护生效)");
            } else if (count % 50 == 1) {
                // #ifdef DEBUG
                if (BuildConfig.DEBUG) {
                    Debug.d(TAG, "HOOK[" + name + "] 已第 " + count + " 次被调用, 持续短路");
                }
                // #endif
            }
            return null; // void：不 proceed = 空实现
        }
    }

    /**
     * iyq.a(String root, String dir, HashMap scan, HashMap delete) 恒 false：
     * 让 NomediaScanner 对任何目录都判定"无 .nomedia 需处理"。
     * 日志策略：⚠️ 本方法参数含真实目录路径(root/dir)，属调试信息 →
     *          整个跟踪块用 if (BuildConfig.DEBUG) 包裹（调用点常量折叠），
     *          正式版连路径字符串都不编入 APK，零泄漏。
     */
    static class NomediaCheckHooker implements XposedInterface.Hooker {
        private static final HashSet<String> sSeenDirs = new HashSet<>();
        private static int sCount;

        @Override public Object intercept(XposedInterface.Chain chain) throws Throwable {
            // #ifdef DEBUG
            if (BuildConfig.DEBUG) {
                sCount++;
                Object root = chain.getArg(0);
                Object dir  = chain.getArg(1);
                String key = root + "|" + dir;
                if (sSeenDirs.add(key)) {
                    Debug.d(TAG, "🏁 HOOK-生效[NomediaCheck iyq.a] root=" + root + " dir=" + dir
                        + " → 已强制 false(不处理该目录 .nomedia)");
                } else if (sCount % 100 == 0) {
                    Debug.d(TAG, "NOMEDIA-CHECK 累计第 " + sCount + " 次, 最新 dir=" + dir);
                }
            }
            // #endif
            return Boolean.FALSE;
        }
    }
}
