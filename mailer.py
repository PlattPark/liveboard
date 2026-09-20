#!/usr/bin/env python3
"""
mailer.py - Platt Park Brewing
Email copies of Computa's posts for the people who aren't in Slack (Victor in the kitchen).
Plain text, sent through the Workspace account with an app password. Off unless MAIL_USER and
MAIL_PASS are set; a failure prints and returns False, it never stops the Slack post.

  MAIL_USER=computa@plattparkbrewing.com   MAIL_PASS=<16-char app password>
  PRESHIFT_MAIL_TO="victor@..., christian@..."    OUTLOOK_MAIL_TO="colby@..., greg@..."
"""
import os, re, smtplib
from email.message import EmailMessage

USER = os.environ.get("MAIL_USER", "")
PASS = os.environ.get("MAIL_PASS", "")
HOST = os.environ.get("MAIL_HOST", "smtp.gmail.com")
PORT = int(os.environ.get("MAIL_PORT", "587"))


def enabled():
    return bool(USER and PASS)


def plain(mrkdwn):
    """Slack mrkdwn -> readable plain text."""
    t = re.sub(r":[a-z0-9_+\-]+:", "", mrkdwn)                    # :emoji:
    t = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", t)      # <url|label>
    t = re.sub(r"<(https?://[^>]+)>", r"\1", t)
    t = re.sub(r"[*_~]", "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def send(to, subject, mrkdwn):
    if not enabled():
        return False
    tos = [x.strip() for x in re.split(r"[,;\s]+", to or "") if x.strip()]
    if not tos:
        return False
    msg = EmailMessage()
    msg["From"] = USER
    msg["To"] = ", ".join(tos)
    msg["Subject"] = subject
    msg.set_content(plain(mrkdwn))
    try:
        with smtplib.SMTP(HOST, PORT, timeout=25) as s:
            s.starttls()
            s.login(USER, PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        print("  ! mail: %s" % e)
        return False
