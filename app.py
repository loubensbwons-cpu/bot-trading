# =============================================================================
#  DASHBOARD WEB - Bot de Trading Crypto
#  Serveur Flask : controle du bot + interface temps reel
# =============================================================================

import os
import json
import subprocess
import threading
import time
import csv
import pyotp
import qrcode
import requests
import hashlib
import hmac
import base64
from io import BytesIO
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, jsonify, request, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import ccxt
import pandas as pd
import numpy as np
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import anthropic as anthropic_lib
except ImportError:
    anthropic_lib = None

try:
    from binance.client import Client as BinanceClient
except ImportError:
    BinanceClient = None

try:
    from web3 import Web3
except ImportError:
    Web3 = None

try:
    import jwt
except ImportError:
    jwt = None

try:
    from flask_wtf.csrf import CSRFProtect
except ImportError:
    CSRFProtect = None

try:
    import stripe
except ImportError:
    stripe = None

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-secret-key-now")

# Validate FLASK_SECRET_KEY is set properly
if app.config["SECRET_KEY"] == "change-this-secret-key-now":
    print("⚠️  WARNING: Using default FLASK_SECRET_KEY. Set FLASK_SECRET_KEY in .env for production!")

# Enable CSRF protection if available
if CSRFProtect:
    csrf = CSRFProtect(app)
    print("✅ CSRF protection enabled")

# Session configuration
app.config["SESSION_COOKIE_SECURE"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_AGE"] = 86400  # 24h expiry

# =========================================================================
# SECURITY HEADERS - Apply to all responses
# =========================================================================
@app.after_request
def set_security_headers(response):
    """Set security headers on all responses."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    # Only enable HSTS in production
    if not app.debug:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# --------------------------------------------------------------------------
# SECURITE: RATE-LIMIT, 2FA, ALERTES, OAUTH
# --------------------------------------------------------------------------
LOGIN_RATE_LIMIT = {}  # {username: [(timestamp, count)]}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_WINDOW_SEC = 300  # 5 min
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# OAuth Google
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://localhost:5000/api/oauth/google/callback")

# Payment Processing - Stripe
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
if stripe and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# OAuth Binance
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# Email SMTP Configuration
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.sendgrid.net")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "apikey")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "noreply@bot-trading.local")

# Blockchain / On-chain
WEB3_RPC_URL = os.getenv("WEB3_RPC_URL", "https://mainnet.infura.io/v3/YOUR_INFURA_KEY")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "")

# Exchange Multi Support
SUPPORTED_EXCHANGES = ["binance", "coinbase", "kraken", "kucoin", "bybit", "dydx"]
IS_PRODUCTION = os.getenv("FLASK_ENV", "").strip().lower() == "production"

# =========================================================================
# ENVIRONMENT VALIDATION - Critical for security
# =========================================================================
def validate_environment():
    """Validate critical environment variables."""
    warnings = []
    secret_key = os.getenv("FLASK_SECRET_KEY", "")
    admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    
    # Check FLASK_SECRET_KEY
    if secret_key.startswith("your-super-secret-key") or len(secret_key) < 32:
        warnings.append("⚠️  FLASK_SECRET_KEY is weak or default. Set a strong random 50+ char key!")
    
    # Warn about missing optional security vars
    if not os.getenv("GOOGLE_CLIENT_ID"):
        warnings.append("⚠️  GOOGLE_CLIENT_ID not set (Google OAuth won't work)")
    
    if not os.getenv("STRIPE_SECRET_KEY"):
        warnings.append("⚠️  STRIPE_SECRET_KEY not set (payments won't work)")

    if not admin_password:
        warnings.append("⚠️  ADMIN_PASSWORD not set (admin password falls back to default value)")

    if IS_PRODUCTION and (secret_key.startswith("your-super-secret-key") or len(secret_key) < 32):
        raise RuntimeError("FLASK_SECRET_KEY must be set to a strong value in production.")

    if IS_PRODUCTION and not admin_password:
        raise RuntimeError("ADMIN_PASSWORD must be set in production.")
    
    # Print warnings but don't block startup
    for warning in warnings:
        print(warning)
    
    return len(warnings) == 0

# ---------------------------------------------------------------------------
# ETAT GLOBAL DU BOT
# ---------------------------------------------------------------------------
bot_process   = None
bot_lock      = threading.Lock()
log_buffer    = []
MAX_LOG_LINES = 200
bot_started_at = None
bot_last_log_at = None
bot_error_count = 0

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
PORTFOLIO_FILE = os.path.join(BASE_DIR, "portfolio.json")
JOURNAL_FILE   = os.path.join(BASE_DIR, "journal_trading.csv")
BOT_SCRIPT     = os.path.join(BASE_DIR, "main.py")
ENV_FILE       = os.path.join(BASE_DIR, ".env")
USERS_FILE     = os.path.join(BASE_DIR, "users.json")
ADMIN_AUDIT_FILE = os.path.join(BASE_DIR, "admin_audit.jsonl")

ADMIN_USERNAME = "Jupiter"
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "1234")
ADMIN_PASSWORD_FROM_ENV = bool(os.getenv("ADMIN_PASSWORD", "").strip())

validate_environment()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def validate_password_strength(password: str, admin: bool = False) -> str:
    min_length = 12 if admin else 10
    if len(password) < min_length:
        return f"Mot de passe trop court (min {min_length} caracteres)."
    if not any(ch.islower() for ch in password):
        return "Le mot de passe doit contenir au moins une minuscule."
    if not any(ch.isupper() for ch in password):
        return "Le mot de passe doit contenir au moins une majuscule."
    if not any(ch.isdigit() for ch in password):
        return "Le mot de passe doit contenir au moins un chiffre."
    if not any(not ch.isalnum() for ch in password):
        return "Le mot de passe doit contenir au moins un caractere special."
    return ""


def load_users() -> dict:
    if not os.path.exists(USERS_FILE):
        return {"users": [], "subscriptions": {}}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"users": [], "subscriptions": {}}
        data.setdefault("users", [])
        data.setdefault("subscriptions", {})
        # Initialize 2FA and subscription fields for existing users
        for user in data.get("users", []):
            user.setdefault("totp_secret", "")
            user.setdefault("totp_enabled", False)
            user.setdefault("email_confirmed", False)
            user.setdefault("confirmation_token", "")
            user.setdefault("subscription_plan", "free")
            user.setdefault("subscription_expires", "")
            user.setdefault("dca_enabled", False)
            user.setdefault("dca_amount", 100.0)
            user.setdefault("dca_interval_hours", 24)
            user.setdefault("take_profit_pct", 10.0)
            user.setdefault("telegram_chat_id", "")
            user.setdefault("telegram_alerts_enabled", False)
            user.setdefault("discord_webhook", "")
            user.setdefault("discord_alerts_enabled", False)
            # OAuth Google
            user.setdefault("google_id", "")
            user.setdefault("google_email", "")
            user.setdefault("google_token", "")
            # OAuth Binance
            user.setdefault("binance_api_key", "")
            user.setdefault("binance_api_secret", "")
            # Multi-Exchange Support
            user.setdefault("exchange_keys", {})  # {exchange: {api_key, api_secret, sub_account}}
            # Whale Alerts
            user.setdefault("whale_alerts_enabled", False)
            user.setdefault("tracked_addresses", [])  # List of blockchain addresses to monitor
            user.setdefault("whale_alert_threshold_eur", 10000.0)  # Alert if transaction > this
        return data
    except Exception as e:
        print(f"[LOAD_USERS ERROR] {e}")
        return {"users": [], "subscriptions": {}}


def save_users(data: dict) -> None:
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, USERS_FILE)


def log_admin_event(actor: str, action: str, details: dict) -> None:
    payload = {
        "timestamp": now_str(),
        "actor": actor,
        "action": action,
        "details": details,
    }
    try:
        with open(ADMIN_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


def read_admin_audit(limit: int = 100) -> list:
    if not os.path.exists(ADMIN_AUDIT_FILE):
        return []
    lines = []
    try:
        with open(ADMIN_AUDIT_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    events = []
    for line in reversed(lines[-limit:]):
        try:
            events.append(json.loads(line.strip()))
        except Exception:
            continue
    return events


def find_user(username: str) -> dict:
    users = load_users().get("users", [])
    for u in users:
        if str(u.get("username", "")).lower() == username.lower():
            return u
    return {}


def ensure_admin_user() -> None:
    db = load_users()
    users = db.get("users", [])
    for u in users:
        if str(u.get("username", "")).lower() == ADMIN_USERNAME.lower():
            u["is_admin"] = True
            if not u.get("password_hash"):
                u["password_hash"] = generate_password_hash(ADMIN_PASSWORD)
            elif ADMIN_PASSWORD_FROM_ENV and not check_password_hash(u.get("password_hash", ""), ADMIN_PASSWORD):
                u["password_hash"] = generate_password_hash(ADMIN_PASSWORD)
            save_users(db)
            return
    users.append({
        "username": ADMIN_USERNAME,
        "password_hash": generate_password_hash(ADMIN_PASSWORD),
        "is_admin": True,
        "created_at": now_str(),
        "last_login": None,
        "disabled": False,
    })
    db["users"] = users
    save_users(db)


def current_user() -> dict:
    username = session.get("username")
    if not username:
        return {}
    return find_user(username)


def login_required_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("username"):
            return jsonify({"ok": False, "msg": "Authentification requise."}), 401
        return fn(*args, **kwargs)
    return wrapper


def admin_required_api(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        u = current_user()
        if not u:
            return jsonify({"ok": False, "msg": "Authentification requise."}), 401
        if not bool(u.get("is_admin", False)):
            return jsonify({"ok": False, "msg": "Acces administrateur requis."}), 403
        return fn(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------------------------
# UTILITAIRES .env
# ---------------------------------------------------------------------------
def read_env() -> dict:
    env = {}
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except Exception:
        pass
    return env

def write_env(data: dict) -> None:
    env = read_env()
    env.update(data)
    lines = []
    for k, v in env.items():
        lines.append(f"{k}={v}")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

# ---------------------------------------------------------------------------
# LECTURE LOG EN TEMPS REEL
# ---------------------------------------------------------------------------
def read_bot_output(proc):
    global log_buffer, bot_last_log_at, bot_error_count
    for line in iter(proc.stdout.readline, ""):
        clean = line.strip()
        if clean:
            bot_last_log_at = datetime.now()
            if "[ERROR]" in clean or "[CRITICAL]" in clean:
                bot_error_count += 1
            log_buffer.append({"time": datetime.now().strftime("%H:%M:%S"), "msg": clean})
            if len(log_buffer) > MAX_LOG_LINES:
                log_buffer = log_buffer[-MAX_LOG_LINES:]
    proc.stdout.close()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def mask_key(v: str) -> str:
    return (v[:8] + "..." + v[-4:]) if len(v) > 12 else ("***" if v else "")

# ---------------------------------------------------------------------------
# UTILITIES: 2FA, RATE-LIMIT, EMAIL, TELEGRAM
# ---------------------------------------------------------------------------

def check_login_rate_limit(username: str) -> bool:
    """Check if user has exceeded login attempts; returns True if ok, False if blocked."""
    global LOGIN_RATE_LIMIT
    now = time.time()
    username_lower = username.lower()
    
    if username_lower not in LOGIN_RATE_LIMIT:
        LOGIN_RATE_LIMIT[username_lower] = []
    
    # Remove old attempts outside the window
    LOGIN_RATE_LIMIT[username_lower] = [
        ts for ts in LOGIN_RATE_LIMIT[username_lower] 
        if now - ts < LOGIN_WINDOW_SEC
    ]
    
    if len(LOGIN_RATE_LIMIT[username_lower]) >= LOGIN_MAX_ATTEMPTS:
        return False
    
    # Record this attempt
    LOGIN_RATE_LIMIT[username_lower].append(now)
    return True

def record_login_attempt(username: str) -> None:
    """Record a login attempt for rate limiting."""
    global LOGIN_RATE_LIMIT
    username_lower = username.lower()
    if username_lower not in LOGIN_RATE_LIMIT:
        LOGIN_RATE_LIMIT[username_lower] = []
    LOGIN_RATE_LIMIT[username_lower].append(time.time())

def send_email_confirmation(email: str, token: str, username: str) -> bool:
    """Send email confirmation (mock - logs to console). Upgrade to real SMTP later."""
    print(f"[EMAIL] Confirmation token for {username} ({email}): {token}")
    try:
        # TODO: Integrate with SMTP (mailgun, sendgrid, etc)
        # For now, just log it
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False

def generate_totp_secret() -> str:
    """Generate a TOTP secret for 2FA (Google Authenticator compatible)."""
    return pyotp.random_base32()

def get_totp_uri(username: str, secret: str) -> str:
    """Get the provisioning URI for QR code."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name="Bot Trading Crypto")

def verify_totp(secret: str, token: str) -> bool:
    """Verify a TOTP token (6-digit code)."""
    try:
        if not GOOGLE_CLIENT_ID or not token:
        return totp.verify(token, valid_window=1)

        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": token},
            timeout=10,
        )
        if response.status_code != 200:
            return {}

        data = response.json()
        if data.get("aud") != GOOGLE_CLIENT_ID:
            return {}
        if data.get("iss") not in ["https://accounts.google.com", "accounts.google.com"]:
            return {}
        if data.get("email") and str(data.get("email_verified", "false")).lower() != "true":
            return {}

        exp = data.get("exp")
        if exp:
            try:
                if int(exp) <= int(time.time()):
                    return {}
            except (TypeError, ValueError):
                return {}

        return {
            "sub": data.get("sub", ""),
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
        }
    except requests.RequestException as e:
        print(f"[GOOGLE TOKEN NETWORK ERROR] {e}")
        return {}
    except Exception as e:
        print(f"[GOOGLE TOKEN VERIFY ERROR] {e}")
        return {}
    """Check if user has pro or enterprise access."""
    plan = get_subscription_plan(user)
    return plan in {"pro", "enterprise"}

def has_enterprise_features(user: dict) -> bool:
    """Check if user has enterprise access."""
    plan = get_subscription_plan(user)
    return plan == "enterprise"

def is_subscription_active(user: dict) -> bool:
    """Check if user's subscription is active and not expired."""
    if get_subscription_plan(user) == "free":
        return True
    expires = user.get("subscription_expires", "")
    if not expires:
        return False
    try:
        exp_dt = datetime.fromisoformat(expires)
        return datetime.now() < exp_dt
    except Exception:
        return False

# ---------------------------------------------------------------------------
# DEVICE AUTHORIZATION (Admin Access Control)
# ---------------------------------------------------------------------------
def generate_device_fingerprint(request_obj) -> str:
    """Generate a unique device fingerprint based on browser/OS/IP."""
    user_agent = request_obj.headers.get('User-Agent', '')
    ip_addr = request_obj.remote_addr or ''
    # Create hash of User-Agent + IP (simple fingerprint)
    fingerprint_str = f"{user_agent}|{ip_addr}"
    return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:32]

def is_device_authorized(username: str, device_id: str) -> bool:
    """Check if device is authorized for admin access."""
    try:
        db = load_users()
        for user in db.get("users", []):
            if user.get("username") == username and user.get("is_admin"):
                authorized_devices = user.get("authorized_devices", [])
                # Always require confirmation for new devices (even first time)
                return device_id in authorized_devices
        return False
    except Exception:
        return False

def register_device_for_user(username: str, device_id: str, device_name: str = "Device"):
    """Register a new device for admin user."""
    try:
        db = load_users()
        for user in db.get("users", []):
            if user.get("username") == username and user.get("is_admin"):
                if "authorized_devices" not in user:
                    user["authorized_devices"] = []
                if device_id not in user["authorized_devices"]:
                    user["authorized_devices"].append(device_id)
                    save_users(db)
                    return True
        return False
    except Exception:
        return False

# ---------------------------------------------------------------------------
# OAUTH & SOCIAL LOGIN
# ---------------------------------------------------------------------------
def verify_google_token(token: str) -> dict:
    """Verify Google ID token and return user info."""
    try:
        if not GOOGLE_CLIENT_ID or not token:
            return {}
        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": token},
            timeout=10,
        )
        if response.status_code != 200:
            return {}

        data = response.json()
        if data.get("aud") != GOOGLE_CLIENT_ID:
            return {}
        if data.get("iss") not in ["https://accounts.google.com", "accounts.google.com"]:
            return {}
        if data.get("email") and str(data.get("email_verified", "false")).lower() != "true":
            return {}

        exp = data.get("exp")
        if exp:
            try:
                if int(exp) <= int(time.time()):
                    return {}
            except (TypeError, ValueError):
                return {}

        return {
            "sub": data.get("sub", ""),
            "email": data.get("email", ""),
            "name": data.get("name", ""),
            "picture": data.get("picture", ""),
        }
    except requests.RequestException as e:
        print(f"[GOOGLE TOKEN NETWORK ERROR] {e}")
        return {}
    except Exception as e:
        print(f"[GOOGLE TOKEN VERIFY ERROR] {e}")
        return {}

def get_binance_account_value(api_key: str, api_secret: str) -> float:
    """Get total account value from Binance in EUR (mock for now)."""
    try:
        if not api_key or not api_secret or not BinanceClient:
            return 0.0
        client = BinanceClient(api_key=api_key, api_secret=api_secret)
        account = client.get_account()
        # Sum all balances converted to EUR (requires price data)
        return 1000.0  # Mock value
    except Exception as e:
        print(f"[BINANCE ERROR] {e}")
        return 0.0

def send_email_smtp(to_email: str, subject: str, html_body: str) -> bool:
    """Send email via SMTP (real implementation)."""
    try:
        if not SMTP_PASSWORD:
            return False
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(html_body, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"[SMTP ERROR] {e}")
        return False

def send_email_confirmation_real(email: str, token: str) -> bool:
    """Send real email confirmation (upgraded from mock)."""
    confirmation_url = f"http://localhost:5000/#/confirm/{token}"
    html = f"""
    <h2>Confirmation d'Email</h2>
    <p>Cliquez sur le lien ci-dessous pour confirmer votre adresse email:</p>
    <a href="{confirmation_url}">Confirmer mon email</a>
    <p>Lien: {confirmation_url}</p>
    """
    return send_email_smtp(email, "Confirmation d'Email - Bot Trading", html)

def get_whale_alerts() -> list:
    """Get recent whale/whale movement alerts from blockchain APIs (mock data)."""
    try:
        if not Web3:
            return []
        # Integration point: would use Etherscan API or custom blockchain indexer
        alerts = [
            {
                "timestamp": datetime.now().isoformat(),
                "token": "ETH",
                "amount_eur": 50000.0,
                "from_address": "0x1234...",
                "to_address": "0x5678...",
                "tx_hash": "0xabc...",
                "type": "transfer"
            }
        ]
        return alerts
    except Exception as e:
        print(f"[WHALE ALERTS ERROR] {e}")
        return []

def get_exchange_portfolio(exchange: str, api_key: str, api_secret: str) -> dict:
    """Get portfolio data from multiple exchanges via CCXT."""
    try:
        if not api_key or not api_secret:
            return {"balance": 0.0, "positions": []}
        
        # Create exchange instance
        if exchange.lower() == "binance":
            ccxt_exchange = ccxt.binance({"apiKey": api_key, "secret": api_secret})
        elif exchange.lower() == "coinbase":
            ccxt_exchange = ccxt.coinbase({"apiKey": api_key, "secret": api_secret})
        elif exchange.lower() == "kraken":
            ccxt_exchange = ccxt.kraken({"apiKey": api_key, "secret": api_secret})
        elif exchange.lower() == "kucoin":
            ccxt_exchange = ccxt.kucoin({"apiKey": api_key, "secret": api_secret})
        else:
            return {"balance": 0.0, "positions": []}
        
        balance = ccxt_exchange.fetch_balance()
        total = balance.get("total", {})
        total_eur = sum(f for c, f in total.items() if c in ["BTC", "ETH", "USDT"] and f > 0) * 1000  # Mock conversion
        
        return {
            "exchange": exchange,
            "balance": total_eur,
            "positions": list(total.keys())
        }
    except Exception as e:
        print(f"[EXCHANGE PORTFOLIO ERROR] {e}")
        return {"balance": 0.0, "positions": []}

# ---------------------------------------------------------------------------
# ROUTES PRINCIPALES
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/auth/register", methods=["POST"])
def api_auth_register():
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    signup_method = str(data.get("signup_method", "username")).strip().lower()
    email = str(data.get("email", "")).strip()
    phone = str(data.get("phone", "")).strip()
    binance_account = str(data.get("binance_account", "")).strip()

    if len(username) < 3 or len(username) > 32:
        return jsonify({"ok": False, "msg": "Nom d'utilisateur invalide (3-32 caracteres)."})
    if any(ch in username for ch in [" ", "\t", "\n", "/", "\\"]):
        return jsonify({"ok": False, "msg": "Nom d'utilisateur invalide."})
    password_error = validate_password_strength(password)
    if password_error:
        return jsonify({"ok": False, "msg": password_error})

    allowed_methods = {"username", "gmail", "google", "telephone", "binance"}
    if signup_method not in allowed_methods:
        signup_method = "username"

    if signup_method in {"gmail", "google"} and not email:
        return jsonify({"ok": False, "msg": "Email requis pour ce type de compte."})
    if signup_method == "telephone" and not phone:
        return jsonify({"ok": False, "msg": "Numero de telephone requis pour ce type de compte."})
    if signup_method == "binance" and not binance_account:
        return jsonify({"ok": False, "msg": "Identifiant compte Binance requis pour ce type de compte."})

    db = load_users()
    users = db.get("users", [])
    if any(str(u.get("username", "")).lower() == username.lower() for u in users):
        return jsonify({"ok": False, "msg": "Ce nom d'utilisateur existe deja."})

    users.append({
        "username": username,
        "password_hash": generate_password_hash(password),
        "is_admin": False,
        "created_at": now_str(),
        "last_login": None,
        "disabled": False,
        "signup_method": signup_method,
        "email": email,
        "phone": phone,
        "binance_account": binance_account,
    })
    db["users"] = users
    save_users(db)
    log_admin_event("system", "register_user", {"username": username})
    return jsonify({"ok": True, "msg": "Compte cree avec succes."})


@app.route("/api/auth/login", methods=["POST"])
def api_auth_login():
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    totp_code = str(data.get("totp_code", "")).strip()

    # Rate-limit check
    if not check_login_rate_limit(username):
        return jsonify({"ok": False, "msg": "Trop de tentatives. Ressayez dans 5 minutes."})

    u = find_user(username)
    if not u:
        record_login_attempt(username)
        return jsonify({"ok": False, "msg": "Identifiants invalides."})
    if bool(u.get("disabled", False)):
        record_login_attempt(username)
        return jsonify({"ok": False, "msg": "Identifiants invalides."})
    if not check_password_hash(u.get("password_hash", ""), password):
        record_login_attempt(username)
        return jsonify({"ok": False, "msg": "Identifiants invalides."})

    # 2FA check
    if bool(u.get("totp_enabled", False)):
        secret = u.get("totp_secret", "")
        if not secret or not totp_code:
            return jsonify({"ok": False, "msg": "Code 2FA requis.", "requires_2fa": True})
        if not verify_totp(secret, totp_code):
            return jsonify({"ok": False, "msg": "Code 2FA invalide."})

    session["username"] = u.get("username")
    u["last_login"] = now_str()
    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            item["last_login"] = u["last_login"]
            break
    save_users(db)
    log_admin_event(u.get("username", "unknown"), "login", {"is_admin": bool(u.get("is_admin", False)), "2fa": bool(u.get("totp_enabled"))})

    return jsonify({
        "ok": True,
        "msg": "Connexion reussie.",
        "user": {
            "username": u.get("username"),
            "is_admin": bool(u.get("is_admin", False)),
            "subscription_plan": u.get("subscription_plan", "free"),
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    username = session.get("username", "unknown")
    session.clear()
    log_admin_event(username, "logout", {})
    return jsonify({"ok": True, "msg": "Deconnexion reussie."})


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "logged_in": False})
    return jsonify({
        "ok": True,
        "logged_in": True,
        "user": {
            "username": u.get("username"),
            "is_admin": bool(u.get("is_admin", False)),
            "subscription_plan": u.get("subscription_plan", "free"),
            "has_2fa": bool(u.get("totp_enabled", False)),
        }
    })

# ---------------------------------------------------------------------------
# 2FA ENDPOINTS
# ---------------------------------------------------------------------------
@app.route("/api/auth/2fa/enable", methods=["POST"])
@login_required_api
def api_2fa_enable():
    """Generate TOTP secret and QR code for setup."""
    u = current_user()
    if bool(u.get("totp_enabled", False)):
        return jsonify({"ok": False, "msg": "2FA est deja activee."})

    secret = generate_totp_secret()
    uri = get_totp_uri(u.get("username", ""), secret)
    qr_base64 = generate_qr_code(uri)

    # Store temporarily in session
    session["pending_2fa_secret"] = secret

    return jsonify({
        "ok": True,
        "secret": secret,
        "uri": uri,
        "qr_code": qr_base64,
        "msg": "Scanned le QR code avec Google Authenticator ou Authy, puis confirmez."
    })

@app.route("/api/auth/2fa/verify", methods=["POST"])
@login_required_api
def api_2fa_verify():
    """Verify TOTP code and enable 2FA."""
    data = request.get_json() or {}
    totp_code = str(data.get("totp_code", "")).strip()
    secret = session.get("pending_2fa_secret", "")

    if not secret:
        return jsonify({"ok": False, "msg": "Pas de secret pending. Re-generez d'abord."})
    if not totp_code or len(totp_code) != 6:
        return jsonify({"ok": False, "msg": "Code invalide (6 digits attendus)."})

    if not verify_totp(secret, totp_code):
        return jsonify({"ok": False, "msg": "Code incorrect."})

    # Save to user
    u = current_user()
    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            item["totp_secret"] = secret
            item["totp_enabled"] = True
            break
    save_users(db)
    session.pop("pending_2fa_secret", None)
    log_admin_event(u.get("username"), "2fa_enabled", {})

    return jsonify({"ok": True, "msg": "2FA activee avec succes !"})

@app.route("/api/auth/2fa/disable", methods=["POST"])
@login_required_api
def api_2fa_disable():
    """Disable 2FA."""
    data = request.get_json() or {}
    password = str(data.get("password", "")).strip()

    u = current_user()
    if not check_password_hash(u.get("password_hash", ""), password):
        return jsonify({"ok": False, "msg": "Mot de passe incorrect."})

    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            item["totp_secret"] = ""
            item["totp_enabled"] = False
            break
    save_users(db)
    log_admin_event(u.get("username"), "2fa_disabled", {})

    return jsonify({"ok": True, "msg": "2FA desactivee."})

# ---------------------------------------------------------------------------
# SUBSCRIPTION ENDPOINTS
# ---------------------------------------------------------------------------
@app.route("/api/subscription/info", methods=["GET"])
@login_required_api
def api_subscription_info():
    """Get user's subscription info."""
    u = current_user()
    plan = get_subscription_plan(u)
    active = is_subscription_active(u)
    expires = u.get("subscription_expires", "")

    plans_info = {
        "free": {
            "name": "Free",
            "price": "0€/mois",
            "features": ["5 paires max", "1 trade/heure", "Mode simulation", "Backtest basique"],
            "upgrade_to_pro_price_eur": 49,
        },
        "pro": {
            "name": "Pro",
            "price": "49€/mois",
            "features": ["Illimite paires", "Alertes Telegram/Discord", "DCA + Take-profit", "API webhooks", "2FA"],
            "upgrade_to_enterprise_price_eur": 199,
        },
        "enterprise": {
            "name": "Enterprise",
            "price": "199€/mois",
            "features": ["Tout du Pro", "4+ exchanges", "On-chain data", "Support Slack 24/7", "White-label"],
            "upgrade_available": False,
        },
    }

    return jsonify({
        "ok": True,
        "subscription": {
            "plan": plan,
            "active": active,
            "expires": expires,
            "info": plans_info.get(plan, {}),
        },
        "all_plans": plans_info,
        "google_client_id": GOOGLE_CLIENT_ID,
    })

@app.route("/api/public/google-client-id", methods=["GET"])
def api_public_google_client_id():
    """Get Google Client ID (public, no auth required)."""
    return jsonify({
        "ok": True,
        "google_client_id": GOOGLE_CLIENT_ID or ""
    })

@app.route("/api/public/stripe-config", methods=["GET"])
def api_public_stripe_config():
    """Get Stripe public key (public, no auth required)."""
    return jsonify({
        "ok": True,
        "stripe_public_key": STRIPE_PUBLIC_KEY or ""
    })

@app.route("/api/payment/process", methods=["POST"])
@login_required_api
def api_payment_process():
    """Process payment securely with Stripe."""
    if not stripe or not STRIPE_SECRET_KEY:
        return jsonify({"ok": False, "msg": "Paiement non disponible"})
    
    data = request.get_json() or {}
    payment_method_id = str(data.get("payment_method_id", "")).strip()
    plan = str(data.get("plan", "")).strip().lower()
    amount_eur = int(data.get("amount_eur", 0))
    email = str(data.get("email", "")).strip()
    
    # Validate
    if not payment_method_id or plan not in {"pro", "enterprise"}:
        return jsonify({"ok": False, "msg": "Données invalides"})
    
    if not email or "@" not in email:
        return jsonify({"ok": False, "msg": "Email invalide"})
    
    # Validate amount matches plan
    valid_amounts = {"pro": 4900, "enterprise": 19900}  # in cents
    if amount_eur * 100 != valid_amounts.get(plan, 0):
        return jsonify({"ok": False, "msg": "Montant invalide"})
    
    u = current_user()
    
    try:
        # Create charge with Stripe
        charge = stripe.Charge.create(
            amount=amount_eur * 100,  # Convert to cents
            currency="eur",
            payment_method=payment_method_id,
            confirm=True,
            description=f"Upgrade to {plan.upper()} - {u.get('username')}",
            metadata={
                "username": u.get("username"),
                "plan": plan,
                "email": email
            },
            off_session=False
        )
        
        if charge.status != "succeeded":
            return jsonify({"ok": False, "msg": "Paiement refusé"})
        
        # Update user subscription
        db = load_users()
        for item in db.get("users", []):
            if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
                item["subscription_plan"] = plan
                item["subscription_expires"] = (datetime.now() + timedelta(days=30)).isoformat()
                item["stripe_customer_id"] = charge.customer or ""
                break
        
        save_users(db)
        
        # Log audit
        log_audit(u.get("username"), f"payment_successful", f"Upgraded to {plan}")
        
        return jsonify({
            "ok": True,
            "msg": f"Paiement reçu ! Bienvenue en {plan.upper()}",
            "plan": plan,
            "expires": item.get("subscription_expires")
        })
        
    except stripe.error.CardError as e:
        return jsonify({"ok": False, "msg": f"Carte refusée: {e.user_message}"})
    except stripe.error.StripeException as e:
        log_audit(u.get("username"), f"payment_failed", f"Stripe error: {str(e)}")
        return jsonify({"ok": False, "msg": "Erreur de paiement. Réessayez."})

@app.route("/api/subscription/upgrade", methods=["POST"])
@login_required_api
def api_subscription_upgrade():
    """Upgrade to a plan (mock - no payment integration yet)."""
    data = request.get_json() or {}
    target_plan = str(data.get("plan", "")).strip().lower()

    if target_plan not in {"pro", "enterprise"}:
        return jsonify({"ok": False, "msg": "Plan invalide."})

    u = current_user()
    current_plan = get_subscription_plan(u)

    if current_plan == target_plan:
        return jsonify({"ok": False, "msg": "Vous etes deja sur ce plan."})

    # TODO: Integrate with Stripe or PayPal for real payment
    # For now, just accept the upgrade (mock)
    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            item["subscription_plan"] = target_plan
            # Set expiration to 1 month from now
            expires = (datetime.now() + timedelta(days=30)).isoformat()
            item["subscription_expires"] = expires
            break
    save_users(db)
    log_admin_event(u.get("username"), "subscription_upgraded", {"plan": target_plan})

    return jsonify({
        "ok": True,
        "msg": f"Bienvenue sur le plan {target_plan.upper()} !",
        "expires": (datetime.now() + timedelta(days=30)).isoformat(),
    })

# ---------------------------------------------------------------------------
# ALERTS ENDPOINTS (Telegram, Discord)
# ---------------------------------------------------------------------------
@app.route("/api/alerts/telegram/test", methods=["POST"])
@login_required_api
def api_alerts_telegram_test():
    """Send a test message to Telegram."""
    data = request.get_json() or {}
    chat_id = str(data.get("chat_id", "")).strip()
    bot_token = str(data.get("bot_token", "")).strip()

    if not chat_id or not bot_token:
        return jsonify({"ok": False, "msg": "chat_id et bot_token requis."})

    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": "✅ Test message from Bot Trading Crypto",
        }
        resp = requests.post(url, json=payload, timeout=5)
        if resp.status_code == 200:
            # Save to user
            u = current_user()
            db = load_users()
            for item in db.get("users", []):
                if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
                    item["telegram_chat_id"] = chat_id
                    item["telegram_alerts_enabled"] = True
                    break
            save_users(db)
            return jsonify({"ok": True, "msg": "Test envoye avec succes !"})
        else:
            return jsonify({"ok": False, "msg": "Erreur Telegram: " + resp.text})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erreur: {str(e)}"})

@app.route("/api/alerts/discord/test", methods=["POST"])
@login_required_api
def api_alerts_discord_test():
    """Send a test message to Discord."""
    data = request.get_json() or {}
    webhook_url = str(data.get("webhook_url", "")).strip()

    if not webhook_url:
        return jsonify({"ok": False, "msg": "webhook_url requis."})

    try:
        payload = {"content": "✅ Test message from Bot Trading Crypto"}
        resp = requests.post(webhook_url, json=payload, timeout=5)
        if resp.status_code == 200:
            # Save to user
            u = current_user()
            db = load_users()
            for item in db.get("users", []):
                if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
                    item["discord_webhook"] = webhook_url
                    item["discord_alerts_enabled"] = True
                    break
            save_users(db)
            return jsonify({"ok": True, "msg": "Test envoye avec succes !"})
        else:
            return jsonify({"ok": False, "msg": "Erreur Discord: " + resp.text})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erreur: {str(e)}"})

@app.route("/api/alerts/toggle", methods=["POST"])
@login_required_api
def api_alerts_toggle():
    """Enable/disable alerts for telegram and discord."""
    data = request.get_json() or {}
    toggle_telegram = data.get("telegram_enabled")
    toggle_discord = data.get("discord_enabled")

    u = current_user()
    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            if toggle_telegram is not None:
                item["telegram_alerts_enabled"] = bool(toggle_telegram)
            if toggle_discord is not None:
                item["discord_alerts_enabled"] = bool(toggle_discord)
            break
    save_users(db)
    return jsonify({"ok": True, "msg": "Alertes mises a jour."})


@app.route("/api/admin/stats", methods=["GET"])
@admin_required_api
def api_admin_stats():
    db = load_users()
    users = db.get("users", [])
    total_users = len(users)
    admin_count = sum(1 for u in users if bool(u.get("is_admin", False)))
    active_count = sum(1 for u in users if not bool(u.get("disabled", False)))

    recent_users = sorted(users, key=lambda x: str(x.get("created_at", "")), reverse=True)[:10]
    recent_users_public = [
        {
            "username": u.get("username"),
            "is_admin": bool(u.get("is_admin", False)),
            "created_at": u.get("created_at"),
            "last_login": u.get("last_login"),
            "disabled": bool(u.get("disabled", False)),
        }
        for u in recent_users
    ]

    nb_trades = 0
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            nb_trades = max(0, sum(1 for _ in f) - 1)
    except Exception:
        pass

    running = bot_process is not None and bot_process.poll() is None
    return jsonify({
        "ok": True,
        "stats": {
            "total_users": total_users,
            "admin_users": admin_count,
            "active_users": active_count,
            "trades_logged": nb_trades,
            "bot_running": running,
            "bot_errors": bot_error_count,
            "server_time": now_str(),
        },
        "recent_users": recent_users_public,
        "recent_audit": read_admin_audit(20),
    })


@app.route("/api/admin/change-password", methods=["POST"])
@admin_required_api
def api_admin_change_password():
    u = current_user()
    data = request.get_json() or {}
    old_password = str(data.get("old_password", "")).strip()
    new_password = str(data.get("new_password", "")).strip()

    if str(u.get("username", "")) != ADMIN_USERNAME:
        return jsonify({"ok": False, "msg": "Action reservee au compte administrateur principal."}), 403
    password_error = validate_password_strength(new_password, admin=True)
    if password_error:
        return jsonify({"ok": False, "msg": password_error})
    if not check_password_hash(u.get("password_hash", ""), old_password):
        return jsonify({"ok": False, "msg": "Ancien mot de passe invalide."})

    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == ADMIN_USERNAME.lower():
            item["password_hash"] = generate_password_hash(new_password)
            break
    save_users(db)
    log_admin_event(ADMIN_USERNAME, "change_admin_password", {})
    return jsonify({"ok": True, "msg": "Mot de passe admin mis a jour."})


@app.route("/api/admin/user-status", methods=["POST"])
@admin_required_api
def api_admin_user_status():
    actor = current_user()
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip()
    disabled = bool(data.get("disabled", False))

    if not username:
        return jsonify({"ok": False, "msg": "username requis."})
    if username.lower() == ADMIN_USERNAME.lower():
        return jsonify({"ok": False, "msg": "Le compte administrateur principal ne peut pas etre desactive."})

    db = load_users()
    changed = False
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == username.lower():
            item["disabled"] = disabled
            changed = True
            break

    if not changed:
        return jsonify({"ok": False, "msg": "Utilisateur introuvable."})

    save_users(db)
    log_admin_event(actor.get("username", "admin"), "set_user_status", {"username": username, "disabled": disabled})
    return jsonify({"ok": True, "msg": "Statut utilisateur mis a jour."})


@app.route("/api/admin/reset-user-password", methods=["POST"])
@admin_required_api
def api_admin_reset_user_password():
    actor = current_user()
    data = request.get_json() or {}
    username = str(data.get("username", "")).strip()
    new_password = str(data.get("new_password", "")).strip()

    if not username:
        return jsonify({"ok": False, "msg": "username requis."})
    password_error = validate_password_strength(new_password)
    if password_error:
        return jsonify({"ok": False, "msg": password_error})

    db = load_users()
    target = None
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == username.lower():
            target = item
            break

    if not target:
        return jsonify({"ok": False, "msg": "Utilisateur introuvable."})

    # Protection: ne pas toucher les comptes admin via cette route
    if bool(target.get("is_admin", False)):
        return jsonify({"ok": False, "msg": "Impossible de reinitialiser un compte admin avec cette action."})

    target["password_hash"] = generate_password_hash(new_password)
    save_users(db)
    log_admin_event(actor.get("username", "admin"), "reset_user_password", {"username": username})
    return jsonify({"ok": True, "msg": "Mot de passe utilisateur reinitialise."})


@app.route("/api/admin/audit", methods=["GET"])
@admin_required_api
def api_admin_audit():
    limit = request.args.get("limit", "50")
    try:
        limit_n = max(1, min(500, int(limit)))
    except ValueError:
        limit_n = 50
    return jsonify({"ok": True, "events": read_admin_audit(limit_n)})

@app.route("/api/admin/devices", methods=["GET"])
@admin_required_api
def api_admin_devices():
    """List all authorized devices for current admin."""
    username = session.get("username")
    db = load_users()
    for user in db.get("users", []):
        if user.get("username") == username and user.get("is_admin"):
            devices = user.get("authorized_devices", [])
            return jsonify({"ok": True, "devices": devices, "count": len(devices)})
    return jsonify({"ok": False, "msg": "Admin not found"})

@app.route("/api/admin/devices/register", methods=["POST"])
def api_admin_register_device():
    """Register a new device for admin (requires password verification)."""
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")
    device_name = data.get("device_name", "New Device")
    
    try:
        db = load_users()
        user = next((u for u in db.get("users", []) if u.get("username") == username), None)
        
        if not user or not user.get("is_admin"):
            return jsonify({"ok": False, "msg": "Not an admin account"})
        
        if not check_password_hash(user.get("password_hash", ""), password):
            return jsonify({"ok": False, "msg": "Invalid password"})
        
        # Generate device ID
        device_id = generate_device_fingerprint(request)
        
        # Register device
        if "authorized_devices" not in user:
            user["authorized_devices"] = []
        
        if device_id not in user["authorized_devices"]:
            user["authorized_devices"].append(device_id)
            save_users(db)
            log_audit(username, "device_registered", f"Device registered: {device_name}")
        
        return jsonify({"ok": True, "msg": "Device registered successfully", "device_id": device_id})
    except Exception as e:
        print(f"[DEVICE REGISTER ERROR] {e}")
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/status")
@login_required_api
def api_status():
    global bot_process, bot_started_at, bot_last_log_at, bot_error_count
    running = bot_process is not None and bot_process.poll() is None
    portfolio = {"solde_eur": 0, "positions": {}, "statistiques": {}}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception:
        pass
    valeur_totale = portfolio.get("solde_eur", 0)
    nb_trades = 0
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            nb_trades = max(0, sum(1 for _ in f) - 1)
    except Exception:
        pass
    historique = portfolio.get("historique_valeur", [])[-30:]
    if historique:
        peak = max(float(x.get("valeur_totale_eur", 0)) for x in historique)
        cur = float(historique[-1].get("valeur_totale_eur", 0))
        drawdown = ((cur - peak) / peak * 100) if peak > 0 else 0.0
    else:
        drawdown = 0.0

    uptime_sec = 0
    if running and bot_started_at:
        uptime_sec = int((datetime.now() - bot_started_at).total_seconds())

    env = read_env()
    return jsonify({
        "running":        running,
        "solde_eur":      round(portfolio.get("solde_eur", 0), 2),
        "valeur_totale":  round(valeur_totale, 2),
        "positions":      portfolio.get("positions", {}),
        "statistiques":   portfolio.get("statistiques", {}),
        "nb_trades":      nb_trades,
        "historique":     historique,
        "progression":    round((valeur_totale / 10000) * 100, 1),
        "drawdown_pct":   round(drawdown, 2),
        "mode_simulation": env.get("MODE_SIMULATION", "True") != "False",
        "top_n_markets":  int(env.get("TOP_N_MARKETS", 100)),
        "health": {
            "running": running,
            "pid": bot_process.pid if running and bot_process else None,
            "uptime_sec": uptime_sec,
            "last_log_at": bot_last_log_at.strftime("%H:%M:%S") if bot_last_log_at else None,
            "error_count": bot_error_count,
            "last_log": log_buffer[-1]["msg"] if log_buffer else "",
        }
    })

@app.route("/api/logs")
@login_required_api
def api_logs():
    return jsonify({"logs": log_buffer[-100:]})

@app.route("/api/start", methods=["POST"])
@login_required_api
def api_start():
    global bot_process, log_buffer, bot_started_at, bot_last_log_at, bot_error_count
    with bot_lock:
        if bot_process is not None and bot_process.poll() is None:
            return jsonify({"ok": False, "msg": "Le bot tourne deja."})
        try:
            log_buffer  = []
            bot_error_count = 0
            bot_process = subprocess.Popen(
                ["python", "-u", BOT_SCRIPT],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=BASE_DIR,
            )
            bot_started_at = datetime.now()
            bot_last_log_at = bot_started_at
            threading.Thread(target=read_bot_output, args=(bot_process,), daemon=True).start()
            return jsonify({"ok": True, "msg": "Bot demarre !"})
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/stop", methods=["POST"])
@login_required_api
def api_stop():
    global bot_process
    with bot_lock:
        if bot_process is None or bot_process.poll() is not None:
            return jsonify({"ok": False, "msg": "Le bot ne tourne pas."})
        try:
            bot_process.terminate()
            bot_process.wait(timeout=5)
            bot_process = None
            return jsonify({"ok": True, "msg": "Bot arrete."})
        except Exception as e:
            return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/journal")
@login_required_api
def api_journal():
    trades = []
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 1:
            headers = lines[0].strip().split(",")
            for line in reversed(lines[1:]):
                if line.strip():
                    trades.append(dict(zip(headers, line.strip().split(",", len(headers)-1))))
                if len(trades) >= 20:
                    break
    except Exception:
        pass
    return jsonify({"trades": trades})

# ---------------------------------------------------------------------------
# ROUTE PARAMETRES - LECTURE
# ---------------------------------------------------------------------------
@app.route("/api/settings", methods=["GET"])
@login_required_api
def api_settings_get():
    env = read_env()
    def mask(k):
        v = env.get(k, "")
        return mask_key(v)
    def isset(k):
        return bool(env.get(k, ""))
    return jsonify({
        "ai_provider":          env.get("AI_PROVIDER",  "deepseek"),
        "ai_model":             env.get("AI_MODEL",     "deepseek-chat"),
        "deepseek_key_set":     isset("DEEPSEEK_API_KEY"),
        "deepseek_key_masked":  mask("DEEPSEEK_API_KEY"),
        "openai_key_set":       isset("OPENAI_API_KEY"),
        "openai_key_masked":    mask("OPENAI_API_KEY"),
        "anthropic_key_set":    isset("ANTHROPIC_API_KEY"),
        "anthropic_key_masked": mask("ANTHROPIC_API_KEY"),
        "gemini_key_set":       isset("GEMINI_API_KEY"),
        "gemini_key_masked":    mask("GEMINI_API_KEY"),
        "mistral_key_set":      isset("MISTRAL_API_KEY"),
        "mistral_key_masked":   mask("MISTRAL_API_KEY"),
        "groq_key_set":         isset("GROQ_API_KEY"),
        "groq_key_masked":      mask("GROQ_API_KEY"),
        "xai_key_set":          isset("XAI_API_KEY"),
        "xai_key_masked":       mask("XAI_API_KEY"),
        "top_n_markets":        int(env.get("TOP_N_MARKETS", 100)),
        "mode_simulation":      env.get("MODE_SIMULATION", "True") != "False",
        "risk_daily_stop_enabled":      env.get("RISK_DAILY_STOP_ENABLED", "True") == "True",
        "risk_daily_stop_pct":          float(env.get("RISK_DAILY_STOP_PCT", "3.0")),
        "risk_max_trades_hour_enabled": env.get("RISK_MAX_TRADES_HOUR_ENABLED", "True") == "True",
        "risk_max_trades_per_hour":     int(env.get("RISK_MAX_TRADES_PER_HOUR", "6")),
        "risk_vol_filter_enabled":      env.get("RISK_VOL_FILTER_ENABLED", "True") == "True",
        "risk_max_volatility_pct":      float(env.get("RISK_MAX_VOLATILITY_PCT", "12.0")),
        "risk_spread_filter_enabled":   env.get("RISK_SPREAD_FILTER_ENABLED", "True") == "True",
        "risk_max_spread_pct":          float(env.get("RISK_MAX_SPREAD_PCT", "1.0")),
        "decision_dual_validation_enabled": env.get("DECISION_DUAL_VALIDATION_ENABLED", "True") == "True",
        "decision_log_prompts_enabled":     env.get("DECISION_LOG_PROMPTS_ENABLED", "True") == "True",
        "scan_parallel_workers":            int(env.get("SCAN_PARALLEL_WORKERS", "6")),
        "binance_key_set":      isset("BINANCE_API_KEY"),
        "binance_secret_set":   isset("BINANCE_API_SECRET"),
    })

# ---------------------------------------------------------------------------
# ROUTE PARAMETRES - SAUVEGARDE
# ---------------------------------------------------------------------------
@app.route("/api/settings", methods=["POST"])
@login_required_api
def api_settings_post():
    data = request.get_json() or {}
    to_save = {}

    if "ai_provider" in data and str(data["ai_provider"]).strip():
        to_save["AI_PROVIDER"] = str(data["ai_provider"]).strip()

    if "ai_model" in data and str(data["ai_model"]).strip():
        to_save["AI_MODEL"] = str(data["ai_model"]).strip()

    # Cles API pour chaque fournisseur IA
    for env_key, data_key in [
        ("DEEPSEEK_API_KEY",  "deepseek_api_key"),
        ("OPENAI_API_KEY",    "openai_api_key"),
        ("ANTHROPIC_API_KEY", "anthropic_api_key"),
        ("GEMINI_API_KEY",    "gemini_api_key"),
        ("MISTRAL_API_KEY",   "mistral_api_key"),
        ("GROQ_API_KEY",      "groq_api_key"),
        ("XAI_API_KEY",       "xai_api_key"),
    ]:
        if data_key in data and str(data[data_key]).strip():
            to_save[env_key] = str(data[data_key]).strip()

    if "top_n_markets" in data:
        val = int(data["top_n_markets"])
        val = max(20, min(300, val))  # Borne : 20 minimum, 300 maximum
        to_save["TOP_N_MARKETS"] = str(val)

    if "binance_api_key" in data and data["binance_api_key"].strip():
        to_save["BINANCE_API_KEY"] = data["binance_api_key"].strip()

    if "binance_api_secret" in data and data["binance_api_secret"].strip():
        to_save["BINANCE_API_SECRET"] = data["binance_api_secret"].strip()

    if "mode_simulation" in data:
        to_save["MODE_SIMULATION"] = "False" if data["mode_simulation"] is False else "True"

    # Risque (toggle + valeurs)
    bool_fields = [
        ("RISK_DAILY_STOP_ENABLED", "risk_daily_stop_enabled"),
        ("RISK_MAX_TRADES_HOUR_ENABLED", "risk_max_trades_hour_enabled"),
        ("RISK_VOL_FILTER_ENABLED", "risk_vol_filter_enabled"),
        ("RISK_SPREAD_FILTER_ENABLED", "risk_spread_filter_enabled"),
        ("DECISION_DUAL_VALIDATION_ENABLED", "decision_dual_validation_enabled"),
        ("DECISION_LOG_PROMPTS_ENABLED", "decision_log_prompts_enabled"),
    ]
    for env_key, data_key in bool_fields:
        if data_key in data:
            to_save[env_key] = "True" if bool(data[data_key]) else "False"

    if "risk_daily_stop_pct" in data:
        val = float(data["risk_daily_stop_pct"])
        val = max(0.1, min(50.0, val))
        to_save["RISK_DAILY_STOP_PCT"] = f"{val:.2f}"

    if "risk_max_trades_per_hour" in data:
        val = int(data["risk_max_trades_per_hour"])
        val = max(1, min(100, val))
        to_save["RISK_MAX_TRADES_PER_HOUR"] = str(val)

    if "risk_max_volatility_pct" in data:
        val = float(data["risk_max_volatility_pct"])
        val = max(0.5, min(200.0, val))
        to_save["RISK_MAX_VOLATILITY_PCT"] = f"{val:.3f}"

    if "risk_max_spread_pct" in data:
        val = float(data["risk_max_spread_pct"])
        val = max(0.01, min(50.0, val))
        to_save["RISK_MAX_SPREAD_PCT"] = f"{val:.3f}"

    if "scan_parallel_workers" in data:
        val = int(data["scan_parallel_workers"])
        val = max(1, min(20, val))
        to_save["SCAN_PARALLEL_WORKERS"] = str(val)

    if not to_save:
        return jsonify({"ok": False, "msg": "Aucun parametre a sauvegarder."})

    write_env(to_save)
    return jsonify({"ok": True, "msg": "Parametres sauvegardes ! Redemarrez le bot pour appliquer.", "saved": list(to_save.keys())})

# ---------------------------------------------------------------------------
# DCA & TAKE-PROFIT SETTINGS
# ---------------------------------------------------------------------------
@app.route("/api/strategy/dca/config", methods=["GET"])
@login_required_api
def api_strategy_dca_config_get():
    """Get DCA configuration for user."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise."})
    
    return jsonify({
        "ok": True,
        "dca": {
            "enabled": u.get("dca_enabled", False),
            "amount_eur": u.get("dca_amount", 100.0),
            "interval_hours": u.get("dca_interval_hours", 24),
        }
    })

@app.route("/api/strategy/dca/config", methods=["POST"])
@login_required_api
def api_strategy_dca_config_set():
    """Update DCA configuration."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise."})
    
    data = request.get_json() or {}
    enabled = bool(data.get("enabled", False))
    amount = float(data.get("amount_eur", 100.0))
    interval = int(data.get("interval_hours", 24))

    amount = max(10.0, min(10000.0, amount))
    interval = max(1, min(168, interval))  # 1h to 7 days

    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            item["dca_enabled"] = enabled
            item["dca_amount"] = amount
            item["dca_interval_hours"] = interval
            break
    save_users(db)
    log_admin_event(u.get("username"), "dca_config_updated", {"enabled": enabled, "amount": amount})

    return jsonify({"ok": True, "msg": "Configuration DCA mises a jour !"})

@app.route("/api/strategy/takeprofit/config", methods=["GET"])
@login_required_api
def api_strategy_tp_config_get():
    """Get Take-Profit configuration for user."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise."})
    
    return jsonify({
        "ok": True,
        "take_profit": {
            "percentage": u.get("take_profit_pct", 10.0),
        }
    })

@app.route("/api/strategy/takeprofit/config", methods=["POST"])
@login_required_api
def api_strategy_tp_config_set():
    """Update Take-Profit configuration."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise."})
    
    data = request.get_json() or {}
    tp_pct = float(data.get("percentage", 10.0))
    tp_pct = max(0.1, min(500.0, tp_pct))

    db = load_users()
    for item in db.get("users", []):
        if str(item.get("username", "")).lower() == str(u.get("username", "")).lower():
            item["take_profit_pct"] = tp_pct
            break
    save_users(db)
    log_admin_event(u.get("username"), "take_profit_updated", {"percentage": tp_pct})

    return jsonify({"ok": True, "msg": "Configuration Take-Profit mises a jour !"})

# ---------------------------------------------------------------------------
# ADVANCED STATISTICS & ANALYTICS
# ---------------------------------------------------------------------------
@app.route("/api/stats/detailed", methods=["GET"])
@login_required_api
def api_stats_detailed():
    """Get detailed statistics and analytics."""
    portfolio = {"solde_eur": 0, "positions": {}, "statistiques": {}, "historique_valeur": []}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception:
        pass

    historique = portfolio.get("historique_valeur", [])
    trades = []
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > 1:
            headers = lines[0].strip().split(",")
            for line in lines[1:]:
                if line.strip():
                    try:
                        trades.append(dict(zip(headers, line.strip().split(",", len(headers)-1))))
                    except Exception:
                        continue
    except Exception:
        pass

    # Calculate statistics
    win_count = 0
    loss_count = 0
    total_profit = 0.0
    for trade in trades:
        try:
            amount = float(trade.get("montant_eur", 0))
            if amount > 0:
                win_count += 1
                total_profit += amount
            elif amount < 0:
                loss_count += 1
                total_profit += amount
        except Exception:
            continue

    win_rate = (win_count / (win_count + loss_count) * 100) if (win_count + loss_count) > 0 else 0
    avg_profit_per_trade = (total_profit / len(trades)) if len(trades) > 0 else 0

    # Volatility over time
    returns = []
    if len(historique) > 1:
        for i in range(1, len(historique)):
            v_prev = float(historique[i-1].get("valeur_totale_eur", 0))
            v_curr = float(historique[i].get("valeur_totale_eur", 0))
            if v_prev > 0:
                ret = ((v_curr - v_prev) / v_prev) * 100
                returns.append(ret)

    volatility = float(np.std(returns)) if returns else 0
    sharpe = (np.mean(returns) / volatility) if volatility > 0 and returns else 0

    return jsonify({
        "ok": True,
        "stats": {
            "total_trades": len(trades),
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate_pct": round(win_rate, 2),
            "total_profit_eur": round(total_profit, 2),
            "avg_profit_per_trade": round(avg_profit_per_trade, 2),
            "volatility_pct": round(volatility, 2),
            "sharpe_ratio": round(sharpe, 3),
            "current_value_eur": round(portfolio.get("solde_eur", 0), 2),
            "daily_change_pct": round((returns[-1] if returns else 0), 2),
        },
        "trades_last_30": trades[-30:],
    })

@app.route("/api/journal/export")
@login_required_api
def api_journal_export():
    if not os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "action", "symbole", "prix_eur", "montant_eur", "raison"])
    return send_file(JOURNAL_FILE, as_attachment=True, download_name="journal_trading.csv")


@app.route("/api/test-ai-key", methods=["POST"])
@login_required_api
def api_test_ai_key():
    data = request.get_json() or {}
    provider = str(data.get("provider", "")).strip().lower()
    model = str(data.get("model", "")).strip()
    api_key = str(data.get("api_key", "")).strip()

    if not provider or not model or not api_key:
        return jsonify({"ok": False, "msg": "provider, model et api_key sont requis."})

    try:
        if provider == "anthropic":
            try:
                import anthropic  # type: ignore
            except ImportError:
                return jsonify({"ok": False, "msg": "Package anthropic non installe (pip install anthropic)."})
            client = anthropic.Anthropic(api_key=api_key)
            client.messages.create(
                model=model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
        else:
            base_map = {
                "deepseek": "https://api.deepseek.com",
                "openai": None,
                "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
                "mistral": "https://api.mistral.ai/v1",
                "groq": "https://api.groq.com/openai/v1",
                "xai": "https://api.x.ai/v1",
            }
            base_url = base_map.get(provider)
            client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
            client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Return exactly: pong"}],
                max_tokens=10,
                temperature=0,
            )
        return jsonify({"ok": True, "msg": "Cle API valide (test reussi)."})
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Test echoue: {e}"})


@app.route("/api/backtest", methods=["POST"])
@login_required_api
def api_backtest():
    data = request.get_json() or {}
    symbol = str(data.get("symbol", "BTC/USDT"))
    timeframe = str(data.get("timeframe", "1h"))
    limit = int(data.get("limit", 300))
    limit = max(100, min(1000, limit))
    buy_rsi = float(data.get("buy_rsi", 30))
    sell_rsi = float(data.get("sell_rsi", 70))

    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 50:
            return jsonify({"ok": False, "msg": "Donnees insuffisantes pour backtest."})

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["rsi"] = compute_rsi(df["close"], 14)

        cash = 10000.0
        qty = 0.0
        trades = 0
        wins = 0
        last_buy_price = None
        curve = []
        buy_hold_curve = []
        labels = []
        first_close = float(df["close"].iloc[0])

        for _, row in df.iterrows():
            close = float(row["close"])
            rsi = float(row["rsi"]) if not pd.isna(row["rsi"]) else None
            ts = datetime.utcfromtimestamp(float(row["timestamp"]) / 1000.0).strftime("%m-%d %H:%M")
            labels.append(ts)
            if rsi is None:
                curve.append(cash + qty * close)
                buy_hold_curve.append((10000.0 / first_close) * close)
                continue

            if rsi < buy_rsi and cash >= 20:
                invest = cash * 0.25
                buy_qty = invest / close
                qty += buy_qty
                cash -= invest
                trades += 1
                last_buy_price = close
            elif rsi > sell_rsi and qty > 0:
                proceeds = qty * close
                cash += proceeds
                if last_buy_price and close > last_buy_price:
                    wins += 1
                qty = 0.0
                trades += 1

            curve.append(cash + qty * close)
            buy_hold_curve.append((10000.0 / first_close) * close)

        final_value = curve[-1] if curve else 10000.0
        perf_pct = ((final_value - 10000.0) / 10000.0) * 100.0
        peak = max(curve) if curve else final_value
        trough = min(curve) if curve else final_value
        drawdown_pct = ((trough - peak) / peak * 100.0) if peak > 0 else 0.0
        winrate = (wins / trades * 100.0) if trades > 0 else 0.0

        return jsonify({
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "candles": len(df),
            "total_trades": trades,
            "winrate_pct": round(winrate, 2),
            "final_value": round(final_value, 2),
            "perf_pct": round(perf_pct, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "buy_hold_pct": round(((float(df["close"].iloc[-1]) - float(df["close"].iloc[0])) / float(df["close"].iloc[0])) * 100.0, 2),
            "equity_curve": [round(v, 2) for v in curve],
            "buy_hold_curve": [round(v, 2) for v in buy_hold_curve],
            "labels": labels,
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

# ---------------------------------------------------------------------------
# OAUTH & SOCIAL LOGIN
# ---------------------------------------------------------------------------
@app.route("/api/oauth/google/callback", methods=["POST"])
def api_oauth_google_callback():
    """Handle Google OAuth callback and token exchange."""
    try:
        data = request.get_json() or {}
        token = data.get("id_token", "")
        
        user_info = verify_google_token(token)
        if not user_info:
            return jsonify({"ok": False, "msg": "Invalid Google token"})
        
        google_id = user_info.get("sub", "")
        google_email = user_info.get("email", "")
        
        db = load_users()
        existing = None
        for u in db.get("users", []):
            if u.get("google_id") == google_id:
                existing = u
                break
        
        if existing:
            # Login existing Google user
            session["username"] = existing.get("username")
            return jsonify({
                "ok": True,
                "msg": "Google login success",
                "username": existing.get("username"),
                "email": existing.get("email", ""),
                "token": existing.get("username")  # Simple session token
            })
        else:
            # Create new account with Google
            new_user = {
                "username": google_email.split("@")[0] + "_google_" + google_id[:8],
                "password": generate_password_hash(google_id + "google_auto"),
                "email": google_email,
                "google_id": google_id,
                "google_email": google_email,
                "google_token": token,
                "email_confirmed": True,
                "created_at": now_str(),
                "subscription_plan": "free"
            }
            db["users"].append(new_user)
            save_users(db)
            session["username"] = new_user["username"]
            log_admin_event(new_user["username"], "account_created_via_google", {})
            return jsonify({
                "ok": True,
                "msg": "Google account created",
                "username": new_user["username"],
                "email": google_email,
                "token": new_user["username"]
            })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/oauth/binance/connect", methods=["POST"])
@login_required_api
def api_oauth_binance_connect():
    """Connect Binance account via API keys."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise"})
    
    try:
        data = request.get_json() or {}
        api_key = data.get("api_key", "")
        api_secret = data.get("api_secret", "")
        
        # Verify Binance credentials
        account_value = get_binance_account_value(api_key, api_secret)
        
        db = load_users()
        for user in db.get("users", []):
            if user.get("username") == u.get("username"):
                user["binance_api_key"] = api_key
                user["binance_api_secret"] = api_secret
                break
        save_users(db)
        
        log_admin_event(u.get("username"), "binance_connected", {
            "account_value": account_value
        })
        
        return jsonify({
            "ok": True,
            "msg": "Binance account connected",
            "account_value": round(account_value, 2)
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

# ---------------------------------------------------------------------------
# MULTI-EXCHANGE SUPPORT
# ---------------------------------------------------------------------------
@app.route("/api/exchange/connect", methods=["POST"])
@login_required_api
def api_exchange_connect():
    """Connect to any supported exchange."""
    u = current_user()
    if not has_enterprise_features(u):
        return jsonify({"ok": False, "msg": "Enterprise feature required"})
    
    try:
        data = request.get_json() or {}
        exchange = data.get("exchange", "").lower()
        api_key = data.get("api_key", "")
        api_secret = data.get("api_secret", "")
        sub_account = data.get("sub_account", "")
        
        if exchange not in SUPPORTED_EXCHANGES:
            return jsonify({"ok": False, "msg": f"Exchange not supported. Supported: {SUPPORTED_EXCHANGES}"})
        
        db = load_users()
        for user in db.get("users", []):
            if user.get("username") == u.get("username"):
                if "exchange_keys" not in user:
                    user["exchange_keys"] = {}
                user["exchange_keys"][exchange] = {
                    "api_key": api_key,
                    "api_secret": api_secret,
                    "sub_account": sub_account
                }
                break
        save_users(db)
        
        log_admin_event(u.get("username"), "exchange_connected", {"exchange": exchange})
        
        return jsonify({
            "ok": True,
            "msg": f"{exchange.capitalize()} connected successfully"
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/exchange/portfolio/<exchange>", methods=["GET"])
@login_required_api
def api_exchange_portfolio(exchange):
    """Get portfolio from any connected exchange."""
    u = current_user()
    if not has_enterprise_features(u):
        return jsonify({"ok": False, "msg": "Enterprise feature required"})
    
    try:
        exchange_keys = u.get("exchange_keys", {})
        if exchange not in exchange_keys:
            return jsonify({"ok": False, "msg": f"Exchange {exchange} not connected"})
        
        keys = exchange_keys[exchange]
        portfolio = get_exchange_portfolio(
            exchange,
            keys.get("api_key", ""),
            keys.get("api_secret", "")
        )
        
        return jsonify({
            "ok": True,
            "portfolio": portfolio
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

# ---------------------------------------------------------------------------
# EMAIL CONFIRMATION
# ---------------------------------------------------------------------------
@app.route("/api/confirmation/send", methods=["POST"])
@login_required_api
def api_confirmation_send():
    """Send email confirmation (upgrade from mock)."""
    u = current_user()
    
    try:
        email = u.get("email", "")
        if not email:
            return jsonify({"ok": False, "msg": "Email not found in profile"})
        
        token = hashlib.sha256(
            (u.get("username") + now_str() + os.urandom(16).hex()).encode()
        ).hexdigest()
        
        success = send_email_confirmation_real(email, token)
        
        if success:
            db = load_users()
            for user in db.get("users", []):
                if user.get("username") == u.get("username"):
                    user["confirmation_token"] = token
                    break
            save_users(db)
            
            return jsonify({
                "ok": True,
                "msg": "Confirmation email sent"
            })
        else:
            return jsonify({"ok": False, "msg": "Failed to send email"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/confirmation/verify/<token>", methods=["GET"])
def api_confirmation_verify(token):
    """Verify email confirmation token."""
    try:
        db = load_users()
        for user in db.get("users", []):
            if user.get("confirmation_token") == token:
                user["email_confirmed"] = True
                user["confirmation_token"] = ""
                break
        save_users(db)
        
        return jsonify({
            "ok": True,
            "msg": "Email confirmed successfully"
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

# ---------------------------------------------------------------------------
# WHALE ALERTS & ON-CHAIN
# ---------------------------------------------------------------------------
@app.route("/api/whale/alerts", methods=["GET"])
@login_required_api
def api_whale_alerts():
    """Get whale movement alerts on blockchain."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise"})
    
    try:
        alerts = get_whale_alerts()
        return jsonify({
            "ok": True,
            "alerts": alerts
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/whale/track", methods=["POST"])
@login_required_api
def api_whale_track():
    """Add blockchain address to track for whale movements."""
    u = current_user()
    if not has_pro_features(u):
        return jsonify({"ok": False, "msg": "Feature Pro requise"})
    
    try:
        data = request.get_json() or {}
        address = data.get("address", "").lower()
        threshold = float(data.get("threshold_eur", 10000.0))
        
        if not address.startswith("0x") or len(address) != 42:
            return jsonify({"ok": False, "msg": "Invalid Ethereum address"})
        
        db = load_users()
        for user in db.get("users", []):
            if user.get("username") == u.get("username"):
                if address not in user.get("tracked_addresses", []):
                    if "tracked_addresses" not in user:
                        user["tracked_addresses"] = []
                    user["tracked_addresses"].append(address)
                user["whale_alert_threshold_eur"] = threshold
                user["whale_alerts_enabled"] = True
                break
        save_users(db)
        
        log_admin_event(u.get("username"), "whale_tracking_started", {
            "address": address,
            "threshold": threshold
        })
        
        return jsonify({
            "ok": True,
            "msg": "Address tracking enabled"
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

# ---------------------------------------------------------------------------
# LANCEMENT
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    ensure_admin_user()
    print("\n  Dashboard Bot Trading => http://localhost:5000\n")
    app.run(debug=False, host="0.0.0.0", port=5000, use_reloader=False)

ensure_admin_user()
