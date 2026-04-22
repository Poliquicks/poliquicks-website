#!/bin/bash
# Re-download the live Squarespace site into ./mirror/ (reference only).
# Requires: wget (brew install wget)
set -euo pipefail

cd "$(dirname "$0")/../mirror"

wget \
  --mirror \
  --convert-links \
  --adjust-extension \
  --page-requisites \
  --no-parent \
  --span-hosts \
  --domains=poliquicks.com,www.poliquicks.com,images.squarespace-cdn.com,static1.squarespace.com \
  --wait=0.3 --random-wait \
  --user-agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" \
  https://www.poliquicks.com/ \
  https://www.poliquicks.com/about \
  https://www.poliquicks.com/curriculum-supplements-1 \
  https://www.poliquicks.com/curriculum-supplements \
  https://www.poliquicks.com/partners-and-sources \
  https://www.poliquicks.com/for-candidates-and-reps \
  https://www.poliquicks.com/privacy-policy \
  https://www.poliquicks.com/delete-account \
  https://www.poliquicks.com/auth-action
