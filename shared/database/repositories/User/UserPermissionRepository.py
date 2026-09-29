from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_

from shared.database.repositories.Repository import Repository
from shared.database.models import UserPermission,User,Permission,Action,RolePermission
from local.logging_config import error_logger,performence_logger


class UserPermissionRepository(Repository):
    def __init__(self, db: Session, model_class=UserPermission):
        super().__init__(model_class, db)
    
    def existing_user_permission_details(self,user_id:int=None, permission_id:int=None, 
                                         action_id:int=None,user_permission_id:int=None,
                                         get_api=None,page_size:int=None,offset:int=None,search:str=None):
        try:
            user_permission_details = self.session.query(UserPermission.user_permission_id,
                                                         UserPermission.user_id,
                                                         UserPermission.permission_id,
                                                         UserPermission.action_id,
                                                         UserPermission.allow,
                                                         User.is_active,
                                                         User.client_id,
                                                         User.custom_client_id,
                                                         User.username.label('username'),
                                                         Permission.permission_name,
                                                         Permission.nav_link_fe,
                                                         Permission.nav_link_icon_fe,
                                                         Action.name.label('action_name'))\
                .join(User, User.user_id == UserPermission.user_id)\
                .join(Permission, Permission.permission_id == UserPermission.permission_id)\
                .join(Action, Action.action_id == UserPermission.action_id)
            
            if user_id is not None:
                user_permission_details = user_permission_details.filter(UserPermission.user_id == user_id)
            if permission_id is not None:
                user_permission_details = user_permission_details.filter(UserPermission.permission_id == permission_id)
            if action_id is not None:
                user_permission_details = user_permission_details.filter(UserPermission.action_id == action_id)
            if user_permission_id is not None:
                user_permission_details = user_permission_details.filter(UserPermission.user_permission_id == user_permission_id)
            if page_size and offset is not None:
                user_permission_details = user_permission_details.order_by(UserPermission.user_id).limit(page_size).offset(offset)
            if get_api:
                return user_permission_details.all()
            else:
                return user_permission_details.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('error in existing_user_permission_details %s',e)
            return None
    
    def permission_details(self,user_id:int=None):
        try:
            base = self.session.query(UserPermission.user_id,
                                      UserPermission.user_permission_id,
                                      UserPermission.allow,
                                      UserPermission.action_id,
                                      UserPermission.permission_id,
                                      RolePermission.role_permission_id
                                      ,RolePermission.role_id,
                                      RolePermission.action_id,
                                      RolePermission.permission_id,
                                      RolePermission.allow).outerjoin(RolePermission,UserPermission.user_id == RolePermission.user)
        except Exception as e:
            traceback.print_exc()
            error_logger.error('error in permission details api is %s',e)