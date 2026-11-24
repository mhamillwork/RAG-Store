#!/usr/bin/env bash
set -euo pipefail

die() { echo "error: $*" >&2; exit 1; }

usage() { sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'; }

confirm() {
  if [[ "${DRY_RUN:-}" == "1" ]]; then
    echo "dry-run: $*"
    return 0
  fi
  if [[ "${ASSUME_YES:-}" == "1" ]]; then
    return 0
  fi
  read -r -p "$1 [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]]
}
