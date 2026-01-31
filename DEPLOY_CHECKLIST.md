# Railway Deployment Checklist

## ✅ Completed (Ready to Deploy)

### Code Fixes
- [x] Fixed hardcoded path in `app.py` line 77
  - Before: `/Users/lukasz/YPBv2/real_example.svg`
  - After: `str(config.BASE_DIR / "real_example.svg")`

- [x] Made debug mode configurable via environment variable
  - Uses `FLASK_DEBUG` env var (defaults to False)
  - Safe for production deployment

- [x] Wrapped macOS-specific code in try-except
  - Won't crash on Railway (Linux environment)

- [x] Added Railway Volume support to config.py
  - Auto-detects `/data` volume if mounted
  - Falls back to local storage if not available
  - Persistent storage across deployments

### New Files Created
- [x] `Procfile` - Tells Railway how to start the app
- [x] `nixpacks.toml` - System dependencies (Cairo, Pango, etc.)
- [x] `.env.railway.example` - Template for environment variables
- [x] `RAILWAY_DEPLOYMENT.md` - Complete deployment guide
- [x] `DEPLOY_CHECKLIST.md` - This file

---

## 🚀 Quick Deploy Steps

### 1. Push to GitHub
```bash
git add .
git commit -m "Railway deployment ready"
git push origin main
```

### 2. Deploy on Railway
1. Go to [railway.app](https://railway.app)
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your repository
4. Railway will auto-detect Python and deploy

### 3. Set Environment Variables
In Railway dashboard → Settings → Variables:
```
GEMINI_API_KEY=your_actual_api_key_here
FLASK_DEBUG=false
```

### 4. (Optional) Add Persistent Storage
In Railway dashboard → Volumes:
- Create volume: `/data`
- Size: 5 GB (or as needed)
- This prevents data loss on restarts

### 5. Test Deployment
- Open Railway-provided URL
- Upload template and CSV
- Generate labels
- Test mockup generation

---

## 📊 What Changed

| File | Change | Why |
|------|--------|-----|
| `app.py` line 77 | Hardcoded path → relative path | Works on any server |
| `app.py` line 4516 | `debug=True` → env var | Production safety |
| `app.py` line 4502-4506 | Added try-except | Linux compatibility |
| `config.py` line 23-34 | Added Railway Volume support | Persistent storage |
| `Procfile` | Created | Railway startup command |
| `nixpacks.toml` | Created | System dependencies |

---

## ⚠️ Important Notes

### Data Persistence
Without Railway Volume, all uploaded files and generated labels will be lost on restart. Add a volume at `/data` for persistence.

### API Key
The application will work without `GEMINI_API_KEY`, but mockup generation will fail. Make sure to set it in Railway environment variables.

### First Deploy
First deployment takes 3-5 minutes while Railway installs Cairo and other system dependencies. Subsequent deploys are faster.

### Testing Locally
Before deploying, test locally to ensure changes work:
```bash
export FLASK_DEBUG=true
python app.py
# Visit http://localhost:8000
```

---

## 🔧 Troubleshooting

### "ModuleNotFoundError: No module named 'cairo'"
- Verify `nixpacks.toml` is in root directory
- Check Railway build logs for Cairo installation

### "FileNotFoundError: real_example.svg"
- Ensure `real_example.svg` is in git repository
- Check that file is not in `.gitignore`

### "All files disappear after restart"
- Add Railway Volume at `/data` mount point
- Application will auto-detect and use it

### "Gemini API not working"
- Set `GEMINI_API_KEY` in Railway environment variables
- Check API key is valid at [Google AI Studio](https://aistudio.google.com/app/apikey)

---

## ✅ Ready to Deploy!

All critical issues have been fixed. The application is now Railway-ready.

**Estimated deploy time**: 5 minutes
**Difficulty**: ⭐⭐☆☆☆ Easy

See `RAILWAY_DEPLOYMENT.md` for complete documentation.
