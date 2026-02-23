"""
Email Notification Service - Send discovery results via Gmail SMTP
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending email notifications about discovery results"""
    
    
    def __init__(
        self, 
        gmail_user: Optional[str] = None, 
        gmail_app_password: Optional[str] = None, 
        recipient: Optional[str] = None,
        sendgrid_api_key: Optional[str] = None,
        sendgrid_from_email: Optional[str] = None,
        recipients: Optional[List[str]] = None
    ):
        """
        Initialize notification service with SendGrid or Gmail SMTP
        """
        self.recipients = recipients or []
        if recipient and recipient not in self.recipients:
            self.recipients.append(recipient)
        
        # SendGrid Configuration
        self.sendgrid_api_key = sendgrid_api_key
        self.sendgrid_from_email = sendgrid_from_email
        
        # Gmail SMTP Configuration (Legacy/Fallback)
        self.gmail_user = gmail_user
        self.gmail_app_password = gmail_app_password
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port_tls = 587
        self.smtp_port_ssl = 465
        
        if self.sendgrid_api_key and self.sendgrid_from_email:
            logger.info(f"[Notification] initialized with SendGrid (sender: {sendgrid_from_email})")
        elif self.gmail_user and self.gmail_app_password:
            logger.info(f"[Notification] Initialized with Gmail SMTP (sender: {gmail_user})")
        else:
            logger.warning("[Notification] No email credentials provided!")
    
    def send_discovery_notification(self, result: Dict, discovery_type: str = "daily") -> bool:
        """
        Send email notification with discovery results
        
        Args:
            result: Discovery result dict from CompanyDiscoveryService
            discovery_type: Type of discovery ('daily', 'hourly', 'manual')
        
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            companies = result.get('companies', [])
            total_companies = len(companies)
            sources_used = result.get('sources_used', [])
            source_stats = result.get('source_stats', {})
            duration = result.get('duration', 0)
            errors = result.get('error')
            
            # Build email subject
            subject = f"Company Discovery Report - {total_companies} Companies Found ({discovery_type.title()})"
            
            # Build email body
            html_body = self._build_html_email(
                companies=companies,
                total_companies=total_companies,
                sources_used=sources_used,
                source_stats=source_stats,
                duration=duration,
                discovery_type=discovery_type,
                errors=errors
            )
            
            
            # 1. Try SendGrid first if configured
            if self.sendgrid_api_key and self.sendgrid_from_email:
                try:
                    logger.info(f"[Notification] Sending email via SendGrid to {', '.join(self.recipients)}...")
                    sg = SendGridAPIClient(self.sendgrid_api_key)
                    message = Mail(
                        from_email=self.sendgrid_from_email,
                        to_emails=self.recipients,
                        subject=subject,
                        html_content=html_body
                    )
                    response = sg.send(message)
                    logger.info(f"[Notification] Email sent via SendGrid! Status: {response.status_code}")
                    return True
                except Exception as e:
                    logger.error(f"[Notification] SendGrid failed: {e}")
                    logger.info("[Notification] Falling back to Gmail SMTP...")
            
            # 2. Fallback to Gmail SMTP if SendGrid missing or failed
            if not self.gmail_user or not self.gmail_app_password:
                logger.error("[Notification] No Gmail credentials for fallback. Email not sent.")
                return False

            # Create SMTP email message
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = self.gmail_user
            message['To'] = ", ".join(self.recipients)
            
            # Attach HTML body
            html_part = MIMEText(html_body, 'html')
            message.attach(html_part)
            
            # Try sending email via Gmail SMTP with fallback
            logger.info(f"[Notification] Sending email via Gmail SMTP to {', '.join(self.recipients)}...")
            
            # Try TLS first (port 587)
            try:
                with smtplib.SMTP(self.smtp_server, self.smtp_port_tls, timeout=10) as server:
                    server.starttls()  # Secure connection
                    server.login(self.gmail_user, self.gmail_app_password)
                    server.send_message(message)
                logger.info(f"[Notification] Email sent successfully via TLS (port {self.smtp_port_tls})")
                return True
            except (OSError, smtplib.SMTPException) as e:
                logger.warning(f"[Notification] TLS connection failed: {e}")
                
                 # Fallback to SSL (port 465)
                try:
                    with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port_ssl, timeout=10) as server:
                        server.login(self.gmail_user, self.gmail_app_password)
                        server.send_message(message)
                    logger.info(f"[Notification] Email sent successfully via SSL (port {self.smtp_port_ssl})")
                    return True
                except Exception as ssl_error:
                    logger.error(f"[Notification] SSL connection also failed: {ssl_error}")
                    raise
            
        except Exception as e:
            logger.error(f"[Notification] Failed to send email: {type(e).__name__}: {e}", exc_info=True)
            return False
    
    def _build_html_email(
        self,
        companies: List[Dict],
        total_companies: int,
        sources_used: List[str],
        source_stats: Dict,
        duration: float,
        discovery_type: str,
        errors: Optional[str] = None
    ) -> str:
        """Build HTML email body with discovery results"""
        
        # Get current time in IST (Indian Standard Time, UTC+5:30)
        ist = timezone(timedelta(hours=5, minutes=30))
        timestamp = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S IST')
        
        # Start HTML
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
                .summary {{ background-color: #f4f4f4; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                .stat {{ display: inline-block; margin: 10px 20px; }}
                .stat-label {{ font-weight: bold; color: #555; }}
                .stat-value {{ font-size: 24px; color: #4CAF50; }}
                .source-breakdown {{ margin: 20px 0; }}
                .source-item {{ padding: 8px; margin: 5px 0; background-color: #f9f9f9; border-left: 4px solid #4CAF50; }}
                .companies-list {{ margin: 20px 0; }}
                .company-item {{ padding: 12px; margin: 8px 0; background-color: #fff; border: 1px solid #ddd; border-radius: 4px; }}
                .company-name {{ font-weight: bold; color: #2196F3; font-size: 16px; }}
                .company-details {{ color: #666; font-size: 14px; margin-top: 5px; }}
                .error-box {{ background-color: #ffebee; color: #c62828; padding: 15px; margin: 20px 0; border-radius: 5px; border-left: 4px solid #c62828; }}
                .footer {{ text-align: center; color: #888; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Company Discovery Report</h1>
                <p>{discovery_type.title()} Discovery - {timestamp}</p>
            </div>
            
            <div class="summary">
                <div class="stat">
                    <div class="stat-label">Total Companies</div>
                    <div class="stat-value">{total_companies}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Sources Used</div>
                    <div class="stat-value">{len(sources_used)}</div>
                </div>
                <div class="stat">
                    <div class="stat-label">Duration</div>
                    <div class="stat-value">{duration:.1f}s</div>
                </div>
            </div>
        """
        
        # Add error section if there are errors
        if errors:
            html += f"""
            <div class="error-box">
                <strong>⚠️ Errors Encountered:</strong><br>
                {errors}
            </div>
            """
        
        # Add source breakdown
        if source_stats:
            html += """
            <div class="source-breakdown">
                <h2>📊 Source Breakdown</h2>
            """
            for source, stats in source_stats.items():
                count = stats.get('count', 0)
                duration_s = stats.get('duration', 0)
                error = stats.get('error')
                
                if error:
                    html += f"""
                    <div class="source-item" style="border-left-color: #f44336;">
                        <strong>{source}</strong>: ❌ Error - {error}
                    </div>
                    """
                else:
                    html += f"""
                    <div class="source-item">
                        <strong>{source}</strong>: {count} companies ({duration_s:.1f}s)
                    </div>
                    """
            html += "</div>"
        
        # Add companies list (show top 20)
        if companies:
            display_count = min(50, len(companies))
            html += f"""
            <div class="companies-list">
                <h2>🏢 Discovered Companies (Top {display_count})</h2>
            """
            
            for company in companies[:display_count]:
                company_name = company.get('company_name', 'Unknown')
                website = company.get('website', 'N/A')
                funding_info = company.get('funding_info', 'N/A')
                source = company.get('source', 'Unknown')
                description = company.get('description', '')
                
                # Truncate description if too long
                if description and len(description) > 150:
                    description = description[:150] + "..."
                
                html += f"""
                <div class="company-item">
                    <div class="company-name">{company_name}</div>
                    <div class="company-details">
                        <strong>Website:</strong> {website}<br>
                        <strong>Funding:</strong> {funding_info}<br>
                        <strong>Source:</strong> {source}
                """
                
                if description:
                    html += f"<br><strong>Description:</strong> {description}"
                
                html += """
                    </div>
                </div>
                """
            
            if len(companies) > display_count:
                html += f"<p><em>... and {len(companies) - display_count} more companies</em></p>"
            
            html += "</div>"
        else:
            html += """
            <div class="companies-list">
                <p>No companies discovered in this run.</p>
            </div>
            """
        
        # Footer
        html += f"""
            <div class="footer">
                <p>This is an automated notification from JobProspectorBE</p>
                <p>Discovery Type: {discovery_type.title()} | Timestamp: {timestamp}</p>
            </div>
        </body>
        </html>
        """
        
        return html
