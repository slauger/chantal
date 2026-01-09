#!/bin/bash
set -e

cd /Users/simon/git/chantal

echo "Initializing git repository..."
git init
git branch -M main

echo "Adding files..."
git add .

echo "Creating initial commit..."
git commit -m "Initial commit: Chantal - because every other name was already taken"

echo "Adding remote..."
git remote add origin https://github.com/slauger/chantal.git

echo "Pushing to GitHub..."
git push -u origin main

echo "Setting repository description and topics..."
gh repo edit slauger/chantal \
  --description "A unified CLI tool for offline repository mirroring across APT and RPM ecosystems" \
  --add-topic linux \
  --add-topic repository \
  --add-topic mirror \
  --add-topic apt \
  --add-topic rpm \
  --add-topic debian \
  --add-topic ubuntu \
  --add-topic rhel \
  --add-topic deduplication \
  --add-topic snapshot \
  --add-topic patch-management

echo "Done! Repository is live at https://github.com/slauger/chantal"
