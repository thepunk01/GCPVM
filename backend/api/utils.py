from sqlmodel import Session, select
from api.notification import send_email
from core.enums import OperationStatus, OperationType
from api.schema import ParentJob, engine, ChildJob
import time, logging, os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

sender = os.environ.get("SENDER")
password = os.environ.get("PASSWORD")

def child_retry(zone, job, gcloud, session: Session):
    """Retries the operation and logs the attempt in the database."""
    logging.info(f"Retrying {job.type} operation for ParentJob {job.id}")

    if job.type == OperationType.START:
        new_operation = gcloud.start_instance(zone, job.name)
    elif job.type == OperationType.STOP:
        new_operation = gcloud.stop_instance(zone, job.name)
    else:
        logging.error(f"Unknown operation type for {job.name}. Cannot retry.")
        return

    # Log retry attempt in the database
    child_job = ChildJob(parent_id=job.id,
        is_successful=False,
        request_time=datetime.fromisoformat(new_operation.timestamps.insertTime) if new_operation.timestamps.insertTime else None,
        start_time=datetime.fromisoformat(new_operation.timestamps.startTime) if new_operation.timestamps.startTime else None,
        end_time=datetime.fromisoformat(new_operation.timestamps.endTime) if new_operation.timestamps.endTime else None)

    session.add(child_job)
    session.commit()
    session.refresh(child_job)

    logging.info(f"Logged ChildJob {child_job.id} for retry of ParentJob {job.id}")

def check_operation_status(zone, gcloud, receiver, operation_name, job, no_of_retries=3):
    """Background task to monitor operation status, update the database, and trigger retries if needed."""
    session = Session(engine)
    retries = 0  

    try:
        while retries <= no_of_retries:
            operation_data = gcloud.get_operation_data(zone, operation_name)

            if operation_data.status in [OperationStatus.PENDING, OperationStatus.RUNNING]:
                logging.info(f" Waiting... Operation {operation_name} is currently in {operation_data.status}")
                time.sleep(3)

            elif operation_data.status == OperationStatus.DONE:
                print("CONFIRMED", operation_data.type)
                send_email(sender, receiver, operation_data.type, password)
                parentjob = session.exec(select(ParentJob).where((ParentJob.id == job.id) & (ParentJob.zone == zone))).first()
                if parentjob.type == operation_data.type:
                    parentjob.status = operation_data.status
                    parentjob.is_successful = True
                    session.commit()
                    session.refresh(parentjob)
                    logging.info(f"ParentJob {parentjob.id} completed successfully.")
                    break  # Exit loop if operation was successful and type matches
                else:
                    logging.warning(
                        f"ParentJob {parentjob.id} completed but has type `{operation_data.type}` instead of `{parentjob.type}`."
                        f" Triggering retry ({retries + 1}/{no_of_retries})...")

                    # Log a retry attempt as a new `ChildJob`
                    child_retry(zone, job, gcloud, session)
                    retries += 1  # Increment retries after triggering a retry
        logging.info(f"Operation status logged: {operation_data.name} - {operation_data.status} - {operation_data.type}")
    finally:
        session.close()  # Ensure the session is closed
