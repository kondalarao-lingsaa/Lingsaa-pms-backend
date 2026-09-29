from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository
from shared.database.models import project_business_domain, project_category, project_stakeholders, project_tags, project_type, projects, project_files
from local.logging_config import error_logger,performence_logger

class project_type_Repository(Repository):
    def __init__(self, db: Session, model_class=project_type):
        super().__init__(model_class, db)
    
    def get_project_type(self, client_id:int, user_id:int , project_type_id:int=None):
        try:
            if project_type_id is not None:
                query_one = self.session.query(project_type).filter(and_(project_type.client_id==client_id, project_type.user_id==user_id, project_type.project_type_id==project_type_id)).first()
                return query_one
            else:
                query_two = self.session.query(project_type).filter(and_(project_type.client_id==client_id, project_type.user_id==user_id)).all()
                return query_two
        except Exception as e :
            traceback.print_exc()
            return {str(e)}