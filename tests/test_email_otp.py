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
        self.smtp_cfg_starttls = {
            "host": "smtp.example.com",
            "port": 587,
            "user": "test@example.com",
            "password": "password123"
        }
        self.smtp_cfg_ssl = {
            "host": "smtp.example.com",
            "port": 465,
            "user": "test@example.com",
            "password": "password123"
        }

    @patch("email_otp.config")
    @patch("smtplib.SMTP")
    def test_send_success_starttls(self, mock_smtp, mock_config):
        mock_config.return_value = {"smtp": self.smtp_cfg_starttls}

        # Configure mock
        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertTrue(success)
        self.assertEqual(error, "")
        mock_instance.starttls.assert_called_once()
        mock_instance.login.assert_called_once_with("test@example.com", "password123")
        mock_instance.sendmail.assert_called_once()

    @patch("email_otp.config")
    @patch("smtplib.SMTP_SSL")
    def test_send_success_ssl(self, mock_smtp_ssl, mock_config):
        mock_config.return_value = {"smtp": self.smtp_cfg_ssl}

        # Configure mock
        mock_instance = MagicMock()
        mock_smtp_ssl.return_value.__enter__.return_value = mock_instance

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertTrue(success)
        self.assertEqual(error, "")
        mock_instance.login.assert_called_once_with("test@example.com", "password123")
        mock_instance.sendmail.assert_called_once()

    @patch("email_otp.config")
    @patch("smtplib.SMTP")
    def test_retry_on_exception(self, mock_smtp, mock_config):
        mock_config.return_value = {"smtp": self.smtp_cfg_starttls}

        mock_instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_instance

        # Simulate exception on first two calls, success on third
        mock_instance.login.side_effect = [smtplib.SMTPException("Unexpected EOF"), smtplib.SMTPException("Unexpected EOF"), None]

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertEqual(mock_instance.login.call_count, 3)

    @patch("email_otp.config")
    def test_missing_config(self, mock_config):
        mock_config.return_value = {"smtp": {}}

        success, error = email_otp.send_otp_email("user@example.com", "123456")

        self.assertFalse(success)
        self.assertIn("تنظیمات ایمیل ناقص است", error)

if __name__ == "__main__":
    unittest.main()
