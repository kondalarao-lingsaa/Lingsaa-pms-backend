from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import base64


def encrypt_text(plaintext, key=b'this_is_a_16_key'):
    cipher = AES.new(key, AES.MODE_CBC)
    ciphertext = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(cipher.iv + ciphertext).decode()


