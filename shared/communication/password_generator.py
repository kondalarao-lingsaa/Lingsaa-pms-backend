import secrets
import string
import random


class PasscodeGenerator:
    @staticmethod
    def generate_otp():
        otp = "".join([str(random.randint(0, 9)) for x in range(4)])
        return otp

    @staticmethod
    def generate_password():
        alpha_num = string.ascii_letters + string.digits
        password = ''.join([secrets.choice(alpha_num) for each in range(10)])
        return password
