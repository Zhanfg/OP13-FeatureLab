#!/usr/bin/env sh
# SPDX-License-Identifier: GPL-3.0-only
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

note() {
  printf 'CHECK: %s\n' "$*"
}

note "rejecting prohibited repository paths"
for path in payload extracted vendor-baseline device-dumps generated-release local-build; do
  [ ! -e "$path" ] || fail "proprietary/local path is present: $path"
done

note "rejecting firmware and packaged binary extensions"
if find . -type f \
  ! -path './.git/*' \
  \( -name '*.img' -o -name '*.mbn' -o -name '*.elf' -o -name '*.apk' \
     -o -name '*.apex' -o -name '*.dex' -o -name '*.so' -o -name '*.bin' \) \
  | grep -q .; then
  find . -type f \
    ! -path './.git/*' \
    \( -name '*.img' -o -name '*.mbn' -o -name '*.elf' -o -name '*.apk' \
       -o -name '*.apex' -o -name '*.dex' -o -name '*.so' -o -name '*.bin' \)
  fail "prohibited firmware/binary files found"
fi

note "rejecting credential and secret paths in tracked source"
SENSITIVE_PATTERN='/data/system/locksettings|/data/system/spblob|/data/misc/gatekeeper|/data/vendor/weaver|/metadata/vold|/data/unencrypted'
if git grep -nE "$SENSITIVE_PATTERN" -- . \
  ':!SECURITY.md' ':!README.md' ':!docs/**' ':!tools/audit-repository.sh' >/tmp/op13-sensitive.$$ 2>/dev/null; then
  cat /tmp/op13-sensitive.$$
  rm -f /tmp/op13-sensitive.$$
  fail "sensitive paths used outside policy/documentation files"
fi
rm -f /tmp/op13-sensitive.$$

note "rejecting release WebUI mock-success fallback"
if [ -d src/webui ]; then
  if git grep -nE 'mockRun|mock success|fake device|demo success' -- src/webui >/tmp/op13-mock.$$ 2>/dev/null; then
    cat /tmp/op13-mock.$$
    rm -f /tmp/op13-mock.$$
    fail "mock-success logic found in release WebUI source"
  fi
fi
rm -f /tmp/op13-mock.$$

note "checking shell syntax"
find scripts tools -type f -name '*.sh' 2>/dev/null | while IFS= read -r script; do
  sh -n "$script" || fail "shell syntax failed: $script"
done

note "checking JSON syntax"
if command -v python3 >/dev/null 2>&1; then
  find config schemas -type f -name '*.json' 2>/dev/null | while IFS= read -r json; do
    python3 -m json.tool "$json" >/dev/null || fail "JSON syntax failed: $json"
  done
fi

note "checking required governance files"
for file in README.md LICENSE SECURITY.md CONTRIBUTING.md PROPRIETARY_ASSETS.md THIRD_PARTY_NOTICES.md TRADEMARKS.md docs/RELEASE_GATES.md; do
  [ -s "$file" ] || fail "required file missing or empty: $file"
done

printf 'PASS: repository audit completed\n'
