from azure.storage.blob import BlobClient
from azure.core.exceptions import ResourceNotFoundError
from exceptions.AzureBlobUploadException import AzureBlobUploadException
from exceptions.AzureBlobDeletionException import AzureBlobDeletionException
import os

class AzureBlobManager:
    def __init__(self):
        """
        Uses a base container-level SAS URL from environment.
        Example: https://<account>.blob.core.windows.net/<container>?<sas_token>
        """
        self.base_sas_url = os.environ.get('sasurl')  # container-level SAS URL

        if not self.base_sas_url or '?' not in self.base_sas_url:
            raise ValueError("Invalid or missing SAS URL in environment")

        self.base_url, self.sas_token = self.base_sas_url.split('?', 1)

    def _build_blob_url(self, file_name: str) -> str:
        """
        Construct the full blob URL from base container URL and blob name.
        """
        return f"{self.base_url}/{file_name}?{self.sas_token}"

    def upload_file(self, location: str, file_name: str) -> bool:
        """
        Uploads a file from the given local path to Azure Blob Storage.
        """
        try:
            blob_url = self._build_blob_url(file_name)
            blob_client = BlobClient.from_blob_url(blob_url)
            with open(location, 'rb') as f:
                blob_client.upload_blob(f, overwrite=True)
        except Exception as e:
            print(e, "Exception at Azure blob upload")
            raise AzureBlobUploadException()
        return True

    def download_blob(self, file_name: str) -> bytes:
        """
        Downloads the specified blob and returns its content as bytes.
        """
        try:
            blob_url = self._build_blob_url(file_name)
            blob_client = BlobClient.from_blob_url(blob_url)
            blob_data = blob_client.download_blob()
            return blob_data.readall()
        except ResourceNotFoundError:
            print(f"Blob not found: {file_name}")
        except ValueError:
            print(f"Invalid URL or data for blob: {file_name}")
        except Exception as e:
            print(type(e))
            raise AzureBlobDeletionException()

    def delete_blob(self, file_name: str) -> None:
        """
        Deletes the specified blob from Azure Blob Storage.
        """
        try:
            blob_url = self._build_blob_url(file_name)
            blob_client = BlobClient.from_blob_url(blob_url)
            blob_client.delete_blob()
        except Exception as e:
            print(e)
            raise AzureBlobDeletionException()
        
    def generate_sas_token(self, blob_name):
        return f"{self.base_url}/{blob_name}?{self.sas_token}"