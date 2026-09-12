import os
import time
import requests
import cloudscraper
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from mail_senders import SmtpSender, HourMailerSender, MailSenderFactory

# Load environment variables
load_dotenv()

# --- Configuration ---
FROM_CITY = os.getenv("FROM_CITY", "75493")
TO_CITY = os.getenv("TO_CITY", "314648")
DATE = os.getenv("DATE", "28-Sep-2026")
LIMIT = int(os.getenv("LIMIT", "50"))

# Mail Configuration
HOURMAILER_API_KEY = os.getenv("HOURMAILER_API_KEY", "")
SMTP_HOST     = os.getenv("SMTP_HOST", "")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "")
TO_EMAILS = os.getenv("TO_EMAILS", "anilabhadatta@gmail.com").split(",")

# Tracker Settings
CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
# ---------------------

# Build mail factory — senders tried in order; first success wins
mail_factory = MailSenderFactory([
    SmtpSender(SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM),  # Priority 1
    HourMailerSender(HOURMAILER_API_KEY),                                        # Priority 2 (fallback)
])

# Tracks the set of bus names from the last notification to detect changes
previous_bus_names = None  # None = first run (no prior state)

def send_email(subject, body):
    mail_factory.send(TO_EMAILS, subject, body)

def send_telegram(bus_list):
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    
    if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        print("Skipping Telegram notification — credentials not configured.")
        return
        
    try:
        # Build plain text message using MarkdownV2 format for Telegram
        text_msg = "🚍 *NBSTC Bus Found on RedBus!*\n\n"
        for b in bus_list:
            name = b.get('travelsName', '')
            date = b.get('checked_date', '')
            
            time_str = b.get('serviceStartTime', b.get('departureTime', ''))
            if ' ' in time_str:
                time_str = time_str.split(' ')[1]
            time_str = time_str[:12]
            
            bus_type = b.get('busType', '')
            seats = str(b.get('availableSeats', ''))
            
            fare_info = []
            fare_details = b.get('fareDetailsBySeatType', {})
            for seat_type, fares in fare_details.items():
                if isinstance(fares, list) and len(fares) > 0:
                    price = fares[0].get('originalPrice', '')
                    fare_info.append(f"₹{price}")
                    
            fare_str = ", ".join(fare_info)
            if not fare_str:
                fare_list = b.get('fareList', [])
                if fare_list:
                    fare_str = f"₹{fare_list[0]}"
                    
            text_msg += f"🚌 *{name}*\n"
            text_msg += f"📅 {date} | 🕒 {time_str}\n"
            text_msg += f"💺 {seats} seats | 💰 {fare_str}\n"
            text_msg += f"ℹ️ {bus_type}\n"
            text_msg += "------------------------\n"
        
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text_msg,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("Telegram message sent successfully!")
        else:
            print(f"Failed to send Telegram message: {response.text}")
    except Exception as e:
        print(f"Failed to send Telegram message: {e}")

def _make_single_twilio_call(client, twiml_msg, call_from, call_to, max_retries, retry_delay):
    for attempt in range(max_retries):
        try:
            call = client.calls.create(
                twiml=twiml_msg,
                to=call_to,
                from_=call_from
            )
            print(f"[{call_to}] Phone call initiated (Attempt {attempt+1}/{max_retries}). Call SID: {call.sid}")
            
            # Poll the call status to see if they picked up
            while True:
                time.sleep(1)
                call_status = client.calls(call.sid).fetch().status
                if call_status in ['queued', 'ringing', 'in-progress']:
                    continue
                else:
                    break
            
            print(f"[{call_to}] Call ended with status: {call_status}")
            if call_status == 'completed':
                print(f"[{call_to}] Call was picked up successfully!")
                return # Exit the function, no need to retry
            else:
                print(f"[{call_to}] Call was not answered. (Status: {call_status})")
        
        except Exception as e:
            print(f"[{call_to}] Failed to place phone call on attempt {attempt+1}: {e}")
            
        if attempt < max_retries - 1:
            print(f"[{call_to}] Retrying call in {retry_delay} seconds...")
            time.sleep(retry_delay)

def make_twilio_call(date_str):
    TWILIO_CALL_ENABLED = os.getenv("TWILIO_CALL_ENABLED", "false").lower() == "true"
    
    if not TWILIO_CALL_ENABLED:
        print("Skipping Twilio voice call — disabled via TWILIO_CALL_ENABLED flag.")
        return

    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_CALL_FROM = os.getenv("TWILIO_CALL_FROM", "+18042590516")
    twilio_call_to_raw = os.getenv("TWILIO_CALL_TO", "+917003346153")
    
    max_retries = int(os.getenv("TWILIO_CALL_MAX_RETRIES", "3"))
    retry_delay = int(os.getenv("TWILIO_CALL_RETRY_DELAY_SEC", "20"))
    
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN]):
        print("Skipping Twilio voice call — credentials not configured.")
        return
        
    call_to_numbers = [num.strip() for num in twilio_call_to_raw.split(',') if num.strip()]
    if not call_to_numbers:
        print("Skipping Twilio voice call — no destination numbers configured.")
        return
        
    try:
        from twilio.rest import Client
        import concurrent.futures
        
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        twiml_msg = f'<Response><Say>Redbus ticket found for {date_str}</Say></Response>'
        
        print(f"Initiating Twilio calls to {len(call_to_numbers)} number(s)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(call_to_numbers)) as executor:
            for number in call_to_numbers:
                executor.submit(_make_single_twilio_call, client, twiml_msg, TWILIO_CALL_FROM, number, max_retries, retry_delay)
                
    except Exception as e:
        print(f"Failed to initialize Twilio client: {e}")

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
            body += "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse; font-family:sans-serif; font-size:13px; text-align:left;'>"
            body += "<tr style='background-color:#1a1a2e; color:#ffffff;'>"
            body += "<th>Bus Name</th><th>Date</th><th>Time</th><th>Type</th><th>Seats</th><th>Fare</th>"
            body += "</tr>"

            # Show ALL buses; highlight newly added ones in green with ★ NEW badge
            for i, b in enumerate(found_buses):
                name = b.get('travelsName', '')
                is_new = name.upper() in added

                if is_new:
                    row_style = "background-color:#d4edda; font-weight:bold;"
                elif i % 2 == 0:
                    row_style = "background-color:#f9f9f9;"
                else:
                    row_style = ""

                badge = (
                    ' &nbsp;<span style="background:#28a745;color:#fff;padding:1px 6px;'
                    'border-radius:4px;font-size:11px;">★ NEW</span>'
                    if is_new else ""
                )

                date = b.get('checked_date', '')

                # Try getting serviceStartTime or departureTime
                time_str = b.get('serviceStartTime', b.get('departureTime', ''))
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

                body += (
                    f"<tr style='{row_style}'>"
                    f"<td>{name}{badge}</td><td>{date}</td><td>{time_str}</td>"
                    f"<td>{bus_type}</td><td>{seats}</td><td>{fare_str}</td>"
                    f"</tr>"
                )

            body += "</table>"

            send_email(subject, body)
            
            # Send Telegram notification with all newly found buses
            new_buses = [b for b in found_buses if b.get('travelsName', '').upper() in added]
            if not new_buses:
                new_buses = found_buses
                
            if new_buses:
                send_telegram(new_buses)
                make_twilio_call(DATE)

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
