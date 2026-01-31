# Railway Deployment Guide for YPBv2

**Date**: 29 January 2026
**Status**: ⚠️ Requires modifications before deployment

---

## ✅ WHAT WORKS (Good News)

1. **Port Configuration** - ✅ Perfect
   - Uses `PORT` environment variable (Railway-compatible)
   - Host set to `0.0.0.0` (accepts external connections)
   ```python
   port = int(os.environ.get('PORT', 8000))
   app.run(debug=True, host='0.0.0.0', port=port)
   ```

2. **Path Configuration** - ✅ Mostly Good
   - `config.py` uses relative paths with `Path(__file__).parent`
   - All directories created dynamically (TEMP_DIR, OUTPUT_DIR, etc.)

3. **Environment Variables** - ✅ Good
   - Uses `.env.local` for secrets (git-ignored)
   - `python-dotenv` already in requirements.txt

4. **Dependencies** - ✅ Complete
   - `requirements.txt` includes all Python packages

---

## ❌ CRITICAL ISSUES (Must Fix)

### 1. **Hardcoded Local Path** - BLOCKING DEPLOYMENT

**File**: `app.py` (line 77)
```python
DEFAULT_TEMPLATE = "/Users/lukasz/YPBv2/real_example.svg"  # ❌ WRONG
```

**Fix Required**:
```python
DEFAULT_TEMPLATE = str(config.BASE_DIR / "real_example.svg")  # ✅ CORRECT
```

**Impact**: Application will crash on Railway because this path doesn't exist.

---

### 2. **Hardcoded Paths in Shell Scripts** - NOT NEEDED ON RAILWAY

**Files**:
- `start.sh` (line 4): `cd /Users/lukasz/YPBv2`
- `restart.sh` (line 4): `cd /Users/lukasz/YPBv2`

**Solution**: Railway doesn't use these scripts. Will use Procfile instead.

---

### 3. **No Procfile** - REQUIRED FOR RAILWAY

Railway needs a `Procfile` to know how to start the application.

**Create**: `Procfile` (new file)
```
web: python app.py
```

---

### 4. **System Dependencies Missing** - CRITICAL

The application requires system libraries that Railway needs to install:

**Required**:
- **Cairo** (cairosvg dependency) - For PNG rendering
- **Pango** (Cairo text rendering)
- **GDK-PixBuf** (image loading)
- **LibRSVG** (SVG parsing)

**Solution**: Create `nixpacks.toml` (Railway uses Nixpacks for Python)

**Create**: `nixpacks.toml` (new file)
```toml
[phases.setup]
nixPkgs = ["cairo", "pango", "gdk-pixbuf", "librsvg"]

[start]
cmd = "python app.py"
```

Alternative: Create `Aptfile` (if Railway uses Buildpack):
```
libcairo2-dev
libpango1.0-dev
libgdk-pixbuf2.0-dev
librsvg2-dev
```

---

### 5. **Ephemeral Filesystem** - DATA LOSS WARNING

⚠️ **Railway uses ephemeral storage** - all files are deleted on restart/redeploy.

**Current Storage Usage**:
- `temp/`: 262 MB
- `output/`: 514 MB
- `uploads/`: 18 MB
- **Total**: ~794 MB of data LOST on every restart

**Problem Areas**:
```python
TEMP_DIR = BASE_DIR / "temp"      # ❌ Lost on restart
OUTPUT_DIR = BASE_DIR / "output"  # ❌ Lost on restart
UPLOAD_DIR = BASE_DIR / "uploads" # ❌ Lost on restart
```

**Solutions** (choose one):

#### Option A: External Storage (Recommended)
Use AWS S3, Cloudflare R2, or Railway Volumes for persistent storage.

**Railway Volumes** (easiest):
```bash
# In Railway dashboard:
# Create volume: /data
# Mount point: /app/data
```

Then update `config.py`:
```python
# Check if running on Railway (volume mounted)
if Path("/data").exists():
    BASE_STORAGE = Path("/data")
else:
    BASE_STORAGE = BASE_DIR

TEMP_DIR = BASE_STORAGE / "temp"
OUTPUT_DIR = BASE_STORAGE / "output"
UPLOAD_DIR = BASE_STORAGE / "uploads"
```

#### Option B: Accept Data Loss (Not Recommended)
- All generated files lost on restart
- Users must re-upload templates/CSVs
- Archive page will be empty after restart

---

### 6. **Debug Mode Enabled** - SECURITY RISK

**File**: `app.py` (line 4516)
```python
app.run(debug=True, host='0.0.0.0', port=port)  # ❌ Debug=True in production
```

**Fix Required**:
```python
debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
app.run(debug=debug_mode, host='0.0.0.0', port=port)
```

Then set in Railway environment variables:
```
FLASK_DEBUG=false
```

---

### 7. **macOS-Specific Code** - WILL FAIL ON RAILWAY

**File**: `app.py` (lines 4502-4506)
```python
if sys.platform == 'darwin':  # macOS
    os.environ['PKG_CONFIG_PATH'] = '/opt/homebrew/lib/pkgconfig:' + ...
    os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + ...
```

**Fix**: Wrap in try-except or skip on Linux
```python
if sys.platform == 'darwin':  # macOS only
    try:
        os.environ['PKG_CONFIG_PATH'] = '/opt/homebrew/lib/pkgconfig:' + os.environ.get('PKG_CONFIG_PATH', '')
        os.environ['DYLD_LIBRARY_PATH'] = '/opt/homebrew/lib:' + os.environ.get('DYLD_LIBRARY_PATH', '')
    except Exception:
        pass  # Not needed on Linux/Railway
```

---

### 8. **Missing Environment Variables Setup**

Railway needs these environment variables configured:

**Required**:
```
GEMINI_API_KEY=your_gemini_api_key_here
PORT=8000
FLASK_DEBUG=false
```

**Optional**:
```
AUTH_USER=Admin
AUTH_PASS=your_secure_password_here
DISABLE_AUTH=false
```

---

## 📋 DEPLOYMENT CHECKLIST

### Before Deployment

- [ ] Fix hardcoded path in `app.py` line 77
- [ ] Create `Procfile`
- [ ] Create `nixpacks.toml` or `Aptfile`
- [ ] Disable debug mode (environment variable)
- [ ] Decide on storage strategy (Railway Volumes recommended)
- [ ] Set up environment variables in Railway dashboard
- [ ] Test locally with Railway CLI (optional)

### After Deployment

- [ ] Verify Cairo/system dependencies installed
- [ ] Test image generation (PNG rendering)
- [ ] Test mockup generation (Gemini API)
- [ ] Verify file uploads work
- [ ] Check if restart button works
- [ ] Test archive page
- [ ] Monitor logs for errors

---

## 🚀 DEPLOYMENT STEPS

### 1. Fix Code Issues

**Fix app.py line 77**:
```python
# Before
DEFAULT_TEMPLATE = "/Users/lukasz/YPBv2/real_example.svg"

# After
DEFAULT_TEMPLATE = str(config.BASE_DIR / "real_example.svg")
```

**Fix app.py line 4516**:
```python
# Before
app.run(debug=True, host='0.0.0.0', port=port)

# After
debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
app.run(debug=debug_mode, host='0.0.0.0', port=port)
```

### 2. Create Procfile

Create new file `Procfile`:
```
web: python app.py
```

### 3. Create nixpacks.toml

Create new file `nixpacks.toml`:
```toml
[phases.setup]
nixPkgs = ["cairo", "pango", "gdk-pixbuf", "librsvg"]

[start]
cmd = "python app.py"
```

### 4. Push to GitHub

```bash
git add .
git commit -m "Prepare for Railway deployment"
git push origin main
```

### 5. Deploy to Railway

1. Go to [railway.app](https://railway.app)
2. Click "New Project"
3. Select "Deploy from GitHub repo"
4. Choose your repository
5. Railway auto-detects Python and installs dependencies
6. Set environment variables:
   - `GEMINI_API_KEY`
   - `FLASK_DEBUG=false`
   - `PORT` (auto-set by Railway)

### 6. Add Volume (Optional but Recommended)

1. In Railway dashboard, go to your service
2. Click "Volumes" tab
3. Create new volume:
   - Mount path: `/data`
   - Size: 5 GB (adjust based on needs)
4. Update `config.py` to use `/data` when available

### 7. Test Deployment

1. Open Railway-provided URL
2. Test file upload
3. Test label generation
4. Test mockup generation
5. Check logs for errors

---

## 🔍 EXPECTED ISSUES & SOLUTIONS

### Issue 1: "ModuleNotFoundError: No module named 'cairo'"

**Cause**: Cairo system dependency not installed
**Solution**: Verify `nixpacks.toml` is present and correct

### Issue 2: "FileNotFoundError: real_example.svg"

**Cause**: Hardcoded path not fixed
**Solution**: Fix `app.py` line 77 as shown above

### Issue 3: "All files disappear after restart"

**Cause**: Ephemeral filesystem, no volume mounted
**Solution**: Add Railway Volume at `/data`

### Issue 4: "Gemini API not working"

**Cause**: `GEMINI_API_KEY` not set
**Solution**: Add environment variable in Railway dashboard

### Issue 5: "Port already in use"

**Cause**: Railway sets PORT automatically
**Solution**: No action needed - code already handles this

---

## 💰 COST ESTIMATION

**Railway Pricing** (as of 2026):
- **Hobby Plan**: $5/month
  - 500 hours runtime
  - $0.000231/GB-hour for memory
  - Volume: $0.25/GB/month

**Expected Costs**:
- App runtime: $5/month (Hobby plan)
- Volume (5 GB): $1.25/month
- **Total**: ~$6.25/month

**Gemini API** (separate):
- gemini-2.5-flash-image: ~$0.10 per 1000 images
- Based on usage (pay-per-request)

---

## ✅ SUMMARY

**Can you deploy to Railway?**
✅ **YES**, but requires fixes first.

**What needs to be done?**

1. **Code Changes** (2 fixes):
   - Fix hardcoded path (`app.py` line 77)
   - Disable debug mode (`app.py` line 4516)

2. **New Files** (2 files):
   - Create `Procfile`
   - Create `nixpacks.toml`

3. **Configuration**:
   - Set environment variables in Railway dashboard
   - Optional: Add Railway Volume for persistent storage

**Time to Deploy**: ~15 minutes (after fixes)

**Difficulty**: ⭐⭐☆☆☆ (Easy, after code fixes)

---

## 📞 SUPPORT

If deployment fails:
1. Check Railway logs: `railway logs`
2. Verify all environment variables are set
3. Ensure `nixpacks.toml` is in root directory
4. Test Cairo locally: `python -c "import cairosvg; print('OK')"`

---

**Ready to deploy?** Start with Step 1: Fix Code Issues (see above).
