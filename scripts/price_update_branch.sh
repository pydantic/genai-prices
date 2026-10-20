#!/usr/bin/env bash
set -euo pipefail

message='Update provider prices from official sources'
identity="genai-prices-automation[bot]@users.noreply.github.com $message"

check_branch() {
  local candidate="$1" previous="$2" commits
  commits="$(git log --format='%ae %s' "$candidate..$previous")"
  if [ -n "$commits" ] && grep -Fxv "$identity" <<< "$commits"; then
    echo '::error::The price proposal contains repairs. Keep this branch unchanged until it is merged or closed.' >&2
    return 1
  fi
}

case "$1" in
  check)
    check_branch "$2" "$3"
    ;;
  publish)
    remote="$2" branch="$3" previous="$4" candidate="$(git rev-parse HEAD)"
    if [ -n "$previous" ]; then
      check_branch "$candidate" "$previous"
      if [ "$(git rev-parse "$previous^{tree}")" = "$(git rev-parse "$candidate^{tree}")" ]; then
        echo "$previous"
        exit 0
      fi
      # Keep the previous proposal and current main in history; a concurrent push fails normally.
      candidate="$(git commit-tree "$candidate^{tree}" -p "$previous" -p "$candidate" -m "$message")"
    fi
    git push "$remote" "$candidate:refs/heads/$branch"
    echo "$candidate"
    ;;
  *)
    echo 'usage: price_update_branch.sh check BASE PREVIOUS | publish REMOTE BRANCH PREVIOUS' >&2
    exit 2
    ;;
esac
