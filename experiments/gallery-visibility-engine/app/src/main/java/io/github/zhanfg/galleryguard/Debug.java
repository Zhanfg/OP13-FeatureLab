package io.github.zhanfg.galleryguard;

/**
 * D 级调试日志：双通道（框架日志 + logcat）。
 * <p>
 * release 构建下 BuildConfig.DEBUG=false → javac 常量折叠, d() 方法体为空 → 正式版零日志副作用。
 */
public class Debug {

    /** hook 进程由 MainHook 注入 */
    public static HookLogger sLogger;

    public static void d(String tag, String msg) {
        if (BuildConfig.DEBUG) {
            if (sLogger != null) sLogger.logD(tag, msg);
            android.util.Log.i(tag, msg);
        }
    }

    public static void d(String tag, String msg, Throwable tr) {
        if (BuildConfig.DEBUG) {
            if (sLogger != null) sLogger.logD(tag, msg, tr);
            android.util.Log.i(tag, msg, tr);
        }
    }
}
