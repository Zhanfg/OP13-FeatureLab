package io.github.zhanfg.galleryguard;

import android.net.Uri;
import android.provider.DocumentsContract;

public final class PathCodec {
    private PathCodec() {}

    public static String fromTreeUri(Uri uri) {
        if (uri == null) return null;
        try {
            String id = DocumentsContract.getTreeDocumentId(uri);
            int colon = id.indexOf(':');
            if (colon < 0) return null;
            String volume = id.substring(0, colon);
            String rel = id.substring(colon + 1);
            String base = "primary".equalsIgnoreCase(volume)
                    ? "/storage/emulated/0"
                    : "/storage/" + volume;
            if (rel.isEmpty()) return base;
            return VisibilityPolicy.normalize(base + "/" + rel);
        } catch (Throwable t) {
            return null;
        }
    }
}
