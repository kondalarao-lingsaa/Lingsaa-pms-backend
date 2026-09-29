from fastapi import UploadFile, File


def validate_if_file_is_none(file):
    if file is not None:
        return True
    return False
