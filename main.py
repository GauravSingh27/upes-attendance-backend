import math
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright

app = FastAPI(title="UPES Attendance API")

# Enable CORS for Cloudflare Pages frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginRequest(BaseModel):
    email: str
    password: str

def compute_bunks(attended: int, total: int, target: float = 75.0):
    if total <= 0:
        return {"percentage": 0.0, "safe": True, "bunks": 0, "needed": 0}
    pct = (attended / total) * 100.0
    if pct >= target:
        bunks = math.floor((attended * 100.0) / target - total)
        return {"percentage": round(pct, 2), "safe": True, "bunks": max(0, bunks), "needed": 0}
    else:
        needed = math.ceil((target * total - 100.0 * attended) / (100.0 - target))
        return {"percentage": round(pct, 2), "safe": False, "bunks": 0, "needed": max(0, needed)}

@app.get("/")
def health_check():
    return {"status": "Backend running"}

@app.post("/")
@app.post("/api/attendance")
@app.post("/api/attendance/")
async def get_attendance(data: LoginRequest):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--no-zygote",
                "--single-process",
                "--disable-extensions"
            ]
        )
        page = await browser.new_page()
        try:
            # 1. Open Portal using domcontentloaded to prevent networkidle stalls
            await page.goto("https://myupes-beta.upes.ac.in/", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            # Debug log to track redirects in Render console
            print(f"[DEBUG] Current URL: {page.url} | Title: {await page.title()}")

            # 2. Check for an initial "Sign In" or "Student Login" landing button
            login_entry_btn = page.locator('text=Sign In, text=Login, text=Student Login, button:has-text("Sign In")').first
            if await login_entry_btn.is_visible():
                await login_entry_btn.click()
                await page.wait_for_timeout(2000)

            # 3. Locate Username / Email field (covers UPES Angular portal, Microsoft SSO, and standard inputs)
            user_input = page.locator(
                'input[type="email"], input[name="loginfmt"], input[name="username"], '
                'input[formcontrolname="username"], input[id*="user"], input[id*="email"], '
                'input[placeholder*="Email" i], input[placeholder*="SAP" i]'
            ).first

            await user_input.wait_for(state="visible", timeout=30000)
            await user_input.click()
            await user_input.fill("")
            await page.keyboard.type(data.email, delay=30)
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(1000)

            # 4. Handle Microsoft SSO "Next" button if username and password are on separate steps
            next_btn = page.locator('input[type="submit"][value="Next"], button:has-text("Next")').first
            if await next_btn.is_visible():
                await next_btn.click()
                await page.wait_for_timeout(2000)

            # 5. Locate Password field
            pwd_input = page.locator(
                'input[type="password"], input[name="passwd"], input[name="password"], '
                'input[formcontrolname="password"], input[id*="password"]'
            ).first

            await pwd_input.wait_for(state="visible", timeout=20000)
            await pwd_input.click()
            await pwd_input.fill("")
            await page.keyboard.type(data.password, delay=30)
            await page.wait_for_timeout(1000)

            # 6. Submit the form
            submit_btn = page.locator(
                'button[type="submit"], input[type="submit"], button:has-text("Sign in"), button:has-text("Login")'
            ).first

            if await submit_btn.is_visible():
                try:
                    await submit_btn.click(timeout=5000)
                except Exception:
                    await pwd_input.press("Enter")
            else:
                await pwd_input.press("Enter")

            # 7. Dismiss "Stay signed in?" screen if Microsoft SSO prompts
            try:
                stay_signed_in = page.locator('input[type="submit"][value="Yes"], input[value="Sign in"], button:has-text("Yes")').first
                await stay_signed_in.wait_for(state="visible", timeout=5000)
                await stay_signed_in.click()
            except Exception:
                pass

            # 8. Wait for dashboard and navigate to Attendance
            await page.wait_for_timeout(3000)
            attendance_trigger = page.locator('text=View Student Attendance, text=Attendance, a[href*="attendance"]').first
            await attendance_trigger.wait_for(state="visible", timeout=30000)
            await attendance_trigger.click()
            await page.wait_for_timeout(4000)

            # 9. Extract ledger data from the table
            records = await page.evaluate('''() => {
                const rows = Array.from(document.querySelectorAll("table tbody tr"));
                return rows.map(r => {
                    const cols = r.querySelectorAll("td");
                    if (cols.length >= 4) {
                        return {
                            subject: cols[1]?.innerText.trim() || cols[0]?.innerText.trim(),
                            attended: parseInt(cols[2]?.innerText.trim(), 10) || 0,
                            total: parseInt(cols[3]?.innerText.trim(), 10) || 0
                        };
                    }
                    return null;
                }).filter(Boolean);
            }''')

            await browser.close()

            results = [{**item, **compute_bunks(item["attended"], item["total"])} for item in records]
            return {"success": True, "data": results}

        except Exception as e:
            # Print page state upon failure for debugging in Render logs
            print(f"[ERROR] Failed at URL: {page.url}")
            await browser.close()
            raise HTTPException(status_code=400, detail=str(e))
          