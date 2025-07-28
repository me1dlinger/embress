# email_notifier.py
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from logging_utils import get_logger
from pathlib import Path
import logging

LOGS_PATH = Path(os.getenv("LOG_PATH", "./data/logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


class EmailNotifier:
    def __init__(self):
        # 从环境变量读取配置
        self.EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
        self.EMAIL_HOST = os.getenv("EMAIL_HOST", "")
        self.EMAIL_PORT = int(os.getenv("EMAIL_PORT", 465))
        self.EMAIL_USER = os.getenv("EMAIL_USER", "")
        self.EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
        self.EMAIL_SENDER = os.getenv("EMAIL_SENDER", self.EMAIL_USER)
        self.EMAIL_RECIPIENTS = (
            os.getenv("EMAIL_RECIPIENTS", "").split(",")
            if os.getenv("EMAIL_RECIPIENTS")
            else []
        )
        self.logger = self._setup_logger()

    def _setup_logger(self) -> logging.Logger:
        return get_logger(
            name="EmailNotifier",
            log_dir=LOGS_PATH,
            base_name="email_notifier",
            level=getattr(logging, LOG_LEVEL, logging.INFO),
            to_console=True,
        )

    def send_notification(self, result):
        """根据扫描结果发送通知邮件"""
        if not self._check_email_config():
            return

        if result.get("status") == "completed":
            self._send_success_notification(result)
        elif result.get("status") == "error":
            self._send_error_notification(result)

    def _send_success_notification(self, result):
        """发送成功通知"""
        subject = "EMBRESS - 自动扫描完成通知"

        # 构建未重命名文件详情
        unrenamed_details = ""
        if result.get("unrenamed_count", 0) > 0:
            unrenamed_details = "<h3>未重命名文件详情:</h3><ul>"
            for file in result.get("unrenamed_files", []):
                unrenamed_details += f"<li>{file.get('path')}</li>"
            unrenamed_details += "</ul>"

        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                h1 {{ color: #2c3e50; margin-top: 0; }}
                h2 {{ color: #3498db; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
                h3 {{ color: #2c3e50; }}
                .stats {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                .stat-item {{ margin-bottom: 8px; }}
                .changes {{ font-weight: bold; color: #27ae60; }}
                .unrenamed {{ font-weight: bold; color: #e74c3c; }}
                ul {{ padding-left: 20px; }}
                li {{ margin-bottom: 5px; }}
                .footer {{ margin-top: 20px; font-size: 0.9em; color: #7f8c8d; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>EMBRESS - 自动扫描完成通知</h1>
                </div>
                
                <p>自动扫描已完成，检测到以下变更：</p>
                
                <div class="stats">
                    <h2>扫描信息</h2>
                    <div class="stat-item"><strong>处理时间:</strong> {result.get("timestamp")}</div>
                    <div class="stat-item"><strong>扫描路径:</strong> {result.get("target", "ALL")}</div>
                </div>
                
                <div class="stats">
                    <h2>变更统计</h2>
                    <div class="stat-item"><span class="changes">重命名视频文件:</span> {result.get("renamed", 0)}</div>
                    <div class="stat-item"><span class="changes">重命名字幕文件:</span> {result.get("renamed_subtitle", 0)}</div>
                    <div class="stat-item"><span class="changes">重命名音频文件:</span> {result.get("renamed_audio", 0)}</div>
                    <div class="stat-item"><span class="changes">重命名图片文件:</span> {result.get("renamed_picture", 0)}</div>
                    <div class="stat-item"><span class="changes">删除NFO文件:</span> {result.get("deleted_nfo", 0)}</div>
                    <div class="stat-item"><span class="unrenamed">未重命名文件数量:</span> {result.get("unrenamed_count", 0)}</div>
                </div>
                
                {unrenamed_details}
                
                <div class="footer">
                    <p>详细信息请登录系统查看。</p>
                </div>
            </div>
        </body>
        </html>
        """

        self._send_email(subject, html_content, is_html=True)

    def _send_error_notification(self, result):
        """发送错误通知"""
        subject = "EMBRESS - 自动扫描错误通知"
        html_content = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
                h1 {{ color: #e74c3c; margin-top: 0; }}
                .error {{ color: #e74c3c; font-weight: bold; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>EMBRESS - 自动扫描错误通知</h1>
                </div>
                
                <p>自动扫描过程中发生错误：</p>
                
                <div class="stat-item"><strong>错误时间:</strong> {result.get("timestamp")}</div>
                <div class="stat-item"><span class="error">错误信息:</span> {result.get("message")}</div>
                
                <p>请检查系统日志以获取更多详细信息。</p>
            </div>
        </body>
        </html>
        """
        self._send_email(subject, html_content, is_html=True)

    def _send_email(self, subject, content, is_html=False):
        """发送邮件核心方法"""
        try:
            # 创建邮件对象
            message = MIMEMultipart()
            message["From"] = Header(self.EMAIL_SENDER, "utf-8")
            message["Subject"] = Header(subject, "utf-8")

            # 添加邮件正文
            if is_html:
                message.attach(MIMEText(content, "html", "utf-8"))
            else:
                message.attach(MIMEText(content, "plain", "utf-8"))

            # 连接SMTP服务器并发送邮件
            server = smtplib.SMTP(self.EMAIL_HOST, self.EMAIL_PORT)
            server.starttls()
            server.login(self.EMAIL_USER, self.EMAIL_PASSWORD)

            for recipient in self.EMAIL_RECIPIENTS:
                if recipient.strip():
                    message["To"] = Header(recipient.strip(), "utf-8")
                    server.sendmail(
                        self.EMAIL_SENDER, recipient.strip(), message.as_string()
                    )

            server.quit()
            self.logger.info("Email notification sent successfully")
        except Exception as e:
            self.logger.error(f"Failed to send email notification: {e}")

    def _check_email_config(self):
        """检查邮件配置是否完整"""
        return (
            self.EMAIL_ENABLED
            and self.EMAIL_HOST
            and self.EMAIL_USER
            and self.EMAIL_PASSWORD
            and self.EMAIL_RECIPIENTS
        )
