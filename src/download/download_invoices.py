import os
import re
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError

# load login from env
load_dotenv()

USERNAME = os.environ.get("SUPPLIER_USERNAME")
PASSWORD = os.environ.get("SUPPLIER_PASSWORD")

print("USERNAME loaded:", bool(USERNAME))
print("PASSWORD loaded:", bool(PASSWORD))
print("USERNAME value:", USERNAME)

# make sure the directory exists
DOWNLOAD_DIR = Path("data/downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

# raw invoice csvs live here, named by invoice date like 2026-03-17.csv (ingest.py reads the date from the filename)
RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# table dates look like "Tuesday, June 09, 2026"
DATE_RE = re.compile(r"^\w+, \w+ \d{1,2}, \d{4}$")


def run():
    with sync_playwright() as p:
        print("Launching browser...")
        browser = p.chromium.launch(headless=False)
        
        # spoof a chrome user agent
        context = browser.new_context(
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            print("Attempting to log in...")

            page.goto(
                "https://b2biamgbnazprod.b2clogin.com/b2biamgbnazprod.onmicrosoft.com/oauth2/v2.0/authorize?p=b2c_1a_signin_signup_us&redirect_uri=https%3A%2F%2Fmybeesapp.com%2Fapi%2Fauth%2Fverify&response_type=id_token&response_mode=form_post&client_id=0d94d8f7-ff0f-41ce-b00e-e095aec22b5a&ui_locales=en-US&state=CUSTOMRj_wA_-Jb90sfgDS6hA4vLw9Wu30Kb4r%3Flanguage%3Den%26country%3DUS%26p%3DB2C_1A_SIGNIN_SIGNUP_US&nonce=bvc91igSDUuBK-y0lWBGBLG-W_HJOplU&scope=profile%20openid&x-client-SKU=passport-azure-ad&x-client-Ver=4.3.2",
                wait_until="domcontentloaded",
            )

            # first page email
            page.wait_for_selector("#signInName", state="visible")
            print("Found username field")

            page.click("#signInName")

            # clear any existing value
            page.press("#signInName", "Meta+A")
            page.press("#signInName", "Backspace")

            # type slowly to see username being filled
            # nevermind no delay
            page.type("#signInName", USERNAME)

            typed_value = page.locator("#signInName").input_value()
            print("Typed username:", typed_value)

            if not typed_value:
                raise ValueError("Username was not entered into #signInName")

            page.screenshot(path="before_continue.png")

            # button is not continue
            page.wait_for_selector("#continueNew", state="visible")
            print("Found Continue button")
            page.locator("#continueNew").click()

            page.screenshot(path="after_continue.png")

            # sometimes it goes straight ot password other times it will ask for choice
            try:
                page.wait_for_selector("button.choice-form__choice", state="visible", timeout=5000)
                print("Password choice screen detected")
                page.locator("button.choice-form__choice").filter(has_text="Password").click()
            except TimeoutError:
                print("Password choice screen did not appear; checking for direct password page")

            # password page
            page.wait_for_selector("#password", state="visible")
            print("Found password field")
            page.fill("#password", PASSWORD)

            password_value = page.locator("#password").input_value()
            print("Password entered:", bool(password_value))

            page.screenshot(path="before_login_click.png")

            # click log in
            page.get_by_role("button", name="Log In").click()

            print("Waiting for redirect to the intermediate page...")
            
            # wait for it to route back to home page
            page.wait_for_url("https://mybeesapp.com/")
            
            print("Clicking the secondary 'Log In' button...")
            page.wait_for_selector("text='Log In'", state="visible")
            page.locator("text='Log In'").first.click()

            # wait for invoices text on header
            # page.wait_for_selector("text='Invoices'", state="visible")
            
        #    page.locator("a.bees-link-wrapper[href='/invoices']").first.click()

            page.goto("https://mybeesapp.com/invoices")
            print("Sucessfully got to invoices page")
            
            """
            print("Waiting for the Invoices link to become visible...")
            # exvlude the footer links and and only select the one visible
            invoices_link = page.locator("a.bees-link-wrapper[href='/invoices']:not([target='_blank']):visible")
            
            # page.get_by_text("Invoices").first.click()
            # if there is still a race condition then wait for this to be visible
            invoices_link.wait_for(state="visible")
            invoices_link.click()

            print("Clicked invoices")

            print("Logged in successfully!")
            print("This is the url after login:", page.url)
            """
            page.screenshot(path="logged_in_state.png")
            
            # Use wait_for_timeout to wait a split second (1000 milliseconds = 1 second)
            page.wait_for_timeout(1000)
            
            page.wait_for_selector("text='All Invoices'").click()
            print("Selected All Invoices...")
            
            # Wait another split second before looking for table rows
            page.wait_for_timeout(1000)
            
            with open("debug_page.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("tbody count:", page.locator("tbody").count())
            print("tr count:", page.locator("tr").count())
            print("amount count:", page.locator("span.bees-number-display").count())
            print("EyeOn count:", page.locator("button:has(svg[data-icon-name='EyeOn'])").count())

            # Anchor off amount spans, since those were present in the working invoice HTML you sent earlier
            page.locator("span.bees-number-display").first.wait_for(state="visible", timeout=60000)

            amount_locator = page.locator("span.bees-number-display").first
            amount_text = amount_locator.inner_text().strip()
            amount = float(amount_text.replace("$", "").replace(",", "").strip())

            print("Amount text:", amount_text)

            # The website DOM is actually rendering all 'td' cells directly or inside a single container without 'tr' elements bounding each invoice!
            # Since we just want the most recent (first) invoice, we can simply align them by taking the first of each element in the tbody.
            
            invoice_number = None
            try:
                # The invoice number is the first link inside the table body
                invoice_number = page.locator("tbody a.hexa-text-link").first.inner_text(timeout=2000).strip()
                print("Invoice number:", invoice_number)
            except Exception as e:
                print(f"Could not extract invoice number. Error: {e}")

            if amount > 200:
                # The view button is the first button with the EyeOn icon in the table body
                view_btn = page.locator("tbody button:has(svg[data-icon-name='EyeOn'])").first
                view_btn.wait_for(state="visible", timeout=10000)

                # remember where we are so we can tell if the click routed us somewhere new
                list_url = page.url
                view_btn.click()
                print(f"Clicked View Details for invoice {invoice_number or '[unknown]'}")

                # the invoice links have no href, so details opens via js.
                # could be a route change or a modal, handle both
                try:
                    page.wait_for_url(lambda url: url != list_url, timeout=10000)
                    print("URL changed, details is its own page")
                except TimeoutError:
                    print("URL did not change, checking for a modal/drawer instead")
                    page.wait_for_selector(
                        "[role='dialog'], .hexa-modal, [class*='drawer']",
                        state="visible",
                        timeout=10000,
                    )
                    print("Details opened in a modal/drawer")

                # let it finish rendering before we capture anything
                page.wait_for_timeout(1000)

                print("Details page URL:", page.url)
                page.screenshot(path="invoice_details.png")
                with open("debug_details_page.html", "w", encoding="utf-8") as f:
                    f.write(page.content())

                # quick counts so we know what to target for the download step
                print("button count:", page.locator("button").count())
                print("'Download' elements:", page.locator("text=/download/i").count())
                print("'Export' elements:", page.locator("text=/export/i").count())
                print("'PDF' elements:", page.locator("text=/pdf/i").count())

                # the download trigger has no aria-label, so anchor off its svg icon.
                # clicking it opens the dropdown with the 3 download options (PDF / CSV / etc.)
                download_menu_btn = page.locator("button:has(svg[data-icon-name='Download'])").first
                download_menu_btn.wait_for(state="visible", timeout=10000)
                download_menu_btn.click()
                print("Opened the download options dropdown")

                print(f"Reached invoice details page for invoice {invoice_number or '[unknown]'}")
            else:
                print("Most recent invoice total is not above 200, so skipping.")

            input("Press Enter to close the browser...")
        
            


        except Exception as e:
            print(f"Automation failed: {e}")
            page.screenshot(path="error_capture.png")
            # input("Browser is paused AFTER ERROR for debugging. Inspect the page, then press Enter to close...")
"""
        finally:
            print("Closing browser...")
            browser.close()
"""

if __name__ == "__main__":
    if not USERNAME or not PASSWORD:
        print("Error: check SUPPLIER_USERNAME and SUPPLIER_PASSWORD in .env")
    else:
        run()