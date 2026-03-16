# 📋 Pre-Deployment Checklist

## 🔐 Security (MUST DO)

- [ ] **FLASK_SECRET_KEY Generated**
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(50))"
  # Result: Add to .env
  ```

- [ ] **Default Password Changed**
  - [ ] Login as Jupiter/1234
  - [ ] Go to Account Settings
  - [ ] Change password to something strong

- [ ] **.env File Created**
  - [ ] Copy `.env.example` to `.env`
  - [ ] Fill in FLASK_SECRET_KEY
  - [ ] Fill in GOOGLE_CLIENT_ID
  - [ ] Fill in GOOGLE_CLIENT_SECRET

- [ ] **Git Ignore Verified**
  - [ ] `.env` in `.gitignore`
  - [ ] `.gitignore` has .env entry
  - [ ] Run `git status` - should NOT show .env

- [ ] **No Secrets in Code**
  - [ ] Search app.py for hardcoded keys
  - [ ] Search templates for hardcoded APIs
  - [ ] Check main.py for sensitive data

---

## 📦 Code Quality

- [ ] **Dependencies Updated**
  ```bash
  pip install --upgrade -r requirements.txt
  ```

- [ ] **No Python Errors**
  ```bash
  python -m py_compile app.py
  echo "✅ No syntax errors"
  ```

- [ ] **App Starts Locally**
  ```bash
  python app.py
  # Should show: "Running on http://127.0.0.1:5000"
  ```

- [ ] **Website Loads**
  - [ ] Visit http://localhost:5000
  - [ ] See login form
  - [ ] Signup works
  - [ ] Login works

---

## ✅ Feature Testing

- [ ] **Login System**
  - [ ] Can create new user
  - [ ] Can login with username/password
  - [ ] Password hashing works (passwords different)
  - [ ] Rate limiting works (try 6 failed logins)

- [ ] **Google OAuth**
  - [ ] Google popup appears when clicking button
  - [ ] Can sign in with Google account
  - [ ] Account auto-created on first login
  - [ ] Can list Google accounts in Connexions tab

- [ ] **2FA Works**
  - [ ] Can enable 2FA
  - [ ] QR code displays
  - [ ] Can scan with Google Authenticator
  - [ ] TOTP codes verify correctly
  - [ ] Can disable 2FA with password

- [ ] **Portfolio Display**
  - [ ] Portfolio page shows (if logged in)
  - [ ] Can view statistics
  - [ ] Exchange balance displays

- [ ] **Admin Features**
  - [ ] Login as Jupiter/1234
  - [ ] View audit logs
  - [ ] Logs show user actions

---

## 🌐 Deployment Prep

- [ ] **GitHub Repository**
  - [ ] Created GitHub account (if needed)
  - [ ] Created private repository
  - [ ] Code pushed to main branch
  - [ ] .env NOT committed

- [ ] **Render.com Account**
  - [ ] Created account at https://render.com
  - [ ] Connected GitHub
  - [ ] Can create new service

- [ ] **Google OAuth Production**
  - [ ] Created Google Cloud Project
  - [ ] Created OAuth 2.0 credentials
  - [ ] Set authorized redirect URI to: `https://your-domain.com/api/oauth/google/callback`
  - [ ] Copied Client ID to .env
  - [ ] Copied Client Secret to .env
  - [ ] Tested locally first

---

## 🚀 Render.com Deployment Steps

- [ ] **Create Web Service**
  1. Click "New +" → "Web Service"
  2. Connect GitHub repository
  3. Name: `bot-trading` (or your choice)
  4. Build command: `pip install -r requirements.txt`
  5. Start command: `gunicorn --bind 0.0.0.0:5000 app:app`

- [ ] **Environment Variables**
  Click "Environment" and add:
  - [ ] `FLASK_SECRET_KEY` = your-generated-key
  - [ ] `GOOGLE_CLIENT_ID` = from Google console
  - [ ] `GOOGLE_CLIENT_SECRET` = from Google console
  - [ ] `DEEPSEEK_API_KEY` = (if using)
  - [ ] `STRIPE_SECRET_KEY` = (if using payments)

- [ ] **Deploy**
  1. Click "Deploy"
  2. Wait 2-5 minutes
  3. Check "Logs" tab for errors
  4. Visit `https://your-app.onrender.com`

- [ ] **Verify Production**
  - [ ] Homepage loads
  - [ ] Signup form appears
  - [ ] Google button works (new Client ID)
  - [ ] Can create test account
  - [ ] Can login

---

## 📝 Post-Deployment

- [ ] **Monitoring**
  - [ ] Check Render.com logs daily first week
  - [ ] Monitor performance metrics
  - [ ] Set up backup of users.json

- [ ] **Testing in Production**
  - [ ] Sign up with new email
  - [ ] Enable 2FA
  - [ ] Test Google OAuth
  - [ ] Reset password
  - [ ] Change password

- [ ] **Custom Domain** (Optional)
  - [ ] Domain purchased (GoDaddy, Namecheap, etc.)
  - [ ] DNS configured to Render.com
  - [ ] SSL certificate auto-generated
  - [ ] HTTPS working

- [ ] **Monitoring Setup** (Optional)
  - [ ] Set up error tracking (Sentry)
  - [ ] Set up log aggregation (Papertrail)
  - [ ] Set up uptime monitoring (Pingdom)

---

## 🚨 Emergency Procedure

**If something breaks in production:**

1. **Stop the bleeding**
   - [ ] Click "Suspend" in Render.com

2. **Diagnose**
   - [ ] Check Render.com Logs tab
   - [ ] Look for Python errors
   - [ ] Check if .env variables are set

3. **Fix**
   - [ ] Make code change locally
   - [ ] Test locally: `python app.py`
   - [ ] Push to GitHub
   - [ ] Render.com auto-redeploys

4. **Verify**
   - [ ] Check Logs again
   - [ ] Test functionality
   - [ ] Monitor for 24 hours

---

## 📞 Quick Links

- Render.com Dashboard: https://dashboard.render.com
- Google Cloud Console: https://console.cloud.google.com
- GitHub Repository: https://github.com/yourusername/bot-trading
- Local Testing: http://localhost:5000
- Production: https://your-app.onrender.com

---

## ⚡ Performance Checklist

- [ ] Page loads in < 2 seconds
- [ ] Google popup appears < 1 second
- [ ] Login/signup < 3 seconds
- [ ] No 404 errors in console
- [ ] No JavaScript errors (F12 → Console)

---

## ✅ Final Sign-Off

- [ ] All security items completed
- [ ] All features tested locally
- [ ] GitHub push completed
- [ ] Render.com deployment successful
- [ ] Production tests passed
- [ ] Admin password changed
- [ ] This checklist reviewed

**Deployment Date**: _______________  
**Checked By**: _______________  
**Status**: _______________

---

**Questions?** See `README.md`, `DEPLOYMENT.md`, or `SECURITY.md`
