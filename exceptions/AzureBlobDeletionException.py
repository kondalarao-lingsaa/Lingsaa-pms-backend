from starlette import status
from starlette.exceptions import HTTPException

# this exception is raised when azure blob deletion fails


class AzureBlobDeletionException(HTTPException):
    def __init__(self):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail="something went wrong when deleting blob in the azure container")
