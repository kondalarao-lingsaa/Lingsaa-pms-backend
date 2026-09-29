import json
from openpyxl.styles import Font
import traceback
from fastapi import APIRouter,Depends
from openpyxl import load_workbook
from azure_service.AzureBlobManager import AzureBlobManager
from constants import Tags, project_fields
import pandas as pd
from fastapi.responses import FileResponse 
from fastapi import APIRouter,Depends
from shared.database.repositories.ActiveColumns import ListsActiveColumnsRepository
from shared.database.repositories.Projects.ProjectBusinessDominRepository import project_business_domain_Repository
from shared.database.repositories.Projects.ProjectCategoryRepository import project_category_Repository
from shared.database.repositories.Projects.ProjectFilesRepository import project_files_Repository
from shared.database.repositories.Projects.ProjectStakeHolder import project_stakeholders_Repository
from shared.database.repositories.Projects.ProjectTagsRepository import project_tags_Repository
from shared.database.repositories.Projects.ProjectTypeRepository import project_type_Repository
from sqlalchemy.orm import Session
from shared.database.get_db import get_db
from fastapi.responses import JSONResponse
from local.logging_config import error_logger,performence_logger
from shared.database.repositories.Projects.ProjectsRepository import Projects_Repository
from shared.database.repositories.Tasks import TasksRepository
from shared.database.repositories.Teams import TeamRepository


router= APIRouter(prefix='/admin', tags=[Tags.ADMIN])


@router.get("/get_projects")
def get_projects(client_id:int, user_id:int, search:str=None, status:int=None, priority:int=None, project_client:int=None, project_manager:int=None,project_name:int=None, 
                 page_size:int=None, offset:int=None, start_date:str=None, end_date:str=None ,db:Session=Depends(get_db)):
    try:
        projects_repo = Projects_Repository(db)
        blobmanager_repo=AzureBlobManager()
        project_list,status_result, total_projects= projects_repo.get_project_details(
            client_id=client_id,
            user_id=user_id,
            search=search,
            status=status,
            priority=priority,
            page_size=page_size,
            offset=offset,
            start_date=start_date,
            end_date=end_date,
            project_name=project_name,
            project_client=project_client,
            project_manager=project_manager
        )
        result=[]
        for each in project_list:
            result.append({
                "project_id": each.project_id,
                "project_pic_file_name":each.project_pic_file_name,
                "project_pic_file_location":blobmanager_repo.generate_sas_token(each.project_pic_file_location) if each.project_pic_file_location else '',
                "project_no":each.project_no,
                "project_name": each.project_name,
                "project_client":each.project_client,
                "project_manager":each.project_manager,
                "start_date": each.start_date.strftime("%Y-%m-%d") if each.start_date else None,
                "end_date": each.end_date.strftime("%Y-%m-%d") if each.end_date else None,
                "budget":each.budget,
                "description": each.description,
                "status": each.status_id,
                "priority":each.priority_id,            
                # "client_id": each.client_id,
                # "user_id": each.user_id,
                "permission_id": each.permission_id,
            })
        return JSONResponse(
                status_code=200,
                content={
                    "total_projects":total_projects,
                    "Draft":status_result.Draft,
                    "Pending_Approval":status_result.Pending_Approval,
                    "Approved":status_result.Approved,
                    "Active":status_result.Active,
                    "On_Hold":status_result.On_Hold,
                    "Closed":status_result.Closed,
                    "result":result
                    })
    except Exception as e:
        traceback.print_exc()
        error_logger.error(f"Error at _get_project_------%s",e)
    
@router.get("/view_projects")
def view_projects(client_id:int, user_id:int, project_id:int, db:Session=Depends(get_db)):
    try:
        projects_repo = Projects_Repository(db)
        blobmanager_repo=AzureBlobManager()
        project_type_repo=project_type_Repository(db)
        project_category_repo=project_category_Repository(db)
        project_business_domain_repo=project_business_domain_Repository(db)
        projects_tags_repo=project_tags_Repository(db)
        project_stakeholders_repo=project_stakeholders_Repository(db)
        project_files_repo=project_files_Repository(db)

        if project_id is not None:
            result=[]
            data=  projects_repo.get_project_details(client_id=client_id, user_id=user_id, project_id=project_id )
            if data:
                temp={
                    "project_id": data.project_id,
                    # "project_pic_file_name":data.project_pic_file_name,
                    # "project_pic file_location":blobmanager_repo.generate_sas_token(data.project_pic_file_location) if data.project_pic_file_location else '',
                    "project_no":data.project_no,
                    "project_name": data.project_name,
                    "project_client":data.project_client,
                    "project_manager":data.project_manager,
                    "start_date": data.start_date.strftime("%Y-%m-%d") if data.start_date else None,
                    "end_date": data.end_date.strftime("%Y-%m-%d") if data.end_date else None,
                    "budget":data.budget,
                    "description": data.description,
                    "status":data.status_id,
                    "priority":data.priority_id,            
                    # "client_id": data.client_id,
                    # "user_id": data.user_id,
                    # "permission_id": data.permission_id,
                }
                project_types_names=project_type_repo.get(id_=data.project_type_id)
                temp["project_type_name"]=project_types_names.project_type_name if project_types_names else None 

                category_name=project_category_repo.get(id_=data.project_category_id)   
                temp['category']=category_name.project_category_name if category_name else None

                business_domain = project_business_domain_repo.get(id_=data.project_business_domain_id)

                temp["business_domain_name"] = business_domain.project_business_domain_name if business_domain else None

                project_tags=projects_tags_repo.get_project_tags(client_id=client_id, user_id=user_id, project_id=data.project_id)
                
                result_one=[]

                for each in project_tags:
                    result_one.append({
                        "tag id":each.project_tag_id,
                        "project_tag_name":each.project_tag_name,
                        "project id": each.project_id
                    })
                temp["tags"]=result_one

                project_stakeholders=project_stakeholders_repo.get_project_stakeholders(client_id=client_id, user_id=user_id, project_id=data.project_id)
                result_two=[]
                for each in project_stakeholders:
                    result_two.append({
                        "project_stakeholder_id":each.project_stakeholder_id,
                        "stakeholder_type_id ":each.project_stakeholder_type,
                        "stakeholder_name":each.stakeholder_name,
                        "stakeholder_email ": each.stakeholder_email,
                        "stakeholder_role":each.stakeholder_role,
                        "project_id ":each.project_id

                    })
                temp["stakeholders"]=result_two

                project_files=project_files_repo.get_project_files(
                    client_id=client_id,
                    user_id=user_id,
                    project_id=project_id
                )
                result_three=[]
                
                for each in project_files:
                        result_three.append({
                            "project_id":each.project_id,
                            "file_type_id":each.file_type_id,
                            "project_pic file_location":blobmanager_repo.generate_sas_token(each.project_files) if each.project_files else '',
                        })
                temp["project_files"]=result_three

                result.append(temp)

                return JSONResponse(status_code=200,content={"details":result})
            else:
                return JSONResponse(status_code=404,content={"detail": "details not found"})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500,content={"detail": str(e)})

@router.get("/get_project_type")
def get_project_type_details(client_id:int, user_id:int, db:Session = Depends(get_db)):
    try:
        repo=project_type_Repository(db)
        new_project_type=repo.get_project_type(
            client_id=client_id,
            user_id=user_id
        )
        result=[]
        for each in new_project_type:
            result.append({
                "project type" : each.project_type_name,
                "project_type_id":each.project_type_id

            })
        return JSONResponse(status_code=200,content={"details":result})
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})
    
@router.get("/get_project_category")
def get_project_category_details(client_id:int, user_id:int, db:Session = Depends(get_db)):
    try:
        repo=project_category_Repository(db)
        new_project_category=repo.get_project_category(
            client_id=client_id,
            user_id=user_id
        )
        result=[]
        for each in new_project_category:
            result.append({
                "project category" : each.project_category_name,
                "project_category_id":each.project_category_id
            })
        return result
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})

@router.get("/get_project_business_domain")
def get_project_business_domain_details(client_id:int, user_id:int, db:Session = Depends(get_db)):
    try:
        repo=project_business_domain_Repository(db)
        new_project_businees_domain=repo.get_project_business_domain(
            client_id=client_id,
            user_id=user_id
        )
        result=[]
        for each in new_project_businees_domain:
            result.append({
                "project business domain name" : each.project_business_domain_name,
                "project_business_domain_id":each.project_business_domain_id
            })
        return result
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})

@router.get("/export_project_data")
def get_export_project_data(client_id:int, user_id:int, db:Session = Depends(get_db)):
    try:
        projects_repo = Projects_Repository(db)
        project_type_repo=project_type_Repository(db)
        project_category_repo=project_category_Repository(db)
        project_business_domain_repo=project_business_domain_Repository(db)
        projects_tags_repo=project_tags_Repository(db)
        project_stakeholders_repo=project_stakeholders_Repository(db)
        result=[]
        projects_data = projects_repo.export_project_data(
            client_id=client_id,
            user_id=user_id
        )
        if not projects_data:
            return JSONResponse(
                status_code=404,
                content={"detail": "No projects found"}
            )
        result = []
        for project in projects_data:
            project_type = project_type_repo.get(
                id_=project.project_type_id
            )
            category = project_category_repo.get(
                id_=project.project_category_id
            )
            business_domain = project_business_domain_repo.get(
                id_=project.project_business_domain_id
            )
            tags = projects_tags_repo.get_project_tags(
                client_id=client_id,
                user_id=user_id,
                project_id=project.project_id
            )
            stakeholders = project_stakeholders_repo.get_project_stakeholders(
                client_id=client_id,
                user_id=user_id,
                project_id=project.project_id
            )
            tag_names = ", ".join(
                [tag.project_tag_name for tag in tags]
            ) if tags else ""
            stakeholder_names = ", ".join(
                [stakeholder.stakeholder_name for stakeholder in stakeholders]
            ) if stakeholders else ""
            temp = {
                # "Project ID": project.project_id,
                "Project No": project.project_no,
                "Project Name": project.project_name,
                "Project Client": project.project_client,
                "Project Manager": project.project_manager,
                "Start Date": project.start_date.strftime("%Y-%m-%d")
                if project.start_date else "",
                "End Date": project.end_date.strftime("%Y-%m-%d")
                if project.end_date else "",
                "Budget": project.budget,
                "Description": project.description,
                "Status": project_fields.status[project.status_id] if project.status_id else " ",
                "Priority": project_fields.priority[project.priority_id] if project.priority_id else " ",
                "Permission ID": project.permission_id,
                "Project Type":
                    project_type.project_type_name
                    if project_type else "",
                "Category":
                    category.project_category_name
                    if category else "",
                "Business Domain":
                    business_domain.project_business_domain_name
                    if business_domain else "",
                "Tags": tag_names,
                "Stakeholders": stakeholder_names
            }
            result.append(temp)
        df = pd.DataFrame(result)
        file_name = "Project_info.xlsx"
        df.to_excel(
            file_name,
            index=False,
            engine="openpyxl"
        )
        wb = load_workbook(file_name)
        ws = wb.active

        # Make header row bold
        for cell in ws[1]:
            cell.font = Font(bold=True)

        wb.save(file_name)
        return FileResponse(
            path=file_name,
            filename="Project_info.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )

    ##...................._get_tasks_with_search_filters   (tasks_page)  .....................##

@router.get("/get_task")
def get_task_details(client_id:int, user_id:int, search:str = None, task_status:int = None, priority:int=None, page_size:int = None, offset:int = None, start_date:str = None, end_date:str = None, db:Session = Depends(get_db)):
    try:
        repo = TasksRepository(db)
        tasks_data, querytwo, total_tasks = repo.get_task_details(
            client_id=client_id,
            user_id=user_id,
            search=search,
            status=task_status,
            priority=priority,
            page_size=page_size,
            offset=offset,
            start_date=start_date,
            end_date=end_date
        )
        result= []
        for each in tasks_data:
            result.append({
                "project_id": each.project_id,
                "project_name": each.project_name,
                "task_id": each.task_id,
                "task_no": each.task_no,
                "task_name": each.task_name,
                "assignee": each.assignee,
                "module": each.module,
                "work_type": each.work_type,
                "priority": each.priority,
                "status": each.status,
                "start_date": each.start_date.strftime("%Y-%m-%d") if each.start_date else None,
                "end_date": each.end_date.strftime("%Y-%m-%d") if each.end_date else None,
                "Description": each.description,
                "notes":each.notes,
                "blockers":each.blockers
            }) 
        return JSONResponse(
            status_code=200,
            content={
                "total_tasks": total_tasks,
                "total_pending_tasks": querytwo.pending,
                "total_done_tasks": querytwo.inprogress,
                "total_tasks_inprogress": querytwo.todo,
                "total_todo_tasks": querytwo.completed,
                "total_testing_tasks": querytwo.backlog,
                "total_backlog":querytwo.testing,
                "result": result
            }
        )
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})

##...................._get_tasks_with_search_filters   (tasks_page)  .....................##
@router.get("/get_team") 
def get_team_details(client_id:int, user_id:int, search:str = None, page_size:int = None, status:int=None, offset:int = None, db:Session = Depends(get_db)):
    try:
        repo = TeamRepository(db)
        team_data,total_teams, querytwo=repo.get_team_details(
            client_id=client_id,
            user_id=user_id,
            status=status,
            search=search,
            page_size=page_size,
            offset=offset
        )
        result= []
        for each in team_data:
            result.append({
                 "team_id":each.team_id,
                 "team_name": each.team_name,
                 "team_key":each.team_key,
                 "team_type":each.team_type,
                 "team_dept":each.team_dept,
                 "team_lead":each.team_lead,
                 "status":each.status, 
                 "Description": each.description,
            })
        return JSONResponse(
            status_code=200,
            content={
                "total_teams": total_teams,
                "total_active":querytwo.active,
                "total_inactive":querytwo.inactive,
                "total_hold":querytwo.hold,
                "result": result
            })
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"detail": str(e)})


# @router.get("/get_project_status")
# def get_project_status_details(client_id:int, user_id:int, db:Session = Depends(get_db)):
#     try:
#         repo=project_status_Repository(db)
#         new_project_status=repo.get_project_status(
#             client_id=client_id,
#             user_id=user_id
#         )
#         if not new_project_status:
#             result_one=[]
#             for each in ["Draft","Pending approval","Approved","Active", "On hold", "Closed"]:
#                 repo.create(
#                     project_status_name=each,
#                     client_id=client_id,
#                     user_id=user_id
#                 )
#                 result_one.append({
#                     "project status" : each
#                 })
#             return result_one
#         if new_project_status:
#             result_two=[]
#             for each in new_project_status:
#                 result_two.append({
#                     "project status" : each.project_status_name 
#                 })
#             return result_two
#     except Exception as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=500, content={"detail": str(e)})
    
# @router.get("/get_project_priority")
# def get_project_priority_details(client_id:int, user_id:int, db:Session = Depends(get_db)):
#     try:
#         repo=project_priority_Repository(db)
#         new_project_priority=repo.get_project_priority(
#             client_id=client_id,
#             user_id=user_id
#         )
#         if not new_project_priority:
#             result_one=[]
#             for each in ["Low","Medium","High","Critical"]:
#                 repo.create(
#                     project_priority_name=each,cd env
#                     client_id=client_id,
#                     user_id=user_id
#                 )
#                 result_one.append({
#                     "project priority" : each
#                 })
#             return result_one
#         if new_project_priority:
#             result_two=[]
#             for each in new_project_priority:
#                 result_two.append({
#                     "project priority" : each.project_priority_name
#                 })
#             return JSONResponse(status_code=200, content={"detail":result_two})
#     except Exception as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=500, content={"detail": str(e)})

# @router.get("/get_project_tags")
# def get_project_tags_details(client_id:int, user_id:int, project_id:int ,db:Session = Depends(get_db)):
#     try:
#         repo=project_tags_Repository(db)
#         new_project_tags=repo.get_project_tags(
#             project_id=project_id,
#             client_id=client_id,
#             user_id=user_id
#         )
#         result=[]
#         for each in new_project_tags:
#             result.append({
#                 "project tag" : each.project_tag_name
#             })
#         return result
#     except Exception as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=500, content={"detail": str(e)})
    
# @router.get("/get_project_stakeholders")
# def get_project_stakeholders(client_id:int, user_id:int, project_id:int ,db:Session = Depends(get_db)):
#     try:
#         repo=project_stakeholders_Repository(db)
#         new_project_stakeholders=repo.get_project_stakeholders(
#             client_id=client_id,
#             user_id=user_id,
#             project_id=project_id
#         )
#         result=[]
#         for each in new_project_stakeholders:
#             result.append({
#                 "project stakeholder name" : each.stakeholder_name,
#                 "project stakeholder email" :each.stakeholder_email,
#                 "project stakeholder role ": each.stakeholder_role
#             })
#         return result
#     except Exception as e:
#         traceback.print_exc()
#         return JSONResponse(status_code=500, content={"detail": str(e)})  

@router.get('/get_all_lists_active_columns_list')                    
def get_all_invoice_columns_list(client_id:int,user_id:int,permission_id:int,db:Session=Depends(get_db)):
    try:
        columns_active_repo = ListsActiveColumnsRepository(db=db)
        data = columns_active_repo.get_list_by_user_id(client_id=client_id,user_id=user_id,permission_id=permission_id)
        performence_logger.debug('dataaa---%s',data)
        if data is not None:
            result =[{
                'list_column_id':data.list_column_id,
                'active_columns':json.loads(data.active_columns),
                'feild_value_id' :json.loads(data.feild_value_id) if data.feild_value_id is not None else []
            }]
            return JSONResponse(status_code=200,content={'detail':result})
        return JSONResponse(status_code=404,content={'detail':'No Data Found'})
    except Exception as e:
        traceback.print_exc()
        error_logger.error(f'Error at get_all_invoices_column_list------{e}')