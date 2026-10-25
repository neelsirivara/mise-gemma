#!/usr/bin/env bash
# Print a line whenever a branch head or pull request on GitHub changes (teammate pushes, new PRs).
#   scripts/watch_repo.sh [interval_seconds]
INTERVAL="${1:-45}"
GH="${GH:-gh}"
snap() {
  git ls-remote --heads origin 2>/dev/null | awk '{print substr($1,1,7), $2}' | sed 's#refs/heads/##' | sort -k2
  "$GH" pr list --state all --json number,state,title,headRefOid --jq '.[] | "PR#\(.number) \(.state) \(.headRefOid[0:7]) \(.title)"' 2>/dev/null | sort
}
prev="$(snap)"
echo "watching repo: $(echo "$prev" | wc -l | tr -d ' ') branches/PRs"
while true; do
  sleep "$INTERVAL"
  cur="$(snap)" || continue
  [ -z "$cur" ] && continue
  diff <(echo "$prev") <(echo "$cur") | grep '^>' | sed 's/^> /changed: /'
  prev="$cur"
done
