import os
import time
import re
import json
import logging
from playwright.sync_api import sync_playwright
import urllib.parse

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
        browser = pw.chromium.launch(headless=False)
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
    browser = pw.chromium.launch(headless=True)
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

        # 1. Switch to Liverpool in Winners Cup
        leagues = get_user_leagues(pw, cookies)
        target_slot = None
        target_league_data = None
        
        for l in leagues:
            if "liverpool" in l["team_name"].lower() and "winners cup" in l["league_name"].lower():
                target_slot = l["slot_index"]
                target_league_data = l
                break

        if target_slot is None:
            log.warning("Could not find Liverpool in Winners Cup exactly. Looking for any Liverpool...")
            for l in leagues:
                if "liverpool" in l["team_name"].lower():
                    target_slot = l["slot_index"]
                    target_league_data = l
                    break
                    
        if target_slot is not None:
            log.info(f"Switching to slot {target_slot}...")
            switch_league_slot(pw, target_league_data)
        else:
            log.error("Could not find Liverpool in any slot. Continuing anyway...")

        # 2. Launch browser and loop
        # We launch headless=False. On cloud servers, this requires xvfb!
        browser = pw.chromium.launch(
            headless=False,
            args=["--mute-audio", "--window-position=-32000,-32000", "--window-size=1280,800"]
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
        
        while True:
            try:
                log.info("Navigating to Business Club...")
                page.goto(f"{BASE_URL}/BusinessClub", wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                
                initial_coins = page.evaluate(GET_BOSS_COINS_JS)
                log.info(f"💰 Current Boss Coins: {initial_coins}")
                
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
                        return
                        
                    log.info("Ad started playing. Waiting 45 seconds...")
                    page.wait_for_timeout(45000)
                    
                    log.info("Reloading for next ad...")
                    page.reload(wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)
                    
                    coins = page.evaluate(GET_BOSS_COINS_JS)
                    log.info(f"🎉 New total of Boss Coins: {coins}")
                else:
                    limit_text = page.locator("text=Come back in").first
                    if limit_text.is_visible(timeout=2000):
                        text = limit_text.inner_text()
                        log.info(f"Limit reached (button hidden): {text}")
                        log.info("Exiting script. GitHub Actions will restart it later!")
                        return
                    else:
                        log.warning("'Watch ad' button not found and no limit popup. Waiting 10 seconds before checking again...")
                        page.wait_for_timeout(10000)
                    
            except Exception as e:
                log.error(f"Error in claim loop: {e}")
                log.info("Exiting on error...")
                return

if __name__ == "__main__":
    claim_loop()
