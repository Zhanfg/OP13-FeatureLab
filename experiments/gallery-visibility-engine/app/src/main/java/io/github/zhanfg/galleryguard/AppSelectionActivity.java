package io.github.zhanfg.galleryguard;

import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.drawable.Drawable;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextUtils;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.recyclerview.widget.LinearLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.google.android.material.button.MaterialButton;
import com.google.android.material.card.MaterialCardView;
import com.google.android.material.checkbox.MaterialCheckBox;
import com.google.android.material.color.MaterialColors;
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
 * Visual layout follows a Material 3 Expressive-style container hierarchy:
 * page grid -> control surface -> app surface cards. Selection state is cached locally so
 * RecyclerView binding never performs cross-process RemotePreferences reads.
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
    private final HashSet<String> selectedPackages = new HashSet<>();
    private final Collator collator = Collator.getInstance(Locale.getDefault());

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        app = (GalleryGuardApp) getApplication();
        buildUi();
        loadApps();
        app.addServiceListener(this, true);
    }

    @Override protected void onResume() {
        super.onResume();
        if (service != null) {
            reloadSelectionFromPrefs();
            if (adapter != null) adapter.filter(currentQuery());
        }
    }

    @Override protected void onDestroy() {
        app.removeServiceListener(this);
        super.onDestroy();
    }

    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);

        TextView title = new TextView(this);
        title.setText("选择应用透传");
        title.setTextSize(25);
        root.addView(title);

        TextView subtitle = new TextView(this);
        subtitle.setText("可搜索并多选任意应用；已选应用会自动置顶。");
        subtitle.setPadding(0, dp(4), 0, dp(10));
        root.addView(subtitle);

        status = new TextView(this);
        status.setText("正在连接 LSPosed…");
        status.setPadding(0, 0, 0, dp(10));
        root.addView(status);

        MaterialCardView controlsCard = new MaterialCardView(this);
        controlsCard.setRadius(dp(28));
        controlsCard.setCardElevation(0f);
        controlsCard.setStrokeWidth(0);
        controlsCard.setCardBackgroundColor(MaterialColors.getColor(
                controlsCard, com.google.android.material.R.attr.colorSurfaceContainer));
        LinearLayout.LayoutParams controlsLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        controlsLp.bottomMargin = dp(10);
        root.addView(controlsCard, controlsLp);

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.VERTICAL);
        controls.setPadding(dp(14), dp(14), dp(14), dp(14));
        controlsCard.addView(controls, new MaterialCardView.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        TextInputLayout searchBox = new TextInputLayout(this);
        searchBox.setHint("搜索应用或包名");
        searchBox.setBoxBackgroundMode(TextInputLayout.BOX_BACKGROUND_FILLED);
        searchBox.setBoxCornerRadii(dp(20), dp(20), dp(20), dp(20));
        search = new TextInputEditText(this);
        search.setSingleLine(true);
        searchBox.addView(search, new TextInputLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        controls.addView(searchBox, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        MaterialButton reset = new MaterialButton(this);
        reset.setText("恢复初始勾选");
        reset.setCornerRadius(dp(22));
        LinearLayout.LayoutParams resetLp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(52));
        resetLp.topMargin = dp(10);
        controls.addView(reset, resetLp);
        reset.setOnClickListener(v -> resetDefaults());

        recycler = new RecyclerView(this);
        recycler.setLayoutManager(new LinearLayoutManager(this));
        recycler.setItemAnimator(null);
        recycler.setClipToPadding(false);
        recycler.setPadding(0, 0, 0, dp(24));
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
        EdgeToEdgeInsets.apply(this, root, 20, 12, 12);
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
            result.sort(this::compareAlphabetically);

            runOnUiThread(() -> {
                allApps.clear();
                allApps.addAll(result);
                adapter.filter(currentQuery());
            });
        }, "gallery-app-enumerator").start();
    }

    private SharedPreferences prefs() {
        return service == null ? null : service.getRemotePreferences(GuardPrefs.GROUP);
    }

    private void reloadSelectionFromPrefs() {
        SharedPreferences p = prefs();
        if (p == null) return;

        Set<String> source;
        if (!p.contains(GuardPrefs.KEY_PASSTHROUGH_APPS)) {
            source = AppMediaRegistry.defaultCommunicationPackages();
        } else {
            Set<String> saved = p.getStringSet(
                    GuardPrefs.KEY_PASSTHROUGH_APPS, Collections.emptySet());
            source = saved == null ? Collections.emptySet() : saved;
        }

        selectedPackages.clear();
        selectedPackages.addAll(source);
        updateStatus();
    }

    private void setSelected(String packageName, boolean selected) {
        SharedPreferences p = prefs();
        if (p == null) {
            Toast.makeText(this, "LSPosed 服务尚未连接", Toast.LENGTH_SHORT).show();
            return;
        }

        if (selected) {
            selectedPackages.add(packageName);
        } else {
            selectedPackages.remove(packageName);
        }

        p.edit()
                .putStringSet(GuardPrefs.KEY_PASSTHROUGH_APPS,
                        new HashSet<>(selectedPackages))
                .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                        p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                .apply();

        updateStatus();
        adapter.filter(currentQuery());
    }

    private void resetDefaults() {
        SharedPreferences p = prefs();
        if (p == null) return;

        selectedPackages.clear();
        selectedPackages.addAll(AppMediaRegistry.defaultCommunicationPackages());

        p.edit()
                .putStringSet(GuardPrefs.KEY_PASSTHROUGH_APPS,
                        new HashSet<>(selectedPackages))
                .putInt(GuardPrefs.KEY_POLICY_GENERATION,
                        p.getInt(GuardPrefs.KEY_POLICY_GENERATION, 0) + 1)
                .apply();

        updateStatus();
        adapter.filter(currentQuery());
    }

    private String currentQuery() {
        return search == null || search.getText() == null ? "" : search.getText().toString();
    }

    private void updateStatus() {
        if (status == null) return;
        if (service == null) {
            status.setText("LSPosed 服务已断开");
        } else {
            status.setText("已连接 · 已选择 " + selectedPackages.size() + " 个应用");
        }
    }

    private int compareAlphabetically(AppItem a, AppItem b) {
        int c = collator.compare(a.label, b.label);
        return c != 0 ? c : a.packageName.compareTo(b.packageName);
    }

    private int compareForDisplay(AppItem a, AppItem b) {
        boolean aSelected = selectedPackages.contains(a.packageName);
        boolean bSelected = selectedPackages.contains(b.packageName);
        if (aSelected != bSelected) return aSelected ? -1 : 1;
        return compareAlphabetically(a, b);
    }

    @Override public void onServiceBind(XposedService service) {
        this.service = service;
        runOnUiThread(() -> {
            reloadSelectionFromPrefs();
            adapter.filter(currentQuery());
        });
    }

    @Override public void onServiceDied(XposedService service) {
        if (this.service == service) this.service = null;
        runOnUiThread(this::updateStatus);
    }

    private final class AppAdapter extends RecyclerView.Adapter<AppViewHolder> {
        private final ArrayList<AppItem> visible = new ArrayList<>();

        void filter(String query) {
            String q = query == null ? "" : query.trim().toLowerCase(Locale.ROOT);
            visible.clear();

            for (AppItem item : allApps) {
                if (q.isEmpty()
                        || item.label.toLowerCase(Locale.ROOT).contains(q)
                        || item.packageName.toLowerCase(Locale.ROOT).contains(q)) {
                    visible.add(item);
                }
            }

            visible.sort(AppSelectionActivity.this::compareForDisplay);
            notifyDataSetChanged();
        }

        @NonNull @Override public AppViewHolder onCreateViewHolder(
                @NonNull ViewGroup parent, int viewType) {

            MaterialCardView card = new MaterialCardView(parent.getContext());
            card.setRadius(dp(24));
            card.setCardElevation(0f);
            card.setClickable(true);
            card.setFocusable(true);

            RecyclerView.LayoutParams cardLp = new RecyclerView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT);
            cardLp.topMargin = dp(4);
            cardLp.bottomMargin = dp(4);
            card.setLayoutParams(cardLp);

            LinearLayout row = new LinearLayout(parent.getContext());
            row.setOrientation(LinearLayout.HORIZONTAL);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.setMinimumHeight(dp(76));
            row.setPadding(dp(14), dp(10), dp(10), dp(10));
            card.addView(row, new MaterialCardView.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT));

            ImageView icon = new ImageView(parent.getContext());
            LinearLayout.LayoutParams iconLp = new LinearLayout.LayoutParams(dp(48), dp(48));
            row.addView(icon, iconLp);

            LinearLayout textBox = new LinearLayout(parent.getContext());
            textBox.setOrientation(LinearLayout.VERTICAL);
            textBox.setPadding(dp(14), 0, dp(8), 0);

            TextView label = new TextView(parent.getContext());
            label.setTextSize(16);
            label.setSingleLine(true);
            label.setEllipsize(TextUtils.TruncateAt.END);
            textBox.addView(label, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

            TextView pkg = new TextView(parent.getContext());
            pkg.setTextSize(12);
            pkg.setSingleLine(true);
            pkg.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            textBox.addView(pkg, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

            row.addView(textBox, new LinearLayout.LayoutParams(
                    0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));

            FrameLayout checkSlot = new FrameLayout(parent.getContext());
            LinearLayout.LayoutParams slotLp =
                    new LinearLayout.LayoutParams(dp(48), dp(56));
            row.addView(checkSlot, slotLp);

            MaterialCheckBox check = new MaterialCheckBox(parent.getContext());
            check.setMinWidth(0);
            check.setMinimumWidth(0);
            check.setMinHeight(0);
            check.setMinimumHeight(0);
            FrameLayout.LayoutParams checkLp =
                    new FrameLayout.LayoutParams(dp(48), dp(48), Gravity.CENTER);
            checkSlot.addView(check, checkLp);

            return new AppViewHolder(card, icon, label, pkg, check);
        }

        @Override public void onBindViewHolder(@NonNull AppViewHolder h, int position) {
            AppItem item = visible.get(position);
            boolean selected = selectedPackages.contains(item.packageName);

            h.icon.setImageDrawable(item.icon);
            h.label.setText(item.label);
            h.pkg.setText(item.packageName);

            int backgroundAttr = selected
                    ? com.google.android.material.R.attr.colorSecondaryContainer
                    : com.google.android.material.R.attr.colorSurfaceContainerLow;
            int labelAttr = selected
                    ? com.google.android.material.R.attr.colorOnSecondaryContainer
                    : com.google.android.material.R.attr.colorOnSurface;
            int packageAttr = selected
                    ? com.google.android.material.R.attr.colorOnSecondaryContainer
                    : com.google.android.material.R.attr.colorOnSurfaceVariant;

            h.card.setCardBackgroundColor(MaterialColors.getColor(h.card, backgroundAttr));
            h.card.setStrokeWidth(selected ? dp(1) : 0);
            if (selected) {
                h.card.setStrokeColor(MaterialColors.getColor(
                        h.card, com.google.android.material.R.attr.colorOutlineVariant));
            }
            h.label.setTextColor(MaterialColors.getColor(h.card, labelAttr));
            h.pkg.setTextColor(MaterialColors.getColor(h.card, packageAttr));

            h.check.setOnCheckedChangeListener(null);
            h.check.setChecked(selected);
            h.check.setEnabled(service != null);
            h.check.setOnCheckedChangeListener(
                    (button, checked) -> setSelected(item.packageName, checked));

            h.card.setOnClickListener(v -> {
                if (service != null) h.check.toggle();
            });
        }

        @Override public int getItemCount() {
            return visible.size();
        }
    }

    private static final class AppViewHolder extends RecyclerView.ViewHolder {
        final MaterialCardView card;
        final ImageView icon;
        final TextView label;
        final TextView pkg;
        final MaterialCheckBox check;

        AppViewHolder(MaterialCardView card, ImageView icon, TextView label,
                      TextView pkg, MaterialCheckBox check) {
            super(card);
            this.card = card;
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
