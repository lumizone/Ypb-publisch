# 🔒 Authentication Setup Guide

## Overview

The application uses **Basic HTTP Authentication** to protect access to the dashboard and API endpoints.

## Configuration

Authentication is configured via environment variables in `.env.local`:

```bash
# Basic Authentication
AUTH_USER=Admin
AUTH_PASS=admin123
DISABLE_AUTH=true  # Set to 'false' or remove for production
```

---

## Local Development (Cursor/VSCode)

**Problem:** Built-in browsers in IDEs (like Cursor) don't support Basic Auth properly.

**Solution:** Disable auth locally using the `DISABLE_AUTH` flag:

### `.env.local` for Development:
```bash
GEMINI_API_KEY=your_api_key_here

# Basic Authentication
AUTH_USER=Admin
AUTH_PASS=admin123
DISABLE_AUTH=true  # ⚠️ Auth disabled - for local dev only!
```

With `DISABLE_AUTH=true`:
- ✅ No login required
- ✅ Works in Cursor/VSCode built-in browser
- ✅ Faster development workflow
- ⚠️ **DO NOT use in production!**

---

## Production Deployment (Railway/Render)

### Railway Setup:

1. Go to your Railway project → **Variables**
2. Add these environment variables:
   ```
   AUTH_USER=Admin
   AUTH_PASS=YourStrongPassword123!
   GEMINI_API_KEY=your_api_key_here
   ```
3. **DO NOT set `DISABLE_AUTH`** - it will default to `false` (auth enabled)

### Render Setup:

1. Go to your Render service → **Environment**
2. Add these environment variables:
   ```
   AUTH_USER=Admin
   AUTH_PASS=YourStrongPassword123!
   GEMINI_API_KEY=your_api_key_here
   ```
3. **DO NOT set `DISABLE_AUTH`** - it will default to `false` (auth enabled)

---

## How It Works

### When `DISABLE_AUTH=true` (Development):
```
User → http://localhost:8000/ → ✅ Direct access (no login)
```

### When `DISABLE_AUTH=false` or not set (Production):
```
User → https://your-app.railway.app/ 
     → 🔒 Browser shows login popup
     → User enters: Admin / YourPassword
     → ✅ Access granted
```

---

## Testing Authentication

### Test locally (with auth disabled):
```bash
# Just open in browser:
http://localhost:8000/
```

### Test locally (with auth enabled):
```bash
# In .env.local, set:
DISABLE_AUTH=false

# Then open in Safari/Chrome (not Cursor):
http://localhost:8000/

# Or test with curl:
curl -u Admin:admin123 http://localhost:8000/
```

### Test production:
```bash
# Browser will show login popup automatically:
https://your-app.railway.app/

# Or test with curl:
curl -u Admin:YourPassword https://your-app.railway.app/
```

---

## Security Best Practices

### ✅ DO:
- Use strong passwords in production (min 12 characters, mixed case, numbers, symbols)
- Keep `.env.local` in `.gitignore` (already configured)
- Set `DISABLE_AUTH=false` or remove it entirely on production
- Use HTTPS in production (Railway/Render provide this automatically)

### ❌ DON'T:
- Don't commit `.env.local` to git
- Don't use `DISABLE_AUTH=true` in production
- Don't share your production credentials publicly
- Don't use weak passwords like "admin123" in production

---

## Troubleshooting

### Problem: "Page is not working" in Cursor browser
**Solution:** Set `DISABLE_AUTH=true` in `.env.local` and restart the app.

### Problem: Can't login in Safari/Chrome
**Solution:** 
1. Check `.env.local` has correct credentials
2. Restart the Flask app completely (Ctrl+C, then `./start.sh`)
3. Clear browser cache (Cmd+Shift+R)
4. Try incognito mode (Cmd+Shift+N)

### Problem: Auth not working on Railway/Render
**Solution:**
1. Verify environment variables are set in Railway/Render dashboard
2. Make sure `DISABLE_AUTH` is NOT set (or set to `false`)
3. Check deployment logs for: `🔒 Basic Auth ENABLED`
4. Redeploy the application

---

## Logs

### Auth Enabled (Production):
```
INFO:__main__:🔒 Basic Auth ENABLED - Username: Admin
```

### Auth Disabled (Development):
```
WARNING:__main__:⚠️  Basic Auth DISABLED (DISABLE_AUTH=true) - Development mode only!
```

### Successful Login:
```
INFO:__main__:✅ Auth successful - User: Admin
```

### Failed Login:
```
WARNING:__main__:Auth FAILED - Username mismatch or wrong password
```

---

## Quick Reference

| Environment | DISABLE_AUTH | Auth Required | Use Case |
|-------------|--------------|---------------|----------|
| Local (Cursor) | `true` | ❌ No | Development in IDE |
| Local (Safari/Chrome) | `false` | ✅ Yes | Testing auth locally |
| Production (Railway) | not set | ✅ Yes | Live deployment |
| Production (Render) | not set | ✅ Yes | Live deployment |

---

## Example Configurations

### Development `.env.local`:
```bash
# Gemini Key
GEMINI_API_KEY=AIzaSyC...

# Basic Authentication (disabled for local dev)
AUTH_USER=Admin
AUTH_PASS=admin123
DISABLE_AUTH=true
```

### Production Environment Variables (Railway/Render):
```bash
GEMINI_API_KEY=AIzaSyC...
AUTH_USER=Admin
AUTH_PASS=Str0ng!Pr0duct10nP@ssw0rd
# DISABLE_AUTH is NOT set - defaults to false (auth enabled)
```
