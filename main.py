import asyncio
import cloudscraper
import json
import time
import uuid
import random
from loguru import logger

# Konfigurasi
PING_INTERVAL = 30  # Interval waktu ping (detik)
MAX_RETRIES = 3  # Maksimal percakapan ulang untuk tiap proxy
MAX_CONNECTIONS = 15  # Jumlah koneksi simultan yang diperbolehkan
BACKOFF_BASE = 2  # Basis waktu backoff eksponensial

# URL API
DOMAIN_API = {
    "SESSION": "https://api.nodepay.ai/api/auth/session",
    "PING": [
        "http://13.215.134.222/api/network/ping",
        "http://52.77.10.116/api/network/ping"
    ]
}

# Status koneksi
CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

status_connect = CONNECTION_STATES["NONE_CONNECTION"]
account_info = {}

# Informasi Browser
browser_id = {
    'ping_count': 0,
    'successful_pings': 0,
    'score': 0,
    'start_time': time.time(),
    'last_ping_status': 'Waiting...',
    'last_ping_time': None
}

# Fungsi untuk memuat token
def load_token():
    try:
        with open('Token.txt', 'r') as file:
            token = file.read().strip()
            return token
    except Exception as e:
        logger.error(f"Failed to load token: {e}")
        raise SystemExit("Exiting due to failure in loading token")

# Token info
token_info = load_token()

# Membuat scraper
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    }
)

# UUID generator
def uuidv4():
    return str(uuid.uuid4())

# Validasi respon dari API
def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("Invalid response")
    return resp

# Fungsi untuk merender info profil pengguna
async def render_profile_info(proxy):
    global account_info

    try:
        np_session_info = load_session_info(proxy)

        if not np_session_info:
            response = await call_api(DOMAIN_API["SESSION"], {}, proxy)
            valid_resp(response)
            account_info = response["data"]
            if account_info.get("uid"):
                save_session_info(proxy, account_info)
                await start_ping(proxy)
            else:
                handle_logout(proxy)
        else:
            account_info = np_session_info
            await start_ping(proxy)
    except Exception as e:
        logger.error(f"Error in render_profile_info for proxy {proxy}: {e}")
        if any(phrase in str(e) for phrase in [
            "sent 1011 (internal error) keepalive ping timeout; no close frame received",
            "500 Internal Server Error"
        ]):
            logger.info(f"Removing error proxy from the list: {proxy}")
            remove_proxy_from_list(proxy)
        return None

# Fungsi untuk melakukan panggilan API
async def call_api(url, data, proxy, token=None):
    headers = {
        "Authorization": f"Bearer {token or token_info}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://app.nodepay.ai/",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://app.nodepay.ai",
        "Sec-Ch-Ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cors-site"
    }

    try:
        response = scraper.post(url, json=data, headers=headers, proxies={"http": proxy, "https": proxy}, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Error during API call: {e}")
        raise ValueError(f"Failed API call to {url}")

    return valid_resp(response.json())

# Fungsi untuk memulai ping ke server secara periodik
async def start_ping(proxy):
    try:
        await ping(proxy)
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await ping(proxy)
    except asyncio.CancelledError:
        logger.info(f"Ping task for proxy {proxy} was cancelled")
    except Exception as e:
        logger.error(f"Error in start_ping for proxy {proxy}: {e}")

# Fungsi untuk melakukan ping
async def ping(proxy):
    global status_connect

    retries = 0
    for url in DOMAIN_API["PING"]:
        try:
            data = {
                "id": account_info.get("uid"),
                "browser_id": browser_id,
                "timestamp": int(time.time())
            }

            response = await call_api(url, data, proxy)
            if response["code"] == 0:
                logger.info(f"Ping successful via proxy {proxy} using URL {url}: {response}")
                status_connect = CONNECTION_STATES["CONNECTED"]
                browser_id['successful_pings'] += 1
                return
            else:
                retries += 1
                await handle_ping_fail(proxy, retries)
        except Exception as e:
            logger.error(f"Ping failed via proxy {proxy} using URL {url}: {e}")
            retries += 1
            await handle_ping_fail(proxy, retries)

# Fungsi untuk menangani kegagalan ping
async def handle_ping_fail(proxy, retries):
    global status_connect

    if retries >= MAX_RETRIES:
        logger.error(f"Max retries reached for proxy {proxy}, disconnecting.")
        status_connect = CONNECTION_STATES["DISCONNECTED"]
    else:
        backoff_time = BACKOFF_BASE ** retries  # Backoff eksponensial
        logger.warning(f"Retrying proxy {proxy}, attempt {retries}. Backing off for {backoff_time} seconds.")
        await asyncio.sleep(backoff_time)

# Fungsi untuk menangani logout dan reset sesi
def handle_logout(proxy):
    global token_info, status_connect, account_info
    token_info = None
    status_connect = CONNECTION_STATES["NONE_CONNECTION"]
    account_info = {}
    save_status(proxy, None)
    logger.info(f"Logged out and cleared session info for proxy {proxy}")

# Fungsi untuk memuat proxy dari file
def load_proxies(proxy_file):
    try:
        with open(proxy_file, 'r') as file:
            proxies = file.read().splitlines()
        return proxies
    except Exception as e:
        logger.error(f"Failed to load proxies: {e}")
        raise SystemExit("Exiting due to failure in loading proxies")

# Fungsi untuk menyimpan status
def save_status(proxy, status):
    # Placeholder: Anda bisa menambahkan logika untuk menyimpan status ke database atau file
    pass

# Fungsi untuk menyimpan info sesi
def save_session_info(proxy, data):
    # Placeholder: Simpan info sesi ke file atau database
    pass

# Fungsi untuk memuat info sesi
def load_session_info(proxy):
    # Placeholder: Muat info sesi jika ada
    return {}

# Fungsi untuk memvalidasi proxy
def is_valid_proxy(proxy):
    try:
        response = scraper.get("http://example.com", proxies={"http": proxy, "https": proxy}, timeout=5)
        return response.status_code == 200
    except Exception:
        return False

# Fungsi untuk menghapus proxy dari daftar
def remove_proxy_from_list(proxy):
    # Placeholder: Implementasikan penghapusan proxy dari daftar aktif
    pass

# Fungsi utama yang menjalankan program
async def main():
    with open('Proxy.txt', 'r') as f:
        all_proxies = f.read().splitlines()
    
    active_proxies = [proxy for proxy in all_proxies[:MAX_CONNECTIONS] if is_valid_proxy(proxy)]
    tasks = {asyncio.create_task(render_profile_info(proxy)): proxy for proxy in active_proxies}

    while True:
        done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        
        for task in done:
            failed_proxy = tasks[task]
            
            if task.result() is None:
                logger.info(f"Removing and replacing failed proxy: {failed_proxy}")
                active_proxies.remove(failed_proxy)
                
                if all_proxies:
                    new_proxy = all_proxies.pop(0)
                    if is_valid_proxy(new_proxy):
                        active_proxies.append(new_proxy)
                        new_task = asyncio.create_task(render_profile_info(new_proxy))
                        tasks[new_task] = new_proxy
            
            tasks.pop(task)

        while len(tasks) < MAX_CONNECTIONS and all_proxies:
            new_proxy = all_proxies.pop(0)
            if is_valid_proxy(new_proxy):
                active_proxies.append(new_proxy)
                new_task = asyncio.create_task(render_profile_info(new_proxy))
                tasks[new_task] = new_proxy

        await asyncio.sleep(3)

# Menjalankan program utama
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Program terminated by user.")
