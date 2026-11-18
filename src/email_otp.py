# -*- coding: utf-8 -*-
"""ارسال ایمیل با SMTP."""

import os
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from remote import config


def send_otp_email(to_email: str, code: str) -> tuple[bool, str]:
    """ارسال کد OTP به ایمیل با بازتلاش امن."""
    cfg = config().get("smtp", {})

    host = cfg.get("host", "smtp.gmail.com")
    port = int(cfg.get("port", 587))
    user = cfg.get("user", "")
    password = cfg.get("password", "")

    if not password or password == "APP_PASSWORD":
        if os.environ.get("ROZTASH_OTP_CONSOLE_DEBUG", "").lower() in ("1", "true", "yes"):
            print(f"[LOCAL OTP TEST ONLY] {code}")
        return False, "تنظیمات ایمیل ناقص است (لطفاً پسورد را تنظیم کنید)."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "کد تأیید ورود - سامانه پایش سلامت رزتاش"
    msg["From"] = user
    msg["To"] = to_email

    # HTML and Text content...
    html = f"""
    <html>
    <body style="font-family: Tahoma, Arial, sans-serif; direction: rtl; text-align: right;">
        <div style="background-color: #f5f5f5; padding: 20px; border-radius: 10px;">
            <h2 style="color: #333;">سامانه پایش سلامت رزتاش</h2>
            <p>کد تأیید ورود شما:</p>
            <div style="background-color: #fff; padding: 15px; border-radius: 5px;
                        border: 2px solid #1E8E4E; font-size: 24px;
                        font-weight: bold; color: #1E8E4E; text-align: center;
                        letter-spacing: 5px;">
                {code}
            </div>
            <p style="color: #666; font-size: 12px;">
                این کد تا ۵ دقیقه معتبر است.
            </p>
        </div>
    </body>
    </html>
    """
    text = f"کد تأیید ورود شما: {code}\n\nاین کد تا ۵ دقیقه معتبر است."
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()

    max_retries = 3
    for attempt in range(max_retries):
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                    server.login(user, password)
                    server.sendmail(user, to_email, msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=20) as server:
                    server.starttls(context=context)
                    server.login(user, password)
                    server.sendmail(user, to_email, msg.as_string())

            return True, ""

        except (smtplib.SMTPException, ssl.SSLError, ConnectionError, OSError) as e:
            error_msg = str(e)
            print(f"DEBUG: caught exception: {error_msg}")
            if attempt < max_retries - 1:
                time.sleep(1)  # Simple backoff
                continue

            # Map common errors to Persian
            if "EOF" in error_msg or "SSL" in error_msg:
                return False, "خطای امنیتی در اتصال به سرور ایمیل. لطفاً دوباره تلاش کنید."
            if "authentication" in error_msg.lower():
                return False, "نام کاربری یا رمز عبور اشتباه است."

            return False, f"خطا در ارسال ایمیل: {error_msg}"
        except Exception as e:
            return False, "خطای غیرمنتظره در ارسال ایمیل."
