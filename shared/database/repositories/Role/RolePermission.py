from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_

from shared.database.repositories.Repository import Repository
from shared.database.models import RolePermission,Role,Permission,Action
from local.logging_config import error_logger,performence_logger


class RolePermissionRepository(Repository):
    def __init__(self, db: Session, model_class=RolePermission):
        super().__init__(model_class, db)
    
    def existing_role_permission_details(self, role_id:int=None, permission_id:int=None, 
                                         action_id:int=None,role_permission_id:int=None,
                                         get_api=None,page_size:int=None,offset:int=None,search:str=None):
        try:
            role_permission_details = self.session.query(RolePermission.role_permission_id,
                                                         RolePermission.role_id,
                                                         RolePermission.permission_id,
                                                         RolePermission.action_id,
                                                         RolePermission.allow,
                                                         Role.name.label('role_name'),
                                                         Permission.permission_name,
                                                         Permission.nav_link_fe,
                                                         Permission.nav_link_icon_fe,
                                                         Action.name.label('action_name'))\
                .join(Role, Role.role_id == RolePermission.role_id)\
                .join(Permission, Permission.permission_id == RolePermission.permission_id)\
                .join(Action, Action.action_id == RolePermission.action_id)
            
            if role_id is not None:
                role_permission_details = role_permission_details.filter(RolePermission.role_id == role_id)
            if permission_id is not None:
                role_permission_details = role_permission_details.filter(RolePermission.permission_id == permission_id)
            if action_id is not None:
                role_permission_details = role_permission_details.filter(RolePermission.action_id == action_id)
            if role_permission_id is not None:
                role_permission_details = role_permission_details.filter(RolePermission.role_permission_id == role_permission_id)
            if page_size and offset is not None:
                role_permission_details = role_permission_details.order_by(RolePermission.role_id).limit(page_size).offset(offset)
            if get_api:
                return role_permission_details.all()
            else:
                return role_permission_details.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('error in existing_role_permission_details %s',e)
            return None