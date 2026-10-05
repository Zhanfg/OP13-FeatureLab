package io.github.zhanfg.galleryguard;

import android.content.ContentResolver;
import android.os.Bundle;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import io.github.libxposed.api.XposedInterface;

/**
 * Converts the visibility policy into SQL selection before the provider executes a query.
 *
 * This replaces the old hot-path design that iterated every returned Cursor row before UI could
 * render. The provider/SQLite engine now discards disallowed paths directly.
 */
final class VisibilityQueryPushdown {
    private static volatile Snapshot sSnapshot = Snapshot.disabled(-1L);

    private VisibilityQueryPushdown() {}

    static Object[] inject(XposedInterface.Chain chain) {
        Snapshot snapshot = current();
        if (!snapshot.enabled || snapshot.selection.isEmpty()) return null;

        Object[] args = chain.getArgs().toArray(new Object[0]);
        if (args.length < 3) return null;

        Object selectionArg = args[2];

        if (selectionArg == null || selectionArg instanceof String) {
            if (args.length < 4) return null;

            String originalSelection = selectionArg instanceof String
                    ? (String) selectionArg : null;
            String[] originalArgs = args[3] instanceof String[]
                    ? (String[]) args[3] : null;

            args[2] = mergeSelection(snapshot.selection, originalSelection);
            args[3] = mergeArgs(snapshot.args, originalArgs);
            return args;
        }

        if (selectionArg instanceof Bundle) {
            Bundle queryArgs = new Bundle((Bundle) selectionArg);

            String originalSelection = queryArgs.getString(
                    ContentResolver.QUERY_ARG_SQL_SELECTION);
            String[] originalArgs = queryArgs.getStringArray(
                    ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS);

            queryArgs.putString(
                    ContentResolver.QUERY_ARG_SQL_SELECTION,
                    mergeSelection(snapshot.selection, originalSelection));
            queryArgs.putStringArray(
                    ContentResolver.QUERY_ARG_SQL_SELECTION_ARGS,
                    mergeArgs(snapshot.args, originalArgs));

            args[2] = queryArgs;
            return args;
        }

        return null;
    }

    private static Snapshot current() {
        long generation = VisibilityPolicy.generation();
        Snapshot current = sSnapshot;
        if (current.generation == generation) return current;

        synchronized (VisibilityQueryPushdown.class) {
            current = sSnapshot;
            if (current.generation == generation) return current;

            if (!VisibilityPolicy.strictIsolationEnabled()) {
                current = Snapshot.disabled(generation);
            } else {
                current = build(generation, VisibilityPolicy.allowedRootSnapshot());
            }

            sSnapshot = current;
            return current;
        }
    }

    private static Snapshot build(long generation, Set<String> roots) {
        if (roots == null || roots.isEmpty()) {
            return Snapshot.disabled(generation);
        }

        StringBuilder selection = new StringBuilder("(");
        ArrayList<String> args = new ArrayList<>(roots.size());

        boolean first = true;
        for (String root : roots) {
            if (root == null || root.isEmpty()) continue;
            if (!first) selection.append(" OR ");
            first = false;
            selection.append("_data LIKE ? ESCAPE '!'");
            args.add(escapeLike(root) + "/%");
        }

        if (first) return Snapshot.disabled(generation);

        selection.append(')');
        return new Snapshot(
                generation,
                true,
                selection.toString(),
                args.toArray(new String[0]));
    }

    private static String escapeLike(String value) {
        return value
                .replace("!", "!!")
                .replace("%", "!%")
                .replace("_", "!_");
    }

    private static String mergeSelection(String policy, String original) {
        if (original == null || original.trim().isEmpty()) return policy;
        return "(" + policy + ") AND (" + original + ")";
    }

    private static String[] mergeArgs(String[] policyArgs, String[] originalArgs) {
        int originalLength = originalArgs == null ? 0 : originalArgs.length;
        String[] out = new String[policyArgs.length + originalLength];

        System.arraycopy(policyArgs, 0, out, 0, policyArgs.length);
        if (originalLength > 0) {
            System.arraycopy(originalArgs, 0, out, policyArgs.length, originalLength);
        }
        return out;
    }

    private static final class Snapshot {
        final long generation;
        final boolean enabled;
        final String selection;
        final String[] args;

        Snapshot(long generation, boolean enabled, String selection, String[] args) {
            this.generation = generation;
            this.enabled = enabled;
            this.selection = selection;
            this.args = args;
        }

        static Snapshot disabled(long generation) {
            return new Snapshot(generation, false, "", new String[0]);
        }
    }
}
