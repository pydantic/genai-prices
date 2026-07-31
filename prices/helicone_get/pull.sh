#!/bin/bash

set -e

cd "$(dirname "$0")"
rm -rf cost

# Pinned deliberately. `main.ts` *imports* `cost/providers/mappings.ts`, so this repository's
# TypeScript executes on our machine - tracking `main` would run whatever landed upstream since the
# last pull, with no review. Bump this SHA in its own commit so the change is reviewable.
#
# To bump: pick the new SHA, run `make helicone-get`, and confirm the diff in
# `prices/source_prices/helicone.json` is only price data.
HELICONE_SHA="67df07b8d807a960f2e53d9ec2a9c49513ca2379"

# HTTPS rather than SSH: this is a public repository, so there is no reason to hand the clone an
# authenticated SSH agent.
HELICONE_REMOTE="https://github.com/Helicone/helicone.git"

if [ ! -d helicone-repo/.git ]; then
    rm -rf helicone-repo
    git init -q helicone-repo
    git -C helicone-repo remote add origin "$HELICONE_REMOTE"
fi

git -C helicone-repo remote set-url origin "$HELICONE_REMOTE"
git -C helicone-repo fetch -q --depth 1 origin "$HELICONE_SHA"
git -C helicone-repo checkout -q --detach FETCH_HEAD

echo "helicone-repo pinned at $HELICONE_SHA"
cp -r helicone-repo/packages/cost .
