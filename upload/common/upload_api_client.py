from urllib.parse import urljoin
import requests
from .logging import get_logger
import json
import os
import pdb

logger = get_logger(__name__)

url = os.environ["API_HOST"]
api_version = "v1"
header = {'Content-type': 'application/json'}


def update_event(event, file_payload, client=requests):
    event_type = type(event).__name__
    if event_type == "UploadedFileValidationEvent":
        action = 'update_validation'
    elif event_type == "UploadedFileChecksumEvent":
        action = 'update_checksum'

    data = {"status": event.status,
            "job_id": event.job_id,
            "payload": file_payload
            }
    upload_area_id = file_payload["upload_area_id"]
    event_id = event.id
    api_url = f"http://{url}/{api_version}/area/{upload_area_id}/{action}/{event_id}"
    response = client.post(api_url, headers=header, data=json.dumps(data))
    return response
