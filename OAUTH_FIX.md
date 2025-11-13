# OAuth Login Setup Guide

## Issues Fixed

### ✅ Google OAuth - Opens in New Tab
- Changed `target="_self"` to `target="_blank"`
- Google OAuth pages don't work in iframes, now opens in new browser tab
- Works for both local and production

### ✅ GitHub OAuth - Separate Apps for Local & Production
- Production uses main OAuth app (callback: `https://docsamajh-ai.streamlit.app`)
- Local can use separate OAuth app (callback: `http://localhost:8501`)
- Fallback to production credentials if local not configured

## Setup Instructions

### 1. Google OAuth (Works Everywhere)

**Google Cloud Console:**
1. Go to https://console.cloud.google.com/apis/credentials
2. Click your OAuth 2.0 Client ID
3. Add **both** redirect URIs:
   ```
   http://localhost:8501
   https://docsamajh-ai.streamlit.app
   ```
4. Save

**Your `.env`:**
```env
CLIENT_ID=27929630813-05it1h6pvofeomk3kofg2tnt16gquhd9.apps.googleusercontent.com
CLIENT_SECRET=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
```

### 2. GitHub OAuth - Option A: Production Only

**GitHub Settings:**
1. Use existing OAuth app with callback: `https://docsamajh-ai.streamlit.app`
2. GitHub login will only work in production
3. Local testing will fail with "redirect_uri not associated"

**Your `.env`:**
```env
GITHUB_CLIENT_ID=Ov23liCAyznNWbTifLY8
GITHUB_CLIENT_SECRET=5bb707c3b3dc8c371c354fc45a188b9d3908c59e
ENV=local
```

### 3. GitHub OAuth - Option B: Separate Local App (Recommended)

**Create New GitHub OAuth App for Local:**
1. Go to https://github.com/settings/developers
2. Click **New OAuth App**
3. Fill in:
   - **Application name:** DocSamajh AI (Local Dev)
   - **Homepage URL:** http://localhost:8501
   - **Authorization callback URL:** `http://localhost:8501`
4. Click **Register application**
5. Generate client secret

**Your `.env`:**
```env
# Production GitHub OAuth
GITHUB_CLIENT_ID=Ov23liCAyznNWbTifLY8
GITHUB_CLIENT_SECRET=5bb707c3b3dc8c371c354fc45a188b9d3908c59e

# Local GitHub OAuth (separate app)
GITHUB_CLIENT_ID_LOCAL=your_new_local_client_id
GITHUB_CLIENT_SECRET_LOCAL=your_new_local_client_secret

ENV=local
```

## How It Works

### Local Development (`ENV=local`):
- **Redirect URI:** `http://localhost:8501`
- **Google:** Opens in new tab → logs in → redirects back ✅
- **GitHub:** 
  - If `GITHUB_CLIENT_ID_LOCAL` set: Uses local app → works ✅
  - If not set: Uses production app → fails (redirect mismatch) ❌

### Production (`ENV=production`):
- **Redirect URI:** `https://docsamajh-ai.streamlit.app`
- **Google:** Opens in new tab → logs in → redirects back ✅
- **GitHub:** Uses production credentials → works ✅

## Testing

### Test Google OAuth (Local):
1. Run `streamlit run src/docsamajh/app.py`
2. Click **Google** button
3. New tab opens with Google login
4. After login, redirects back to `http://localhost:8501?state=google&code=...`
5. Should auto-login ✅

### Test GitHub OAuth (Local - with local app):
1. Create separate GitHub OAuth app (see Option B above)
2. Add credentials to `.env` as `GITHUB_CLIENT_ID_LOCAL`
3. Click **GitHub** button
4. New tab opens with GitHub login
5. After login, redirects back to `http://localhost:8501?state=github&code=...`
6. Should auto-login ✅

### Test Production:
1. Deploy to Streamlit Cloud
2. Set `ENV=production` in Streamlit Secrets
3. Both Google and GitHub work with new tab redirect ✅

## Streamlit Cloud Secrets

```toml
# Environment
ENV = "production"

# Google OAuth
CLIENT_ID = "27929630813-05it1h6pvofeomk3kofg2tnt16gquhd9.apps.googleusercontent.com"
CLIENT_SECRET = "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"

# GitHub OAuth (Production only)
GITHUB_CLIENT_ID = "Ov23liCAyznNWbTifLY8"
GITHUB_CLIENT_SECRET = "5bb707c3b3dc8c371c354fc45a188b9d3908c59e"

# Other secrets...
ADE_API_KEY = "..."
GEMINI_API_KEY = "..."
```

## Summary

| Feature | Before | After |
|---------|--------|-------|
| Google Local | ❌ Iframe blocked | ✅ New tab works |
| Google Production | ❌ Iframe blocked | ✅ New tab works |
| GitHub Local | ❌ Redirect mismatch | ✅ Separate app (optional) |
| GitHub Production | ✅ Works | ✅ Works |

**Recommendation:** Create separate GitHub OAuth app for local development for best experience! 🚀
