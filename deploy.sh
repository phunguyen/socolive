#!/usr/bin/env bash
# Crawl locally (Mac's residential VN IP isn't geo-blocked) and publish the
# playlist to the `pages` branch as a single rolling commit (no history bloat).
# Run every 5 min via launchd. Run setup-local.sh once before first use.
set -euo pipefail
cd "$(dirname "$0")"

# launchd runs with a minimal PATH — make python3/git findable.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# 1) crawl. If the API is blocked/down, main.py exits non-zero → set -e stops
#    here and the last published playlist stays untouched.
SOCOLIVE_OUT=public python3 main.py

# 2) self-heal the worktree if missing (e.g. first run after a fresh clone).
if [ ! -e .pages/.git ]; then
  git worktree prune
  git fetch -q origin pages
  git worktree add --force .pages pages
fi

# 3) publish: copy outputs, amend the single rolling commit, force-push.
cp public/socolive.m3u public/index.html .pages/
touch .pages/.nojekyll
git -C .pages add -A
git -C .pages commit -q --amend -m "socolive m3u $(date -u +%FT%TZ)" \
  || git -C .pages commit -q -m "socolive m3u $(date -u +%FT%TZ)"
git -C .pages push -qf origin pages
echo "published $(date -u +%FT%TZ)"
