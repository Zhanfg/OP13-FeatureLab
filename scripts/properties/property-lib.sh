#!/system/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
FL_PROP_LIB_DIR="${FEATURELAB_PROP_LIB_DIR:-${0%/*}}"
. "$FL_PROP_LIB_DIR/../runtime/platform.sh" || return 1
. "$FL_PROP_LIB_DIR/property-platform.sh" || return 1
. "$FL_PROP_LIB_DIR/property-policy.sh" || return 1
. "$FL_PROP_LIB_DIR/property-transaction.sh" || return 1
