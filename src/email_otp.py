# -*- coding: utf-8 -*-
"""ارسال ایمیل با SMTP."""

import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from remote import config


def send_otp_email(to_email: str, code: str) -> tuple[bool, str]:
    """ارسال کد OTP به ایمیل.
    
    Returns:
        (success, error_message)
    """
    cfg = config().get("smtp", {})
    
    host = cfg.get("host", "smtp.gmail.com")
    port = cfg.get("port", 587)
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    
    # اگر پسورد تنظیم نشده
    if not password or password == "APP_PASSWORD":
        # Fallback به چاپ در کنسول
        print(f"\n{'='*50}")
        print(f"کد تأیید برای {to_email}: {code}")
        print(f"(SMTP تنظیم نشده - در کنسول چاپ شد)")
        print(f"{'='*50}\n")
        return False, "SMTP تنظیم نشده - کد در کنسول چاپ شد"
    
    try:
        # ساخت پیام
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "کد تأیید ورود - سامانه پایش سلامت رزتاش"
        msg["From"] = user
        msg["To"] = to_email
        
        # متن HTML
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
        
        text = f"""کد تأیید ورود شما: {code}
        
این کد تا ۵ دقیقه معتبر است.
        """
        
        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        
        # اتصال به SMTP
        context = ssl.create_default_context()
        
        with smtplib.SMTP(host, port) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(user, to_email, msg.as_string())
        
        return True, ""
        
    except Exception as e:
        error_msg = str(e)
        print(f"Email error: {error_msg}")
        return False, error_msg