from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_

from shared.database.repositories.Repository import Repository
from shared.database.models import UserRole
from local.logging_config import error_logger,performence_logger


class UserRoleRepository(Repository):
    def __init__(self, db: Session, model_class=UserRole):
        super().__init__(model_class, db)
    def get_by_user_id(self,user_id:int=None):
        try:
            base = self.session.query(UserRole)
            if user_id is not None:
                base = base.filter(UserRole.user_id == user_id)
            return base.first()
        except Exception as e:
            traceback.print_exc()
            error_logger.error('error in get by user id is %s',e)