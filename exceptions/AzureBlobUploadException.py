from starlette import status
from starlette.exceptions import HTTPException


class AzureBlobUploadException(HTTPException):
    def __init__(self):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="something went wrong when uploading files to blob")
