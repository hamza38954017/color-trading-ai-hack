"""
wingo_proxy.py — Async proxy to fetch WinGo game data from draw.ar-lottery01.com
Mimics the PHP cURL logic exactly.
"""
import requests, time

HEADERS = {
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-GB",
    "Origin":          "https://jaiclub00.com",
    "Referer":         "https://jaiclub00.com/",
    "User-Agent":      "Mozilla/5.0 (Android 15; Mobile; rv:151.0) Gecko/151.0 Firefox/151.0",
}
ALLOWED = {"WinGo_3M", "WinGo_5M"}
TIMEOUT = 10

def fetch_wingo(game: str, data_type: str) -> dict:
    """Fetch current or history data for a WinGo game. Returns parsed JSON or {error:...}."""
    if game not in ALLOWED:
        return {"error": "Invalid game code"}
    ts = int(time.time() * 1000)
    if data_type == "current":
        url = f"https://draw.ar-lottery01.com/WinGo/{game}.json?ts={ts}"
    else:
        url = f"https://draw.ar-lottery01.com/WinGo/{game}/GetHistoryIssuePage.json?ts={ts}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, verify=False)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}
