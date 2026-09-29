from shared.database.database import Base_main, Base_hrms, Base_accounts, Base_crms,Base_pm
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, UniqueConstraint, ForeignKey, Time, Sequence,Boolean, Text,DECIMAL,BigInteger, Unicode
from datetime import datetime
from constants import DBConstants
import traceback

                                                                        ##### Schema handles validation, model handles database interaction ######
class Lists_active_columns(Base_accounts):
    __tablename__ = "lists_active_columns"
    __table_args__ = {'schema':'Accounts'}
    list_column_id = Column(Integer, primary_key=True,autoincrement=True)
    client_id = Column(Integer,nullable=True)
    user_id = Column(Integer,nullable=True)
    user_name = Column(String,nullable=True)
    permission_id = Column(Integer,nullable=True)
    active_columns = Column(String,nullable=True)
    field_value_id = Column(String,nullable=True)

class projects(Base_pm):
      __tablename__="projects"
      __table_args__={"schema":"projectmanagement"}
      project_id = Column(Integer, primary_key=True, autoincrement=True)
      project_pic_file_name=Column(String , nullable=True)
      project_pic_file_location=Column(String , nullable=True)
      project_no=Column(String, nullable=True)
      project_name=Column(Integer,nullable=True)
      project_client=Column(String, nullable=True)
      start_date=Column(DateTime,nullable=True)
      end_date=Column(DateTime,nullable=True)
      budget=Column(Integer,nullable=True)
      description=Column(String, nullable=True)
      project_type_id=Column(Integer, nullable=True)
      project_category_id=Column(Integer, nullable=True)
      project_business_domain_id=Column(Integer, nullable=True)
      status_id=Column(Integer,nullable=True)
      priority_id=Column(Integer, nullable=True)
      project_manager=Column(String, nullable=True)
      stakeholder_id=Column(Integer, nullable=True) 
      client_id=Column(Integer,nullable=True)
      user_id=Column(Integer,nullable=True)
      permission_id=Column(Integer,nullable=True)
      created_at=Column(DateTime,nullable=True)
      updated_at=Column(DateTime, nullable=True)
      
class project_files(Base_pm):
      __tablename__="project_files"
      __table_args__={"schema":"projectmanagement"}
      project_files_id=Column(Integer,primary_key=True)
      project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id"))
      file_type_id=Column(Integer, nullable=True)
      client_id=Column(Integer, nullable=True)
      user_id=Column(Integer, nullable=True)
      project_files=Column(String, nullable=True)
      created_at=Column(DateTime,nullable=True)
      updated_at=Column(DateTime, nullable=True)
      
class tasks(Base_pm):
      __tablename__="tasks"
      __table_args__={"schema":"projectmanagement"}
      task_id=Column(Integer, primary_key=True)
      project_id=Column(Integer, nullable=True)
      task_no=Column(String, nullable=True)
      task_name=Column(String, nullable=True)
      assignee=Column(String, nullable=True)
      module=Column(String, nullable=True)
      work_type=Column(String, nullable=True)
      priority=Column(Integer, nullable=True)
      status=Column(Integer, nullable=True)
      client_id=Column(Integer, nullable=True)
      user_id=Column(Integer, nullable=True)
      start_date=Column(DateTime, nullable=True)
      end_date=Column(DateTime, nullable=True)
      description=Column(String, nullable=True)
      notes=Column(String, nullable=True)
      blockers=Column(String, nullable=True)
      created_at=Column(DateTime, nullable=True)
      updated_at=Column(DateTime, nullable=True)


class teams(Base_pm):
      __tablename__="teams" 
      __table_args__={"schema":"projectmanagement"}
      team_id=Column(Integer, primary_key=True)
      team_name=Column(String, nullable=True)
      team_key=Column(Integer, nullable=True)
      description=Column(String, nullable=True)
      team_type=Column(String, nullable=True)
      team_dept=Column(String, nullable=True)
      team_lead=Column(String, nullable=True)
      status=Column(Integer, nullable=True)
      client_id=Column(Integer, nullable=True)
      user_id=Column(Integer, nullable=True)
      created_at=Column(DateTime, nullable=True)
      updated_at=Column(DateTime, nullable=True)


class project_type(Base_pm):
      __tablename__="project_type"
      __table_args__={"schema":"projectmanagement"}
      project_type_id=Column(Integer, primary_key=True)
      # project_id=Column(Integer,ForeignKey("projectmanagement.projects.project_id"))
      project_type_name=Column(String, nullable=True)
      user_id=Column(Integer, nullable=True)
      client_id=Column(Integer, nullable=True)
      created_at=Column(DateTime, nullable=True)
      updated_at=Column(DateTime, nullable=True)

class project_category(Base_pm):
      __tablename__="project_category"
      __table_args__={"schema":"projectmanagement"}
      project_category_id=Column(Integer, primary_key=True)
      # project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id"))
      project_category_name=Column(String, nullable=True)
      user_id=Column(Integer, nullable=True)
      client_id=Column(Integer, nullable=True)
      created_at=Column(DateTime, nullable=True)
      updated_at=Column(DateTime, nullable=True)

class project_business_domain(Base_pm):
      __tablename__="project_business_domain"
      __table_args__={"schema":"projectmanagement"}
      project_business_domain_id=Column(Integer, primary_key=True)	
      # project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id"))
      project_business_domain_name=Column(String, nullable=True)
      client_id=Column(Integer, nullable=True)
      user_id=Column(Integer, nullable=True)
      created_at=Column(DateTime, nullable=True)
      updated_at=Column(DateTime, nullable=True)

# class project_status(Base_pm):
#       __tablename__="project_status"
#       __table_args__={"schema":"projectmanagement"}
#       project_status_id=Column(Integer, primary_key=True)	
#       # project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id"))
#       project_status_name=Column(String, nullable=True)
#       user_id=Column(Integer, nullable=True)
#       client_id=Column(Integer, nullable=True)
#       created_at=Column(DateTime, nullable=True)
#       updated_at=Column(DateTime, nullable=True)
            
# class project_priority(Base_pm):
#        __tablename__="project_priority"
#        __table_args__={"schema":"projectmanagement"}
#        project_priority_id=Column(Integer, primary_key=True)
#       #  project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id"))
#        project_priority_name=Column(String, nullable=True)
#        user_id=Column(Integer, nullable=True)
#        client_id=Column(Integer, nullable=True)
#        created_at=Column(DateTime, nullable=True)
#        updated_at=Column(DateTime, nullable=True)

class project_tags(Base_pm):
       __tablename__="project_tags"
       __table_args__={"schema":"projectmanagement"} 
       project_tag_id=Column(Integer, primary_key=True)
       project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id")) 
       project_tag_name=Column(String, nullable=True)
       user_id=Column(Integer, nullable=True)
       client_id=Column(Integer, nullable=True)
       created_at=Column(DateTime, nullable=True)
       updated_at=Column(DateTime, nullable=True)

class project_stakeholders(Base_pm):
       __tablename__="project_stakeholders"
       __table_args__={"schema":"projectmanagement"} 
       project_stakeholder_id=Column(Integer, primary_key=True)
       project_id=Column(Integer, ForeignKey("projectmanagement.projects.project_id"))
       project_stakeholder_type=Column(Integer, nullable=True)
       stakeholder_name=Column(String, nullable=True)
       stakeholder_email=Column(String, nullable=True)
       stakeholder_role=Column(String, nullable=True)
       user_id=Column(Integer, nullable=True)
       client_id=Column(Integer, nullable=True)
       created_at=Column(DateTime, nullable=True)
       updated_at=Column(DateTime, nullable=True)


