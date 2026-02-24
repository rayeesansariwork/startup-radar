import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class EmailQueueService:
    """
    Background worker service that polls an asyncio.Queue and processes
    emails sequentially with a deliberate delay between each send.
    """
    def __init__(self, delay_seconds: int = 60, send_real_emails: bool = False):
        self.queue = asyncio.Queue()
        self.delay_seconds = delay_seconds
        self.send_real_emails = send_real_emails
        self.worker_task = None
        
    async def start(self):
        """Starts the background worker task."""
        if self.worker_task is None:
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
        Add an email payload to the queue.
        Payload expected format: {"to": str, "to_name": str, "subject": str, "body": str}
        """
        await self.queue.put(payload)
        logger.info(f"📥 Queued outreach email to {payload.get('to')} (Queue size: {self.queue.qsize()})")

    async def _process_queue(self):
        """Infinite loop processing emails one by one with a delay."""
        while True:
            try:
                payload = await self.queue.get()
                
                to_addr = payload.get("to")
                to_name = payload.get("to_name")
                subject = payload.get("subject")
                body = payload.get("body")
                
                logger.info(f"📧 Processing queued email for {to_name} <{to_addr}>...")
                
                # Development / Testing phase logic
                if not self.send_real_emails:
                    print("\n" + "="*60)
                    print(f"  [DEV MODE] Simulated Email Dispatch")
                    print("="*60)
                    print(f"  To     : {to_name} <{to_addr}>")
                    print(f"  Subject: {subject}")
                    print("-"*60)
                    print(body)
                    print("="*60 + "\n")
                    logger.info(f"✅ [DEV MODE] Simulated send to {to_addr}")
                else:
                    # In true production, here you would:
                    # 1. Obtain JWT token from SalesTechBE
                    # 2. POST to /gamil/send_mail/
                    # We leave this disabled for now as per user request to just print it
                    logger.warning(f"⚠️ Real email dispatch is currently configured but logic is mocked. Sending to {to_addr}")
                
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
email_queue = EmailQueueService(delay_seconds=60, send_real_emails=False)
