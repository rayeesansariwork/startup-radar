import asyncio
import logging
from typing import Dict, Any
import requests

from config import settings

logger = logging.getLogger(__name__)


def body_to_html(text: str) -> str:
    """
    Convert a plain-text email body (with \\n newlines and embedded HTML
    fragments like <a> and <img>) into a properly formatted HTML email.
    Each double-newline becomes a paragraph. Single newlines become <br>.
    """
    import re

    paragraphs = re.split(r'\n{2,}', text.strip())
    html_parts = []
    for para in paragraphs:
        para_html = para.replace('\n', '<br>')
        stripped = para_html.strip()
        # If the paragraph is already an HTML element (img, a, etc.) don't wrap it
        if stripped.startswith('<') and not stripped.startswith('<br'):
            html_parts.append(stripped)
        else:
            html_parts.append(f'<p style="margin:0 0 14px 0;">{para_html}</p>')

    body_inner = '\n'.join(html_parts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;font-size:15px;line-height:1.7;color:#2d2d2d;">
  <table width="100%" cellpadding="0" cellspacing="0" border="0">
    <tr><td align="center">
      <table width="620" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;width:100%;padding:32px 24px;">
        <tr><td>
{body_inner}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


class EmailQueueService:
    """
    Background worker service that polls an asyncio.Queue and processes
    emails sequentially with a deliberate delay between each send (15 minutes for production).
    """
    def __init__(self, delay_seconds: int = 900, send_real_emails: bool = settings.send_real_emails):
        self.queue = asyncio.Queue()
        self.delay_seconds = delay_seconds
        self.send_real_emails = send_real_emails
        self.worker_task = None
        self._main_loop = None  # Will be set when start() is called on the main loop
        
    async def start(self):
        """Starts the background worker task."""
        if self.worker_task is None:
            self._main_loop = asyncio.get_event_loop()  # Capture the main FastAPI event loop
            self.worker_task = asyncio.create_task(self._process_queue())
            logger.info(f"✅ Started EmailQueueService background worker (delay: {self.delay_seconds}s)")

    async def stop(self):
        """Stops the worker gracefully."""
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
            self.worker_task = None
            logger.info("🛑 Stopped EmailQueueService background worker")

    async def enqueue_email(self, payload: Dict[str, Any]):
        """
        Add an email payload to the queue (from within the main async event loop).
        """
        await self.queue.put(payload)
        logger.info(f"📥 Queued outreach email to {payload.get('to')} (Queue size: {self.queue.qsize()})")

    def enqueue_threadsafe(self, payload: Dict[str, Any]):
        """
        Thread-safe version for calling from a background thread (e.g., APScheduler cron job).
        Schedules the put() on the main FastAPI event loop using run_coroutine_threadsafe.
        """
        if self._main_loop is None or self._main_loop.is_closed():
            logger.error("❌ Cannot enqueue email: main event loop not available")
            return
        future = asyncio.run_coroutine_threadsafe(self.queue.put(payload), self._main_loop)
        try:
            future.result(timeout=5)  # block briefly to confirm it was queued
            logger.info(f"📥 [Thread-safe] Queued email to {payload.get('to')} (Queue size: ~{self.queue.qsize()})")
        except Exception as e:
            logger.error(f"❌ Failed to thread-safe enqueue email to {payload.get('to')}: {e}")

    async def _process_queue(self):
        """Infinite loop processing emails one by one with a delay."""
        while True:
            try:
                payload = await self.queue.get()
                
                to_addr = payload.get("to")
                to_name = payload.get("to_name")
                subject = payload.get("subject")
                body = payload.get("body")
                result_id = payload.get("result_id", "N/A")
                already_emailed = payload.get("already_emailed", False)
                
                logger.info(f"📧 Processing queued email for {to_name} <{to_addr}> (Result ID: {result_id})...")
                
                # Development / Testing phase logic
                if not self.send_real_emails:
                    print("\n" + "="*60)
                    print(f"  [DEV MODE] Simulated Email Dispatch")
                    print("="*60)
                    print(f"  To             : {to_name} <{to_addr}>")
                    print(f"  Subject        : {subject}")
                    print(f"  SalesTechBE ID : {result_id}")
                    print(f"  Already Sent?  : {already_emailed}")
                    print("-"*60)
                    print(body)
                    print("="*60 + "\n")
                    logger.info(f"✅ [DEV MODE] Simulated send to {to_addr}")
                else:
                    # In actual production, hit the core SalesTechBE endpoint
                    try:
                        logger.info(f"🚀 [PRODUCTION] Executing real HTTP POST to SalesTechBE for {to_addr}... ")
                        
                        if not settings.shilpi_crm_email or not settings.shilpi_crm_password:
                            logger.error("❌ CRITICAL: Shilpi CRM Auth is missing from config. Cannot send real email.")
                        else:
                            # 1. Always Auth to ensure valid token for long queues
                            auth_resp = requests.post(f"{settings.crm_base_url}/token/obtain/", json={
                                "email": settings.shilpi_crm_email,
                                "password": settings.shilpi_crm_password
                            }, timeout=10)
                            
                            if auth_resp.status_code == 200:
                                jwt_token = auth_resp.json().get("access")
                                headers = {
                                    "Authorization": f"Bearer {jwt_token}",
                                    "Content-Type": "application/json"
                                }
                                
                                # 2. Send the outbound email
                                endpoint = f"{settings.crm_base_url}/gamil/send_mail/"
                                mail_payload = {
                                    "to": to_addr,
                                    "subject": subject,
                                    "body": body_to_html(body)   # convert to proper HTML
                                }
                                
                                req = requests.post(endpoint, headers=headers, json=mail_payload, timeout=20)
                                if req.status_code == 200:
                                    logger.info(f"✅ Success: Real email dispatched via Shilpi Bhatia to {to_addr}")
                                    
                                    # 3. Mark Record as Sent
                                    if result_id != "N/A":
                                        mark_req = requests.post(
                                            f"{settings.crm_base_url}/hiring-outreach-results/{result_id}/send_email/",
                                            headers=headers,
                                            timeout=10
                                        )
                                        if mark_req.status_code == 200:
                                            logger.info(f"✅ Marked Outreach Result ID {result_id} as email_sent in SalesTechBE")
                                else:
                                    logger.error(f"❌ Failed to dispatch real email to {to_addr}: {req.status_code} - {req.text}")
                            else:
                                logger.error(f"❌ JobProspectorBE could not authenticate as Shilpi Bhatia: {auth_resp.text}")
                    except Exception as e:
                        logger.error(f"❌ HTTP Exception sending real email to {to_addr}: {e}")
                
                self.queue.task_done()
                
                # ── Staggered Delay ──
                logger.info(f"⏳ Sleeping for {self.delay_seconds} seconds before next email dispatch...")
                await asyncio.sleep(self.delay_seconds)
                
            except asyncio.CancelledError:
                # Break out of loop when shut down
                break
            except Exception as e:
                logger.error(f"❌ Error in email queue worker: {e}", exc_info=True)
                # Still sleep on error to avoid tight error loops
                await asyncio.sleep(self.delay_seconds)

# Global singleton instance for the app to use
email_queue = EmailQueueService(delay_seconds=900, send_real_emails=settings.send_real_emails)
