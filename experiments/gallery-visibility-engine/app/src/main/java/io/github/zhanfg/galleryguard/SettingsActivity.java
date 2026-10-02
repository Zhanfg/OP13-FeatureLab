package io.github.zhanfg.galleryguard;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.materialswitch.MaterialSwitch;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

import io.github.libxposed.service.XposedService;
import io.github.libxposed.service.XposedServiceHelper;

public final class SettingsActivity extends AppCompatActivity implements XposedServiceHelper.OnServiceListener {
    private static final int REQ_TREE = 1001;

    private GalleryGuardApp app;
    private XposedService service;
    private LinearLayout list;
    private TextView status;
    private MaterialButton addButton;
    private MaterialSwitch strictSwitch;
    private boolean bindingUi;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        app = (GalleryGuardApp) getApplication();
        buildUi();
        app.addServiceListener(this, true);
    }

    @Override protected void onDestroy() {
        app.removeServiceListener(this);
        super.onDestroy();
    }

    private void buildUi() {
        int pad = dp(20);

        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, pad);
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = new TextView(this);
        title.setText("Gallery Visibility Engine");
        title.setTextSize(26);
        title.setPadding(0, 0, 0, dp(8));
        root.addView(title);

        status = new TextView(this);
        status.setText("正在连接 LSPosed…");
        root.addView(status);

        strictSwitch = new MaterialSwitch(this);
        strictSwitch.setText("默认隔离第三方目录");
        strictSwitch.setChecked(true);
        strictSwitch.setEnabled(false);
        strictSwitch.setOnCheckedChangeListener((button, checked) -> {
            if (bindingUi) return;
            SharedPreferences p = prefs();
            if (p == null) return;
            p.edit()
                    .putBoolean(GuardPrefs.KEY_STRICT_ISOLATION, checked)
                    .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                            p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                    .apply();
        });
        root.addView(strictSwitch);

        TextView hint = new TextView(this);
        hint.setText("相机、截图与 ColorOS 自身常用目录默认可见；其他目录默认不可见。下面只列你主动透传的第三方目录。");
        hint.setPadding(0, dp(6), 0, dp(12));
        root.addView(hint);

        addButton = new MaterialButton(this);
        addButton.setText("添加透传目录");
        addButton.setEnabled(false);
        addButton.setOnClickListener(v -> openTreePicker());
        root.addView(addButton);

        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        list.setPadding(0, dp(12), 0, 0);
        root.addView(list, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(scroll);
    }

    private void openTreePicker() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        startActivityForResult(i, REQ_TREE);
    }

    @Override protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQ_TREE || resultCode != Activity.RESULT_OK || data == null) return;

        Uri uri = data.getData();
        if (uri == null) return;

        try {
            int flags = data.getFlags()
                    & (Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            getContentResolver().takePersistableUriPermission(uri, flags);
        } catch (Throwable ignored) {}

        String path = PathCodec.fromTreeUri(uri);
        if (path == null) {
            Toast.makeText(this, "该目录无法映射为共享存储路径", Toast.LENGTH_LONG).show();
            return;
        }

        SharedPreferences p = prefs();
        if (p == null) return;

        Set<String> next = new HashSet<>(
                p.getStringSet(GuardPrefs.KEY_PASSTHROUGH_DIRS, Collections.emptySet()));
        next.add(path);
        p.edit()
                .putStringSet(GuardPrefs.KEY_PASSTHROUGH_DIRS, next)
                .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                        p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                .apply();

        PassthroughScanner.scanAsync(this, path);
        render();
    }

    private void removePath(String path) {
        SharedPreferences p = prefs();
        if (p == null) return;

        Set<String> next = new HashSet<>(
                p.getStringSet(GuardPrefs.KEY_PASSTHROUGH_DIRS, Collections.emptySet()));
        next.remove(path);
        p.edit()
                .putStringSet(GuardPrefs.KEY_PASSTHROUGH_DIRS, next)
                .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                        p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                .apply();

        render();
    }

    private SharedPreferences prefs() {
        return service == null ? null : service.getRemotePreferences(GuardPrefs.GROUP);
    }

    private void render() {
        SharedPreferences p = prefs();
        if (p == null) {
            status.setText("LSPosed 服务未连接；请确认模块由支持 API 101/102 的框架管理。");
            addButton.setEnabled(false);
            strictSwitch.setEnabled(false);
            list.removeAllViews();
            return;
        }

        status.setText("LSPosed 已连接 · 配置可热更新");
        addButton.setEnabled(true);
        strictSwitch.setEnabled(true);

        bindingUi = true;
        strictSwitch.setChecked(p.getBoolean(GuardPrefs.KEY_STRICT_ISOLATION, true));
        bindingUi = false;

        ArrayList<String> paths = new ArrayList<>(
                p.getStringSet(GuardPrefs.KEY_PASSTHROUGH_DIRS, Collections.emptySet()));
        Collections.sort(paths);

        list.removeAllViews();
        if (paths.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("尚未透传第三方目录");
            list.addView(empty);
            return;
        }

        for (String path : paths) {
            LinearLayout row = new LinearLayout(this);
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(0, dp(5), 0, dp(5));

            TextView text = new TextView(this);
            text.setText(path);
            text.setTextSize(14);
            row.addView(text, new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

            MaterialButton remove = new MaterialButton(this);
            remove.setText("移除");
            remove.setOnClickListener(v -> removePath(path));
            row.addView(remove);

            list.addView(row);
        }
    }

    @Override public void onServiceBind(XposedService service) {
        this.service = service;
        runOnUiThread(this::render);
    }

    @Override public void onServiceDied(XposedService service) {
        if (this.service == service) this.service = null;
        runOnUiThread(this::render);
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
