import base64
import os
from sendgrid import SendGridAPIClient, Mail, Attachment, FileContent, FileName, FileType, Disposition
from constants import BaseConstants, MobileMessages
from shared.communication.password_generator import PasscodeGenerator
import requests
from local.logging_config import performence_logger

def Email_verification_Template(name, otp):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="./index.css" rel="stylesheet" type="text/css">
   
    <title>Email</title>
</head>
<body >
    <div style="display:flex; align-items:center;flex-direction:column; margin-top:3rem">
        <div style='background-color:white'>
        <div>
            <img style='width:150px;' src="https://res.cloudinary.com/dcqzidejd/image/upload/v1703246556/logo_hsimfx.png" alt="logo"/>
        </div>
        <div style="display: flex; align-items:center;background-color:#d28eff; margin-left:1rem; color:white;">
            <div style="margin:0px 2rem 0px 2rem; >
                <span style="font-size: 150px;">&#127881;</span>
            </div>
            <div>
                <h1>Congratulations</h1>
                <p>Welcome to Lingsaa Algo Trader Platform</p>
            </div>
        </div>
        <div style="margin: 25px;" >
            <p>Hi {name},</p>
            <p>Greeting From Lingsaa Algo Trader Pvt Ltd.</p>
            <p>We are thrilled to hear that you are interested in becoming a part of the Lingsaa Algo Trader Pvt Ltd family! We believe that you would be satisfied using our product. </p>
            <p style="margin-top: 30px;">Before Enjoying the services of our product, kindly confirm your mail id</p>
            <p>Your Verification code is : {otp}</p>
            <p style="margin-top: 50px;">Thanks and Regards,</p>
            <p> Lingsaa Algo Trader Pvt Ltd.</p>
            <p  style="font-size: 0.6rem; margin-top: 50px;">Please Ignore this email if you didn't register in Lingsaa Algo Trader Pvt Ltd.</p>
        </div>
    </div>
       
    </div>
</body>
</html>'''


class Message:
    @staticmethod
    def send_otp(mobile):
        otp = PasscodeGenerator.generate_otp()
        if os.environ.get(BaseConstants.MODE) == BaseConstants.PRODMODE:
            res = requests.get(os.environ.get("MESSAGE_URL"), params={
                'User': os.environ.get("MESSAGE_USERNAME"),
                'passwd': os.environ.get("MESSAGE_PASSWORD"),
                'mobilenumber': mobile,
                'message': MobileMessages.OTP_VERIFICATION_CODE.format(otp),
            })
            return res.status_code == 200, otp
        return True, otp

    @staticmethod
    def send_message(mobile, message):
        performence_logger.debug(os.environ.get(BaseConstants.MODE))
        performence_logger.debug('base_constanta value is %s',BaseConstants.PRODMODE)
        if os.environ.get(BaseConstants.MODE) == BaseConstants.PRODMODE:
            res = requests.get(os.environ.get("MESSAGE_URL"), params={
                'User': os.environ.get("MESSAGE_USERNAME"),
                'passwd': os.environ.get("MESSAGE_PASSWORD"),
                'mobilenumber': mobile,
                'message': message
            })
            performence_logger.debug('sent---------------')
            return res.status_code == 200

        return True

    @staticmethod
    def send_email(email, name, code, subject, attachment_file_location=None):
        if email is None:
            return True
        if os.environ.get('email') != 'Y':
            return True
        message = Mail(
            from_email="helpdesk@lingsaa.com",
            to_emails=email,
            subject=subject,
            html_content=Email_verification_Template(name=name, otp=code))
        if attachment_file_location is not None:
            with open(attachment_file_location, 'rb') as f:
                data = f.read()
                f.close()
            encoded_file = base64.b64encode(data).decode()
            attachedFile = Attachment(
                FileContent(encoded_file),
                FileName('attachment.pdf'),
                FileType('application/pdf'),
                Disposition('attachment')
            )
            message.attachment = attachedFile
        try:
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            response = sg.send(message)
        except Exception as e:
            print(e)

    @staticmethod
    def send_developer_email(email, message, subject, attachment_file_location=None):
        if email is None:
            return True
        message = Mail(
            from_email="helpdesk@lingsaa.com",
            to_emails=email,
            subject=subject,
            html_content=f"""
            # <img src="https://anucdeprodstorage.blob.core.windows.net/static/all.jpg" alt="Acharya Nagarjuna University">
            <p>{message}</p>
            <strong>Center for Distance Education</strong>
            <strong>Acharya Nagarjuna University</strong>
            <br>
            <strong>Andhra Pradesh</strong>
            <br>
            <strong>India</strong>
            """)
        try:
            sg = SendGridAPIClient(os.environ.get('SENDGRID_API_KEY'))
            response = sg.send(message)
            print(response)
        except Exception as e:
            print(e)
