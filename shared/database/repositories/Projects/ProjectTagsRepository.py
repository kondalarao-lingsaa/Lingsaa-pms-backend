from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository
from shared.database.models import project_business_domain, project_category, project_stakeholders, project_tags, project_type, projects, project_files
from local.logging_config import error_logger,performence_logger

class project_tags_Repository(Repository):
    def __init__(self, db: Session, model_class=project_tags):
        super().__init__(model_class, db)

    def get_project_tags(self, client_id:int, user_id:int=None,project_id:int=None) :
        try:
            query = self.session.query(project_tags).filter(and_(project_tags.client_id==client_id, project_tags.user_id==user_id)).all()
            if project_id is not None:
                    query_two = self.session.query(project_tags).filter(and_(project_tags.client_id==client_id, project_tags.user_id==user_id, project_tags.project_id==project_id)).all()
                    return query_two
            return query
        except Exception as e :
            traceback.print_exc()
            return {str(e)}
        
    def project_tags_to_delete(self, tag_ids, project_id:int=None, client_id:int=None, user_id:int=None):
        try:
            query = self.session.query(project_tags).filter(and_(project_tags.client_id==client_id, 
                                                            project_tags.user_id==user_id,
                                                            project_tags.project_id==project_id, 
                                                            project_tags.project_tag_id.notin_(tag_ids))).all()
            return query
        except Exception as e:
            traceback.print_exc()
            return {str(e)}