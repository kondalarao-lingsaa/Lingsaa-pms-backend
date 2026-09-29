from starlette import status
from starlette.exceptions import HTTPException


class FileUploadException(HTTPException):
    def __init__(self,message) -> None:
        super().__init__(status_code=403, detail=f"file upload failed{message}")
