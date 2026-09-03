import os
import time
import requests
import cloudscraper
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- Configuration ---
FROM_CITY = os.getenv("FROM_CITY", "75493")
TO_CITY = os.getenv("TO_CITY", "314648")
DATE = os.getenv("DATE", "28-Sep-2026")
LIMIT = int(os.getenv("LIMIT", "50"))

# Mail Configuration
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY", "")
TO_EMAILS = os.getenv("TO_EMAILS", "anilabhadatta@gmail.com").split(",")

# Tracker Settings
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
# ---------------------

# Tracks the set of bus names from the last notification to detect changes
previous_bus_names = None  # None = first run (no prior state)

def send_email(subject, body):
    url = "https://hourmailer.p.rapidapi.com/send"
    headers = {
        "content-type": "application/json",
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "hourmailer.p.rapidapi.com"
    }
    
    for email_address in TO_EMAILS:
        email_address = email_address.strip()
        if not email_address:
            continue
            
        payload = {
            "toAddress": email_address,
            "title": subject,
            "message": body
        }
        
        try:
            response = requests.request("POST", url, json=payload, headers=headers)
            print(f"Email sent to {email_address} - API Response: {response.text}")
        except Exception as e:
            print(f"Error sending email to {email_address}: {e}")

def get_scraper():
    import ssl
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.orig_wrap_socket = ctx.wrap_socket
    return cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True},
        ssl_context=ctx
    )

def check_bus_availability():
    global previous_bus_names
        
    # Using cloudscraper to bypass potential bot protections (like Cloudflare)
    scraper = get_scraper()
    
    headers = {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9,en-IN;q=0.8",
        "content-type": "application/json",
        "origin": "https://www.redbus.in",
        "referer": "https://www.redbus.in/search?fromCityName=Esplanade&toCityName=Siliguri%20Junction%2C%20Siliguri&fromCityId=75493&toCityId=314648&onward=26-Sep-2026&return=NaN-undefined-NaN&ref=modifyDate",
        "sec-ch-ua": '"Chromium";v="152", "Not?A_Brand";v="24", "Microsoft Edge";v="152"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36 Edg/152.0.0.0"
    }
    
    # URL 1: General search
    url1 = f"https://www.redbus.in/rpw/api/searchResults?fromCity={FROM_CITY}&toCity={TO_CITY}&DOJ={DATE}&limit={LIMIT}&offset=0&meta=false&groupId=0&sectionId=1&sort=0&sortOrder=0&from=use%20effect%20search%20render&getUuid=false&bT=1&clearLMBFilter=undefined&isFilterApplied=false"
    
    # URL 2: Group ID 24978 search (NBSTC group ID)
    url2 = f"https://www.redbus.in/rpw/api/searchResults?fromCity={FROM_CITY}&toCity={TO_CITY}&DOJ={DATE}&limit={LIMIT}&offset=0&meta=false&groupId=24978&sectionId=1&sort=0&sortOrder=0&from=useeffect_group_load&getUuid=false&bT=1&clearLMBFilter=undefined&isFilterApplied=false"
    
    found_buses = []
    seen_route_ids = set()
    
    for url in [url1, url2]:
        response = None
        for attempt in range(3):
            try:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking URL for {DATE} (Attempt {attempt+1}/3)...")
                response = scraper.post(url, headers=headers, json={}, timeout=15)
                
                if response.status_code == 200:
                    break
                else:
                    print(f"Failed to fetch data, status code: {response.status_code}. Retrying...")
                    scraper = get_scraper()
                    time.sleep(2)
            except Exception as e:
                print(f"Error fetching data: {type(e).__name__} - {e}. Retrying...")
                scraper = get_scraper()
                time.sleep(2)
        
        if not response or response.status_code != 200:
            print(f"Skipping URL after 3 failed attempts.")
            continue
            
        try:
            data = response.json()
        except Exception as e:
            print(f"Error parsing JSON. Response snippet: {response.text[:300]}")
            continue
        
        # Check response structure
        if data.get("success") and "data" in data and "inventories" in data["data"]:
            inventories = data["data"]["inventories"]
            
            for bus in inventories:
                travels_name = bus.get("travelsName", "").upper()
                operator_id = bus.get("operatorId")
                
                # Identify NBSTC buses by name or operator ID
                if "NBSTC" in travels_name or operator_id == 24978:
                    if travels_name not in seen_route_ids:
                        bus['checked_date'] = DATE
                        found_buses.append(bus)
                        seen_route_ids.add(travels_name)
        else:
            print(f"Unexpected response structure or no data. Keys found: {list(data.keys())[:5]}")
            
    current_bus_names = frozenset(b.get('travelsName', '').upper() for b in found_buses)

    if found_buses:
        print(f"Found {len(found_buses)} NBSTC buses!")
        for b in found_buses:
            print(f" - {b.get('travelsName')} on {b.get('checked_date')}")

        # Determine newly added buses since last check (by name only)
        added = current_bus_names - previous_bus_names if previous_bus_names is not None else current_bus_names

        if not added:
            print("No new buses added since last check — skipping email.")
        else:
            if previous_bus_names is None:
                change_reason = f"First detection: {len(added)} bus(es) found."
            else:
                change_reason = f"{len(added)} new bus(es) added."

            print(f"{change_reason} Sending email notification...")
            ist_timezone = timezone(timedelta(hours=5, minutes=30))
            current_ist_time = datetime.now(ist_timezone).strftime('%Y-%m-%d %H:%M:%S')

            subject = "NBSTC Bus Found on RedBus!"

            body = f"<p><strong>Mail generated at:</strong> {current_ist_time} IST</p>"
            body += f"<p><strong>Change detected:</strong> {change_reason}</p>"
            body += "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse: collapse; font-family: sans-serif; text-align: left;'>"
            body += "<tr style='background-color: #f2f2f2;'>"
            body += "<th>Bus Name</th><th>Date</th><th>Time</th><th>Type</th><th>Seats</th><th>Fare</th>"
            body += "</tr>"

            # Only include the newly added buses in the email
            new_buses = [b for b in found_buses if b.get('travelsName', '').upper() in added]
            for b in new_buses:
                name = b.get('travelsName', '')
                date = b.get('checked_date', '')

                # Try getting serviceStartTime or departureTime
                time_str = b.get('serviceStartTime', b.get('departureTime', ''))
                # Just take the time part if it's a full datetime string
                if ' ' in time_str:
                    time_str = time_str.split(' ')[1]
                time_str = time_str[:12]

                bus_type = b.get('busType', '')
                seats = str(b.get('availableSeats', ''))

                # Parse fareDetailsBySeatType
                fare_info = []
                fare_details = b.get('fareDetailsBySeatType', {})
                for seat_type, fares in fare_details.items():
                    if isinstance(fares, list) and len(fares) > 0:
                        price = fares[0].get('originalPrice', '')
                        count = fares[0].get('count', '')
                        fare_info.append(f"{seat_type}: ₹{price} ({count} seats)")

                fare_str = "<br>".join(fare_info)
                if not fare_str:
                    fare_list = b.get('fareList', [])
                    if fare_list:
                        fare_str = str(fare_list[0])

                body += f"<tr><td>{name}</td><td>{date}</td><td>{time_str}</td><td>{bus_type}</td><td>{seats}</td><td>{fare_str}</td></tr>"

            body += "</table>"

            send_email(subject, body)

        # Always update state to reflect current bus list (handles removals silently)
        previous_bus_names = current_bus_names
    else:
        print("No NBSTC buses found at this time.")
        # Reset state so re-appearance of buses triggers a fresh email
        previous_bus_names = current_bus_names

def main():
    print("Starting NBSTC bus tracker...")
    print(f"Parameters: FROM={FROM_CITY}, TO={TO_CITY}, LIMIT={LIMIT}")
    print(f"Checking every {CHECK_INTERVAL_SECONDS} seconds. Email sent only when bus list changes.\n")

    while True:
        check_bus_availability()
        print(f"Waiting for {CHECK_INTERVAL_SECONDS} seconds before next check...\n")
        time.sleep(CHECK_INTERVAL_SECONDS)

if __name__ == "__main__":
    main()
