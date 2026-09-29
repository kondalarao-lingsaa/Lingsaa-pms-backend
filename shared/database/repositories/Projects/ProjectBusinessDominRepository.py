from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository
from shared.database.models import project_business_domain, project_category, project_stakeholders, project_tags, project_type, projects, project_files
from local.logging_config import error_logger,performence_logger

class project_business_domain_Repository(Repository):
    def __init__(self, db: Session, model_class=project_business_domain):
        super().__init__(model_class, db)
    
    def get_project_business_domain(self, client_id:int, user_id:int, project_business_domain_id:int=None):
        try:
            query = self.session.query(project_business_domain).filter(and_(project_business_domain.client_id==client_id, project_business_domain.user_id==user_id)).all()

            if project_business_domain_id is not None:
                query_two=self.session.query(project_business_domain).filter(and_(project_business_domain.client_id==client_id, project_business_domain.user_id==user_id, project_business_domain.project_business_domain_id==project_business_domain_id )).first()
                return query_two
            return query
        except Exception as e :
            traceback.print_exc()
            return {str(e)}