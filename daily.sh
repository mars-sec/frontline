#!/bin/sh
set -e
cd /app

frontline run

today=$(date +%Y-%m-%d)
edition="editions/${today}.html"

if [ -f "$edition" ]; then
    cp "$edition" editions/index.html
    echo "Edition $today ready."
else
    echo "No new edition generated."
    exit 1
fi

if [ -d .git ]; then
    git add editions/
    git commit -m "edition $today" || echo "Nothing new to commit."
    git push personal main || echo "Push failed. Will retry next run."
fi
