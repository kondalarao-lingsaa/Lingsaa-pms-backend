from hashlib import sha512
from hmac import HMAC
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad,unpad
from Crypto.Random import get_random_bytes
import base64

from payment.AESCipher import AESCipher
from core.parser.PaymentResponseParser import PaymentResponseParser

key='ABCDEFGHIJKLMNOP'


class Encryption:
    @staticmethod
    def encrypt_details(raw_string: str, key: str):
        encoded_data = raw_string.encode()
        return HMAC(key.encode(), encoded_data, sha512).digest().hex()

    @staticmethod
    def decrypt(response):
        response_json = PaymentResponseParser.response_to_json(response=response.decode())
        cipher = AESCipher('self')
        if response_json.get('encdata') is not None:
            decrypted_res = cipher.decrypt(response_json.get('encdata'))
            payment_res = PaymentResponseParser.response_to_json(decrypted_res)
            return payment_res
        return None
    

    @staticmethod
    def hashDetails(str):
        new = pad(str.encode(),16)
        chipher = AES.new(key.encode('utf-8'),AES.MODE_ECB)
        result = base64.b64encode(chipher.encrypt(new))
        return result.decode('utf-8')

    @staticmethod
    def unHashDetails(response):
        enc = base64.b64decode(response)
        cipher = AES.new(key.encode('utf-8'),AES.MODE_ECB)
        return unpad(cipher.decrypt(enc),16)
    