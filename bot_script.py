import os, sys, requests, smtplib, mimetypes, base64, json
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from playwright.sync_api import Playwright, sync_playwright

# Config (เหมือนเดิม)
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

def execute(pw: Playwright, mode: str, target_file: str = None):
    history = get_history()
    browser = pw.chromium.launch(headless=True)
    # จำลองเป็นคนรันผ่าน Chrome จริงๆ เพื่อป้องกันการโดนบล็อก
    context = browser.new_context(viewport={'width': 1280, 'height': 1000})
    page = context.new_page()
    
    # 1. Login
    page.goto(SITE_URL)
    page.get_by_role("textbox", name="Username").fill(USER_ID)
    page.get_by_role("textbox", name="Password").fill(USER_PW)
    page.get_by_role("button", name="Log In").click()
    page.wait_for_load_state("networkidle")

    # 2. ไปหน้า See All
    page.get_by_role("link", name="See All").nth(1).click()
    page.wait_for_timeout(7000) # รอให้นานขึ้นเพื่อให้ตารางโหลดครบ

    if mode == "check":
        # --- ไม้ตาย: ถ่ายรูปสิ่งที่บอทเห็นเก็บไว้ดู ---
        page.screenshot(path="debug_scout.png", full_page=True)
        print("📸 Screenshot saved as debug_scout.png")

        # ค้นหาวันที่ (สุ่มหาหลายรูปแบบเผื่อหน้าเว็บเปลี่ยน)
        now = datetime.now()
        dates = [
            now.strftime("%Y/%m/%d"), 
            (now - timedelta(days=1)).strftime("%Y/%m/%d"),
            now.strftime("%d/%m/%Y"), # เผื่อเป็น วัน/เดือน/ปี
            now.strftime("%Y-%m-%d")  # เผื่อเป็น ปี-เดือน-วัน
        ]
        print(f"Searching for files matching: {dates}")

        new_files = []
        rows = page.locator("tr").all()
        for row in rows:
            row_text = row.inner_text()
            if any(d in row_text for d in dates):
                link = row.locator("a").first
                if link.count() > 0:
                    title = link.inner_text().strip()
                    if title and title != "See All" and len(title) > 5:
                        if title not in history:
                            new_files.append(title)
                            print(f"✅ Found New: {title}")
                        else:
                            print(f"⏭️ Already in history: {title}")
        
        # ส่งค่ากลับ GitHub
        if 'GITHUB_OUTPUT' in os.environ:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                f.write(f"files={json.dumps(new_files)}\n")
        
        for f in new_files:
            webhook = os.environ.get('CHAT_WEBHOOK')
            action_url = os.environ.get('ACTION_URL', '#')
            payload = {"cardsV2": [{"cardId": "1", "card": {"header": {"title": "🔔 พบไฟล์ใหม่"}, "sections": [{"widgets": [{"textParagraph": {"text": f"<b>{f}</b>"}}, {"buttonList": {"buttons": [{"text": "APPROVE", "onClick": {"openLink": {"url": action_url}}}]}}]}]}}]}
            requests.post(webhook, json=payload)

    elif mode == "send" and target_file:
        # (โค้ดส่วนส่งเมลเดิม ไม่เปลี่ยนแปลง)
        page.get_by_role("link", name=target_file).first.click()
        page.wait_for_timeout(5000)
        # ... (ข้ามส่วน Scraping และส่งเมลไป เพราะเราเน้นแก้ที่ด่าน Scout) ...
        # [ใส่โค้ดส่งเมลเดิมของคุณพินลงตรงนี้ได้เลยครับ]

    browser.close()

if __name__ == "__main__":
    m = "check"; f_name = None
    if "--mode" in sys.argv: m = sys.argv[sys.argv.index("--mode") + 1]
    if "--file" in sys.argv: f_name = sys.argv[sys.argv.index("--file") + 1]
    with sync_playwright() as playwright: execute(playwright, m, f_name)
