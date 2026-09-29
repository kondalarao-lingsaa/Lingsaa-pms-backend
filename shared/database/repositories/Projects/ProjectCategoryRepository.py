from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository
from shared.database.models import  project_category
from local.logging_config import error_logger,performence_logger

class project_category_Repository(Repository):
    def __init__(self, db: Session, model_class=project_category):
        super().__init__(model_class, db)

    def get_project_category(self, client_id:int, user_id:int ,project_category_id:int=None):
        try:
            query = self.session.query(project_category).filter(and_(project_category.client_id==client_id, project_category.user_id==user_id)).all()
            return query
        except Exception as e :
            traceback.print_exc()
            return {str(e)}