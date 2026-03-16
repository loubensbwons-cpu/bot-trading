# =============================================================================
#  BOT DE TRADING CRYPTO  Architecture "Cerveau & Bras"
#  Auteur    : Senior Quant Developer
#  Version   : 2.3.0  (Python 3.14 - DeepSeek-V3 - 200 marches - Config web)
#  Capital   : 10 000 EUR (simulation)  |  Objectif : 50 000 EUR (x5)
# =============================================================================

import os
import json
import time
import csv
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import ccxt
import pandas as pd
import numpy as np
from openai import OpenAI
from dotenv import load_dotenv
import colorlog

# ---------------------------------------------------------------------------
# 0. CHARGEMENT DES VARIABLES D ENVIRONNEMENT
# ---------------------------------------------------------------------------
load_dotenv()


def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    try:
        v = int(os.getenv(name, str(default)))
    except ValueError:
        v = default
    if min_value is not None:
        v = max(min_value, v)
    if max_value is not None:
        v = min(max_value, v)
    return v


def env_float(name: str, default: float, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
    try:
        v = float(os.getenv(name, str(default)))
    except ValueError:
        v = default
    if min_value is not None:
        v = max(min_value, v)
    if max_value is not None:
        v = min(max_value, v)
    return v

BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY",    "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
AI_PROVIDER        = os.getenv("AI_PROVIDER",        "deepseek")
AI_MODEL           = os.getenv("AI_MODEL",           "deepseek-chat")
DEEPSEEK_API_KEY   = os.getenv("DEEPSEEK_API_KEY",   "")
OPENAI_API_KEY     = os.getenv("OPENAI_API_KEY",     "")
ANTHROPIC_API_KEY  = os.getenv("ANTHROPIC_API_KEY",  "")
GEMINI_API_KEY     = os.getenv("GEMINI_API_KEY",     "")
MISTRAL_API_KEY    = os.getenv("MISTRAL_API_KEY",    "")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY",       "")
XAI_API_KEY        = os.getenv("XAI_API_KEY",        "")

# ---------------------------------------------------------------------------
# 1. CONFIGURATION GLOBALE
# ---------------------------------------------------------------------------
MODE_SIMULATION     = env_bool("MODE_SIMULATION", True)  # False = ordres reels sur Binance
CYCLE_INTERVAL_SEC  = 60      # Delai entre chaque cycle (secondes)
TOP_N_MARKETS       = int(os.getenv("TOP_N_MARKETS", "200"))  # Lu depuis .env (defaut 200, max 300)
QUOTE_CURRENCY      = "USDT"  # Devise de cotation sur Binance
RSI_PERIOD          = 14      # Periode RSI
RSI_SURVENDU        = 30      # Seuil RSI survente  => signal achat
RSI_SURACHETE       = 70      # Seuil RSI surachat => signal vente
VOLUME_SPIKE_FACTOR = 2.0     # Volume x2 vs moyenne => spike detecte
MAX_EXPOSITION_PCT  = 0.10    # Max 10% du portefeuille par actif
MIN_ORDER_EUR       = 10.0    # Montant minimum d un ordre
PORTFOLIO_FILE      = "portfolio.json"
JOURNAL_FILE        = "journal_trading.csv"
EUR_USDT_APPROX     = 1.08    # Taux EUR/USDT par defaut (mis a jour dynamiquement)

# Controles risque (activables / desactivables)
RISK_DAILY_STOP_ENABLED      = env_bool("RISK_DAILY_STOP_ENABLED", True)
RISK_DAILY_STOP_PCT          = env_float("RISK_DAILY_STOP_PCT", 3.0, 0.1, 50.0)
RISK_MAX_TRADES_HOUR_ENABLED = env_bool("RISK_MAX_TRADES_HOUR_ENABLED", True)
RISK_MAX_TRADES_PER_HOUR     = env_int("RISK_MAX_TRADES_PER_HOUR", 6, 1, 100)
RISK_VOL_FILTER_ENABLED      = env_bool("RISK_VOL_FILTER_ENABLED", True)
RISK_MAX_VOLATILITY_PCT      = env_float("RISK_MAX_VOLATILITY_PCT", 12.0, 0.5, 200.0)
RISK_SPREAD_FILTER_ENABLED   = env_bool("RISK_SPREAD_FILTER_ENABLED", True)
RISK_MAX_SPREAD_PCT          = env_float("RISK_MAX_SPREAD_PCT", 1.0, 0.01, 50.0)

# Qualite decision IA (activable / desactivable)
DECISION_DUAL_VALIDATION_ENABLED = env_bool("DECISION_DUAL_VALIDATION_ENABLED", True)
DECISION_LOG_PROMPTS_ENABLED     = env_bool("DECISION_LOG_PROMPTS_ENABLED", True)

# Performance scan
SCAN_PARALLEL_WORKERS = env_int("SCAN_PARALLEL_WORKERS", 6, 1, 20)

# Audit IA
AI_DECISION_AUDIT_FILE = "ai_decisions_audit.jsonl"

# ---------------------------------------------------------------------------
# 2. LOGGER COLORE
# ---------------------------------------------------------------------------
def setup_logger() -> logging.Logger:
    handler_console = colorlog.StreamHandler()
    handler_console.setFormatter(colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s [%(levelname)s]%(reset)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG":    "cyan",
            "INFO":     "green",
            "WARNING":  "yellow",
            "ERROR":    "red",
            "CRITICAL": "bold_red",
        }
    ))
    handler_file = logging.FileHandler("bot_trading.log", encoding="utf-8")
    handler_file.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger = logging.getLogger("TradingBot")
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        logger.addHandler(handler_console)
        logger.addHandler(handler_file)
    return logger

log = setup_logger()

# ---------------------------------------------------------------------------
# 3. CALCUL RSI NATIF (sans pandas-ta)
# ---------------------------------------------------------------------------
def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Calcule le RSI de Wilder a partir d une Serie de prix de cloture."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs  = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

# ---------------------------------------------------------------------------
# 4. GESTION DU PORTFOLIO (Memoire persistante)
# ---------------------------------------------------------------------------
def load_portfolio() -> dict:
    if not os.path.exists(PORTFOLIO_FILE):
        log.warning("portfolio.json introuvable => creation d un portfolio vierge.")
        default = {
            "solde_eur": 10000.00,
            "positions": {},
            "historique_valeur": [],
            "statistiques": {
                "total_trades": 0,
                "trades_gagnants": 0,
                "trades_perdants": 0,
                "plus_haute_valeur": 10000.00,
                "plus_basse_valeur": 10000.00,
            }
        }
        save_portfolio(default)
        return default
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.debug(f"Portfolio charge : {data['solde_eur']:.2f} EUR disponible.")
        return data
    except (json.JSONDecodeError, KeyError) as e:
        log.error(f"Erreur lecture portfolio.json : {e} => reinitialisation.")
        default = {"solde_eur": 10000.00, "positions": {}, "historique_valeur": [], "statistiques": {}}
        save_portfolio(default)
        return default

def save_portfolio(portfolio: dict) -> None:
    try:
        tmp = PORTFOLIO_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(portfolio, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PORTFOLIO_FILE)
    except Exception as e:
        log.error(f"Erreur sauvegarde portfolio : {e}")

def get_portfolio_value(portfolio: dict, current_prices: dict) -> float:
    valeur = portfolio.get("solde_eur", 0.0)
    for symbol, pos in portfolio.get("positions", {}).items():
        prix = current_prices.get(symbol, pos.get("prix_achat_eur", 0.0))
        valeur += pos.get("quantite", 0.0) * prix
    return round(valeur, 2)

def log_journal(action: str, symbol: str, prix_eur: float, montant_eur: float, raison: str) -> None:
    try:
        file_exists = os.path.exists(JOURNAL_FILE)
        with open(JOURNAL_FILE, "a", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=[
                "timestamp", "action", "symbole", "prix_eur", "montant_eur", "raison"
            ])
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "timestamp":   datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "action":      action,
                "symbole":     symbol,
                "prix_eur":    round(prix_eur, 6),
                "montant_eur": round(montant_eur, 2),
                "raison":      raison,
            })
    except Exception as e:
        log.error(f"Erreur ecriture journal : {e}")


def count_recent_executed_trades(minutes: int = 60) -> int:
    """Compte les ACHAT/VENTE dans la fenetre recente."""
    if not os.path.exists(JOURNAL_FILE):
        return 0
    threshold = datetime.now(timezone.utc).timestamp() - (minutes * 60)
    count = 0
    try:
        with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                action = (row.get("action") or "").strip().upper()
                if action not in ("ACHAT", "VENTE"):
                    continue
                ts_str = (row.get("timestamp") or "").strip()
                if not ts_str:
                    continue
                dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                if dt.timestamp() >= threshold:
                    count += 1
    except Exception as e:
        log.debug(f"Impossible de compter les trades recents : {e}")
    return count


def daily_performance_pct(portfolio: dict, current_value: float) -> float:
    """Renvoie la perf du jour en %, basee sur le premier point historique du jour."""
    today = datetime.now(timezone.utc).date()
    base_value = current_value
    history = portfolio.get("historique_valeur", [])
    for pt in history:
        ts = pt.get("timestamp")
        val = pt.get("valeur_totale_eur")
        if not ts or val is None:
            continue
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt.date() == today:
            base_value = float(val)
            break
    if base_value <= 0:
        return 0.0
    return ((current_value - base_value) / base_value) * 100.0

# ---------------------------------------------------------------------------
# 5. CONNEXION EXCHANGE (LE BRAS)
# ---------------------------------------------------------------------------
def connect_exchange() -> ccxt.binance:
    try:
        exchange = ccxt.binance({
            "apiKey":  BINANCE_API_KEY,
            "secret":  BINANCE_API_SECRET,
            "options": {"defaultType": "spot"},
            "enableRateLimit": True,
        })
        log.info("Exchange Binance initialise (mode SIMULATION)." if MODE_SIMULATION
                 else "Connexion Binance etablie (mode REEL).")
        return exchange
    except Exception as e:
        log.critical(f"Impossible de se connecter a Binance : {e}")
        raise

# ---------------------------------------------------------------------------
# 6. COLLECTE DES DONNEES & INDICATEURS (LE BRAS)
# ---------------------------------------------------------------------------
def get_eur_usdt_rate(exchange: ccxt.binance) -> float:
    try:
        ticker = exchange.fetch_ticker("EUR/USDT")
        rate = float(ticker["last"])
        log.debug(f"Taux EUR/USDT = {rate:.4f}")
        return rate
    except Exception:
        log.warning(f"Taux EUR/USDT indisponible, valeur par defaut : {EUR_USDT_APPROX}")
        return EUR_USDT_APPROX

def fetch_top_markets(exchange: ccxt.binance, n: int = TOP_N_MARKETS) -> list:
    try:
        tickers = exchange.fetch_tickers()
        usdt_pairs = {
            sym: data for sym, data in tickers.items()
            if sym.endswith(f"/{QUOTE_CURRENCY}") and data.get("quoteVolume") is not None
        }
        sorted_pairs = sorted(
            usdt_pairs.keys(),
            key=lambda s: usdt_pairs[s]["quoteVolume"] or 0,
            reverse=True
        )
        top = sorted_pairs[:n]
        log.info(f"{len(top)} marches USDT recuperes (Top {n}).")
        return top
    except Exception as e:
        log.error(f"Erreur fetch_top_markets : {e}")
        return []

def fetch_ohlcv_with_indicators(exchange: ccxt.binance, symbol: str,
                                  timeframe: str = "1h", limit: int = 100) -> Optional[pd.DataFrame]:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < RSI_PERIOD + 2:
            return None
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"]    = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["rsi"]          = compute_rsi(df["close"], RSI_PERIOD)
        df["volume_moyen"] = df["volume"].rolling(20).mean()
        return df
    except ccxt.RateLimitExceeded:
        log.warning(f"Rate limit atteint pour {symbol}, pause 10s...")
        time.sleep(10)
        return None
    except Exception as e:
        log.debug(f"Erreur OHLCV {symbol} : {e}")
        return None

def _analyze_symbol(exchange: ccxt.binance, symbol: str, eur_usdt_rate: float) -> tuple:
    """Retourne (opportunity_or_none, symbol, prix_eur_or_none)."""
    df = fetch_ohlcv_with_indicators(exchange, symbol)
    if df is None or df.empty:
        return None, symbol, None

    row           = df.iloc[-1]
    rsi_value     = float(row["rsi"]) if not pd.isna(row["rsi"]) else None
    prix_usdt     = float(row["close"])
    prix_eur      = prix_usdt / eur_usdt_rate
    vol_actuel    = float(row["volume"])
    vol_moyen     = float(row["volume_moyen"]) if not pd.isna(row["volume_moyen"]) else 0

    if rsi_value is None:
        return None, symbol, prix_eur

    signal_achat  = rsi_value < RSI_SURVENDU
    signal_vente  = rsi_value > RSI_SURACHETE
    signal_volume = (vol_moyen > 0 and vol_actuel > vol_moyen * VOLUME_SPIKE_FACTOR)

    ticker = {}
    var_24h = None
    spread_pct = None
    volatility_pct = None
    try:
        ticker = exchange.fetch_ticker(symbol)
        var_24h = ticker.get("percentage", None)
        bid = ticker.get("bid")
        ask = ticker.get("ask")
        if bid and ask and bid > 0:
            spread_pct = ((ask - bid) / bid) * 100.0
    except Exception:
        pass

    try:
        high = float(row["high"])
        low  = float(row["low"])
        if prix_usdt > 0:
            volatility_pct = ((high - low) / prix_usdt) * 100.0
    except Exception:
        pass

    # Filtres de risque activables
    if RISK_VOL_FILTER_ENABLED and volatility_pct is not None and volatility_pct > RISK_MAX_VOLATILITY_PCT:
        return None, symbol, prix_eur
    if RISK_SPREAD_FILTER_ENABLED and spread_pct is not None and spread_pct > RISK_MAX_SPREAD_PCT:
        return None, symbol, prix_eur

    if not (signal_achat or signal_vente or signal_volume):
        return None, symbol, prix_eur

    opp = {
        "symbol":         symbol,
        "prix_eur":       round(prix_eur, 6),
        "rsi":            round(rsi_value, 2),
        "volume_spike":   signal_volume,
        "signal":         ("RSI_SURVENDU" if signal_achat else "RSI_SURACHETE" if signal_vente else "VOLUME_SPIKE"),
        "variation_24h":  round(var_24h, 2) if var_24h is not None else None,
        "spread_pct":     round(spread_pct, 3) if spread_pct is not None else None,
        "volatility_pct": round(volatility_pct, 3) if volatility_pct is not None else None,
    }
    return opp, symbol, prix_eur


def scan_opportunities(exchange: ccxt.binance, top_markets: list,
                        eur_usdt_rate: float) -> tuple:
    opportunities  = []
    current_prices = {}
    log.info(f"Scan de {len(top_markets)} marches en cours...")

    with ThreadPoolExecutor(max_workers=SCAN_PARALLEL_WORKERS) as executor:
        futures = {executor.submit(_analyze_symbol, exchange, symbol, eur_usdt_rate): symbol for symbol in top_markets}
        for future in as_completed(futures):
            symbol = futures[future]
            try:
                opp, sym, prix = future.result()
                if prix is not None:
                    current_prices[sym] = prix
                if opp is not None:
                    opportunities.append(opp)
                    log.debug(f"  >> {sym:15s} | RSI={opp['rsi']:.1f} | Prix={opp['prix_eur']:.4f}EUR")
            except Exception as e:
                log.debug(f"Erreur {symbol} : {e}")
                continue

    log.info(f"Scan termine : {len(opportunities)} opportunite(s) sur {len(top_markets)} marches.")
    return opportunities, current_prices

# ---------------------------------------------------------------------------
# 7. LE CERVEAU  DECISION IA (Multi-fournisseurs)
#    Supporte : DeepSeek, OpenAI, Anthropic Claude, Google Gemini,
#               Mistral AI, Groq, xAI Grok
# ---------------------------------------------------------------------------
# Base URL de chaque fournisseur compatible OpenAI (None = endpoint officiel OpenAI)
_PROVIDER_BASE_URL: dict = {
    "deepseek": "https://api.deepseek.com",
    "openai":   None,
    "gemini":   "https://generativelanguage.googleapis.com/v1beta/openai/",
    "mistral":  "https://api.mistral.ai/v1",
    "groq":     "https://api.groq.com/openai/v1",
    "xai":      "https://api.x.ai/v1",
}

def build_prompt(portfolio: dict, opportunities: list,
                  valeur_totale: float, eur_usdt_rate: float) -> str:
    positions_str = json.dumps(portfolio.get("positions", {}), indent=2, ensure_ascii=False)
    opp_str       = json.dumps(opportunities[:20],              indent=2, ensure_ascii=False)
    return f"""Tu es un expert en trading algorithmique de cryptomonnaies.
Analyse les donnees ci-dessous et prends UNE seule decision optimale.

## ETAT DU PORTFOLIO
- Solde disponible : {portfolio['solde_eur']:.2f} EUR
- Valeur totale    : {valeur_totale:.2f} EUR
- Objectif cible   : 50 000 EUR (x5 depuis 10 000 EUR)
- Taux EUR/USDT    : {eur_usdt_rate:.4f}
- Positions ouvertes :
{positions_str}

## OPPORTUNITES DETECTEES ({len(opportunities)} signaux)
{opp_str}

## REGLES STRICTES
1. Ne JAMAIS acheter si solde_eur < amount_eur (solde : {portfolio['solde_eur']:.2f} EUR).
2. Investir au maximum {valeur_totale * 0.10:.2f} EUR par trade (10% du portfolio).
3. Montant minimum : {MIN_ORDER_EUR} EUR.
4. RSI < 30 => acheter | RSI > 70 => vendre.
5. Vendre uniquement des positions deja ouvertes.
6. Si rien n est clair => GARDER.

## REPONSE : JSON pur uniquement, rien d autre autour.
{{
  "action": "ACHETER" ou "VENDRE" ou "GARDER",
  "symbol": "BTC/USDT" ou null,
  "amount_eur": nombre ou null,
  "reason": "explication courte en francais"
}}"""

def _call_openai_compat(api_key: str, base_url: Optional[str], model: str,
                        system: str, user: str, use_json_mode: bool = True) -> Optional[str]:
    """Appel generique compatible OpenAI (DeepSeek, OpenAI, Gemini, Mistral, Groq, xAI)."""
    kwargs: dict = {}
    if use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.2,
        max_tokens=400,
        **kwargs,
    )
    return response.choices[0].message.content.strip()


def _call_anthropic(api_key: str, model: str, system: str, user: str) -> Optional[str]:
    """Appel Claude via le SDK Anthropic (API differente d OpenAI)."""
    try:
        import anthropic  # type: ignore
    except ImportError:
        log.error("Package 'anthropic' non installe. Lancez : pip install anthropic")
        return None
    client   = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=400,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


def get_ai_decision(portfolio: dict, opportunities: list,
                     valeur_totale: float, eur_usdt_rate: float) -> Optional[dict]:
    provider = AI_PROVIDER
    model    = AI_MODEL
    prompt   = build_prompt(portfolio, opportunities, valeur_totale, eur_usdt_rate)
    system   = "Tu reponds UNIQUEMENT avec du JSON valide, sans markdown, sans texte autour."

    # Cle API du fournisseur actif
    provider_keys = {
        "deepseek":  DEEPSEEK_API_KEY,
        "openai":    OPENAI_API_KEY,
        "anthropic": ANTHROPIC_API_KEY,
        "gemini":    GEMINI_API_KEY,
        "mistral":   MISTRAL_API_KEY,
        "groq":      GROQ_API_KEY,
        "xai":       XAI_API_KEY,
    }
    api_key = provider_keys.get(provider, "")
    if not api_key:
        log.error(f"Cle API manquante pour '{provider}' => Configurez-la dans l'onglet Parametres.")
        return None

    log.info(f"Envoi des donnees au Cerveau IA ({provider.upper()} / {model})...")
    try:
        if provider == "anthropic":
            raw = _call_anthropic(api_key, model, system, prompt)
        else:
            base_url = _PROVIDER_BASE_URL.get(provider)
            # Gemini : json_object mode non garanti sur tous les modeles
            use_json = (provider != "gemini")
            raw = _call_openai_compat(api_key, base_url, model, system, prompt, use_json)

        if not raw:
            log.error("Reponse vide de l IA.")
            return None

        # Nettoyer si l IA a mis du markdown malgre tout
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        decision = json.loads(raw)
        if "action" not in decision:
            raise ValueError("Champ 'action' manquant.")
        if decision["action"] not in ("ACHETER", "VENDRE", "GARDER"):
            raise ValueError(f"Action invalide : {decision['action']}")

        # Validation regles metier + score de confiance
        validation = validate_decision_rules(decision, opportunities, portfolio, valeur_totale)
        decision["confidence_score"] = validation["score"]
        decision["confidence_level"] = (
            "forte" if validation["score"] >= 80 else "moyenne" if validation["score"] >= 55 else "faible"
        )
        decision["validation_notes"] = validation["notes"]

        if DECISION_DUAL_VALIDATION_ENABLED and decision["action"] != "GARDER" and not validation["allowed"]:
            reason = decision.get("reason", "")
            decision["action"] = "GARDER"
            decision["symbol"] = None
            decision["amount_eur"] = None
            decision["reason"] = f"Decision bloquee par validation regles. {reason}".strip()

        if DECISION_LOG_PROMPTS_ENABLED:
            audit_ai_decision(provider, model, prompt, raw, decision)

        log.info(f"DECISION IA => {decision['action']} | {decision.get('symbol','N/A')} | "
                 f"{decision.get('amount_eur','N/A')} EUR | Conf={decision.get('confidence_score','N/A')} | "
                 f"{decision.get('reason','')}")
        return decision
    except json.JSONDecodeError as e:
        log.error(f"JSON invalide recu de l IA : {e}")
        return None
    except Exception as e:
        log.error(f"Erreur appel {provider} : {e}")
        return None


def validate_decision_rules(decision: dict, opportunities: list, portfolio: dict, valeur_totale: float) -> dict:
    """Valide la decision IA avec des regles metier deterministes."""
    action = (decision.get("action") or "").upper()
    symbol = decision.get("symbol")
    amount = float(decision.get("amount_eur") or 0)
    notes = []
    score = 0
    allowed = True

    if action in ("ACHETER", "VENDRE", "GARDER"):
        score += 15
    else:
        notes.append("Action invalide")
        return {"allowed": False, "score": 0, "notes": notes}

    if action == "GARDER":
        return {"allowed": True, "score": 85, "notes": ["Action neutre"]}

    opp_map = {o.get("symbol"): o for o in opportunities}
    max_amount = valeur_totale * MAX_EXPOSITION_PCT

    if action == "ACHETER":
        if symbol in opp_map:
            score += 30
        else:
            allowed = False
            notes.append("Symbole absent des opportunites")

        if MIN_ORDER_EUR <= amount <= max_amount:
            score += 25
        else:
            notes.append(f"Montant hors bornes ({MIN_ORDER_EUR:.2f}-{max_amount:.2f})")

        if amount <= float(portfolio.get("solde_eur", 0)):
            score += 20
        else:
            allowed = False
            notes.append("Fonds insuffisants")

        signal = (opp_map.get(symbol, {}) or {}).get("signal")
        if signal in ("RSI_SURVENDU", "VOLUME_SPIKE"):
            score += 10
        else:
            notes.append("Signal faible pour achat")

    if action == "VENDRE":
        positions = portfolio.get("positions", {})
        if symbol in positions:
            score += 30
        else:
            allowed = False
            notes.append("Aucune position ouverte sur ce symbole")

        if amount >= MIN_ORDER_EUR:
            score += 20
        else:
            notes.append("Montant de vente trop faible")

        if symbol in positions:
            pos = positions[symbol]
            prix = (opp_map.get(symbol, {}) or {}).get("prix_eur", pos.get("prix_achat_eur", 0))
            max_sell = float(pos.get("quantite", 0)) * float(prix)
            if amount <= max_sell + 1e-6:
                score += 20
            else:
                allowed = False
                notes.append("Montant de vente > valeur position")

        signal = (opp_map.get(symbol, {}) or {}).get("signal")
        if signal in ("RSI_SURACHETE", "VOLUME_SPIKE"):
            score += 10

    score = max(0, min(100, score))
    return {"allowed": allowed, "score": score, "notes": notes}


def audit_ai_decision(provider: str, model: str, prompt: str, raw: str, decision: dict) -> None:
    """Journalise les prompts/reponses IA pour audit et debuggage."""
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "raw_response": raw,
        "decision": decision,
    }
    try:
        with open(AI_DECISION_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception as e:
        log.debug(f"Audit IA impossible: {e}")

# ---------------------------------------------------------------------------
# 8. EXECUTION DES ORDRES
# ---------------------------------------------------------------------------
def execute_buy(portfolio: dict, exchange: ccxt.binance,
                decision: dict, current_prices: dict, eur_usdt_rate: float) -> bool:
    symbol     = decision.get("symbol")
    amount_eur = float(decision.get("amount_eur") or 0)
    prix_eur   = current_prices.get(symbol)

    if not symbol or not prix_eur:
        log.warning(f"ACHAT annule : symbole/prix invalide.")
        return False
    if amount_eur < MIN_ORDER_EUR:
        log.warning(f"ACHAT annule : montant {amount_eur:.2f} EUR < minimum {MIN_ORDER_EUR} EUR.")
        return False
    if amount_eur > portfolio["solde_eur"]:
        log.warning(f"ACHAT annule : fonds insuffisants ({amount_eur:.2f} EUR demande, {portfolio['solde_eur']:.2f} EUR disponible).")
        return False

    quantite = amount_eur / prix_eur

    if MODE_SIMULATION:
        portfolio["solde_eur"] = round(portfolio["solde_eur"] - amount_eur, 2)
        if symbol in portfolio["positions"]:
            pos            = portfolio["positions"][symbol]
            total_qty      = pos["quantite"] + quantite
            total_cout     = pos["cout_total_eur"] + amount_eur
            pos["quantite"]        = round(total_qty, 8)
            pos["cout_total_eur"]  = round(total_cout, 2)
            pos["prix_achat_eur"]  = round(total_cout / total_qty, 6)
        else:
            portfolio["positions"][symbol] = {
                "quantite":       round(quantite, 8),
                "prix_achat_eur": round(prix_eur, 6),
                "cout_total_eur": round(amount_eur, 2),
                "date_achat":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }
        portfolio["statistiques"]["total_trades"] = portfolio["statistiques"].get("total_trades", 0) + 1
        save_portfolio(portfolio)
        log.info(f"[SIMULATION] ACHAT OK | {quantite:.6f} {symbol} a {prix_eur:.4f} EUR/u | "
                 f"Cout : {amount_eur:.2f} EUR | Solde restant : {portfolio['solde_eur']:.2f} EUR")
        log_journal("ACHAT", symbol, prix_eur, amount_eur, decision.get("reason", ""))
        return True
    else:
        try:
            order = exchange.create_market_buy_order(symbol, amount_eur * eur_usdt_rate / (prix_eur * eur_usdt_rate))
            log.info(f"[REEL] ACHAT OK | Ordre Binance : {order['id']}")
            log_journal("ACHAT", symbol, prix_eur, amount_eur, decision.get("reason", ""))
            return True
        except Exception as e:
            log.error(f"Erreur ordre achat Binance : {e}")
            return False

def execute_sell(portfolio: dict, exchange: ccxt.binance,
                 decision: dict, current_prices: dict, eur_usdt_rate: float) -> bool:
    symbol     = decision.get("symbol")
    amount_eur = float(decision.get("amount_eur") or 0)
    prix_eur   = current_prices.get(symbol)

    if not symbol or symbol not in portfolio.get("positions", {}):
        log.warning(f"VENTE annulee : aucune position ouverte pour {symbol}.")
        return False
    if not prix_eur:
        log.warning(f"VENTE annulee : prix introuvable pour {symbol}.")
        return False

    pos             = portfolio["positions"][symbol]
    valeur_pos      = pos["quantite"] * prix_eur
    montant_vente   = min(amount_eur, valeur_pos)
    quantite_vendre = montant_vente / prix_eur

    if MODE_SIMULATION:
        cout_unitaire = pos["cout_total_eur"] / pos["quantite"]
        pnl           = (prix_eur - cout_unitaire) * quantite_vendre
        pnl_pct       = ((prix_eur - cout_unitaire) / cout_unitaire) * 100

        portfolio["solde_eur"] = round(portfolio["solde_eur"] + montant_vente, 2)
        nouvelle_qty = pos["quantite"] - quantite_vendre
        if nouvelle_qty < 1e-8:
            del portfolio["positions"][symbol]
            log.info(f"Position {symbol} FERMEE.")
        else:
            pos["quantite"]       = round(nouvelle_qty, 8)
            pos["cout_total_eur"] = round(nouvelle_qty * cout_unitaire, 2)

        portfolio["statistiques"]["total_trades"] = portfolio["statistiques"].get("total_trades", 0) + 1
        if pnl >= 0:
            portfolio["statistiques"]["trades_gagnants"] = portfolio["statistiques"].get("trades_gagnants", 0) + 1
        else:
            portfolio["statistiques"]["trades_perdants"] = portfolio["statistiques"].get("trades_perdants", 0) + 1

        save_portfolio(portfolio)
        log.info(f"[SIMULATION] VENTE OK | {quantite_vendre:.6f} {symbol} a {prix_eur:.4f} EUR/u | "
                 f"Recette : {montant_vente:.2f} EUR | P&L : {pnl:+.2f} EUR ({pnl_pct:+.2f}%) | "
                 f"Solde : {portfolio['solde_eur']:.2f} EUR")
        log_journal("VENTE", symbol, prix_eur, montant_vente, decision.get("reason", ""))
        return True
    else:
        try:
            order = exchange.create_market_sell_order(symbol, quantite_vendre)
            log.info(f"[REEL] VENTE OK | Ordre Binance : {order['id']}")
            log_journal("VENTE", symbol, prix_eur, montant_vente, decision.get("reason", ""))
            return True
        except Exception as e:
            log.error(f"Erreur ordre vente Binance : {e}")
            return False

# ---------------------------------------------------------------------------
# 9. CYCLE DE TRADING
# ---------------------------------------------------------------------------
def trading_cycle(exchange: ccxt.binance, cycle_num: int) -> None:
    sep = "=" * 65
    log.info(sep)
    log.info(f"  CYCLE #{cycle_num} | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    log.info(sep)

    portfolio     = load_portfolio()
    eur_usdt_rate = get_eur_usdt_rate(exchange)
    top_markets   = fetch_top_markets(exchange)

    if not top_markets:
        log.warning("Aucun marche recupere, cycle ignore.")
        return

    opportunities, current_prices = scan_opportunities(exchange, top_markets, eur_usdt_rate)
    valeur_totale = get_portfolio_value(portfolio, current_prices)

    progression = (valeur_totale / 10000 * 100)
    log.info(f"Portfolio : {valeur_totale:.2f} EUR | Objectif : 50 000 EUR | Progression : {progression:.1f}%")

    # Gate risques: stop-loss journalier
    perf_day = daily_performance_pct(portfolio, valeur_totale)
    if RISK_DAILY_STOP_ENABLED and perf_day <= -abs(RISK_DAILY_STOP_PCT):
        log.warning(f"STOP-LOSS JOURNALIER ACTIF: perf jour {perf_day:.2f}% <= -{RISK_DAILY_STOP_PCT:.2f}% => pause trades")
        return

    # Gate risques: limite trades / heure
    if RISK_MAX_TRADES_HOUR_ENABLED:
        recent_trades = count_recent_executed_trades(60)
        if recent_trades >= RISK_MAX_TRADES_PER_HOUR:
            log.warning(f"LIMITE TRADES/H ACTIF: {recent_trades} trades recents >= {RISK_MAX_TRADES_PER_HOUR} => pause")
            return

    # Mise a jour historique (max 1000 points)
    portfolio.setdefault("historique_valeur", []).append({
        "timestamp":         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "valeur_totale_eur": valeur_totale
    })
    portfolio["historique_valeur"] = portfolio["historique_valeur"][-1000:]

    stats = portfolio.setdefault("statistiques", {})
    stats["plus_haute_valeur"] = max(stats.get("plus_haute_valeur", 0),          valeur_totale)
    stats["plus_basse_valeur"] = min(stats.get("plus_basse_valeur", float("inf")), valeur_totale)
    save_portfolio(portfolio)

    if not opportunities:
        log.info("Aucune opportunite => GARDER. Prochain cycle dans 60s.")
        return

    decision = get_ai_decision(portfolio, opportunities, valeur_totale, eur_usdt_rate)
    if decision is None:
        log.warning("Decision IA indisponible => GARDER par defaut.")
        return

    action = decision.get("action", "GARDER")
    if action == "ACHETER":
        execute_buy(portfolio, exchange, decision, current_prices, eur_usdt_rate)
    elif action == "VENDRE":
        execute_sell(portfolio, exchange, decision, current_prices, eur_usdt_rate)
    elif action == "GARDER":
        log.info(f"[GARDER] {decision.get('reason', 'N/A')}")
        log_journal("GARDER", decision.get("symbol") or "N/A", 0.0, 0.0, decision.get("reason", ""))
    else:
        log.warning(f"Action inconnue : {action}")

# ---------------------------------------------------------------------------
# 10. POINT D ENTREE PRINCIPAL
# ---------------------------------------------------------------------------
def main() -> None:
    log.info("================================================================")
    log.info("   BOT DE TRADING CRYPTO  |  Architecture Cerveau & Bras")
    log.info(f"  Mode : {'SIMULATION' if MODE_SIMULATION else 'REEL !!!'}")
    log.info("  Capital initial : 10 000 EUR  =>  Objectif : 50 000 EUR (x5)")
    log.info("================================================================")

    _main_keys = {
        "deepseek": DEEPSEEK_API_KEY, "openai": OPENAI_API_KEY, "anthropic": ANTHROPIC_API_KEY,
        "gemini": GEMINI_API_KEY, "mistral": MISTRAL_API_KEY, "groq": GROQ_API_KEY, "xai": XAI_API_KEY,
    }
    if not _main_keys.get(AI_PROVIDER, ""):
        log.critical(f"Cle API manquante pour le fournisseur '{AI_PROVIDER}' => Arret.")
        log.critical("Configurez la cle dans l'onglet Parametres du dashboard web.")
        return
    log.info(f"  IA : {AI_PROVIDER.upper()} | Modele : {AI_MODEL}")
    log.info(f"  Risque: daily_stop={'ON' if RISK_DAILY_STOP_ENABLED else 'OFF'} ({RISK_DAILY_STOP_PCT:.2f}%) | "
             f"trades/h={'ON' if RISK_MAX_TRADES_HOUR_ENABLED else 'OFF'} ({RISK_MAX_TRADES_PER_HOUR}) | "
             f"vol_filter={'ON' if RISK_VOL_FILTER_ENABLED else 'OFF'} ({RISK_MAX_VOLATILITY_PCT:.2f}%) | "
             f"spread_filter={'ON' if RISK_SPREAD_FILTER_ENABLED else 'OFF'} ({RISK_MAX_SPREAD_PCT:.2f}%)")
    log.info(f"  IA Qualite: dual_validation={'ON' if DECISION_DUAL_VALIDATION_ENABLED else 'OFF'} | "
             f"prompt_audit={'ON' if DECISION_LOG_PROMPTS_ENABLED else 'OFF'}")

    try:
        exchange = connect_exchange()
    except Exception:
        log.critical("Connexion a l exchange impossible => Arret.")
        return

    cycle_num = 1
    while True:
        try:
            trading_cycle(exchange, cycle_num)
        except KeyboardInterrupt:
            log.info("Arret manuel du bot. A bientot !")
            break
        except Exception as e:
            log.error(f"Erreur cycle #{cycle_num} : {e}")
            log.debug(traceback.format_exc())
            log.info("Reprise dans 30s...")
            time.sleep(30)
            continue

        cycle_num += 1
        log.info(f"Pause de {CYCLE_INTERVAL_SEC}s avant le prochain cycle...\n")
        try:
            time.sleep(CYCLE_INTERVAL_SEC)
        except KeyboardInterrupt:
            log.info("Arret manuel du bot. A bientot !")
            break

if __name__ == "__main__":
    main()


