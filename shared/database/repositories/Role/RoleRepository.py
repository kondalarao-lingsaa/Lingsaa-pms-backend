from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_

from shared.database.repositories.Repository import Repository
from shared.database.models import Role
from local.logging_config import error_logger,performence_logger


class RoleRepository(Repository):
    def __init__(self, db: Session, model_class=Role):
        super().__init__(model_class, db)
    
    def existing_role_details(self,role_id:int=None,role_name:str=None,
                              get_api=None,page_size:int=None,offset:int=None,
                              search:str=None,username:str=None,client_id:int=None,module_id:int=None):
        try:
            base = self.session.query(Role)
            if role_id is not None:
                base = base.filter(Role.role_id == role_id)
            if role_name is not None:
                base = base.filter(Role.name == role_name)
            if search is not None:
                base = base.filter(Role.name.ilike(f'%{search}%'))
            if username == 'masteradmin':
                base = base.filter(Role.scope == 1)
            if client_id is not None:
                base = base.filter(Role.client_id == client_id)
            if module_id is not None:
                base = base.filter(Role.module_id == module_id)
            if page_size and offset is not None:
                base = base.order_by(Role.role_id).limit(page_size).offset(offset)
            if get_api:
                return base.all()
            else:
                return base.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('Error in existing role details query is %s',e)
            return None