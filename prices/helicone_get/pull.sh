#!/bin/bash

set -e

cd "$(dirname "$0")"
rm -rf cost

if [ -d "helicone-repo" ]; then
    echo "helicone-repo exists, pulling latest changes..."
    cd helicone-repo
    git pull origin main
    cd ..
else
    git clone --branch main --single-branch --depth 1 git@github.com:Helicone/helicone.git helicone-repo
fi

cp -r helicone-repo/packages/cost .
