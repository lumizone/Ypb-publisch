#!/bin/bash
# Manually trigger Railway deployment

echo "🚀 Triggering Railway deployment..."
echo ""
echo "Option 1: Railway CLI"
echo "  railway up --detach"
echo ""
echo "Option 2: Empty commit push"
echo "  git commit --allow-empty -m 'Trigger Railway deployment'"
echo "  git push origin main"
echo ""
echo "Option 3: Railway Dashboard"
echo "  https://railway.app/dashboard"
echo "  → Select project → Click 'Deploy Now'"
echo ""
