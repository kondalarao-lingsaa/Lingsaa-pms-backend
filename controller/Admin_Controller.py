from local.logging_config import error_logger,performence_logger
import traceback
from fastapi import APIRouter,Depends, Form, HTTPException
from azure_service.AzureBlobManager import AzureBlobManager
from constants import Tags
from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from shared.database.repositories.Projects.ProjectBusinessDominRepository import project_business_domain_Repository
from shared.database.repositories.Projects.ProjectCategoryRepository import project_category_Repository
from shared.database.repositories.Projects.ProjectFilesRepository import project_files_Repository
from shared.database.repositories.Projects.ProjectStakeHolder import project_stakeholders_Repository
from shared.database.repositories.Projects.ProjectTagsRepository import project_tags_Repository
from shared.database.repositories.Projects.ProjectTypeRepository import project_type_Repository
from shared.database.repositories.Projects.ProjectsRepository import Projects_Repository
from shared.database.repositories.Tasks import TasksRepository
from shared.database.repositories.Teams import TeamRepository
from shared.parser.date_parser import converted_indiantime
from shared.database.get_db import get_db
from shared.database.schemas import project_business_domain_schema, project_category_schema,  project_type_schema, projects_schema ,tasks_schema ,teams_schema

from fastapi.responses import JSONResponse
from core.generator import Generator
from fastapi import UploadFile, File
from constants import BaseConstants
from core.FileUploader import FileUploader

router = APIRouter(prefix='/admin', tags=[Tags.ADMIN])
import logging

performence_logger = logging.getLogger("performance_logger")
logging.basicConfig(level=logging.DEBUG)                         


##...................._create_projects ( create , delete , update ) .....................##
@router.post("/create_project")
def post_create_project(client_id:int, user_id:int, project: str = Form(None), delete_project:int=None, project_id:int=None,
                        profile: UploadFile = File(None), db: Session = Depends(get_db)):
    try:
        try:
            performence_logger.debug(f"Parsed product details: {project}")
            project_obj = projects_schema.model_validate_json(project)
            performence_logger.debug(f"Parsed product details: {project_obj}")
        except Exception as parse_error:
            performence_logger.error(f"Failed to parse details_json: {str(parse_error)}")
            return JSONResponse(status_code=400,content={'detail': f'Invalid JSON format: {str(parse_error)}'})
        
        projects_repo = Projects_Repository(db) 
        tag_repo=project_tags_Repository(db)
        project_files_repo = project_files_Repository(db)
        stakeholder_repo=project_stakeholders_Repository(db)
        if delete_project is not None: 
            if project_id is None:
                raise HTTPException(status_code=400, detail="project_id is required to delete")
            profile_pic = projects_repo.get(id_=project_id) 

            file_location = profile_pic.project_pic_file_location if profile_pic else None
            file_uploader = FileUploader(
                    location=BaseConstants.TEMP,
                    file_id=file_location
                )
            file_uploader.delete_file(file=file_location)

            project_delete=projects_repo.get_project_details(
                            client_id=client_id,
                            user_id=user_id,
                            project_id=project_id 
                            )
            if project_delete is not None:
                projects_repo.delete(id_=project_id)
            
            delete_project_tags=tag_repo.get_project_tags(
                            client_id=client_id,
                            user_id=user_id,
                            project_id=project_id 
                            )
            if delete_project_tags is not None:
                for each in delete_project_tags:
                    tag_repo.delete(id_=each.project_tag_id)

            delete_project_stakeholder=stakeholder_repo.get_project_stakeholders(
                            client_id=client_id,
                            user_id=user_id,
                            project_id=project_id 
                            )
            if delete_project_stakeholder is not None:
                for each in delete_project_stakeholder:
                    stakeholder_repo.delete(id_=each.project_stakeholder_id)

            deleted_project_files=project_files_repo.get(id_=project_id)
            
            if deleted_project_files is not None:
                for each in deleted_project_files:
                    file_location = each.project_files
                    file_uploader = FileUploader( location=BaseConstants.TEMP, file_id=file_location ) 
                    file_uploader.delete_file(file=file_location)

            delete_project_files=project_files_repo.get_project_files(
                            client_id=client_id,
                            user_id=user_id,
                            project_id=project_id 
            )
            if delete_project_files is not None:
                 for each in delete_project_files:
                      project_files_repo.delete(
                           id_=each.project_files_id
                      )
            return JSONResponse(
                status_code=200,
                content={"detail": "Project deleted successfully"}
            )
        else:
            if project_id is None:
                create_project = projects_repo.create(
                    project_name=project_obj.project_name,
                    project_no=Generator.project_number(),
                    project_client=project_obj.project_client,
                    start_date=project_obj.start_date,
                    end_date=project_obj.end_date,
                    budget=project_obj.budget,
                    project_type_id=project_obj.project_type_id,
                    project_category_id=project_obj.project_category_id,
                    project_business_domain_id=project_obj.project_business_domain_id,
                    status_id=project_obj.status_id,
                    priority_id=project_obj.priority_id,
                    project_manager=project_obj.project_manager,
                    stakeholder_id=project_obj.stakeholder_id,
                    description=project_obj.description,
                    client_id=client_id,
                    user_id=user_id,
                    created_at=converted_indiantime()
                )
                if project_obj.tags is not None:
                    for each in project_obj.tags:                       
                        tag_repo.create(
                            project_id=create_project.project_id,
                            project_tag_name=each.project_tag_name, 
                            client_id=client_id,
                            user_id=user_id,
                            created_at=converted_indiantime()
                        )
                if project_obj.roles is not None:
                    for each in project_obj.roles:
                        stakeholder_repo.create(
                             project_id=create_project.project_id,
                             project_stakeholder_type=each.project_stakeholder_type,
                             stakeholder_name=each.stakeholder_name,
                             stakeholder_email=each.stakeholder_email,
                             stakeholder_role=each.stakeholder_role,
                             client_id=client_id,
                             user_id=user_id,
                             created_at=converted_indiantime()
                        )
                if project_obj.project_files is not None: 
                    for each in project_obj.project_files:
                        project_files_repo.update(
                             id_=each.project_files_id,
                             project_id=create_project.project_id, 
                             created_at=converted_indiantime()
                        )
                if profile is not None:
                    file_name = f"{create_project.project_id}/{profile.filename}"
                    file_uploader = FileUploader(location=BaseConstants.TEMP, file_id=file_name)
                    file_uploader.upload_file(file=profile)
                    location = f"{file_name}/{profile.filename}"
                    projects_repo.create(
                        id_=create_project.project_id,
                        project_pic_file_name=profile.filename,
                        project_pic_file_location=location,
                        created_at=converted_indiantime()
                    )
                return JSONResponse(status_code=200,content={'detail': "project is created successfully"})
            elif project_id:
                    if profile is not None:
                        profile_pic=projects_repo.get(id_=project_id)
                        file_name = f"{project_id}/{profile.filename}"
                        file_uploader = FileUploader(location=BaseConstants.TEMP, file_id=file_name)
                        file_uploader.delete_file(file=profile_pic.project_pic_file_location)
                        file_uploader.upload_file(file=profile)
                        location = f"{file_name}/{profile.filename}"
                        projects_repo.update(
                                id_=project_id,
                                project_pic_file_name=profile.filename,
                                project_pic_file_location=location,
                                updated_at=converted_indiantime()
                                )
                    projects_repo.update(
                                id_=project_id,
                                project_name=project_obj.project_name,
                                project_client=project_obj.project_client,
                                start_date=project_obj.start_date,
                                end_date=project_obj.end_date,
                                budget=project_obj.budget,
                                project_type_id=project_obj.project_type_id,
                                project_category_id=project_obj.project_category_id,
                                project_business_domain_id=project_obj.project_business_domain_id,
                                status_id=project_obj.status_id,
                                priority_id=project_obj.priority_id,
                                project_manager=project_obj.project_manager,
                                stakeholder_id=project_obj.stakeholder_id,
                                description=project_obj.description,
                                client_id=client_id,
                                user_id=user_id,
                                updated_at=converted_indiantime()
                                )                    
                    project_tags_ids =[each.project_tag_id for each in project_obj.tags if each.project_tag_id is not None ] 

                    removed_tags=tag_repo.project_tags_to_delete( tag_ids=project_tags_ids, project_id=project_id , client_id=client_id , user_id=user_id)

                    if removed_tags is not None:
                        for each in removed_tags:
                            tag_repo.delete(
                                id_=each.project_tag_id
                            )
                    if project_obj.tags :
                        for each in project_obj.tags:
                            if each.project_tag_id is None:
                                tag_repo.create(
                                project_id=project_id,
                                project_tag_name=each.project_tag_name, 
                                client_id=client_id,
                                user_id=user_id,
                                updated_at=converted_indiantime() 
                                        )
                    project_role_ids =[each.project_stakeholder_id for each in project_obj.roles if each.project_stakeholder_id is not None]

                    removed_roles=stakeholder_repo.project_roles_to_delete( role_ids=project_role_ids, project_id=project_id , client_id=client_id , user_id=user_id)

                    if removed_roles is not None:
                        for each in removed_roles:
                            stakeholder_repo.delete(
                                id_=each.project_stakeholder_id
                            )
                    if project_obj.roles :
                        for each in project_obj.roles:
                            if each.project_stakeholder_id is  None:
                                stakeholder_repo.create(
                                    project_id=project_id,
                                    project_stakeholder_type=each.project_stakeholder_type,
                                    stakeholder_name=each.stakeholder_name,
                                    stakeholder_email=each.stakeholder_email,
                                    stakeholder_role=each.stakeholder_role,
                                    client_id=client_id,
                                    user_id=user_id,
                                    updated_at=converted_indiantime()
                                )
                    project_file_ids =[each.project_files_id for each in project_obj.project_files if each.project_files_id is not None]

                    removed_files=project_files_repo.project_files_to_delete( files_ids=project_file_ids, project_id=project_id , client_id=client_id , user_id=user_id)

                    if removed_files is not None:
                        for each in removed_files:
                            project_files_repo.delete(
                                id_=each.project_files_id 
                            )
                            deleted_project_files = project_files_repo.get(id_=each.project_files_id)
                            if deleted_project_files is not None: 
                                file_location = deleted_project_files.project_files
                                file_uploader = FileUploader(
                                                            location=BaseConstants.TEMP,
                                                            file_id=file_location
                                                        )
                                file_uploader.delete_file(file=file_location)
                    if project_obj.project_files is not None:
                         for each in project_obj.project_files:
                              if each.project_id is None:
                                        project_files_repo.update(
                                        id_=each.project_files_id,
                                        file_type_id=each.file_type_id,
                                        project_id=project_id,
                                        updated_at=converted_indiantime() 
                                        )
            return JSONResponse(status_code=200,content={'detail': "project is updated successfully"})
    except Exception as e:
        db.rollback()
        traceback.print_exc()
        error_logger.error(f"Error at _create_project------%s",e)
        raise HTTPException(status_code=500,detail="Failed to create project")

@router.post("/upload_project_files")
def upload_project_files(client_id:int , user_id:int,file_type_id:int, project_id:int=None,project_file_id:int=None,files: UploadFile = File(None), db:Session=Depends(get_db)):
    try:
        project_files_repo = project_files_Repository(db)
        if files is not None:
                        blob_manager=AzureBlobManager()
                        file_name = f"{user_id}/{files.filename}"
                        file_uploader = FileUploader(location=BaseConstants.TEMP, file_id=file_name)
                        file_uploader.upload_file(file=files)
                        location = f"{file_name}/{files.filename}"
                        project_files=project_files_repo.create(
                                        client_id=client_id,
                                        user_id=user_id,
                                        file_type_id=file_type_id,
                                        project_files=location,
                                        created_at=converted_indiantime()
                                    )
                        if project_files is not None:
                                    image = blob_manager.generate_sas_token(location)
                                    result = [{
                                        'project_files_id':project_files.project_files_id,
                                        'image':image,
                                        'file_type_id':file_type_id
                                    }]
                                    return JSONResponse(status_code=200,content={'detail':result})
        else:
            return JSONResponse(status_code=404,content={'detail':'Details Not Found'})  
                           
    except Exception as e:
        traceback.print_exc()
        error_logger.error(f"Error at _upload_files------%s",e)


@router.post("/delete_project_files") 
def delete_project_files(client_id:int , user_id:int, project_id:int=None, project_file_id:list[int]=None, db:Session=Depends(get_db)):
    try:
        project_files_repo = project_files_Repository(db)
        if project_id is None and project_file_id is not None:

            for each in project_file_id:
                deleted_project_files=project_files_repo.get(id_=each)
                if not deleted_project_files:
                        return  JSONResponse(status_code=404,content={'detail':'No data found'})
                file_location = deleted_project_files.project_files
                file_uploader = FileUploader(
                        location=BaseConstants.TEMP,
                        file_id=file_location
                    )
                file_uploader.delete_file(file=file_location)
                project_files_repo.delete(
                        id_=each
                    )
            return JSONResponse(status_code=200,content={'detail':'project files deleted successfully'})
    except Exception as e:
         traceback.print_exc()
         error_logger.error(f"Error at_deleting_files------%s",e)
         
@router.post("/update_project_status")
def update_project_status(client_id:int , user_id:int , new_status_id:int, project_id:int ,db:Session=Depends(get_db)):
     try:
         project_repo=Projects_Repository(db)
         project_repo.update(
              id_=project_id,
              status_id=new_status_id,
              updated_at=converted_indiantime()
         )
         return JSONResponse(status_code=200,content={'detail':"status updated successfully"})
     except Exception as e :
           traceback.print_exc()
           error_logger.error(f"Error at _update_project_status-----%s",e)

@router.post("/update_project_priority")
def update_project_priority(client_id:int, user_id:int, project_id: int, new_priority_id:int, db:Session=Depends(get_db)):
    try:
        project_repo=Projects_Repository(db)
        project_repo.update(
            id_=project_id,
            priority_id=new_priority_id,
            updated_at=converted_indiantime()
        )
        return JSONResponse(status_code=200,content={'detail':"priority updated successfully"})
    except Exception as e :
            traceback.print_exc()
            error_logger.error(f"Error at _update_project_status-----%s",e)

##...................._tasks_projects ( create , delete , update ) .....................##

@router.post("/create_task") 
def create_team(client_id:int , user_id:int, task:tasks_schema, delete_id:int=None, task_id:int=None, db:Session=Depends(get_db)):
        try:
            repo = TasksRepository(db)
            if task_id is  None:
                new_task=repo.create(task_name=task.task_name,
                                     project_id=task.project_id,
                                     task_no=Generator.task_number(),
                                     assignee=task.assignee,
                                     module=task.module,
                                     work_type=task.work_type,
                                     priority=task.priority,
                                     status=task.status,
                                     client_id=client_id,
                                     user_id=user_id,
                                     start_date=task.start_date,
                                     end_date=task.end_date,
                                     description=task.description,
                                     notes=task.notes,
                                     blockers=task.blockers,
                                     created_at=converted_indiantime()
                                     )
                return JSONResponse(status_code=200,content={'detail':"task is created successfully"})
            elif delete_id:
                if not task_id:
                    raise HTTPException(status_code=400, detail="task_id is required to delete")
                delete_task=repo.delete(
                    id_=task_id)
                return JSONResponse(status_code=200, content={"detail": "task deleted successfully"})
            elif task_id:
                update_project=repo.update(id_=task_id,
                                           project_id=task.project_id,
                                           task_name=task.task_name,
                                           assignee=task.assignee,
                                           module=task.module,
                                           work_type=task.work_type,
                                           priority=task.priority,
                                           status=task.status,
                                           client_id=client_id,
                                           user_id=user_id,
                                           start_date=task.start_date,
                                           end_date=task.end_date,
                                           description=task.description,
                                           notes=task.notes,
                                           blockers=task.blockers,
                                           updated_at=converted_indiantime() 
                                           )
                return JSONResponse(status_code=200,content={'detail':"task is updated successfully"})
        except Exception as e:
            db.rollback()
            print("Error while creating project:", str(e))
            raise HTTPException(status_code=500,detail="Failed to create task")
        

# @router.delete("/delete_tasks")
# def delete_tasks(client_id:int, user_id:int , task_id:int , db:Session=Depends(get_db)):
#     try:
#          repo = TasksRepository(db)
#          repo.delete(id_=task_id)
#          return JSONResponse(status_code=200,content={'detail':"task is deleted successfully"})
#     except Exception as e:
#          print(str(e))


@router.post("/create_team")
def create_team(client_id:int, user_id:int, team:teams_schema, delete_id:int=None, team_id:int=None, db:Session=Depends(get_db)):
    try:
            repo = TeamRepository(db)
            if team_id is  None:
                new_team=repo.create(team_name=team.team_name,
                                     team_key=team.team_key,
                                     description=team.description,
                                     team_type=team.team_type,
                                     team_dept=team.team_dept,
                                     team_lead=team.team_lead,
                                     status=team.status,
                                     client_id=client_id,
                                     user_id=user_id,
                                     created_at=converted_indiantime()
                                     )
                return JSONResponse(status_code=200,content={'detail':"team is created successfully"})
            elif delete_id:
                if not team_id:
                    raise HTTPException(status_code=400, detail="team_id is required to delete")
                delete_task=repo.delete(
                    id_=team_id)
                return JSONResponse(status_code=200, content={"detail": "team deleted successfully"})
            elif team_id:
                update_project=repo.update(id_=team_id,
                                            team_name=team.team_name,
                                            team_key=team.team_key,
                                            description=team.description,
                                            team_type=team.team_type,
                                            team_dept=team.team_dept,
                                            team_lead=team.team_lead,
                                            status=team.status,
                                            client_id=client_id,
                                            user_id=user_id,
                                            updated_at=converted_indiantime()
                                            )
                return JSONResponse(status_code=200,content={'detail':"task is updated successfully"})
    except Exception as e:
        db.rollback()
        print("Error while creating team:", str(e))
        raise HTTPException(status_code=500,detail="Failed to create Team")

@router.post("/create_project_type")
def create_project_type(client_id:int, user_id:int, type:project_type_schema, delete_id:int=None, project_type_id:int=None, db:Session=Depends(get_db)):
    try:
        repo = project_type_Repository(db)
        if project_type_id is None:
            repo.create(
                    project_type_name=type.project_type_name,
                    user_id=user_id,
                    client_id=client_id,
                    created_at=converted_indiantime()
            )
            return JSONResponse(status_code=200,content={'detail':"project type is created successfully"})
        elif delete_id:
                if not project_type_id:
                    raise HTTPException(status_code=400, detail="project_type_id is required to delete")
                repo.delete(
                           id_=project_type_id
                           )
                return JSONResponse(status_code=200, content={"detail": "project type deleted successfully"})
        elif project_type_id:
             repo.update(
                    id_=project_type_id,
                    project_type_name=type.project_type_name,
                    user_id=user_id,
                    client_id=client_id,
                    updated_at=converted_indiantime()
            )     
             return JSONResponse(status_code=200,content={'detail':"project type is updated successfully"})
    except Exception as e:
        db.rollback()
        print("Error while creating project type:", str(e))
        raise HTTPException(status_code=500,detail="Failed to create project type")


@router.post("/create_project_category")
def create_project_category(client_id:int, user_id:int, type:project_category_schema, delete_id:int=None, project_category_id:int=None, db:Session=Depends(get_db)):
    try:
        repo = project_category_Repository(db)
        if project_category_id is None:
            repo.create(
                    project_category_name=type.project_category_name,
                    user_id=user_id,
                    client_id=client_id,
                    created_at=converted_indiantime()
            )
            return JSONResponse(status_code=200, content={"detail": "project category created successfully"})
        elif delete_id:
                if not project_category_id:
                    raise HTTPException(status_code=400, detail="project_category_id is required to delete")
                repo.delete(
                           id_=project_category_id
                           )
                return JSONResponse(status_code=200, content={"detail": "project category deleted successfully"})
        elif project_category_id:
            repo.update(
                    id_=project_category_id,
                    project_category_name=type.project_category_name,
                    user_id=user_id,
                    client_id=client_id,
                    updated_at=converted_indiantime()
            )
            return JSONResponse(status_code=200, content={"detail": "project category updated successfully"})
    except Exception as e:
        db.rollback()
        print("Error while creating project_category:", str(e))
        raise HTTPException(status_code=500,detail="Failed to create project_category")
    

@router.post("/create_project_business_domain")
def create_project_business_domain(client_id:int, user_id:int, type:project_business_domain_schema, delete_id:int=None, project_business_domain_id:int=None, db:Session=Depends(get_db)):
     try:
          repo=project_business_domain_Repository(db)
          if project_business_domain_id is None:
            repo.create(
            project_business_domain_name=type.project_business_domain_name,
            client_id=client_id,
            user_id=user_id,
            created_at=converted_indiantime()
            )
            return JSONResponse(status_code=200, content={"detail": "project business domain created successfully"})
          elif delete_id is not None:
              if not project_business_domain_id:
                    raise HTTPException(status_code=400, detail="project_business_domain_id is required to delete")
              repo.delete(
                id_=project_business_domain_id
                )
              return JSONResponse(status_code=200, content={"detail": "project business domain deleted successfully"})
          elif project_business_domain_id:
              repo.update(
                  id_=project_business_domain_id,
                   project_business_domain_name=type.project_business_domain_name,
                  user_id=user_id,
                  client_id=client_id,
                  updated_at=converted_indiantime()
              )
              return JSONResponse(status_code=200, content={"detail": " project business domain updated successfully"}) 
     except Exception as e:
        db.rollback()
        print("Error while creating project business domain :", str(e))
        raise HTTPException(status_code=500,detail="Failed to create project business domain ")
     
# @router.post("/create_project_status")
# def create_project_status(client_id:int, user_id:int,type:project_status_schema,delete_id:int=None, project_status_id:int=None, db:Session=Depends(get_db)):
#     try:
#         repo=project_status_Repository(db)
#         if project_status_id is None:
#             repo.create(
#             project_status_name=type.project_status_name,
#             client_id=client_id,
#             user_id=user_id,
#             created_at=converted_indiantime() 
#             )
#             return JSONResponse(status_code=200, content={"detail": " project status name created successfully"}) 
#         elif delete_id is not None:
#               if not project_status_id:
#                     raise HTTPException(status_code=400, detail="project_status_id is required to delete")
#               repo.delete(
#                 id_=project_status_id
#                 )
#               return JSONResponse(status_code=200, content={"detail": "project status name deleted successfully"})
#         elif project_status_id:
#               repo.update(
#                   id_=project_status_id,
#                   project_status_name=type.project_status_name,
#                   user_id=client_id,
#                   client_id=user_id,
#                   updated_at=converted_indiantime()
#               )
#               return JSONResponse(status_code=200, content={"detail": " project status name updated successfully"}) 
#     except Exception as e:
#         db.rollback()
#         print("Error while creating project status name :", str(e))
#         raise HTTPException(status_code=500,detail="Failed to create project status name")
    
# @router.post("/create_project_priority")
# def create_project_priority(client_id:int, user_id:int,type:project_priority_schema,delete_id:int=None, project_priority_id:int=None, db:Session=Depends(get_db)):
#     try:
#         repo=project_priority_Repository(db)
#         if project_priority_id is None:
#             repo.create(
#             project_priority_name=type.project_priority_name,
#             client_id=client_id,
#             user_id=user_id,
#             created_at=converted_indiantime() 
#             )
#             return JSONResponse(status_code=200, content={"detail": " project priority created successfully"}) 
#         elif delete_id is not None:
#               if not project_priority_id:
#                     raise HTTPException(status_code=400, detail="project_priority_id is required to delete")
#               repo.delete(
#                 id_=project_priority_id
#                 )
#               return JSONResponse(status_code=200, content={"detail": "project priority name deleted successfully"})
#         elif project_priority_id:
#               repo.update(
#                   id_=project_priority_id,
#                   project_priority_name=type.project_priority_name,
#                   user_id=client_id,
#                   client_id=user_id,
#                   updated_at=converted_indiantime()
#               )
#               return JSONResponse(status_code=200, content={"detail": " project priority name updated successfully"}) 
#     except Exception as e:
#         db.rollback()
#         print("Error while creating project priority name :", str(e))
#         raise HTTPException(status_code=500,detail="Failed to create project priority name")
    
# @router.post("/create_project_tags")
# def create_project_business_domain(client_id:int, user_id:int, type:project_tags_schema, delete_id:int=None, project_tag_id:int=None, db:Session=Depends(get_db)):
#      try:
#           repo=project_tags_Repository(db)
#           if project_tag_id is None:
#             repo.create(
#             project_tag_name=type.project_tag_name,
#             project_id=type.project_id,
#             client_id=client_id,
#             user_id=user_id,
#             created_at=converted_indiantime()
#             )
#             return JSONResponse(status_code=200, content={"detail": "project tag created successfully"})
#           elif delete_id is not None:
#               if not project_tag_id:
#                     raise HTTPException(status_code=400, detail="project_tag_id is required to delete")
#               repo.delete(
#                 id_=project_tag_id
#                 )
#               return JSONResponse(status_code=200, content={"detail": "project tag deleted successfully"})
#           elif project_tag_id:
#               repo.update(
#                   id_=project_tag_id,
#                   tags=type.project_tag_name,
#                   client_id=client_id,
#                   user_id=user_id,
#                   updated_at=converted_indiantime()
#               )
#               return JSONResponse(status_code=200, content={"detail": " project tag updated successfully"}) 
#      except Exception as e:
#         db.rollback()
#         print("Error while creating project tag :", str(e))
#         raise HTTPException(status_code=500,detail="Failed to create project tag ")
          
# @router.post("/create_project_stakeholder")
# def create_project_business_domain(client_id:int, user_id:int, type:project_stakeholders_schema, delete_id:int=None, project_stakeholder_id:int=None, db:Session=Depends(get_db)):
#      try:
#           repo=project_stakeholders_Repository(db)
#           if project_stakeholder_id is None:
#             repo.create(
#             project_stakeholder_type=type.project_stakeholder_type,
#             stakeholder_name=type.stakeholder_name,
#             stakeholder_email=type.stakeholder_email,
#             stakeholder_role=type.stakeholder_role,
#             client_id=client_id,
#             user_id=user_id,
#             created_at=converted_indiantime()
#             )
#             return JSONResponse(status_code=200, content={"detail": "project stakeholder created successfully"})
#           elif delete_id is not None:
#               if not project_stakeholder_id:
#                     raise HTTPException(status_code=400, detail="project_stakeholder_id is required to delete")
#               repo.delete(
#                 id_=project_stakeholder_id
#                 )
#               return JSONResponse(status_code=200, content={"detail": "project stakeholder deleted successfully"})
#           elif project_stakeholder_id:
#               repo.update(
#                   id_=project_stakeholder_id,
#                   stakeholder_name=type.stakeholder_name,
#                   stakeholder_email=type.stakeholder_email,
#                   stakeholder_role=type.stakeholder_role,
#                   client_id=client_id,
#                   user_id=user_id,
#                   updated_at=converted_indiantime()
#               )
#               return JSONResponse(status_code=200, content={"detail": " project stakeholder updated successfully"}) 
#      except Exception as e:
#         db.rollback()
#         print("Error while creating project stakeholder :", str(e))
#         raise HTTPException(status_code=500,detail="Failed to create project stakeholder")
