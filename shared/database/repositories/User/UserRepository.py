from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_,func,case

from shared.database.repositories.Repository import Repository
from shared.database.models import User,Client,ClientModule,UserRole
from local.logging_config import error_logger,performence_logger
from fastapi.responses import JSONResponse


class UserRepository(Repository):
    def __init__(self, db: Session, model_class=User):
        super().__init__(model_class, db)

    def existing_user_details(self,client_id:int=None,get_api=None,user_id:int=None,page_size:int=None,offset:int=None,search:str=None,role_id:int=None):
        try:
            base = self.session.query(User.user_id,User.client_id,
                                      User.custom_client_id,
                                      UserRole.role_id,User.username,
                                      User.is_active,User.is_superadmin,
                                      User.module_id).outerjoin(UserRole,User.user_id == UserRole.user_id)
            if client_id is not None:
                base = base.filter(User.client_id == client_id)
            if user_id is not None:
                base = base.filter(User.user_id == user_id)
            if role_id is not None:
                base = base.join(UserRole,User.user_id == UserRole.user_id).filter(UserRole.role_id == role_id)
            if page_size and offset is not None:
                base = base.order_by(User.user_id).limit(page_size).offset(offset)
            if search is not None:
                base = base.filter(User.username.ilike(f'%{search}%'))
            if get_api:
                return base.all()
            else:
                return base.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('Error in existing client details query is %s',e)
            raise e
    
    def get_all_user_details_count(self,client_id:int=None,user_id:int=None,search:str=None,role_id:int=None):
        try:
            base = self.session.query(func.count(User.user_id).label('total'),
                                      func.count(case((User.is_active == 1,1)).label('active')),
                                      func.count(case((User.is_active == 0,1)).label('inactive')))
                  
            if client_id is not None:
                base = base.filter(User.client_id == client_id)
            if user_id is not None:
                base = base.filter(User.user_id == user_id)
            if role_id is not None:
                base = base.join(UserRole,User.user_id == UserRole.user_id).filter(UserRole.role_id == role_id)
            if search is not None:
                base = base.filter(User.username.ilike(f'%{search}%'))
            total,active,inactive = base.one()

            count_pg = self.session.query(func.count(User.user_id)).scalar()
            return {'total':total,
                    'active':active,
                    'inactive':inactive,
                    "count_pg":count_pg}
        except Exception as e:
            traceback.print_exc()
            raise e
    def authenticate_user(self,username:str,password:str=None):
        try:
            base = self.session.query(User.user_id,User.username,User.custom_client_id,
                                      Client.client_id,Client.mobile,User.module_id,Client.email,
                                      User.password,User.temp_password,User.is_superadmin,
                                      User.is_active,User.forgot_otp,User.forgot_sent_at,
                                      User.login_otp,User.subuser_mobile,User.subuser_email,
                                      Client.name,Client.client_id,Client.custom_client_id)\
            .outerjoin(Client,User.client_id == Client.client_id)\
            .filter(or_(User.custom_client_id==username,User.subuser_mobile == username,Client.mobile == username))
            return base.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('Error in authenticate user query is %s',e)
            raise e
    
    def get_user_by_mobile_desc(self,mobile_number:str):
        try:
            base = self.session.query(User).filter((User.custom_client_id==mobile_number))
            return base.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('Error in get user by mobile desc query is %s',e)
            return JSONResponse(status_code=500,content={'message':e})