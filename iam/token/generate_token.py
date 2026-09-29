# import os
# from datetime import datetime, timedelta
# from typing import Union
# import jwt
# from constants import Secret


# def generate_token(data: dict, expires_delta: Union[timedelta, None] = None):
#     to_encode = data.copy()
#     # print(f'to_encode is:-{to_encode}')
#     if expires_delta:
#         expire = datetime.utcnow() + expires_delta
#     else:
#         expire = datetime.utcnow() + timedelta(minutes=60)
#     to_encode.update({"exp": expire})
#     encoded_jwt = jwt.encode(to_encode, os.environ.get(
#         Secret.JWT), algorithm=os.environ.get(Secret.ALGORITHM))
#     return encoded_jwt


import uuid
from datetime import datetime, timedelta
from typing import Union
import jwt
import os
from constants import Secret

def generate_token(data: dict, expires_delta: Union[timedelta, None] = None) -> tuple:
    """
    Returns: (token_string, session_id)
    """
    to_encode = data.copy()
    
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    to_encode.update({"session_id": session_id})
    
    # Set expiry
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=30)  # Your 45s expiry
    
    to_encode.update({"exp": expire})
    

    encoded_jwt = jwt.encode(to_encode, os.environ.get(Secret.JWT), algorithm=os.environ.get(Secret.ALGORITHM))
    
    return encoded_jwt, session_id