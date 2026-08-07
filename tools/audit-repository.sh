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

note "rejecting credential and secret paths in executable source"
SENSITIVE_PATTERN='/data/system/locksettings|/data/system/spblob|/data/misc/gatekeeper|/data/vendor/weaver|/metadata/vold|/data/unencrypted'
# Centralized denylist implementations and synthetic tests must name protected
# paths. All other executable/configuration source remains prohibited.
if git grep -nE "$SENSITIVE_PATTERN" -- . \
  ':!SECURITY.md' ':!README.md' ':!docs/**' ':!tools/audit-repository.sh' \
  ':!src/featurelab/audit.py' ':!scripts/runtime/policy.sh' ':!tests/**' >/tmp/op13-sensitive.$$ 2>/dev/null; then
  cat /tmp/op13-sensitive.$$
  rm -f /tmp/op13-sensitive.$$
  fail "sensitive paths used outside centralized guards or regression tests"
fi
rm -f /tmp/op13-sensitive.$$

note "verifying centralized protected-path registries"
for protected in \
  '/data/system/locksettings' \
  '/data/system/spblob/' \
  '/data/misc/gatekeeper/' \
  '/data/vendor/weaver/' \
  '/metadata/vold/' \
  '/data/unencrypted/'; do
  grep -Fq "$protected" src/featurelab/audit.py \
    || fail "Python protected-path registry is missing: $protected"
  grep -Fq "$protected" scripts/runtime/policy.sh \
    || fail "runtime protected-path registry is missing: $protected"
done

note "rejecting unconditional or persistent property injection"
[ ! -e system.prop ] || fail "root system.prop bypasses recovery-controlled property groups"
[ ! -e module-template/system.prop ] || fail "module template contains an unconditional system.prop"
if git grep -nE '(^|[[:space:]])resetprop[[:space:]]+-p([[:space:]]|$)|(^|[[:space:]])setprop([[:space:]]|$)' -- scripts/properties module-template >/tmp/op13-prop-injection.$$ 2>/dev/null; then
  cat /tmp/op13-prop-injection.$$
  rm -f /tmp/op13-prop-injection.$$
  fail "persistent resetprop or direct setprop found in property controller"
fi
rm -f /tmp/op13-prop-injection.$$

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
find scripts tools module-template tests/runtime tests/properties -type f -name '*.sh' 2>/dev/null | while IFS= read -r script; do
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
