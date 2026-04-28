import os, sys, requests, smtplib, mimetypes, base64, json
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr
from playwright.sync_api import Playwright, sync_playwright

# Config
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

def notify_chat(new_files):
    webhook = os.environ.get('CHAT_WEBHOOK')
    if not webhook or not new_files: return
    
    # สร้างลิงก์ตรงไปยังหน้า Issues
    repo_url = os.environ.get('ACTION_URL', '#').split('/actions')[0]
    issue_url = f"{repo_url}/issues"
    
    file_list_text = "\\n".join([f"• {f}" for f in new_files])
    
    payload = {
        "cardsV2": [{
            "cardId": "checklistNotify",
            "card": {
                "header": { "title": "🔔 พบไฟล์ใหม่!", "subtitle": "กรุณาเลือกไฟล์ที่จะส่ง" },
                "sections": [{
                    "widgets": [
                        { "textParagraph": { "text": f"<b>รายการ:</b>\\n{file_list_text}" } },
                        { "buttonList": { "buttons": [{
                            "text": "ไปที่หน้าเลือกไฟล์ (Issues)",
                            "onClick": { "openLink": { "url": issue_url } }
                        }] } }
                    ]
                }]
            }
        }]
    }
    requests.post(webhook, json=payload)

def execute(pw: Playwright, mode: str, target_list: list = None):
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
        target_dates = [(datetime.now() - timedelta(days=i)).strftime("%Y/%m/%d") for i in range(4)]
        new_found = []
        
        links = page.locator("a").all()
        for link in links:
            title = link.inner_text().strip()
            if len(title) < 10 or title == "See All": continue
            parent_text = page.evaluate("(el) => el.parentElement.parentElement.innerText", link.element_handle())
            if any(d in parent_text for d in target_dates) and title not in history:
                new_found.append(title)
        
        if new_found:
            notify_chat(new_found) # แจ้งเตือนแชท
            if 'GITHUB_OUTPUT' in os.environ:
                with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
                    f.write(f"files={json.dumps(new_found)}\n")

    elif mode == "send" and target_list:
        for f_name in target_list:
            try:
                page.get_by_role("link", name=f_name).first.click()
                page.wait_for_timeout(5000)
                
                info = page.evaluate("""() => {
                    let d = {};
                    document.querySelectorAll('tr').forEach(el => {
                        let pts = el.innerText.split(':');
                        if (pts.length >= 2) {
                            let k = pts[0].trim().toLowerCase();
                            if (k.includes('category')) d['Category'] = pts[1].trim();
                            if (k.includes('document no')) d['DocNo'] = pts[1].trim();
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
                    
                    msg = EmailMessage()
                    msg['Subject'] = f"Update Bulletin: {f_name}"
                    msg['From'] = formataddr(("Technical Support", MY_ADDR))
                    msg['To'] = TARGET_ADDRS[0]
                    if len(TARGET_ADDRS) > 1: msg['Cc'] = ", ".join(TARGET_ADDRS[1:])
                    msg.set_content(f"Category: {info.get('Category', '-')}\nDoc No: {info.get('DocNo', '-')}\n\n{SIGNATURE}")
                    with open(path, 'rb') as att:
                        msg.add_attachment(att.read(), maintype='application', subtype='octet-stream', filename=dl.value.suggested_filename)
                    
                    with smtplib.SMTP('smtp.gmail.com', 587) as smtp:
                        smtp.starttls()
                        smtp.login(MY_ADDR, MY_PW)
                        smtp.send_message(msg)
                    save_history(f_name)
                page.go_back()
            except: page.goto(SITE_URL + "/Listing")

    browser.close()

if __name__ == "__main__":
    m = "check"; targets = []
    if "--mode" in sys.argv: m = sys.argv[sys.argv.index("--mode") + 1]
    if "--files" in sys.argv: targets = json.loads(sys.argv[sys.argv.index("--files") + 1])
    with sync_playwright() as playwright: execute(playwright, m, targets)
