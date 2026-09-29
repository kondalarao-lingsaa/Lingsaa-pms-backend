from random import randrange

def otp_generator():
    otp = ''
    while len(otp) < 4:
        otp += str(randrange(0, 10))
    return otp


def email_otp_generator():
    otp = ''
    while len(otp) < 6:
        otp += str(randrange(0, 10))
    return otp

