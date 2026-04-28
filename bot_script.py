import os, sys, requests, smtplib, mimetypes, base64, json
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from playwright.sync_api import Playwright, sync_playwright

# Config (Secrets)
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

def execute(pw: Playwright, mode: str, target_file: str = None):
    history = get_history()
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1280, 'height': 1200})
    page = context.new_page()
    
    page.goto(SITE_URL)
    page.get_by_role("textbox", name="Username").fill(USER_ID)
    page.get_by_role("textbox", name="Password").fill(USER_PW)
    page.get_by_role("button", name="Log In").click()
    page.wait_for_load_state("networkidle")
    page.get_by_role("link", name="See All").nth(1).click()
    page.wait_for_timeout(7000)

    if mode == "check":
        page.screenshot(path="debug_scout.png", full_page=True)
        
        # ค้นหาวันที่ (อ้างอิงจากรูป 2026/04/28)
        now = datetime.now()
        target_dates = [
            now.strftime("%Y/%m/%d"), 
            (now - timedelta(days=1)).strftime("%Y/%m/%d")
        ]
        print(f"Targeting Dates: {target_dates}")

        new_files = []
        # --- ไม้ตายใหม่: ค้นหาทุกลิงก์บนหน้าเว็บที่ไม่ได้ชื่อ See All ---
        links = page.locator("a").all()
        for link in links:
            title = link.inner_text().strip()
            if len(title) < 10 or title == "See All": continue
            
            # ตรวจสอบหา Parent หรือ Element ใกล้เคียงว่ามีวันที่เป้าหมายไหม
            # วิธีนี้จะหาไฟล์เจอแน่นอนถ้ามีวันที่อยู่บรรทัดเดียวกัน
            parent_text = page.evaluate("(el) => el.parentElement.parentElement.innerText", link.element_handle())
            
            if any(d in parent_text for d in target_dates):
                if title not in history:
                    if title not in new_files:
                        new_files.append(title)
                        print(f"✅ Found: {title}")
                        
                        # แจ้ง Chat
                        webhook = os.environ.get('CHAT_WEBHOOK')
                        action_url = os.environ.get('ACTION_URL', '#')
                        payload = {"cardsV2": [{"cardId": "1", "card": {"header": {"title": "🔔 พบไฟล์ใหม่"}, "sections": [{"widgets": [{"textParagraph": {"text": f"<b>{title}</b>"}}, {"buttonList": {"buttons": [{"text": "APPROVE", "onClick": {"openLink": {"url": action_url}}}]}}]}]}}]}
                        requests.post(webhook, json=payload)
                else:
                    print(f"⏭️ Skipped (In History): {title}")

        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"files={json.dumps(new_files)}\n")

    elif mode == "send" and target_file:
        # คลิกที่ไฟล์เป้าหมาย (ใช้ชื่อที่ส่งมาแบบเป๊ะๆ)
        page.get_by_role("link", name=target_file).first.click()
        page.wait_for_timeout(5000)
        
        # Scraping Category
        info = page.evaluate("""() => {
            let d = {};
            document.querySelectorAll('tr, div').forEach(el => {
                let text = el.innerText.toLowerCase();
                if (text.includes('category') || text.includes('document no') || text.includes('published by') || text.includes('model')) {
                    let parts = el.innerText.split(':');
                    if (parts.length >= 2) {
                        let k = parts[0].trim().toLowerCase();
                        let v = parts[1].trim();
                        if (k.includes('category')) d['Category'] = v;
                        if (k.includes('document no')) d['DocNo'] = v;
                        if (k.includes('published by')) d['Publisher'] = v;
                        if (k.includes('model')) d['Model'] = v;
                    }
                }
            });
            return d;
        }""")

        checkboxes = page.locator("input[type='checkbox']")
        if checkboxes.count() > 0:
            for i in range(checkboxes.count()): checkboxes.nth(i).check()
            page.evaluate('document.querySelector(".download_button")?.removeAttribute("disabled")')
            with page.expect_download() as dl:
                page.locator(".download_button").click(force=True)
            
            path = f"/tmp/{dl.value.suggested_filename}"
            dl.value.save_as(path)
            
            # ส่งเมล
            msg = EmailMessage()
            msg['Subject'] = f"Update : {target_file}"
            msg['From'] = formataddr(("Technical Admin", MY_ADDR))
            msg['To'] = TARGET_ADDRS[0]
            if len(TARGET_ADDRS) > 1: msg['Cc'] = ", ".join(TARGET_ADDRS[1:])
            
            body = f"Dear all,\n\n"
            body += f"Category            : {info.get('Category', '-')}\n"
            body += f"Document No.    : {info.get('DocNo', '-')}\n"
            body += f"Published by      : {info.get('Publisher', '-')}\n"
            body += f"Model Reference  : {info.get('Model', '-')}\n\n"
            body += f"Best Regards,\n\n------------------------------------------------\n{SIGNATURE}"
            msg.set_content(body)
            
            with open(path, 'rb') as f:
                msg.add_attachment(f.read(), maintype='application', subtype='octet-stream', filename=dl.value.suggested_filename)
            
            with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
                smtp.starttls()
                smtp.login(MY_ADDR, MY_PW)
                smtp.send_message(msg)
            save_history(target_file)

    browser.close()

if __name__ == "__main__":
    m = "check"; f_name = None
    if "--mode" in sys.argv: m = sys.argv[sys.argv.index("--mode") + 1]
    if "--file" in sys.argv: f_name = sys.argv[sys.argv.index("--file") + 1]
    with sync_playwright() as playwright: execute(playwright, m, f_name)
