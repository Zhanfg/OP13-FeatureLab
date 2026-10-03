package io.github.zhanfg.galleryguard;

import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.checkbox.MaterialCheckBox;
import com.google.android.material.textfield.TextInputEditText;
import com.google.android.material.textfield.TextInputLayout;

import java.text.Collator;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

import io.github.libxposed.service.XposedService;
import io.github.libxposed.service.XposedServiceHelper;

/**
 * Searchable multi-select app picker.
 *
 * The user chooses apps, while AppMediaRegistry converts package names into media roots.
 * Default communication apps are checked on first run without forcing the user to scan hundreds
 * of entries one by one.
 */
public final class AppSelectionActivity extends AppCompatActivity
        implements XposedServiceHelper.OnServiceListener {

    private GalleryGuardApp app;
    private XposedService service;
    private TextView status;
    private RecyclerView recycler;
    private AppAdapter adapter;
    private TextInputEditText search;
    private final ArrayList<AppItem> allApps = new ArrayList<>();

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        app = (GalleryGuardApp) getApplication();
        buildUi();
        loadApps();
        app.addServiceListener(this, true);
    }

    @Override protected void onDestroy() {
        app.removeServiceListener(this);
        super.onDestroy();
    }

    private void buildUi() {
        int pad = dp(18);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(pad, pad, pad, dp(8));

        TextView title = new TextView(this);
        title.setText("选择应用透传");
        title.setTextSize(25);
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("默认启用常见通讯软件。可搜索并多选任意应用；每次勾选会自动映射它的媒体目录。");
        subtitle.setPadding(0, dp(4), 0, dp(10));
        root.addView(subtitle);

        status = new TextView(this);
        status.setText("正在连接 LSPosed…");
        status.setPadding(0, 0, 0, dp(8));
        root.addView(status);

        TextInputLayout searchBox = new TextInputLayout(this);
        searchBox.setHint("搜索应用或包名");
        search = new TextInputEditText(this);
        search.setSingleLine(true);
        searchBox.addView(search, new TextInputLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(searchBox);

        MaterialButton reset = new MaterialButton(this);
        reset.setText("恢复默认通讯软件");
        reset.setOnClickListener(v -> resetDefaults());
        root.addView(reset);

        recycler = new RecyclerView(this);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        recycler.setItemAnimator(null);
        adapter = new AppAdapter();
        recycler.setAdapter(adapter);
        root.addView(recycler, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        search.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence s, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence s, int start, int before, int count) {
                adapter.filter(s == null ? "" : s.toString());
            }
            @Override public void afterTextChanged(Editable s) {}
        });

        setContentView(root);
    }

    private void loadApps() {
        new Thread(() -> {
            PackageManager pm = getPackageManager();
            Intent launcher = new Intent(Intent.ACTION_MAIN);
            launcher.addCategory(Intent.CATEGORY_LAUNCHER);

            List<ResolveInfo> infos;
            try {
                infos = pm.queryIntentActivities(launcher, 0);
            } catch (Throwable t) {
                infos = Collections.emptyList();
            }

            Map<String, AppItem> unique = new HashMap<>();
            for (ResolveInfo ri : infos) {
                try {
                    String pkg = ri.activityInfo.packageName;
                    if (getPackageName().equals(pkg) || unique.containsKey(pkg)) continue;

                    CharSequence l = ri.loadLabel(pm);
                    String label = l == null ? pkg : l.toString();
                    Drawable icon = ri.loadIcon(pm);
                    unique.put(pkg, new AppItem(pkg, label, icon));
                } catch (Throwable ignored) {}
            }

            ArrayList<AppItem> result = new ArrayList<>(unique.values());
            Collator collator = Collator.getInstance(Locale.getDefault());
            result.sort((a, b) -> {
                boolean ad = AppMediaRegistry.isDefaultCommunicationPackage(a.packageName);
                boolean bd = AppMediaRegistry.isDefaultCommunicationPackage(b.packageName);
                if (ad != bd) return ad ? -1 : 1;
                int c = collator.compare(a.label, b.label);
                return c != 0 ? c : a.packageName.compareTo(b.packageName);
            });

            runOnUiThread(() -> {
                allApps.clear();
                allApps.addAll(result);
                adapter.filter(search.getText() == null ? "" : search.getText().toString());
            });
        }, "gallery-app-enumerator").start();
    }

    private SharedPreferences prefs() {
        return service == null ? null : service.getRemotePreferences(GuardPrefs.GROUP);
    }

    private Set<String> selectedPackages() {
        SharedPreferences p = prefs();
        if (p == null) return Collections.emptySet();

        if (!p.contains(GuardPrefs.KEY_PASSTHROUGH_APPS)) {
            return AppMediaRegistry.defaultCommunicationPackages();
        }

        Set<String> saved = p.getStringSet(
                GuardPrefs.KEY_PASSTHROUGH_APPS, Collections.emptySet());
        return saved == null ? Collections.emptySet() : new HashSet<>(saved);
    }

    private void setSelected(String packageName, boolean selected) {
        SharedPreferences p = prefs();
        if (p == null) {
            Toast.makeText(this, "LSPosed 服务尚未连接", Toast.LENGTH_SHORT).show();
            return;
        }

        Set<String> next = new HashSet<>(selectedPackages());
        if (selected) {
            next.add(packageName);
        } else {
            next.remove(packageName);
        }

        p.edit()
                .putStringSet(GuardPrefs.KEY_PASSTHROUGH_APPS, next)
                .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                        p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                .apply();

        if (selected) {
            for (String root : AppMediaRegistry.rootsForPackage(packageName)) {
                PassthroughScanner.scanAsync(this, root);
            }
        }

        adapter.notifyDataSetChanged();
    }

    private void resetDefaults() {
        SharedPreferences p = prefs();
        if (p == null) return;

        Set<String> defaults = AppMediaRegistry.defaultCommunicationPackages();
        p.edit()
                .putStringSet(GuardPrefs.KEY_PASSTHROUGH_APPS, defaults)
                .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                        p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                .apply();

        for (String pkg : defaults) {
            for (String root : AppMediaRegistry.rootsForPackage(pkg)) {
                PassthroughScanner.scanAsync(this, root);
            }
        }
        adapter.notifyDataSetChanged();
    }

    @Override public void onServiceBind(XposedService service) {
        this.service = service;
        runOnUiThread(() -> {
            status.setText("已连接 · 勾选后立即热更新");
            adapter.notifyDataSetChanged();
        });
    }

    @Override public void onServiceDied(XposedService service) {
        if (this.service == service) this.service = null;
        runOnUiThread(() -> {
            status.setText("LSPosed 服务已断开");
            adapter.notifyDataSetChanged();
        });
    }

    private final class AppAdapter extends RecyclerView.Adapter<AppViewHolder> {
        private final ArrayList<AppItem> visible = new ArrayList<>();

        void filter(String query) {
            String q = query == null ? "" : query.trim().toLowerCase(Locale.ROOT);
            visible.clear();

            if (q.isEmpty()) {
                visible.addAll(allApps);
            } else {
                for (AppItem item : allApps) {
                    if (item.label.toLowerCase(Locale.ROOT).contains(q)
                            || item.packageName.toLowerCase(Locale.ROOT).contains(q)) {
                        visible.add(item);
                    }
                }
            }
            notifyDataSetChanged();
        }

        @NonNull @Override public AppViewHolder onCreateViewHolder(
                @NonNull ViewGroup parent, int viewType) {
            LinearLayout row = new LinearLayout(parent.getContext());
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setPadding(dp(4), dp(8), dp(4), dp(8));

            ImageView icon = new ImageView(parent.getContext());
            row.addView(icon, new LinearLayout.LayoutParams(dp(44), dp(44)));

            LinearLayout textBox = new LinearLayout(parent.getContext());
            textBox.setOrientation(LinearLayout.VERTICAL);
            textBox.setPadding(dp(12), 0, dp(8), 0);

            TextView label = new TextView(parent.getContext());
            label.setTextSize(16);
            textBox.addView(label);

            TextView pkg = new TextView(parent.getContext());
            pkg.setTextSize(12);
            textBox.addView(pkg);

            row.addView(textBox, new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

            MaterialCheckBox check = new MaterialCheckBox(parent.getContext());
            row.addView(check);

            return new AppViewHolder(row, icon, label, pkg, check);
        }

        @Override public void onBindViewHolder(@NonNull AppViewHolder h, int position) {
            AppItem item = visible.get(position);
            Set<String> selected = selectedPackages();

            h.icon.setImageDrawable(item.icon);
            h.label.setText(item.label
                    + (AppMediaRegistry.isDefaultCommunicationPackage(item.packageName)
                    ? "  ·  默认通讯" : ""));
            h.pkg.setText(item.packageName);

            h.check.setOnCheckedChangeListener(null);
            h.check.setChecked(selected.contains(item.packageName));
            h.check.setEnabled(service != null);

            h.check.setOnCheckedChangeListener(
                    (button, checked) -> setSelected(item.packageName, checked));
            h.itemView.setOnClickListener(v -> {
                if (service != null) h.check.toggle();
            });
        }

        @Override public int getItemCount() {
            return visible.size();
        }
    }

    private static final class AppViewHolder extends RecyclerView.ViewHolder {
        final ImageView icon;
        final TextView label;
        final TextView pkg;
        final MaterialCheckBox check;

        AppViewHolder(View itemView, ImageView icon, TextView label,
                      TextView pkg, MaterialCheckBox check) {
            super(itemView);
            this.icon = icon;
            this.label = label;
            this.pkg = pkg;
            this.check = check;
        }
    }

    private static final class AppItem {
        final String packageName;
        final String label;
        final Drawable icon;

        AppItem(String packageName, String label, Drawable icon) {
            this.packageName = packageName;
            this.label = label;
            this.icon = icon;
        }
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }
}
