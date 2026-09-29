from typing import Optional, List
from pydantic import BaseModel, EmailStr,Field
from datetime import datetime
from typing import Optional
from typing import Union
from typing import Union


#................................................................................. ##### Schema handles validation, model handles database interaction ######..........................................................
                                                                       
class project_tags_schema(BaseModel):
       project_id:int=None
       project_tag_id:int=None
       project_tag_name:str=None

class project_stakeholders_schema(BaseModel):
       project_id:int=None
       project_stakeholder_id:int=None
       project_stakeholder_type:int=None
       stakeholder_name:str=None
       stakeholder_email:str=None
       stakeholder_role:str=None 

class project_files_schema(BaseModel):
      project_id:int=None
      project_files_id:int=None
      file_type_id:int=None
      project_files:str=None

class projects_schema(BaseModel):
        project_name:str=None
        project_client:str=None
        start_date:str=None
        end_date:str=None
        budget:int=None 
        description:str=None
        project_type_id:int=None
        project_category_id:int=None
        project_business_domain_id:int=None
        status_id:int=None
        priority_id:int=None
        project_manager:str=None
        stakeholder_id:int=None
        tags:list[project_tags_schema]=None
        roles:list[project_stakeholders_schema]=None
        project_files:list[project_files_schema]=None

class tasks_schema(BaseModel):
      project_id:int=None
      task_name:str=None
      assignee:str=None
      module:str=None
      work_type:str=None
      priority:int=None
      status:int=None
      start_date:str=None
      end_date:str=None
      description:str=None
      notes:str=None
      blockers:str=None

class teams_schema(BaseModel):
      team_name:str=None
      team_key:str=None
      description:str=None 
      team_type:str=None
      team_dept:str=None
      team_lead:str=None 
      status:int=None

class project_type_schema(BaseModel):
      # project_id:int=None
      project_type_name:str=None
      
class project_category_schema(BaseModel):
      # project_id:int=None
      project_category_name:str=None
      
class project_business_domain_schema(BaseModel):
      # project_id:int=None
      project_business_domain_name:str=None

# class project_status_schema(BaseModel):
#       # project_id:int=None
#       project_status_name:str=None 
      
# class project_priority_schema(BaseModel):
#       #  project_id:int=None
#        project_priority_name:str=None



      