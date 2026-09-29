from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository
from shared.database.models import projects , tasks 

##.........querys for the tasks............##

class TasksRepository(Repository):
    def __init__(self, db: Session, model_class=tasks):
        super().__init__(model_class, db)

    def get_task_details(self, client_id:int, user_id:int, search:str=None, priority:int=None ,status:int=None, page_size:int=None, offset:int=None, start_date:str=None, end_date:str=None):
        try:
            query= self.session.query (tasks.project_id,
                                        tasks.task_no,
                                        tasks.task_id,
                                        tasks.task_name,
                                        tasks.module,
                                        tasks.assignee,
                                        tasks.work_type,
                                        tasks.priority,
                                        tasks.status,
                                        tasks.start_date,
                                        tasks.end_date,
                                        tasks.description,
                                        tasks.notes,
                                        tasks.blockers,                                       
                                     projects.project_name).outerjoin(projects, tasks.project_id == projects.project_id).filter(and_(tasks.client_id==client_id, tasks.user_id==user_id))
            if search:
                search_pattern = f"%{search}%"
                query = query.filter(or_(tasks.task_name.ilike(search_pattern),tasks.work_type.ilike(search_pattern),tasks.task_no.ilike(search_pattern),tasks.assignee.ilike(search_pattern)))
            if status is not None:
                query = query.filter(tasks.status == status)
            if priority is not None:
                query = query.filter(tasks.priority ==priority)
            if start_date:
                query = query.filter(tasks.start_date >= start_date)
            if end_date:
                query = query.filter(tasks.end_date <= end_date)
            if page_size is not None and offset is not None:
                query = query.order_by(tasks.task_id).limit(page_size).offset(offset)
                
            querytwo = self.session.query(func.coalesce(func.sum(case((tasks.status == 1, 1), else_=0)), 0).label("pending"),
                        func.coalesce(func.sum(case((tasks.status == 2, 1), else_=0)), 0).label("inprogress"),
                        func.coalesce(func.sum(case((tasks.status == 3, 1), else_=0)), 0).label("todo"),
                        func.coalesce(func.sum(case((tasks.status == 4, 1), else_=0)), 0).label("completed"),
                        func.coalesce(func.sum(case((tasks.status == 5, 1), else_=0)), 0).label("backlog"),
                        func.coalesce(func.sum(case((tasks.status == 6, 1), else_=0)), 0).label("testing")).filter(and_(tasks.client_id==client_id, tasks.user_id==user_id)).first()
            
            total_tasks = self.session.query(tasks).filter(
                                tasks.client_id == client_id,
                                tasks.user_id == user_id
                            ).count()
            
            return query.all(), querytwo, total_tasks
        except Exception as e:    
            traceback.print_exc()
            return {str(e)}
        
    