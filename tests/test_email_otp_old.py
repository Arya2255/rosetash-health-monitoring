# -*- coding: utf-8 -*-
import unittest
from unittest.mock import patch, MagicMock
import smtplib
import ssl
import sys
from pathlib import Path

# Add src to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import email_otp

class TestEmailOtp(unittest.TestCase):

    def setUp(self):
        self.smtp_cfg = {
            "host": "smtp.example.com",
            "port": 587,
            "user": "test@example.com",
            "password": "password123"
        }

    @patch("email_otp.config")
    @patch("email_otp.smtplib.SMTP")
    def test_send_success_starttls(self, mock_smtp, mock_config):
        mock_config.return_value = {"smtp": self.smtp_cfg}

        # send_otp_email uses SMTP as a context manager.
        instance = mock_smtp.return_value.__enter__.return_value

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertTrue(success)
        self.assertEqual(error, "")
        mock_smtp.assert_called_with("smtp.example.com", 587, timeout=20)
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with(self.smtp_cfg["user"], self.smtp_cfg["password"])
        instance.sendmail.assert_called_once()

    @patch("email_otp.config")
    @patch("email_otp.smtplib.SMTP_SSL")
    def test_send_success_ssl(self, mock_smtp_ssl, mock_config):
        cfg = self.smtp_cfg.copy()
        cfg["port"] = 465
        mock_config.return_value = {"smtp": cfg}

        instance = mock_smtp_ssl.return_value.__enter__.return_value

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertTrue(success)
        self.assertEqual(error, "")
        mock_smtp_ssl.assert_called_once()
        instance.login.assert_called_once_with(self.smtp_cfg["user"], self.smtp_cfg["password"])
        instance.sendmail.assert_called_once()

    @patch("email_otp.config")
    @patch("email_otp.smtplib.SMTP")
    def test_retry_on_exception(self, mock_smtp, mock_config):
        mock_config.return_value = {"smtp": self.smtp_cfg}

        # Simulate exception on first two calls, success on third
        instance = mock_smtp.return_value.__enter__.return_value
        instance.login.side_effect = [smtplib.SMTPException("Unexpected EOF"), smtplib.SMTPException("Unexpected EOF"), None]

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertEqual(instance.login.call_count, 3)

    @patch("email_otp.config")
    def test_missing_config(self, mock_config):
        mock_config.return_value = {"smtp": {}}

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertFalse(success)
        self.assertIn("تنظیمات ایمیل ناقص است", error)

if __name__ == "__main__":
    unittest.main()
