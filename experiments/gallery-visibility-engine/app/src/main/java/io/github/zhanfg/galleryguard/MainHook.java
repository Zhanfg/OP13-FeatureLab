package io.github.zhanfg.galleryguard;

import static android.util.Log.DEBUG;
import static android.util.Log.INFO;

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
        try {
            VisibilityPolicy.bind(getRemotePreferences(GuardPrefs.GROUP),
                    MediaQueryFilter::onVisibilityPolicyChanged);
            log(INFO, TAG, "visibility policy bound, api102 module loaded");
        } catch (Throwable t) {
            VisibilityPolicy.bind(null, null);
            log(INFO, TAG, "remote prefs unavailable, using safe defaults: " + t);
        }
    }

    @Override
    public void onPackageReady(XposedModuleInterface.PackageReadyParam param) {
        ClassLoader cl = param.getClassLoader();
        mAppClassLoader = cl;
        // v1.1.9: 注入相册 App ClassLoader，供反射驱动相册自身 MediaSync(loo) 用
        MediaQueryFilter.sAppClassLoader = cl;
        log(INFO, TAG, "[pkg] onPackageReady, classLoader=" + (cl != null ? "non-null" : "NULL!"));
        installHooks(cl);
        startHiddenIdIndexer(cl);
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
        installHooks(cl);
        restoreModuleState();
        log(INFO, TAG, "hot reloaded, hooks reinstalled");
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

    // ===== installHooks =====

    private void installHooks(ClassLoader cl) {
        sHookDetail = new StringBuilder();
        sHookOk = sHookFail = 0;

        // ① 主入口：MediaDBSyncDM#j() —— startNomediaCheckTask（不启动 NomediaScanner）
        hookNoArgVoid(cl,
            "com.oplus.gallery.framework.abilities.mediadbsync.MediaDBSyncDM",
            "j", "entry(j=startNomediaCheckTask)", new BlockHooker("MediaDBSyncDM.j"));

        // ② 兜底：NomediaScanner 主任务 Runnable#run()（即使被其它入口触发也空转）
        hookNoArgVoid(cl,
            "com.oplus.aiunit.vision.gyq",
            "run", "task(gyq.run)", new BlockHooker("gyq.run"));

        // ③ 兜底：NomediaScanner 判定 iyq#a(String,String,HashMap,HashMap) —— 恒 false，
        //        让"目录含 .nomedia"判定永不成立 → delete/scan 集合为空 → .nomedia 永不被改名/删除
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

        log(INFO, TAG, "installHooks done: " + sHookOk + " OK / " + sHookFail + " FAIL / \n" + sHookDetail);
        sHookOk = sHookFail = 0;
        sHookDetail.setLength(0);
    }

    // ===== hook 辅助 =====

    /** hook 无参 void 方法：getDeclaredMethod(cls, method) → 拦截直接短路（不 proceed） */
    private void hookNoArgVoid(ClassLoader cl, String clsName, String methodName,
                               String desc, XposedInterface.Hooker hooker) {
        try {
            Class<?> cls = cl.loadClass(clsName);
            Method m = cls.getDeclaredMethod(methodName);
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

    /** hook NomediaScanner 判定方法 a：签名 a(String,String,HashMap,HashMap)Z，恒返 false */
    private void hookNomediaCheck(ClassLoader cl) {
        try {
            Class<?> cls = cl.loadClass("com.oplus.aiunit.vision.iyq");
            Method m = cls.getDeclaredMethod("a", String.class, String.class,
                HashMap.class, HashMap.class);
            hook(m).intercept(new NomediaCheckHooker());
            sHookOk++;
            sHookDetail.append("[OK] com.oplus.aiunit.vision.iyq#a(String,String,HashMap,HashMap) (nomediaCheck)\n");
        } catch (Throwable e) {
            sHookFail++;
            sHookDetail.append("[FAIL] com.oplus.aiunit.vision.iyq#a(...): ").append(e).append("\n");
            Debug.d(TAG, "hook fail: iyq.a", e);
        }
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
        String clsName = "com.oplus.gallery.foundation.database.provider.GalleryProvider";
        hookQueryProbe(cl, clsName, "query",
            new Class<?>[] { Uri.class, String[].class, String.class, String[].class, String.class },
            "GalleryProvider#query(Uri,String[],String,String[],String)");
        hookQueryProbe(cl, clsName, "query",
            new Class<?>[] { Uri.class, String[].class, String.class, String[].class,
                String.class, CancellationSignal.class },
            "GalleryProvider#query(Uri,String[],String,String[],String,CancellationSignal)");
        hookQueryProbe(cl, clsName, "query",
            new Class<?>[] { Uri.class, String[].class, Bundle.class, CancellationSignal.class },
            "GalleryProvider#query(Uri,String[],Bundle,CancellationSignal)");
    }

    /** 通用 query 探针/过滤注册：成功记 OK / 失败记 FAIL */
    private void hookQueryProbe(ClassLoader cl, String clsName, String methodName,
                                Class<?>[] paramTypes, String desc) {
        try {
            Class<?> cls = cl.loadClass(clsName);
            Method m = cls.getDeclaredMethod(methodName, paramTypes);
            hook(m).intercept(new GalleryQueryHooker(desc));
            sHookOk++;
            sHookDetail.append("[OK] ").append(desc).append(" (v1.4 filter+probe)\n");
        } catch (Throwable e) {
            sHookFail++;
            sHookDetail.append("[FAIL] ").append(desc).append(" (v1.4 filter+probe): ").append(e).append("\n");
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
                MediaQueryFilter.driveGallerySyncForce();
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
