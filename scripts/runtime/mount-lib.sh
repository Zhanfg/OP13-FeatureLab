#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
FL_LIB_DIR="${FEATURELAB_LIB_DIR:-${0%/*}}"
# shellcheck source=platform.sh
. "$FL_LIB_DIR/platform.sh" || return 1
# shellcheck source=policy.sh
. "$FL_LIB_DIR/policy.sh" || return 1
# shellcheck source=transaction.sh
. "$FL_LIB_DIR/transaction.sh" || return 1
