import os
import math
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from playwright.async_api import async_playwright

# Ensure Playwright finds the downloaded browser on Render


app = FastAPI(title="UPES Attendance API")

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
            # 1. Open Portal
            await page.goto("https://myupes-beta.upes.ac.in/", wait_until="networkidle", timeout=35000)

            # 2. Fill login details (Microsoft SSO / UPES Auth)
            email_input = page.locator('input[type="email"], input[name="loginfmt"]')
            if await email_input.is_visible():
                await email_input.fill(data.email)
                await page.click('button[type="submit"], input[type="submit"]')
                await page.wait_for_timeout(1500)

            await page.fill('input[type="password"], input[name="passwd"]', data.password)
            await page.click('button[type="submit"], input[type="submit"]')

            # Handle "Stay signed in?" screen if prompted
            try:
                await page.wait_for_selector('input[type="submit"][value="Yes"], input[value="Sign in"]', timeout=4000)
                await page.click('input[type="submit"][value="Yes"], input[value="Sign in"]')
            except Exception:
                pass

            # 3. Click "View Student Attendance" link
            await page.wait_for_selector("text=View Student Attendance", timeout=25000)
            await page.click("text=View Student Attendance")
            await page.wait_for_load_state("networkidle")

            # 4. Extract subject ledger details
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
            await browser.close()
            raise HTTPException(status_code=400, detail=str(e))