import os, sys, requests, smtplib, mimetypes, base64, json
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from playwright.sync_api import Playwright, sync_playwright

USER_ID = os.environ.get('APP_USER')
USER_PW = os.environ.get('APP_PASS')
SITE_URL = os.environ.get('APP_URL')
KEY = os.environ.get('ENCRYPT_KEY', 'DefaultKey007')
MY_ADDR = os.environ.get('MAIL_USER')
MY_PW = os.environ.get('MAIL_PASS')
TARGET_ADDRS = os.environ.get('MAIL_RECIPIENTS', '').split(',')
SIGNATURE = os.environ.get('MAIL_SIGNATURE', 'Best Regards')
LOG_FILE = "log_history.txt"

def encrypt_name(text):
    res = "".join(chr(ord(text[i]) ^ ord(KEY[i % len(KEY)])) for i in range(len(text)))
    return base64.b64encode(res.encode()).decode()

def decrypt_name(encoded_text):
    try:
        decoded = base64.b64decode(encoded_text).decode()
        return "".join(chr(ord(decoded[i]) ^ ord(KEY[i % len(KEY)])) for i in range(len(decoded)))
    except: return ""

def get_history():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return {decrypt_name(line) for line in f.read().splitlines() if line.strip()}
    return set()

def save_history(entry):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(encrypt_name(entry) + "\n")

def notify_chat(title, action_url):
    webhook = os.environ.get('CHAT_WEBHOOK')
    payload = {
        "cardsV2": [{
            "cardId": "approvalCard",
            "card": {
                "header": { "title": "🔔 พบไฟล์ใหม่รออนุมัติ", "subtitle": "รายไฟล์" },
                "sections": [{
                    "widgets": [
                        { "textParagraph": { "text": f"<b>รายการ:</b> {title}" } },
                        { "buttonList": { "buttons": [{
                            "text": "คลิกเพื่อไปหน้า APPROVE",
                            "onClick": { "openLink": { "url": action_url } }
                        }] } }
                    ]
                }]
            }
        }]
    }
    requests.post(webhook, json=payload)

def execute(pw: Playwright, mode: str, target_file: str = None):
    history = get_history()
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    
    page.goto(SITE_URL)
    page.get_by_role("textbox", name="Username").fill(USER_ID)
    page.get_by_role("textbox", name="Password").fill(USER_PW)
    page.get_by_role("button", name="Log In").click()
    page.get_by_role("link", name="See All").nth(1).click()
    page.wait_for_timeout(5000)

    # ค้นหาวันที่วันนี้และย้อนหลัง 3 วัน
    dates = [(datetime.now() - timedelta(days=i)).strftime("%Y/%m/%d") for i in range(4)]
    
    if mode == "check":
        print(f"Looking for dates: {dates}")
        new_files = []
        
        # กวาดทุกแถวในตาราง
        rows = page.locator("tr").all()
        for row in rows:
            text = row.inner_text()
            # ถ้าในแถวนั้นมีวันที่ที่เราต้องการ
            if any(d in text for d in dates):
                link = row.locator("a").first
                if link.count() > 0:
                    title = link.inner_text().strip()
                    if title and title != "See All" and len(title) > 5:
                        if title not in history:
                            new_files.append(title)
                            print(f"Found: {title}")
                        else:
                            print(f"Already Sent: {title}")
        
        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"files={json.dumps(new_files)}\n")
        
        for f in new_files: 
            notify_chat(f, os.environ.get('ACTION_URL', '#'))
            
    elif mode == "send" and target_file:
        page.get_by_role("link", name=target_file).first.click()
        page.wait_for_timeout(4000)
        
        info = page.evaluate("""() => {
            let d = {};
            document.querySelectorAll('tr').forEach(r => {
                let cells = r.querySelectorAll('th, td');
                if (cells.length >= 2) {
                    let key = cells[0].innerText.replace(/\\s+/g, ' ').trim().toLowerCase();
                    let val = cells[1].innerText.trim();
                    if (key.includes('category')) d['Category'] = val;
                    if (key.includes('document no')) d['DocNo'] = val;
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
            
            # ส่งเมล (โค้ดส่วนส่งเมลเดิม)
            msg = EmailMessage()
            msg['Subject'] = f"Update : {target_file}"
            msg['From'] = formataddr(("Admin", os.environ.get('MAIL_USER')))
            msg['To'] = TARGET_ADDRS[0]
            if len(TARGET_ADDRS) > 1: msg['Cc'] = ", ".join(TARGET_ADDRS[1:])
            msg.set_content(f"Category: {info.get('Category', '-')}\nDoc: {info.get('DocNo', '-')}\n\n{SIGNATURE}")
            
            with open(path, 'rb') as f:
                msg.add_attachment(f.read(), maintype='application', subtype='octet-stream', filename=dl.value.suggested_filename)
            
            with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
                smtp.starttls()
                smtp.login(os.environ.get('MAIL_USER'), os.environ.get('MAIL_PASS'))
                smtp.send_message(msg)
            
            save_history(target_file)
            print(f"Sent: {target_file}")

    browser.close()

if __name__ == "__main__":
    m = "check"; f_name = None
    if "--mode" in sys.argv: m = sys.argv[sys.argv.index("--mode") + 1]
    if "--file" in sys.argv: f_name = sys.argv[sys.argv.index("--file") + 1]
    with sync_playwright() as playwright: execute(playwright, m, f_name)
