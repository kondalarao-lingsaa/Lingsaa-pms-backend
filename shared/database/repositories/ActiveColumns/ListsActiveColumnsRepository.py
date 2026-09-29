from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_

from shared.database.repositories.Repository import Repository
from shared.database.models import Lists_active_columns
from local.logging_config import error_logger,performence_logger


class ListsActiveColumnsRepository(Repository):
    def __init__(self, db: Session, model_class=Lists_active_columns):
        super().__init__(model_class, db)

    def get_list_by_user_id(self,client_id,user_id,permission_id):
        try:
            res = self.session.query(Lists_active_columns).filter(and_(Lists_active_columns.client_id==client_id,
                                                                       Lists_active_columns.user_id==user_id,
                                                                       Lists_active_columns.permission_id==permission_id)).first()
            return res
        except Exception as e:
            traceback.print_exc()
            error_logger.error(f"Error at get_list_by_user_id-------{e}")