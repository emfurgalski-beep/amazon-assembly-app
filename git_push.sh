#!/bin/bash

# Default commit message
MESSAGE="Update app with recent changes"

# If the user provides an argument, use it as the commit message
if [ "$1" != "" ]; then
    MESSAGE="$1"
fi

echo "📦 Staging changes..."
git add .

echo "📝 Committing with message: '$MESSAGE'..."
git commit -m "$MESSAGE"

echo "🚀 Pushing to repository..."
git push

echo "✅ Done!"