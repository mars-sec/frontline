#!/bin/sh
set -e

cd /repo

git config user.name "Marshall Yanis"
git config user.email "marshall.e.yanis@gmail.com"

if [ -n "$GITHUB_TOKEN" ]; then
    git remote set-url personal "https://${GITHUB_TOKEN}@github.com/mars-sec/frontline-personal.git" 2>/dev/null || \
    git remote add personal "https://${GITHUB_TOKEN}@github.com/mars-sec/frontline-personal.git"
fi

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

git add editions/
git commit -m "edition $today" || echo "Nothing new to commit."
git push personal main || echo "Push failed. Will retry next run."
