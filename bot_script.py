import os, sys, requests, smtplib, mimetypes, base64
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from playwright.sync_api import Playwright, sync_playwright

# Configuration from Secrets
USER_ID = os.environ.get('APP_USER')
USER_PW = os.environ.get('APP_PASS')
SITE_URL = os.environ.get('APP_URL')
KEY = os.environ.get('ENCRYPT_KEY', 'DefaultKey007') # กุญแจล็อกไฟล์
MY_ADDR = os.environ.get('MAIL_USER')
MY_PW = os.environ.get('MAIL_PASS')
TARGET_ADDRS = os.environ.get('MAIL_RECIPIENTS', '').split(',')
SIGNATURE = os.environ.get('MAIL_SIGNATURE', 'Best Regards')

LOG_FILE = "log_history.txt"

# --- ระบบล็อก/ปลดล็อกกุญแจชื่อไฟล์ ---
def encrypt_name(text):
    result = ""
    for i in range(len(text)):
        result += chr(ord(text[i]) ^ ord(KEY[i % len(KEY)]))
    return base64.b64encode(result.encode()).decode()

def decrypt_name(encoded_text):
    try:
        decoded = base64.b64decode(encoded_text).decode()
        result = ""
        for i in range(len(decoded)):
            result += chr(ord(decoded[i]) ^ ord(KEY[i % len(KEY)]))
        return result
    except: return ""

def get_history():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return {decrypt_name(line) for line in f.read().splitlines()}
    return set()

def save_history(entry):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(encrypt_name(entry) + "\n")

# --- ระบบแจ้งเตือนและอีเมล ---
def notify_chat(title):
    webhook = os.environ.get('CHAT_WEBHOOK')
    repo_link = os.environ.get('ACTION_URL', '#')
    payload = {
        "cardsV2": [{
            "cardId": "approvalCard",
            "card": {
                "header": { "title": "🔔 พบไฟล์ใหม่รออนุมัติ", "subtitle": "Portal Sync System" },
                "sections": [{
                    "widgets": [
                        { "textParagraph": { "text": f"<b>รายการ:</b> {title}" } },
                        { "buttonList": { "buttons": [{
                            "text": "คลิกเพื่อ APPROVE",
                            "onClick": { "openLink": { "url": repo_link } }
                        }] } }
                    ]
                }]
            }
        }]
    }
    requests.post(webhook, json=payload)

def dispatch_email(file_path, details, title):
    msg = EmailMessage()
    msg['Subject'] = f"Service Bulletin Update : {title}"
    msg['From'] = formataddr(("Technical Support System", MY_ADDR))
    if TARGET_ADDRS:
        msg['To'] = TARGET_ADDRS[0]
        if len(TARGET_ADDRS) > 1: msg['Cc'] = ", ".join(TARGET_ADDRS[1:])

    body = f"Dear all,\n\n"
    body += f"Category            : {details.get('Category', '-')}\n"
    body += f"Document No.    : {details.get('DocNo', '-')}\n"
    body += f"Published by      : {details.get('Publisher', '-')}\n"
    body += f"Model Reference  : {details.get('Model', '-')}\n\n"
    body += "Best Regards,\n\n"
    body += "-----------------------------------------------------------------\n"
    body += f"{SIGNATURE}"
    
    msg.set_content(body)
    ctype, _ = mimetypes.guess_type(file_path)
    maintype, subtype = (ctype or 'application/octet-stream').split('/', 1)
    with open(file_path, 'rb') as f:
        msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=os.path.basename(file_path))

    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
        smtp.starttls()
        smtp.login(MY_ADDR, MY_PW)
        smtp.send_message(msg)

# --- ระบบหลัก ---
def execute(pw: Playwright, mode: str):
    history = get_history()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    
    page.goto(SITE_URL)
    page.get_by_role("textbox", name="Username").fill(USER_ID)
    page.get_by_role("textbox", name="Password").fill(USER_PW)
    page.get_by_role("button", name="Log In").click()
    
    page.get_by_role("link", name="See All").nth(1).click()
    page.wait_for_timeout(5000)

    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y/%m/%d") for i in range(3)]
    
    for d in dates:
        items = page.evaluate(f"""() => {{
            let res = [];
            document.querySelectorAll('a').forEach(a => {{
                let row = a.closest('tr') || a.parentElement.parentElement;
                if (row && row.innerText.includes('{d}')) {{
                    let t = a.innerText.trim();
                    if (t.length > 5 && t !== 'See All') res.push(t);
                }}
            }});
            return res;
        }}""")

        for item_name in items:
            if item_name in history: continue
            
            if mode == "check":
                notify_chat(item_name)
                print(f"Scouted and Notified: {item_name}")
                sys.exit(0)

            if mode == "send":
                page.get_by_role("link", name=item_name).first.click()
                page.wait_for_timeout(4000)
                
                info = page.evaluate("""() => {
                    let d = {};
                    document.querySelectorAll('table tr').forEach(r => {
                        let c = r.querySelectorAll('th, td');
                        if (c.length >= 2) {
                            let k = c[0].innerText.trim();
                            let v = c[1].innerText.trim();
                            if (k.includes('Category')) d['Category'] = v;
                            if (k.includes('Document No')) d['DocNo'] = v;
                            if (k.includes('Published by')) d['Publisher'] = v;
                            if (k.includes('Vehicle Model')) d['Model'] = v;
                        }
                    });
                    return d;
                }""")

                checkboxes = page.locator("input[type='checkbox']")
                if checkboxes.count() > 0:
                    for i in range(checkboxes.count()): checkboxes.nth(i).check()
                    page.evaluate('document.querySelector(".download_button").removeAttribute("disabled")')
                    with page.expect_download() as dl:
                        page.locator(".download_button").click(force=True)
                    
                    path = f"/tmp/{dl.value.suggested_filename}"
                    dl.value.save_as(path)
                    dispatch_email(path, info, item_name)
                    save_history(item_name)
                    print(f"Successfully Dispatched: {item_name}")
                page.go_back()

    browser.close()

if __name__ == "__main__":
    m = "check"
    if "--mode" in sys.argv: m = sys.argv[sys.argv.index("--mode") + 1]
    with sync_playwright() as playwright: execute(playwright, m)
