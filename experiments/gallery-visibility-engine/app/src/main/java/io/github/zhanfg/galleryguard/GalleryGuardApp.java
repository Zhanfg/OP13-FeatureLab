package io.github.zhanfg.galleryguard;

import android.app.Application;

import com.google.android.material.color.DynamicColors;

import java.util.Set;
import java.util.concurrent.CopyOnWriteArraySet;

import io.github.libxposed.service.XposedService;
import io.github.libxposed.service.XposedServiceHelper;

public final class GalleryGuardApp extends Application implements XposedServiceHelper.OnServiceListener {
    private final Set<XposedServiceHelper.OnServiceListener> listeners = new CopyOnWriteArraySet<>();
    private volatile XposedService service;

    @Override public void onCreate() {
        super.onCreate();
        DynamicColors.applyToActivitiesIfAvailable(this);
        XposedServiceHelper.registerListener(this);
    }

    public XposedService service() { return service; }

    public void addServiceListener(XposedServiceHelper.OnServiceListener listener, boolean notify) {
        listeners.add(listener);
        XposedService s = service;
        if (notify && s != null) listener.onServiceBind(s);
    }

    public void removeServiceListener(XposedServiceHelper.OnServiceListener listener) {
        listeners.remove(listener);
    }

    @Override public void onServiceBind(XposedService service) {
        this.service = service;
        for (XposedServiceHelper.OnServiceListener l : listeners) l.onServiceBind(service);
    }

    @Override public void onServiceDied(XposedService service) {
        if (this.service == service) this.service = null;
        for (XposedServiceHelper.OnServiceListener l : listeners) l.onServiceDied(service);
    }
}
