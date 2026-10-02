package io.github.zhanfg.galleryguard;

/**
 * 框架日志桥接口（进程安全）。
 * <p>
 * MainHook 实现它并在 onModuleLoaded/restoreModuleState 通过 Debug.sLogger 注入 this；
 * Debug.d() 通过它同时打框架日志 + logcat。
 */
public interface HookLogger {
    void logD(String tag, String msg);
    void logD(String tag, String msg, Throwable tr);
}
