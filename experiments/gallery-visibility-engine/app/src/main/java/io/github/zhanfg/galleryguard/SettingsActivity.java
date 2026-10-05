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

public final class SettingsActivity extends AppCompatActivity
        implements XposedServiceHelper.OnServiceListener {

    private static final int REQ_TREE = 1001;

    private GalleryGuardApp app;
    private XposedService service;
    private LinearLayout folderList;
    private TextView status;
    private MaterialButton folderButton;
    private MaterialButton appButton;
    private MaterialSwitch strictSwitch;
    private MaterialSwitch pickerAccelSwitch;
    private boolean bindingUi;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        app = (GalleryGuardApp) getApplication();
        buildUi();
        app.addServiceListener(this, true);
    }

    @Override protected void onResume() {
        super.onResume();
        render();
    }

    @Override protected void onDestroy() {
        app.removeServiceListener(this);
        super.onDestroy();
    }

    private void buildUi() {
        ScrollView scroll = new ScrollView(this);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(root, new ScrollView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView title = new TextView(this);
        title.setText("Gallery Visibility Engine");
        title.setTextSize(26);
        title.setPadding(0, 0, 0, dp(8));
        root.addView(title);

        status = new TextView(this);
        status.setText("正在连接 LSPosed…");
        status.setPadding(0, 0, 0, dp(8));
        root.addView(status);

        pickerAccelSwitch = new MaterialSwitch(this);
        pickerAccelSwitch.setText("媒体选择器加速");
        pickerAccelSwitch.setChecked(true);
        pickerAccelSwitch.setEnabled(false);
        pickerAccelSwitch.setOnCheckedChangeListener((button, checked) -> {
            if (bindingUi) return;
            SharedPreferences p = prefs();
            if (p == null) return;
            p.edit().putBoolean(GuardPrefs.KEY_PICKER_ACCEL, checked).apply();
        });
        root.addView(pickerAccelSwitch);

        TextView pickerHint = new TextView(this);
        pickerHint.setText("Android 17 使用系统原生媒体选择器路径；模块不再额外缓存、预取或拦截刷新。");
        pickerHint.setPadding(0, 0, 0, dp(12));
        root.addView(pickerHint);

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

        TextView appTitle = new TextView(this);
        appTitle.setText("应用透传");
        appTitle.setTextSize(19);
        appTitle.setPadding(0, dp(14), 0, dp(4));
        root.addView(appTitle);

        TextView appHint = new TextView(this);
        appHint.setText("选择需要透传媒体的应用；支持搜索和多选。");
        appHint.setPadding(0, 0, 0, dp(8));
        root.addView(appHint);

        appButton = new MaterialButton(this);
        appButton.setText("选择应用透传");
        appButton.setEnabled(false);
        appButton.setOnClickListener(v ->
                startActivity(new Intent(this, AppSelectionActivity.class)));
        root.addView(appButton);

        TextView folderTitle = new TextView(this);
        folderTitle.setText("文件夹透传");
        folderTitle.setTextSize(19);
        folderTitle.setPadding(0, dp(16), 0, dp(4));
        root.addView(folderTitle);

        TextView folderHint = new TextView(this);
        folderHint.setText("保留传统目录选择，适合应用路径特殊、历史迁移目录或你自己整理的媒体目录。");
        folderHint.setPadding(0, 0, 0, dp(8));
        root.addView(folderHint);

        folderButton = new MaterialButton(this);
        folderButton.setText("添加透传文件夹");
        folderButton.setEnabled(false);
        folderButton.setOnClickListener(v -> openTreePicker());
        root.addView(folderButton);

        folderList = new LinearLayout(this);
        folderList.setOrientation(LinearLayout.VERTICAL);
        folderList.setPadding(0, dp(10), 0, 0);
        root.addView(folderList, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(scroll);
        EdgeToEdgeInsets.apply(this, root, 20, 12, 16);
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
                    & (Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
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
        if (status == null) return;

        SharedPreferences p = prefs();
        if (p == null) {
            status.setText("LSPosed 服务未连接；请确认模块由支持 API 101/102 的框架管理。");
            folderButton.setEnabled(false);
            appButton.setEnabled(false);
            strictSwitch.setEnabled(false);
            pickerAccelSwitch.setEnabled(false);
            folderList.removeAllViews();
            return;
        }

        status.setText("LSPosed 已连接 · 配置可热更新");
        folderButton.setEnabled(true);
        appButton.setEnabled(true);
        strictSwitch.setEnabled(true);
        pickerAccelSwitch.setEnabled(true);

        bindingUi = true;
        strictSwitch.setChecked(p.getBoolean(GuardPrefs.KEY_STRICT_ISOLATION, true));
        pickerAccelSwitch.setChecked(p.getBoolean(GuardPrefs.KEY_PICKER_ACCEL, true));
        bindingUi = false;

        ArrayList<String> paths = new ArrayList<>(
                p.getStringSet(GuardPrefs.KEY_PASSTHROUGH_DIRS, Collections.emptySet()));
        Collections.sort(paths);

        folderList.removeAllViews();
        if (paths.isEmpty()) {
            TextView empty = new TextView(this);
            empty.setText("没有额外文件夹透传；应用透传仍会正常生效。");
            folderList.addView(empty);
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

            folderList.addView(row);
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
