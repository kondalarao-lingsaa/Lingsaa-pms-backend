import os

from fastapi import UploadFile
import shutil
from os import path
from starlette import status
from starlette.responses import JSONResponse
from azure_service.AzureBlobManager import AzureBlobManager
from exceptions.FileUploadException import FileUploadException
import traceback


class FileUploader:
    def __init__(self, location, file_id):
        self.location = location
        self.file_id = file_id
        self.blob_manager = AzureBlobManager()

    def upload_file(self, file: UploadFile):
        try:
            if os.path.exists(self.location) is False:
                os.makedirs(self.location)
            file_location = path.join(self.location, file.filename)
            with open(f'{file_location}', 'wb') as buffer:
                shutil.copyfileobj(file.file, buffer)

            azure_result=self.blob_manager.upload_file(
                file_name=f"{self.file_id}/{file.filename}", location=file_location)
            try:
                if os.path.exists(file_location):
                    os.remove(file_location)
            except Exception as e:
                traceback.print_exc()
                print(e)
            return {
            "local_path": file_location,
            "azure_result": azure_result
        }
        except Exception as e:
            print('exc')
            raise FileUploadException(e)

    def delete_file(self, file: str):
        try:
            self.blob_manager.delete_blob(file_name=file)
        except Exception as e:
            # just log the basic error
            print(e)
            # raise e