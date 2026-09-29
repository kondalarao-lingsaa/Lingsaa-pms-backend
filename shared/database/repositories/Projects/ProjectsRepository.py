from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository
from shared.database.models import project_business_domain, project_category, project_stakeholders, project_tags, project_type, projects, project_files
from local.logging_config import error_logger,performence_logger

class Projects_Repository(Repository):
    def __init__(self, db: Session, model_class=projects):
        super().__init__(model_class, db)

    def export_project_data(self, user_id:int, client_id:int):
            query = self.session.query(projects).filter(and_(projects.client_id == client_id, projects.user_id == user_id)).all()
            return query
    
    def get_project_details(self, client_id:int, user_id=int, search:str=None, status:int=None, priority:int=None, page_size:int=None, offset:int=None, start_date:str=None, project_id:int=None, end_date:str=None
                            ,project_client:int=None, project_manager:int=None, project_name:int=None):
        try:
            if project_id is not None:
                view = self.session.query( projects).filter(and_(projects.client_id == client_id,projects.user_id == user_id , projects.project_id==project_id)).first()
                return view
            else:
                query = self.session.query(projects).filter(and_(projects.client_id == client_id,projects.user_id == user_id))
                if search:
                    search_pattern = f"%{search}%"
                    query = query.filter(or_(projects.project_name.ilike(search_pattern),projects.project_no.ilike(search_pattern),projects.project_manager.ilike(search_pattern), projects.project_client.ilike(search_pattern)))
                if status is not None:
                    query = query.filter(projects.status_id == status)
                if priority is not None:
                    query = query.filter(projects.priority_id == priority)
                if start_date:
                    query = query.filter(projects.start_date >= start_date)
                if project_client :
                    query = query.filter(projects.project_id == project_client)
                if project_manager:
                    query = query.filter(projects.project_id == project_manager)
                if project_name:
                    query = query.filter(projects.project_id == project_name)
                if end_date:
                    query = query.filter(projects.end_date <= end_date)
                if page_size is not None and offset is not None:
                    query = query.order_by(projects.project_id).limit(page_size).offset(offset)
                else:
                    query = query.order_by(projects.project_id)
                status_result = self.session.query(
                        func.coalesce(func.sum(case((projects.status_id == 1, 1), else_=0)),0).label("Draft"),
                        func.coalesce(func.sum(case((projects.status_id == 2, 1), else_=0)),0).label("Pending_Approval"),
                        func.coalesce(func.sum(case((projects.status_id == 3, 1), else_=0)),0).label("Approved"),
                        func.coalesce(func.sum(case((projects.status_id == 4, 1), else_=0)),0).label("Active"),
                        func.coalesce(func.sum(case((projects.status_id == 5, 1), else_=0)),0).label("On_Hold"),
                        func.coalesce(func.sum(case((projects.status_id == 6, 1), else_=0)),0).label("Closed"),
                    ).filter(
                        projects.client_id == client_id,
                        projects.user_id == user_id).one() 

                total_projects= self.session.query(projects).filter(projects.client_id==client_id,projects.user_id==user_id).count()

                return query.all(), status_result, total_projects
        except Exception as e:
            traceback.print_exc()
            error_logger.error(f"Error at _get_project_details------%s",e)