import os
from datetime import datetime,timedelta
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session
from starlette import status
from constants import Secret, Roles
from shared.database.get_db import get_db
from shared.database.repositories.User.UserRepository import UserRepository
from shared.database.models import UserSession
# from shared.database.schemas import TokenData, CurrentUser
from passlib.context import CryptContext
from local.logging_config import performence_logger
import pytz
import pandas as pd
import traceback
import random
import string


oauth2_scheme = HTTPBearer()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)



def generate_random_password(length=8):
    # characters to use: letters, digits, punctuation
    characters =  string.digits 
    
    # make sure password has at least 1 of each (uppercase, lowercase, digit, special char)
    password = [

        random.choice(string.ascii_uppercase),
        random.choice(string.digits),

    ]
    
    # fill the rest with random chars
    password += random.choices(characters, k=length - 4)
    
    # shuffle to avoid predictable pattern
    random.shuffle(password)
    
    return ''.join(password)


# Example usage

check_activity = {}
logout_time_dict = {}

async def get_current_user_old(token=Depends(oauth2_scheme), db: Session = Depends(get_db), request=None):
    global check_activity, logout_time_dict
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token.credentials, os.environ.get(Secret.JWT), algorithms=[os.environ.get(Secret.ALGORITHM)])
        user_id = payload.get("user_id")
        if not user_id:
            raise credentials_exception

        current_time = datetime.now(pytz.timezone('Asia/Kolkata'))

        # Initialize tracking if not present
        if user_id not in check_activity:
            check_activity[user_id] = []
        if user_id not in logout_time_dict:
            logout_time_dict[user_id] = {'logout_time': None}

        # Get user's last activity
        last_access_list = check_activity[user_id]

        # Check if logout_time exists and expired
        logout_time = logout_time_dict[user_id]['logout_time']
        if logout_time and current_time > logout_time:
            check_activity[user_id] = []
            logout_time_dict[user_id]['logout_time'] = None
            raise credentials_exception

        # Append current activity
        check_activity[user_id].append(current_time)

        # Update logout time: 1 min after last API hit
        last_api_time = last_access_list[-1] if last_access_list else current_time
        logout_time_dict[user_id]['logout_time'] = last_api_time + timedelta(minutes=30)

        # Log info
        performence_logger.debug(f"[{user_id}] Last API: {last_api_time}, New logout: {logout_time_dict[user_id]['logout_time']}")

        # Build user object
        return {
            'user_id': user_id,
            'role': payload.get('role_name',None),
            'role_id': payload.get('role_id',None),
            'email': payload.get('email',None),
            'mobile': payload.get('mobile',None),
            "username": payload.get("username"),
            'name': payload.get("name")
        }

    except Exception as e:
        traceback.print_exc()
        raise credentials_exception

def is_authorised(db, permission_list, user_id):
    user_repo = UserRepository(db=db)
    permission_avail_list = eval(user_repo.get_available_permissions_by_user_id(
        user_id).permissions_available)
    for i in permission_list:
        if i not in permission_avail_list:
            return False

    return True


from jose import JWTError, jwt
async def get_current_user(token=Depends(oauth2_scheme), db: Session = Depends(get_db)):
    """
    NEW: Uses database sessions instead of global dictionaries
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired. Please login again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # 1. Decode JWT token
        payload = jwt.decode(
            token.credentials, 
            os.environ.get(Secret.JWT), 
            algorithms=[os.environ.get(Secret.ALGORITHM)]
        )
        
        user_id = payload.get("user_id")
        session_id = payload.get("session_id")  # Get session_id from token
        
        if not user_id or not session_id:
            raise credentials_exception

        current_time = datetime.utcnow()  # Use UTC for consistency

        # 2. Check session in database
        session = db.query(UserSession).filter(
            UserSession.user_id == user_id,
            UserSession.session_id == session_id
        ).first()
        
        if not session:
            performence_logger.debug(f"No session found for user_id: {user_id}, session_id: {session_id}")
            raise credentials_exception
        
        if not session.is_active:
            performence_logger.debug(f"Session is inactive for user_id: {user_id}")
            raise credentials_exception

        # 3. Check 1-minute inactivity timeout
        time_since_last_activity = current_time - session.last_activity
        performence_logger.debug(f"User {user_id}: Time since last activity: {time_since_last_activity}")
        
        if time_since_last_activity > timedelta(minutes=1):
            performence_logger.debug(f"Inactivity timeout for user {user_id}. Marking session as inactive.")
            
            # MARK SESSION AS INACTIVE IN DATABASE
            session.is_active = False
            session.logout_time = current_time
            db.commit()
            
            raise credentials_exception

        # 4. Check token expiry (45 seconds)
        # JWT decode already checks expiry, but double-check
        token_expiry = datetime.utcfromtimestamp(payload.get("exp"))
        if current_time > token_expiry:
            performence_logger.debug(f"Token expired for user {user_id}. Marking session as inactive.")
            
            session.is_active = False
            session.logout_time = current_time
            db.commit()
            
            raise credentials_exception

        # 5. Update last activity time to NOW
        old_last_activity = session.last_activity
        session.last_activity = current_time
        db.commit()
        
        performence_logger.debug(f"User {user_id}: Updated last_activity from {old_last_activity} to {current_time}")

        # 6. Build and return user object
        return {
            'user_id': user_id,
            'session_id': session_id,  # Include session_id
            'role': payload.get('role_name'),
            'role_id': payload.get('role_id'),
            'email': payload.get('email'),
            'mobile': payload.get('mobile'),
            "username": payload.get("username"),
            'name': payload.get("name")
        }

    except JWTError as e:
        performence_logger.debug(f"JWT Error: {str(e)}")
        raise credentials_exception
        
    except Exception as e:
        traceback.print_exc()
        performence_logger.error(f"Error in get_current_user: {str(e)}")
        db.rollback()  # Rollback on error
        raise credentials_exception

# def get_student(db: Session, enrollment, user_id, role, lsc_id, application_number=None, email=None, mobile=None, name=None):
#     user_repo = UserRepository(db=db)
#     # student_repo = StudentRepository(db=db)
#     user_role_repository = UserRoleRepository(db=db)
#     role_repo = RoleRepository(db=db)
#     # student = student_repo.get(id_=enrollment) if enrollment is not None else None
#     user = user_repo.get(id_=user_id)
#     user_role = user_role_repository.get_user_role_by(user_id=user_id)
#     user_role_name = role_repo.get(id_=user_role.role_id)

#     return CurrentUser(
#         user_id=user.user_id,
#         role_id=user_role.role_id,
#         is_active=user.active,
#         role_name=user_role_name.role_name,
#         enrollment_number=enrollment,
#         lsc_id=lsc_id,
#         application_number=application_number,
#         name=name if user_role_name.role_name == Roles.STUDENT else user.name,
#         email=email if user_role_name.role_name == Roles.STUDENT else user.email,
#         mobile=mobile if user_role_name.role_name == Roles.STUDENT else user.mobile
#     )


# async def get_current_active_user(current_user: CurrentUser = Depends(get_current_user)):
#     if current_user.is_active == 0:
#         raise HTTPException(status_code=400, detail="Inactive user")
#     return current_user
