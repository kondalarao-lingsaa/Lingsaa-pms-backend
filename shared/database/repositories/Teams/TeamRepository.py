from sqlalchemy.orm import Session
import traceback
from sqlalchemy import or_, and_ , func, case
from fastapi.responses import JSONResponse
from shared.database.repositories.Repository import Repository 
from shared.database.models import teams

class TeamRepository(Repository):
    def __init__(self, db: Session, model_class=teams):
        super().__init__(model_class, db)
    
    def get_team_details(self, client_id:int, user_id:int, search:str=None, status:int=None, page_size:int=None, offset:int=None):
        try:
            query = self.session.query(teams).filter(and_(teams.client_id==client_id, teams.user_id==user_id))
            if search:
                search_pattern = f"%{search}%"
                query = query.filter(or_(teams.team_name.ilike(search_pattern),teams.team_key.ilike(search_pattern),teams.team_dept.ilike(search_pattern), teams.team_type.ilike(search_pattern),teams.team_lead.ilike(search_pattern)))
            if status is not None:
                query = query.filter(teams.status == status)
            if page_size is not None and offset is not None:
                query = query.order_by(teams.team_id).limit(page_size).offset(offset)

            total_teams= self.session.query(teams).filter(teams.client_id==client_id,teams.user_id==user_id).count()
            
            querytwo = self.session.query(func.coalesce(func.sum(case((teams.status == 1, 1), else_=0)), 0).label("active"),
                    func.coalesce(func.sum(case((teams.status == 2, 1), else_=0)), 0).label("inactive"),
                    func.coalesce(func.sum(case((teams.status == 3, 1), else_=0)), 0).label("hold")).filter(and_(teams.client_id==client_id, teams.user_id==user_id)).first()
            
            return query.all() ,total_teams , querytwo
        except Exception as e:
            traceback.print_exc()
            return {str(e)}


