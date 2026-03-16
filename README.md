# 🤖 Bot Trading Crypto - Advanced Dashboard

A **production-ready**, **secure**, and **feature-rich** cryptocurrency trading bot dashboard built with Flask, OAuth, 2FA, and multi-exchange support.

## ✨ Key Features

### 🔐 Security First
- ✅ OAuth 2.0 (Google/Gmail/Binance)
- ✅ 2FA/TOTP authentication
- ✅ CSRF protection on all forms
- ✅ Security headers (XSS, Clickjacking, etc.)
- ✅ Rate limiting (5 attempts/5 min)
- ✅ Password hashing (bcrypt)
- ✅ Audit logging for all admin actions

### 💼 Account Management
- ✅ User authentication & sessions
- ✅ 2FA setup & verification
- ✅ Password reset via email
- ✅ Audit logs (admin only)
- ✅ Subscription management (Free/Pro/Enterprise)

### 💱 Trading Features
- ✅ Multi-exchange support (Binance, Coinbase, Kraken, KuCoin, Bybit)
- ✅ Cryptocurrency portfolio tracking
- ✅ Real-time price monitoring
- ✅ DCA (Dollar Cost Averaging) strategy
- ✅ Take-profit automation
- ✅ Whale alerts (on-chain monitoring)
- ✅ Risk management (daily stops, volatility filters)

### 📊 Advanced Features
- ✅ 7+ AI providers (DeepSeek, OpenAI, Anthropic, Gemini, etc.)
- ✅ Telegram & Discord alerts
- ✅ Email confirmations (SendGrid)
- ✅ Detailed trading statistics
- ✅ Backtest mode
- ✅ Mobile responsive UI

---

## 🚀 Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/yourusername/bot-trading.git
cd bot_trading
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` with your credentials:
```bash
# Essential
FLASK_SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_urlsafe(50))">
GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
GOOGLE_CLIENT_SECRET=<your-google-oauth-secret>

# Optional (for full features)
STRIPE_SECRET_KEY=sk_test_your_key
DEEPSEEK_API_KEY=sk-your-key
BINANCE_API_KEY=<if-trading>
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Locally

```bash
# Development
python app.py

# Visit: http://localhost:5000
```

### 5. Deploy to Production

See [DEPLOYMENT.md](./DEPLOYMENT.md) for detailed instructions:
- **Render.com** (easiest, ⭐ recommended)
- **Railway.app**
- **Heroku**
- **Docker** (for custom hosting)

---

## 📂 Project Structure

```
bot_trading/
├── app.py                 # Flask app (1900+ lines, all features)
├── main.py               # Trading bot logic
├── requirements.txt      # Python dependencies
├── Dockerfile           # Production container
├── docker-compose.yml   # Local dev with Docker
├── DEPLOYMENT.md        # Deployment guide
├── .env                 # Secrets (NOT in git)
├── .env.example         # Template
├── .gitignore          # Git settings
├── templates/
│   └── index.html      # Full SPA frontend (1800+ lines)
├── static/             # CSS/JS assets
├── portfolio.json      # User portfolios (SQLite-like)
├── users.json          # User accounts & 2FA secrets
├── journal_trading.csv # Trade history
└── admin_audit.jsonl   # Admin action logs
```

---

## 🔑 Default Admin Account

**For testing only:**
```
Username: Jupiter
Password: 1234
```

⚠️ **Change this in production!**

---

## 🛠 Configuration

### Environment Variables

All configuration via `.env`:

```bash
# Security
FLASK_SECRET_KEY=<required>

# OAuth
GOOGLE_CLIENT_ID=<for signup>
GOOGLE_CLIENT_SECRET=<for signup>

# Payments
STRIPE_SECRET_KEY=sk_live_xxx

# Exchanges
BINANCE_API_KEY=<optional>
BINANCE_API_SECRET=<optional>

# AI Language Models
DEEPSEEK_API_KEY=<optional>

# Email
SEND_GRID_API_KEY=<optional>

# Notifications
TELEGRAM_BOT_TOKEN=<optional>
DISCORD_WEBHOOK_URL=<optional>
```

Full list: See `.env.example`

---

## 📖 API Documentation

### Authentication
- `POST /api/auth/register` - Create account
- `POST /api/auth/login` - Login
- `POST /api/auth/logout` - Logout
- `GET /api/auth/me` - Current user

### Subscriptions
- `GET /api/subscription/info` - Plan info
- `POST /api/subscription/upgrade` - Upgrade plan

### Trading
- `GET /api/exchange/<name>/balance` - Portfolio balance
- `GET /api/exchange/<name>/trades` - Trade history
- `POST /api/strategy/*/config` - DCA/TakeProfit setup

### 2FA
- `POST /api/auth/2fa/enable` - Generate QR code
- `POST /api/auth/2fa/verify` - Verify code
- `POST /api/auth/2fa/disable` - Disable 2FA

### Admin (Jupiter only)
- `GET /api/admin/audit` - View audit logs
- `POST /api/admin/users/:id/reset` - Reset user password

All endpoints require `Content-Type: application/json`

---

## 🔒 Security Practices

### Before Deploying
1. ✅ Strong FLASK_SECRET_KEY (50+ chars, random)
2. ✅ Real Google OAuth credentials (not test keys)
3. ✅ HTTPS enabled (auto with Render/Railway)
4. ✅ .env in .gitignore (never commit secrets)
5. ✅ Change default admin password
6. ✅ Rate limiting enabled
7. ✅ Email verification working

### Ongoing
- Monitor audit logs regularly
- Review user accounts
- Update dependencies: `pip install --upgrade -r requirements.txt`
- Add backups for `users.json` and `portfolio.json`
- Test password reset flow
- Verify 2FA codes work with authenticator apps

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Kill Flask on port 5000
lsof -ti:5000 | xargs kill -9  # Mac/Linux
Get-Process -Id (Get-NetTCPConnection -LocalPort 5000).OwningProcess | Stop-Process  # Windows
```

### Module Not Found
```bash
# Reinstall dependencies
pip install --force-reinstall -r requirements.txt
```

### Google OAuth Fails
1. Check GOOGLE_CLIENT_ID in `.env`
2. Verify redirect URI in Google Console matches deployment URL
3. Ensure Google+ API is enabled

### 2FA Code Invalid
- Ensure device time is synced (TOTP time-sensitive)
- Authenticator app: Google Authenticator, Authy, Microsoft Authenticator
- Re-scan QR code if needed

---

## 📈 Performance Tips

### Local Development
- Use SQLite (built-in, no setup)
- Run with `python app.py` (Flask dev server)
- Enable debug: `DEBUG=True` in .env

### Production
- Use Gunicorn (4-8 workers recommended)
- Enable caching for static assets
- Monitor memory usage (Render/Railway dashboards)
- Set up error alerting (Sentry, DataDog, etc.)

---

## 🤝 Contributing

1. Create feature branch: `git checkout -b feature/your-feature`
2. Commit changes: `git commit -m "Add feature"`
3. Push: `git push origin feature/your-feature`
4. Open PR

---

## 📋 Checklist Before Production

- [ ] FLASK_SECRET_KEY set (50+ chars)
- [ ] Google OAuth keys configured
- [ ] Default admin password changed
- [ ] HTTPS enabled
- [ ] Email configured (SendGrid)
- [ ] Rate limiting tested
- [ ] 2FA tested with real authenticator
- [ ] Portfolio page displays correctly
- [ ] Audit logs working
- [ ] Backups in place

---

## 📞 Support

- Docs: [DEPLOYMENT.md](./DEPLOYMENT.md)
- Issues: GitHub Issues
- Questions: Check `.env.example` for all settings

---

## 📄 License

[Your License Here]

---

**Ready to trade? Deploy to production:** [DEPLOYMENT.md](./DEPLOYMENT.md) 🚀
