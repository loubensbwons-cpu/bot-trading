# 🚀 Bot Trading Crypto - Production Deployment Guide

## 🔐 Security Features Implemented

✅ **CSRF Protection** - All forms protected with CSRF tokens  
✅ **Security Headers** - XSS, clickjacking, and injection protections  
✅ **Session Security** - HTTPOnly, Secure, SameSite cookies  
✅ **Environment Validation** - Warns about weak/missing configuration  
✅ **Rate Limiting** - 5 login attempts per 5 minutes  
✅ **2FA/TOTP** - Two-factor authentication available  
✅ **Password Hashing** - Bcrypt for all passwords  
✅ **Audit Logging** - Track all admin actions  

---

## 📋 Pre-Deployment Checklist

### 1. Environment Variables (.env)

**CRITICAL**: Generate a strong FLASK_SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

**Update .env with real values:**
```bash
FLASK_SECRET_KEY=<your-50-char-random-key>
GOOGLE_CLIENT_ID=<your-real-client-id>
GOOGLE_CLIENT_SECRET=<your-real-secret>
STRIPE_SECRET_KEY=sk_live_your_real_key
DEEPSEEK_API_KEY=<your-api-key>
BINANCE_API_KEY=<if-trading>
BINANCE_API_SECRET=<if-trading>
```

**⚠️ Important:**
- `.env` is in `.gitignore` - NEVER commit secrets
- Use `.env.example` as template
- Different keys for development vs production

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Test Locally

```bash
# Development mode
python app.py

# Or with Flask CLI
export FLASK_ENV=development
flask run

# Or with Docker (if Docker installed)
docker-compose up
```

---

## 🌐 Deployment Options

### Option A: Render.com (Easiest) ⭐

1. **Push to GitHub**
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git remote add origin https://github.com/yourusername/bot-trading.git
   git push -u origin main
   ```

2. **Create Render Account**
   - Go to https://render.com
   - Connect GitHub account
   - Click "New +" → "Web Service"

3. **Configure Render**
   - Select your GitHub repo
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn --bind 0.0.0.0:5000 app:app`
   - Set environment variables in "Environment" tab:
     - `FLASK_SECRET_KEY`
     - `GOOGLE_CLIENT_ID`
     - `GOOGLE_CLIENT_SECRET`
     - etc...

4. **Deploy**
   - Click "Deploy"
   - Wait 2-5 minutes
   - Get your URL (example.onrender.com)

✅ **You get:**
- Auto HTTPS/SSL
- Auto backups
- Auto restarts
- Custom domain option
- Free tier available

### Option B: Railway.app

Similar to Render:
1. Go to https://railway.app
2. Connect GitHub
3. Create new project
4. Set environment variables
5. Deploy

### Option C: Heroku (Alternative)

```bash
# Install Heroku CLI
# Login and create app
heroku login
heroku create your-bot-app-name

# Add config variables
heroku config:set FLASK_SECRET_KEY="your-key"
heroku config:set GOOGLE_CLIENT_ID="your-id"
# ... etc for all vars

# Deploy
git push heroku main

# View logs
heroku logs --tail
```

---

## 🔒 Production Security Checklist

- [ ] FLASK_SECRET_KEY set to 50+ character random string
- [ ] HTTPS enabled (auto with Render/Railway)
- [ ] All API keys in .env (NOT in code)
- [ ] .env in .gitignore
- [ ] Database backups configured
- [ ] Monitoring/alerting set up
- [ ] Rate limiting tested
- [ ] 2FA enabled for admin account
- [ ] Custom domain configured
- [ ] Email verification working
- [ ] Password reset working
- [ ] Audit logs reviewed

---

## 📊 Monitoring & Logs

### On Render.com
- Logs tab shows real-time logs
- Metrics tab shows CPU/memory usage

### On Railway
- Logs section shows all output
- Deployments show history

### Locally
- Check `journal_trading.csv` for trades
- Check `admin_audit.jsonl` for admin actions
- Flask console shows HTTP requests

---

## 🐛 Troubleshooting

### 502 Bad Gateway / App Crashed
1. Check "Logs" tab in Render/Railway
2. Verify environment variables are set
3. Check that FLASK_SECRET_KEY is set (required!)
4. Run locally: `python app.py` to debug

### Port Issues
- Development: Flask uses `localhost:5000`
- Production: Must bind to `0.0.0.0:5000`
- Dockerfile and Procfile already configured

### Database Issues
- SQLite stored in memory/JSON files
- No external database needed
- Backups: Copy `.json` and `.csv` files

### Google OAuth Not Working
- Verify GOOGLE_CLIENT_ID in .env
- Check redirect URI in Google Console
- Production URL must be in Google authorized redirect URIs

---

## 🔄 Updating Production

1. **Local changes**
   ```bash
   git add .
   git commit -m "Your changes"
   ```

2. **Push to GitHub**
   ```bash
   git push origin main
   ```

3. **Auto-deploy**
   - Render/Railway automatically redeploy on push
   - Takes 2-5 minutes
   - Check "Deployments" tab

---

## 📞 Support & Resources

- Flask docs: https://flask.palletsprojects.com
- Render docs: https://render.com/docs
- Railway docs: https://docs.railway.app
- Google OAuth: https://developers.google.com/identity
- Stripe API: https://stripe.com/docs

---

## 🎯 Next Steps

1. **Generate strong FLASK_SECRET_KEY**
2. **Get Google OAuth credentials** (https://console.cloud.google.com)
3. **Get Stripe key** (https://stripe.com) - if using payments
4. **Push to GitHub**
5. **Deploy to Render/Railway**
6. **Test signup with Google**
7. **Configure custom domain**
8. **Monitor first transactions**

---

**Questions?** Check `.env.example` for all config options.
