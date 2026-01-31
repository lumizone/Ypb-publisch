# Railway Quick Start - YPBv2

**Status**: ✅ Ready to deploy
**Date**: 29 January 2026

---

## 🚀 Deploy in 3 Steps

### Step 1: Push to GitHub (1 minute)
```bash
cd /Users/lukasz/YPBv2
git add .
git commit -m "Railway deployment ready"
git push origin main
```

### Step 2: Deploy on Railway (2 minutes)
1. Go to https://railway.app
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose `YPBv2` repository
5. Wait for automatic deployment

### Step 3: Set API Key (1 minute)
1. In Railway dashboard, go to your project
2. Click on your service
3. Go to "Variables" tab
4. Add variable:
   ```
   GEMINI_API_KEY=AIzaSyCSyrlmwF9LJ8haOrsC5bn4St-viT4wsMM
   ```
5. Click "Add" and redeploy

**Done!** Your app is live at the Railway-provided URL.

---

## 📋 Optional: Add Persistent Storage

Without this, files are deleted on restart. To keep files:

1. In Railway dashboard, click "Volumes" tab
2. Click "New Volume"
3. Settings:
   - **Mount path**: `/data`
   - **Size**: 5 GB (or more based on needs)
4. Click "Add Volume"
5. App will auto-restart and use persistent storage

---

## ✅ What Was Fixed

| Issue | Status | Fix |
|-------|--------|-----|
| Hardcoded local path | ✅ Fixed | Changed to relative path |
| Debug mode enabled | ✅ Fixed | Now uses env var (defaults to false) |
| Missing Procfile | ✅ Fixed | Created |
| Missing system deps | ✅ Fixed | Created nixpacks.toml |
| macOS-specific code | ✅ Fixed | Wrapped in try-except |
| No persistent storage | ✅ Fixed | Added Railway Volume support |

---

## 🧪 Test Deployment

After deployment, test these:

1. **Homepage** - Should load with all 8 tabs
2. **Upload** - Try uploading template SVG
3. **Generate Labels** - Select database and generate
4. **Mockup** - Test mockup generation with Gemini
5. **Archive** - Check if previous generations appear

---

## 🔧 Troubleshooting

### App won't start
- Check Railway logs: Click "Deployments" → Latest deployment → "View Logs"
- Common issue: `GEMINI_API_KEY` not set

### Cairo errors
- Verify `nixpacks.toml` is in root directory
- Should see in logs: "Installing cairo, pango, gdk-pixbuf, librsvg"

### Files disappear after restart
- Add Railway Volume (see "Optional: Add Persistent Storage" above)

### API key invalid
- Get new key at https://aistudio.google.com/app/apikey
- Update in Railway Variables tab

---

## 💰 Cost

**Railway Hobby Plan**: $5/month
- 500 hours runtime (always-on = ~$5/month)
- Volume (5 GB): +$1.25/month
- **Total**: ~$6.25/month

**Gemini API**: Separate billing
- gemini-2.5-flash-image: ~$0.10 per 1000 images
- Pay-per-use through Google Cloud

---

## 📞 Need Help?

1. **Full Guide**: See `RAILWAY_DEPLOYMENT.md`
2. **Checklist**: See `DEPLOY_CHECKLIST.md`
3. **Railway Docs**: https://docs.railway.app
4. **Railway Logs**: Dashboard → Deployments → View Logs

---

**Ready?** Start with Step 1 above! 🚀
