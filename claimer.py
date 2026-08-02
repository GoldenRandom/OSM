import os
import time
import random
import re
import json
import logging
from playwright.sync_api import sync_playwright
import urllib.parse
import urllib.request
import json
import base64

def send_whatsapp_message(text):
    id_instance = os.getenv("GREEN_API_INSTANCE")
    api_token = os.getenv("GREEN_API_TOKEN")
    phone = os.getenv("WHATSAPP_PHONE")
    
    if not all([id_instance, api_token, phone]):
        return
        
    url = f"https://api.green-api.com/waInstance{id_instance}/sendMessage/{api_token}"
    
    # Strip '+' if the user accidentally included it
    clean_phone = phone.replace("+", "").replace(" ", "")
    chat_id = f"{clean_phone}@c.us"
    
    payload = json.dumps({
        "chatId": chat_id,
        "message": text
    }).encode("utf-8")
    
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    
    try:
        urllib.request.urlopen(req)
        log.info("Green API WhatsApp notification sent!")
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        log.error(f"Failed to send Green API message: HTTP Error {e.code} - {error_body}")
    except Exception as e:
        log.error(f"Failed to send Green API message: {e}")

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s │ %(levelname)-8s │ %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("boss_coin_claimer")

BASE_URL = "https://en.onlinesoccermanager.com"
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.json")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

GET_BOSS_COINS_JS = '''() => {
    try {
        let el = document.querySelector('.boss-coin-value, [data-bind*="bossCoins"], [data-type="boss-coin"]');
        if (el && el.innerText.trim()) return el.innerText.replace('+', '').trim();
        
        let nodes = document.querySelectorAll('div, span, button');
        for (let node of nodes) {
            let txt = (node.innerText || "").trim();
            if (txt.match(/^\\d+\\s*\\+$/)) {
                return txt.replace('+', '').trim();
            }
        }
        
        for (let node of nodes) {
            let txt = (node.innerText || "").trim();
            if (txt.match(/^[0-9.]+[MKB]$/)) { // Found budget
                let parent = node.parentElement;
                if (parent && parent.parentElement) {
                    let fullText = parent.parentElement.innerText.trim();
                    let match = fullText.match(/^(\\d+)\\s*\\+?\\s*[0-9.]+[MKB]$/);
                    if (match) return match[1];
                }
            }
        }
    } catch(e) {}
    return "Unknown";
}'''

def interactive_login(pw):
    """Opens a browser for the user to log in locally."""
    log.info("No cookies found. Opening browser for manual login...")
    try:
        browser = pw.chromium.launch(headless=False, channel="chrome")
    except Exception as e:
        log.error("Failed to launch visible browser. If you are on a cloud server, you must provide a valid cookies.json file!")
        raise e
        
    context = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=_USER_AGENT)
    page = context.new_page()
    page.goto(f"{BASE_URL}/Login")
    
    log.info("Please log in. Waiting for you to reach the Dashboard...")
    try:
        page.wait_for_url("**/Dashboard**", timeout=300000) # Wait up to 5 minutes
        cookies = context.cookies()
        with open(COOKIES_PATH, "w", encoding="utf-8") as f:
            json.dump(cookies, f)
        log.info("Login successful! Cookies saved to cookies.json.")
    except Exception as e:
        log.error("Login timed out or failed. Please try again.")
        raise e
    finally:
        browser.close()

def load_cookies():
    # If cookies are provided via environment variable (GitHub Secrets), write them to file
    env_cookies = os.environ.get("OSM_COOKIES")
    if env_cookies:
        try:
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write(env_cookies)
            log.info("Loaded cookies from GitHub Secrets!")
        except Exception as e:
            log.error(f"Failed to load cookies from secrets: {e}")

def get_user_leagues(pw, cookies):
    """Fetch user league slots using API interception."""
    browser = pw.chromium.launch(headless=True, channel="chrome")
    context = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=_USER_AGENT)
    context.add_cookies(cookies)
    page = context.new_page()
    
    accounts_data = {"data": None}
    def handle_response(response):
        if "api/v1/" in response.url and "user/accounts" in response.url:
            try:
                if response.ok:
                    accounts_data["data"] = response.json()
            except: pass
            
    page.on("response", handle_response)
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    
    for _ in range(50):
        if accounts_data["data"]: break
        page.wait_for_timeout(100)
        
    leagues = []
    data = accounts_data["data"] or {}
    for slot_idx, slot_data in data.get("teamSlots", {}).items():
        if "team" in slot_data and "league" in slot_data:
            leagues.append({
                "slot_index": int(slot_idx),
                "league_id": slot_data["team"].get("leagueId", 0),
                "team_id": slot_data["team"].get("id", 0),
                "team_name": slot_data["team"].get("name", "Unknown"),
                "league_name": slot_data["league"].get("name", "Unknown"),
            })
            
    browser.close()
    return leagues

def switch_league_slot(pw, target_league):
    """Modifies the session cookie to switch slots."""
    with open(COOKIES_PATH, "r", encoding="utf-8") as f:
        cookies = json.load(f)
        
    for c in cookies:
        if c["name"] == "session":
            try:
                session_data = json.loads(urllib.parse.unquote(c["value"]))
                session_data["slotIndex"] = target_league["slot_index"]
                session_data["teamId"] = target_league["team_id"]
                session_data["leagueId"] = target_league["league_id"]
                c["value"] = urllib.parse.quote(json.dumps(session_data))
            except: pass
            
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 800}, user_agent=_USER_AGENT)
    context.add_cookies(cookies)
    page = context.new_page()
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    
    with open(COOKIES_PATH, "w", encoding="utf-8") as f:
        json.dump(context.cookies(), f)
    browser.close()

def claim_loop():
    log.info("Starting Boss Coin Claimer...")
    
    load_cookies()
    
    with sync_playwright() as pw:
        if not os.path.exists(COOKIES_PATH):
            interactive_login(pw)
            
        with open(COOKIES_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)

        # 1. Switch to Target Team
        leagues = get_user_leagues(pw, cookies)
        target_slot = None
        target_league_data = None
        
        target_team_env = os.environ.get("TARGET_TEAM", "").strip().lower()
        target_league_env = os.environ.get("TARGET_LEAGUE", "").strip().lower()
        
        if target_team_env:
            log.info("Looking for Target Team in slots...")
            for l in leagues:
                team_match = target_team_env in l["team_name"].lower()
                league_match = not target_league_env or target_league_env in l["league_name"].lower()
                
                if team_match and league_match:
                    target_slot = l["slot_index"]
                    target_league_data = l
                    break

            if target_slot is None:
                log.warning("Could not find exact match for target team. Looking for any partial match...")
                for l in leagues:
                    if target_team_env in l["team_name"].lower():
                        target_slot = l["slot_index"]
                        target_league_data = l
                        break
                        
        if target_slot is not None:
            log.info(f"Switching to slot {target_slot}...")
            switch_league_slot(pw, target_league_data)
        elif target_team_env:
            log.error("Could not find target team in any slot. Continuing on current slot...")
        else:
            log.info("No TARGET_TEAM specified. Continuing on current active slot...")

        # 2. Launch browser and loop
        log.info("Launching browser...")
        browser = pw.chromium.launch(
            headless=False,
            channel="chrome",
            args=[
                "--mute-audio",
                "--window-position=-32000,-32000",
                "--window-size=1280,800"
            ]
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=_USER_AGENT,
        )
        
        # Load fresh cookies (in case slot switch updated them)
        with open(COOKIES_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        
        page = context.new_page()
        
        # --- Check Transfer List Status First ---
        transfer_status = "?/4"
        try:
            log.info("Checking Transfer List status...")
            api_loaded = []
            def handle_res(res):
                if "api/v1/" in res.url and "players" in res.url:
                    api_loaded.append(True)
            page.on("response", handle_res)
            
            page.goto(f"{BASE_URL}/Transferlist", wait_until="domcontentloaded", timeout=60000)
            
            # Wait dynamically up to 10s for the API to return before reading the DOM
            for _ in range(20):
                if api_loaded: break
                page.wait_for_timeout(500)
                
            page.remove_listener("response", handle_res)
            page.wait_for_timeout(1500) # Give Knockout.js time to update the UI
            
            # Using the exact HTML data-bind provided by the user!
            badge = page.locator("span[data-bind*='availableSellPlayerSlotsAmount']").first
            if badge.is_visible(timeout=2000):
                text = badge.inner_text()
                match = re.search(r"(\d/4)", text)
                if match:
                    transfer_status = match.group(1)
            else:
                # Fallback if the UI changes
                body_text = page.locator("body").inner_text()
                matches = re.findall(r"\b([0-4])/4\b", body_text)
                if matches:
                    max_listed = max([int(m) for m in matches])
                    transfer_status = f"{max_listed}/4"
                    
            log.info("Transfer list status checked.")
        except Exception as e:
            log.error(f"Could not read transfer list: {e}")
        # ----------------------------------------
        
        starting_coins = None
        
        while True:
            try:
                log.info("Navigating to Business Club...")
                page.goto(f"{BASE_URL}/BusinessClub", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                current_coins = page.evaluate(GET_BOSS_COINS_JS)
                if starting_coins is None:
                    starting_coins = current_coins
                    log.info("💰 Checked starting Boss Coins.")
                    send_whatsapp_message(f"▶️ OSM Claimer Started\nCurrent balance: {starting_coins} coins\n🛒 Players listed: {transfer_status}")
                else:
                    log.info("💰 Checked current Boss Coins.")
                
                # Accept privacy cookies if the popup appears
                try:
                    accept_btn = page.locator("button:has-text('Accept'), button:has-text('Akkoord')").first
                    if accept_btn.is_visible(timeout=2000):
                        accept_btn.click()
                        page.wait_for_timeout(1000)
                except:
                    pass

                # Look for the Watch Ad button
                watch_ad_btn = page.locator("text='Watch ad'").first
                if watch_ad_btn.is_visible(timeout=3000):
                    log.info("Clicking 'Watch ad'...")
                    watch_ad_btn.click()
                    
                    page.wait_for_timeout(2000)
                    limit_text = page.locator("text=Come back in").first
                    if limit_text.is_visible(timeout=2000):
                        text = limit_text.inner_text()
                        match = re.search(r"Come back in (\d+) minutes", text)
                        wait_time = int(match.group(1)) if match else 24
                        
                        log.info(f"Limit reached: {text}")
                        log.info("Exiting script. GitHub Actions will restart it later!")
                        send_whatsapp_message(f"OSM Update ⚽\nStarted with: {starting_coins} coins\nNew total: {current_coins} coins!\n🛒 Players listed: {transfer_status}")
                        send_whatsapp_message("----------------------------")
                        return
                        
                    log.info("Ad started playing. Waiting 65 seconds to make sure it finishes...")
                    page.wait_for_timeout(65000)
                    
                    log.info("Reloading for next ad...")
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)
                    
                    coins = page.evaluate(GET_BOSS_COINS_JS)
                    log.info("💰 Boss Coins successfully updated.")
                else:
                    limit_text = page.locator("text=Come back in").first
                    if limit_text.is_visible(timeout=2000):
                        text = limit_text.inner_text()
                        log.info(f"Limit reached (button hidden): {text}")
                        log.info("Exiting script. GitHub Actions will restart it later!")
                        send_whatsapp_message(f"OSM Update ⚽\nStarted with: {starting_coins} coins\nNew total: {current_coins} coins!")
                        send_whatsapp_message("----------------------------")
                        return
                    else:
                        log.warning("'Watch ad' button not found and no limit popup. Waiting 10 seconds before checking again...")
                        page.wait_for_timeout(10000)
                    
            except Exception as e:
                log.error(f"Error in claim loop: {e}")
                log.info("Exiting on error...")
                return

if __name__ == "__main__":
    # Add a random delay between 10 seconds and 5 minutes
    delay_seconds = random.randint(10, 300)
    log.info(f"Adding a random human-like delay of {delay_seconds} seconds before starting...")
    time.sleep(delay_seconds)
    claim_loop()
