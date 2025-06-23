#!/bin/bash

set -ex

rm -rf helicone-repo
rm -rf cost
git clone --branch main --single-branch --depth 1 git@github.com:Helicone/helicone.git helicone-repo

cp -r helicone-repo/bifrost/packages/cost .
rm -rf helicone-repo
