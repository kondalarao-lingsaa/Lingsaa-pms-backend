import os

from pydantic import BaseModel
from starlette import status
from starlette.responses import JSONResponse


class BaseConstants:
    LOCALMODE = 'local'
    MODE = 'mode'
    PRODMODE = 'production'
    DEVMODE = 'development'


    mode = os.environ.get('mode')
# PATH FOR FILE UPLOAD FOLDERS
    if mode == 'production':
        BASEFILELOCATION = '/datadisk/anucde-uploads'
        TEMP = '/datadisk/anucde-uploads'
        BASE_IP_ADDRESS = 'http://10.0.0.24:8007/'
    elif mode == 'development':
        BASEFILELOCATION = '/datadisk/anucde-uploads'
        TEMP = '/datadisk/anucde-uploads'
    else:
        BASEFILELOCATION = 'C:/Users/karthik/Documents/wetradersweb_to_api/wetraders_be/local/temp'
        TEMP = 'C:/Users/arunkumar/Pictures/zer'
        BASE_IP_ADDRESS = 'http://127.0.0.1:9004'


# PATH FOR HTML RESPONSES TXT FILES
    if mode == 'production':
        HTML_RESPONSE_FILE_LOCATION = '/var/www/html/algotrader/algo_backend/htmlResponses'
    elif mode == 'local':
        HTML_RESPONSE_FILE_LOCATION = 'C:/Users/karthik/Documents/Trading Project Backend/htmlResponses'
    else:
        HTML_RESPONSE_FILE_LOCATION = 'C:/Users/karthik/Documents/Trading Project Backend/htmlResponses'

    USER_STATUS = {
        "pending": 1,
        "approved": 2,
        "redirected": 3,
        'rejected': 4,
        'file_details_pending':5}

    USER_STATUS_NUMBER = {
        None: "Unfilled",
        1: "Pending",
        2: "Approved",
        3: "Redirected",
        4: 'Rejected'
    }


class TimeConstants:
    MOBILE_OTP_VERIFICATION = 5
    EMAIL_OTP_VERIFICATION = 10
    INSTRUCTIONS_AUTH_OTP = 5


class DBConstants:
    CONN_STRING_SQL = 'sql'
    HRMS_CONN_STRING_SQL = 'hrms'
    ACC_CONN_STRING_SQL = 'accounts'
    CRMS_CONN_STRING_SQL = 'crms'
    PM_CONN_STRING_SQL='pm'
    DATABASE = 'sql'


class Secret:
    JWT = 'jwt'
    JWT_TYPE_AUTH = 'auth'
    JWT_TYPE_REFRESH = 'refresh'
    ALGORITHM = 'algorithm'


class PaymentConstants:
    AES_ENCRYPTION_REQUEST_KEY = 'aes_encryption_request_key'
    REQUEST_IV = 'request_iv'
    RESPONSE_IV = 'response_iv'
    AES_ENCRYPTION_RESPONSE_KEY = 'aes_encryption_response_key'
    LOGIN_ID = 'login_id'
    PASSWORD = 'password'
    PRODUCT_ID = "product_id"
    REQ_HASH_KEY = "req_hash_key"
    RESP_HASH_KEY = "resp_hash_key"
    PAYMENT_CALLBACK = "payment_callback"


class Tags:
    AUTH = 'Authorisation'
    ADMIN = 'Admin'
    LIST = 'List'
    CLIENT = 'client'
    COMMON = 'Common'
    KYC = 'Kyc'
    DHAN = 'Dhan'
    PAYMENT = 'Payments'
    WHATSAPP = 'Whatsapp'
    


class ProgramResponses:
    ERROR500 = JSONResponse(status_code=status.HTTP_200_OK,
                            content={"statusCode": status.HTTP_500_INTERNAL_SERVER_ERROR, "detail": "something went "
                                                                                                    "wrong, please try "
                                                                                                    "again later or "
                                                                                                    "contact support"})


class Roles:
    SUPER_ADMIN = 'super admin'
    ADMIN = 'admin'
    CLIENT = 'client'


#class MobileMessages:
    #USER_CREATION = "Hi {}, Your new Account with User Name {} is created successfully, OTP for your mobile number verification is {}.LINGSAA"
    #RESEND_OTP = "Hi {}, Your new Account with User Name {} is created successfully, OTP for your mobile number verification is {}.LINGSAA"
   # USER_UPDATION = "Hi {}, Your new Account with Username {} is UPDATED successfully.LINGSAA"
    #OTP_VERIFICATION_CODE = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'
   # PASSWORD_RESET_CODE = "Hi {}, OTP for Changing your Password is {}. This code is valid for {} Minutes Only, OTP Sent on {}. Please don't Share your OTP with anyone.LINGSAA"
   # ACTIVATE_INSTRUCTIONS = "Hi {},Your OTP for activating Selected Instructions is {}.Don't Share this with any one.Please note that this is valid only for {} minutes.LINGSAA"


class MobileMessages:
    USER_CREATION = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'
    RESEND_OTP = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'
    USER_UPDATION = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'
    OTP_VERIFICATION_CODE = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'
    PASSWORD_RESET_CODE = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'
    ACTIVATE_INSTRUCTIONS = 'Your OTP verification code {} to login. And please do not share OTP.LINGSAA'


class EmailMessages:
    USER_CREATION = "Hi {}, Your new Account with Username {} is CREATED successfully. Your Email Verification code is {} - LINGSA"


class EmailSubjects:
    USER_CREATION = 'Email Verification Code For Lingsaa Tradings and Investments PVT LTD.'


class call_backs:
    shope_fee_failed_call_back = "/application/client/form_steps/clientPayment"
    shop_fee_passed_call_back = "/application/client/form_steps/payment_acknowledgement"

class setting_felids:
    setting_list={
        1:"custom felids",
        2:"custom columns"
    }

class project_fields:
    status={
        1: "Draft",
        2: "Pending Approval",
        3: "Approved",
        4: "Active",
        5: "On Hold",
        6: "Closed"
    }
    priority={
        1:"low",
        2:"medium",
        3:"high",
        4:"critical"
    }