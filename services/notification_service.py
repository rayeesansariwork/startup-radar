"""
Email Notification Service - Send discovery results via Gmail SMTP
"""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending email notifications about discovery results"""
    
    def __init__(self, gmail_user: str, gmail_app_password: str, recipient: str):
        """
        Initialize notification service
        
        Args:
            gmail_user: Gmail sender email address
            gmail_app_password: Gmail app password (not regular password)
            recipient: Email address to receive notifications
        """
        self.gmail_user = gmail_user
        self.gmail_app_password = gmail_app_password
        self.recipient = recipient
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        
        logger.info(f"[Notification] Initialized with sender: {gmail_user}, recipient: {recipient}")
    
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
            
            # Create email message
            message = MIMEMultipart('alternative')
            message['Subject'] = subject
            message['From'] = self.gmail_user
            message['To'] = self.recipient
            
            # Attach HTML body
            html_part = MIMEText(html_body, 'html')
            message.attach(html_part)
            
            # Send email via Gmail SMTP
            logger.info(f"[Notification] Sending email to {self.recipient}...")
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Secure connection
                server.login(self.gmail_user, self.gmail_app_password)
                server.send_message(message)
            
            logger.info(f"[Notification] ✅ Email sent successfully to {self.recipient}")
            return True
            
        except Exception as e:
            logger.error(f"[Notification] ❌ Failed to send email: {type(e).__name__}: {e}", exc_info=True)
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
