import json
import os
import re
import time
import uuid

import boto3
from six.moves import urllib

from ...common.batch import JobDefinition
from ...common.checksum import UploadedFileChecksummer
from ...common.checksum_event import UploadedFileChecksumEvent
from ...common.database_orm import DBSessionMaker, DbChecksum
from ...common.ingest_notifier import IngestNotifier
from ...common.logging import get_logger
from ...common.retry import retry_on_aws_too_many_requests
from ...common.upload_area import UploadArea
from ...common.upload_config import UploadConfig, UploadVersion

logger = get_logger(__name__)

KB = 1024
MB = KB * KB
GB = MB * KB

batch = boto3.client('batch')


class ChecksumDaemon:

    RECOGNIZED_S3_EVENTS = (
        'ObjectCreated:Put',
        'ObjectCreated:CompleteMultipartUpload',
        'ObjectCreated:Copy'
    )
    USE_BATCH_IF_FILE_LARGER_THAN = 10 * GB

    def __init__(self, context):
        self.request_id = context.aws_request_id
        logger.debug("Ahm ahliiivvve!")
        self.config = UploadConfig()
        self.upload_service_version = UploadVersion().upload_service_version
        logger.debug("UPLOAD_SERVICE_VERSION: {}".format(self.upload_service_version))
        self._read_environment()
        self.upload_area = None
        self.uploaded_file = None

    def _read_environment(self):
        self.deployment_stage = os.environ['DEPLOYMENT_STAGE']
        self.docker_image = os.environ['CSUM_DOCKER_IMAGE']
        self.ingest_amqp_server = os.environ['INGEST_AMQP_SERVER']
        self.api_host = os.environ["API_HOST"]

    def consume_event(self, event):
        for record in event['Records']:
            if record['eventName'] not in self.RECOGNIZED_S3_EVENTS:
                logger.warning(f"Unexpected event: {record['eventName']}")
                continue
            file_key = record['s3']['object']['key']
            self._find_file(file_key)
            checksum_status = self._find_checksum_status_of_event_newer_than_file_last_modified()
            if checksum_status:
                logger.debug("File already (being) checksummed and has not changed.")
                if checksum_status == "CHECKSUMMED":
                    # Only notify ingest if the file has been checksummed.
                    # If the checksum event is in progress, let the other process notify ingest.
                    self._notify_ingest()
            else:
                self._checksum_file()

    def _find_file(self, file_key):
        logger.debug(f"File: {file_key}")
        area_uuid = file_key.split('/')[0]
        filename = urllib.parse.unquote(file_key[len(area_uuid) + 1:])
        logger.debug(f"File: {file_key}")
        logger.info({"request_id": self.request_id, "area_uuid": area_uuid,
                    "file_name": filename, "file_key": file_key, "type": "correlation"})
        self.upload_area = UploadArea(area_uuid)
        self.uploaded_file = self.upload_area.uploaded_file(filename)

    def _checksum_file(self):
        if self.uploaded_file.size > self.USE_BATCH_IF_FILE_LARGER_THAN:
            logger.debug("Scheduling checksumming batch job")
            self._schedule_checksumming()
        else:
            self._checksum_file_now()

    def _notify_ingest(self):
        self._check_content_type()
        file_info = self.uploaded_file.info()
        status = IngestNotifier('file_uploaded').format_and_send_notification(file_info)
        logger.info(f"Notified Ingest: file_info={file_info}, status={status}")

    CHECK_CONTENT_TYPE_INTERVAL = 6
    CHECK_CONTENT_TYPE_TIMES = 5

    """
    If the file's content_type doesn't have a 'dcp-type' suffix, refresh it a few times
    to see if it acquires one.  Due to AWSCLI/S3 failing to correctly apply content_type,
    we occasionally have to add it after the fact.  If it doesn't appear, proceed anyway.
    """
    def _check_content_type(self):
        naps_left = self.CHECK_CONTENT_TYPE_TIMES
        while naps_left > 0 and '; dcp-type=' not in self.uploaded_file.content_type:
            logger.debug(f"No dcp-type in content_type of file {self.uploaded_file.s3_key},"
                         f" checking {naps_left} more times")
            time.sleep(self.CHECK_CONTENT_TYPE_INTERVAL)
            naps_left -= 1
            self.uploaded_file.refresh()
        if '; dcp-type=' not in self.uploaded_file.content_type:
            logger.warning(f"Still no dcp-type in content_type of file {self.uploaded_file.s3_key} after 30s")

    def _find_checksum_status_of_event_newer_than_file_last_modified(self):
        checksum_status = None
        db_session = DBSessionMaker().session()
        checksums = db_session.query(DbChecksum).filter(DbChecksum.file_id == self.uploaded_file.db_id).all()
        for csum in checksums:
            if csum.status == "CHECKSUMMED" and csum.updated_at >= self.uploaded_file.s3_last_modified:
                logger.debug(f"Found a completed checksum ({csum.id}) which is newer ({csum.updated_at}) than "
                             f"the file data ({self.uploaded_file.s3_last_modified})")
                checksum_status = "CHECKSUMMED"
            elif csum.status == "CHECKSUMMING" and csum.updated_at >= self.uploaded_file.s3_last_modified:
                logger.debug(f"Found an in progress checksum event ({csum.id}) which is newer ({csum.updated_at}) than "
                             f"the file data ({self.uploaded_file.s3_last_modified})")
                checksum_status = "CHECKSUMMING"
        return checksum_status

    def _checksum_file_now(self):
        checksum_event = UploadedFileChecksumEvent(checksum_id=str(uuid.uuid4()),
                                                   file_id=self.uploaded_file.db_id,
                                                   status="CHECKSUMMING")
        checksum_event.create_record()

        checksummer = UploadedFileChecksummer(self.uploaded_file)
        checksums = checksummer.checksum(report_progress=True)

        self.uploaded_file.checksums = checksums
        tags = self.uploaded_file.apply_tags_to_s3_object()

        checksum_event.status = "CHECKSUMMED"
        checksum_event.checksums = checksums
        checksum_event.update_record()

        logger.info(f"Checksummed and tagged with: {tags}")
        self._notify_ingest()

    def _schedule_checksumming(self):
        checksum_id = str(uuid.uuid4())
        command = ['python', '/checksummer.py', self.uploaded_file.s3url]
        environment = {
            'BUCKET_NAME': self.config.bucket_name,
            'DEPLOYMENT_STAGE': self.deployment_stage,
            'INGEST_AMQP_SERVER': self.ingest_amqp_server,
            'API_HOST': self.api_host,
            'CHECKSUM_ID': checksum_id,
            'CONTAINER': 'DOCKER'
        }
        job_name = "-".join([
            "csum", self.deployment_stage, self.uploaded_file.upload_area.uuid, self.uploaded_file.name])
        job_id = self._enqueue_batch_job(queue_arn=self.config.csum_job_q_arn,
                                         job_name=job_name,
                                         job_defn=self._find_or_create_job_definition(),
                                         command=command,
                                         environment=environment)
        checksum_event = UploadedFileChecksumEvent(file_id=self.uploaded_file.db_id,
                                                   checksum_id=checksum_id,
                                                   job_id=job_id,
                                                   status="SCHEDULED")
        checksum_event.create_record()

    def _find_or_create_job_definition(self):
        job_defn = JobDefinition(docker_image=self.docker_image, deployment=self.deployment_stage)
        job_defn.find_or_create(self.config.csum_job_role_arn)
        return job_defn

    JOB_NAME_ALLOWABLE_CHARS = '[^\w-]'

    @retry_on_aws_too_many_requests
    def _enqueue_batch_job(self, queue_arn, job_name, job_defn, command, environment):
        job_name = re.sub(self.JOB_NAME_ALLOWABLE_CHARS, "", job_name)[0:128]
        job = batch.submit_job(
            jobName=job_name,
            jobQueue=queue_arn,
            jobDefinition=job_defn.arn,
            containerOverrides={
                'command': command,
                'environment': [dict(name=k, value=v) for k, v in environment.items()]
            }
        )
        logger.info(f"Enqueued job {job_name} [{job['jobId']}] using job definition {job_defn.arn}:")
        logger.info(json.dumps(job))
        return job['jobId']
