package io.github.zhanfg.galleryguard;

import android.content.ContentResolver;
import android.os.Bundle;

import java.util.ArrayList;
import java.util.Set;

import io.github.libxposed.api.XposedInterface;

/**
 * Converts visibility rules into provider-side SQL selection.
 *
 * No Cursor rows are walked here. The expensive filtering work is delegated to the provider's
 * SQLite query, while .nomedia exclusions are supplied by the existing watcher traversal.
 */
final class VisibilityQueryPushdown {
    private static volatile Snapshot sSnapshot = Snapshot.disabled(-1L, -1L);

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
        long policyGeneration = VisibilityPolicy.generation();
        long nomediaGeneration = NomediaIndex.generation();

        Snapshot current = sSnapshot;
        if (current.policyGeneration == policyGeneration
                && current.nomediaGeneration == nomediaGeneration) {
            return current;
        }

        synchronized (VisibilityQueryPushdown.class) {
            current = sSnapshot;
            if (current.policyGeneration == policyGeneration
                    && current.nomediaGeneration == nomediaGeneration) {
                return current;
            }

            current = build(
                    policyGeneration,
                    nomediaGeneration,
                    VisibilityPolicy.strictIsolationEnabled(),
                    VisibilityPolicy.allowedRootSnapshot(),
                    VisibilityPolicy.explicitPassthroughRootSnapshot(),
                    NomediaIndex.snapshot());

            sSnapshot = current;
            return current;
        }
    }

    private static Snapshot build(
            long policyGeneration,
            long nomediaGeneration,
            boolean strictIsolation,
            Set<String> allowedRoots,
            Set<String> explicitRoots,
            Set<String> hiddenDirs) {

        ArrayList<String> args = new ArrayList<>();
        String allow = strictIsolation
                ? pathPredicate(allowedRoots, args)
                : "";

        String explicit = pathPredicate(explicitRoots, args);
        String hidden = pathPredicate(hiddenDirs, args);

        String selection;

        if (strictIsolation) {
            if (allow.isEmpty()) {
                // Fail open rather than returning an unexpectedly empty gallery.
                return Snapshot.disabled(policyGeneration, nomediaGeneration);
            }

            if (hidden.isEmpty()) {
                selection = allow;
            } else if (explicit.isEmpty()) {
                selection = "(" + allow + ") AND NOT (" + hidden + ")";
            } else {
                // Explicit app/folder passthrough wins over an ancestor .nomedia.
                selection = "(" + allow + ") AND ((" + explicit + ") OR NOT (" + hidden + "))";
            }
        } else {
            if (hidden.isEmpty()) {
                return Snapshot.disabled(policyGeneration, nomediaGeneration);
            }
            if (explicit.isEmpty()) {
                selection = "NOT (" + hidden + ")";
            } else {
                selection = "(" + explicit + ") OR NOT (" + hidden + ")";
            }
        }

        return new Snapshot(
                policyGeneration,
                nomediaGeneration,
                true,
                selection,
                args.toArray(new String[0]));
    }

    private static String pathPredicate(Set<String> roots, ArrayList<String> args) {
        if (roots == null || roots.isEmpty()) return "";

        StringBuilder out = new StringBuilder();
        boolean first = true;

        for (String root : roots) {
            String n = VisibilityPolicy.normalize(root);
            if (n == null || n.isEmpty()) continue;

            if (!first) out.append(" OR ");
            first = false;

            out.append("_data LIKE ? ESCAPE '!'");
            args.add(escapeLike(n) + "/%");
        }

        return first ? "" : out.toString();
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
        final long policyGeneration;
        final long nomediaGeneration;
        final boolean enabled;
        final String selection;
        final String[] args;

        Snapshot(
                long policyGeneration,
                long nomediaGeneration,
                boolean enabled,
                String selection,
                String[] args) {
            this.policyGeneration = policyGeneration;
            this.nomediaGeneration = nomediaGeneration;
            this.enabled = enabled;
            this.selection = selection;
            this.args = args;
        }

        static Snapshot disabled(long policyGeneration, long nomediaGeneration) {
            return new Snapshot(
                    policyGeneration,
                    nomediaGeneration,
                    false,
                    "",
                    new String[0]);
        }
    }
}
