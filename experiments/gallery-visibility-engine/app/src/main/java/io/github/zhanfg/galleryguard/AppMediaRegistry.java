package io.github.zhanfg.galleryguard;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * App -> shared-media directory mapping.
 *
 * Generic rule:
 *   /storage/emulated/0/Android/media/<package>
 *
 * Communication apps additionally carry legacy/public paths so selecting one app
 * also covers media created before scoped storage or by vendor-specific builds.
 */
public final class AppMediaRegistry {
    private static final String ROOT = "/storage/emulated/0";

    private static final Set<String> DEFAULT_COMMUNICATION_APPS =
            Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
                    "com.tencent.mm",
                    "com.tencent.mobileqq",
                    "com.tencent.tim",
                    "com.tencent.wework",
                    "org.telegram.messenger",
                    "org.telegram.messenger.web",
                    "com.whatsapp",
                    "com.whatsapp.w4b",
                    "org.thoughtcrime.securesms",
                    "com.facebook.orca",
                    "jp.naver.line.android",
                    "com.discord",
                    "com.alibaba.android.rimet",
                    "com.ss.android.lark",
                    "com.Slack",
                    "com.microsoft.teams",
                    "com.viber.voip",
                    "com.skype.raider"
            )));

    private static final Map<String, List<String>> KNOWN_ROOTS;
    static {
        LinkedHashMap<String, List<String>> m = new LinkedHashMap<>();

        m.put("com.tencent.mm", Arrays.asList(
                ROOT + "/Pictures/WeiXin",
                ROOT + "/Tencent/MicroMsg",
                ROOT + "/tencent/MicroMsg",
                ROOT + "/Android/data/com.tencent.mm/MicroMsg"
        ));
        m.put("com.tencent.mobileqq", Arrays.asList(
                ROOT + "/Tencent/QQ_Images",
                ROOT + "/Tencent/QQfile_recv",
                ROOT + "/Pictures/QQ",
                ROOT + "/Android/data/com.tencent.mobileqq/Tencent"
        ));
        m.put("com.tencent.tim", Arrays.asList(
                ROOT + "/Tencent/TIM_Images",
                ROOT + "/Tencent/TIMfile_recv",
                ROOT + "/Android/data/com.tencent.tim/Tencent"
        ));
        m.put("com.tencent.wework", Arrays.asList(
                ROOT + "/Tencent/WeixinWork",
                ROOT + "/tencent/WeixinWork",
                ROOT + "/Pictures/WeCom"
        ));
        m.put("org.telegram.messenger", Arrays.asList(
                ROOT + "/Telegram",
                ROOT + "/Pictures/Telegram"
        ));
        m.put("org.telegram.messenger.web", Arrays.asList(
                ROOT + "/Telegram",
                ROOT + "/Pictures/Telegram"
        ));
        m.put("com.whatsapp", Arrays.asList(
                ROOT + "/WhatsApp",
                ROOT + "/Pictures/WhatsApp"
        ));
        m.put("com.whatsapp.w4b", Arrays.asList(
                ROOT + "/WhatsApp Business",
                ROOT + "/Pictures/WhatsApp Business"
        ));
        m.put("org.thoughtcrime.securesms",
                Collections.singletonList(ROOT + "/Pictures/Signal"));
        m.put("com.facebook.orca",
                Collections.singletonList(ROOT + "/Pictures/Messenger"));
        m.put("jp.naver.line.android",
                Collections.singletonList(ROOT + "/Pictures/LINE"));
        m.put("com.discord",
                Collections.singletonList(ROOT + "/Pictures/Discord"));
        m.put("com.alibaba.android.rimet", Arrays.asList(
                ROOT + "/DingTalk",
                ROOT + "/Pictures/DingTalk"
        ));
        m.put("com.ss.android.lark", Arrays.asList(
                ROOT + "/Lark",
                ROOT + "/Pictures/Lark"
        ));

        KNOWN_ROOTS = Collections.unmodifiableMap(m);
    }

    private AppMediaRegistry() {}

    public static Set<String> defaultCommunicationPackages() {
        return new LinkedHashSet<>(DEFAULT_COMMUNICATION_APPS);
    }

    public static boolean isDefaultCommunicationPackage(String packageName) {
        return DEFAULT_COMMUNICATION_APPS.contains(packageName);
    }

    public static List<String> rootsForPackage(String packageName) {
        if (packageName == null || packageName.trim().isEmpty()) {
            return Collections.emptyList();
        }

        LinkedHashSet<String> roots = new LinkedHashSet<>();
        String pkg = packageName.trim();

        // Android 11+ standard shared media location.
        roots.add(ROOT + "/Android/media/" + pkg);

        // Some communication apps keep historical media under Android/data.
        // The path may be unreadable to an ordinary app, but the privileged
        // Gallery/MediaProvider process can still use it for visibility matching.
        roots.add(ROOT + "/Android/data/" + pkg);

        List<String> known = KNOWN_ROOTS.get(pkg);
        if (known != null) roots.addAll(known);

        return new ArrayList<>(roots);
    }

    public static Set<String> resolveRoots(Set<String> packages) {
        LinkedHashSet<String> roots = new LinkedHashSet<>();
        if (packages == null) return roots;
        for (String pkg : packages) roots.addAll(rootsForPackage(pkg));
        return roots;
    }
}
