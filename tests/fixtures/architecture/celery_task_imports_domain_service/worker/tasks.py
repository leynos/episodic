"""Allowed Celery task fixture."""

from tests.fixtures.architecture.celery_task_imports_domain_service import service
from tests.fixtures.architecture.celery_task_imports_domain_service.worker import (
    workloads,
)

VALUE = (service.VALUE, workloads.VALUE)
