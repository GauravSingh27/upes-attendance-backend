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
            # 1. Open Portal
            await page.goto("https://myupes-beta.upes.ac.in/", wait_until="networkidle", timeout=45000)

            # 2. Handle Username / Email input
            user_input = page.locator('input[formcontrolname="username"], input[name="username"], input[type="email"], input[name="loginfmt"]').first
            await user_input.wait_for(state="visible", timeout=15000)
            
            # Click and simulate actual keyboard typing so Angular registers validation
            await user_input.click()
            await user_input.fill("")
            await page.keyboard.type(data.email, delay=50)

            # 3. Handle Password input
            pwd_input = page.locator('input[formcontrolname="password"], input[name="password"], input[type="password"], input[name="passwd"]').first
            await pwd_input.wait_for(state="visible", timeout=10000)
            await pwd_input.click()
            await pwd_input.fill("")
            await page.keyboard.type(data.password, delay=50)

            # Allow Angular change detection cycle to evaluate form validity
            await page.wait_for_timeout(1000)

            # 4. Locate and click submit
            submit_btn = page.locator('button[type="submit"], input[type="submit"]').first
            await submit_btn.wait_for(state="visible", timeout=10000)
            
            try:
                await submit_btn.click(timeout=5000)
            except Exception:
                await pwd_input.press("Enter")

            # 5. Handle Microsoft "Stay signed in?" screen if prompted
            try:
                stay_signed_in = page.locator('input[type="submit"][value="Yes"], input[value="Sign in"]').first
                await stay_signed_in.wait_for(state="visible", timeout=4000)
                await stay_signed_in.click()
            except Exception:
                pass

            # 6. Navigate to Student Attendance
            await page.wait_for_selector("text=View Student Attendance", timeout=25000)
            await page.click("text=View Student Attendance")
            await page.wait_for_load_state("networkidle")

            # 7. Extract subject ledger details
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