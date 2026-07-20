#!/usr/bin/env bash
# One-time setup for local publishing:
#   1) create an orphan `pages` branch (holds only the built m3u + index.html)
#   2) add a persistent .pages worktree that deploy.sh publishes into
# Run once:  bash setup-local.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "→ creating orphan 'pages' branch..."
tmp="$(mktemp -d)"
git worktree add --force --detach "$tmp" >/dev/null
git -C "$tmp" checkout --orphan pages
git -C "$tmp" reset --hard >/dev/null 2>&1 || true
git -C "$tmp" clean -fdx >/dev/null 2>&1 || true
echo "socolive" > "$tmp/index.html"
touch "$tmp/.nojekyll"           # tell Pages not to run Jekyll
git -C "$tmp" add -A
git -C "$tmp" commit -q -m "init pages"
git -C "$tmp" push -qf origin pages
git worktree remove --force "$tmp"

echo "→ adding persistent .pages worktree..."
rm -rf .pages
git worktree prune
git worktree add --force .pages pages >/dev/null

echo "✅ done."
echo "Next: GitHub → Settings → Pages → Source: 'Deploy from a branch' → Branch: pages / (root)"
echo "Then run:  bash deploy.sh   (and install the launchd job — see README)"
