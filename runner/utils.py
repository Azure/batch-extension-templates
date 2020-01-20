import azure.batch.models as batchmodels
import azure.storage.blob as azureblob
from msrest.exceptions import ClientRequestError as ClientRequestError
from urllib3.exceptions import MaxRetryError as UrlLibMaxRetryError
from requests.exceptions import ConnectionError as requests_ConnectionError
from azure.storage.blob.models import ContainerPermissions
from azure.keyvault import KeyVaultClient
import azext.batch as batch
from datetime import datetime, timezone, timedelta
import time
import os
from enum import Enum
import pytz
import logger
import threading
import custom_template_factory as ctm
import exceptions as ex
import traceback
import sys
import itertools
import random

utc = pytz.utc

"""
Utility module that holds the data objects and some useful methods
"""


class StorageInfo(object):
    """Data object to store the StorageInfo for the job's input and output containers"""

    def __init__(self, input_container, output_container, input_container_SAS, output_container_SAS):
        super(StorageInfo, self).__init__()
        # The attribute 'input_container' of type 'str'
        self.input_container = input_container
        # The attribute 'output_container' of type 'str'
        self.output_container = output_container
        # The attribute 'input_container_SAS' of type 'str'
        self.input_container_SAS = input_container_SAS
        # The attribute 'output_container_SAS' of type 'str'
        self.output_container_SAS = output_container_SAS

    def __str__(self) -> str:
        return "[input_container: {}, output_container:{}".format(
            self.input_container, self.output_container)


class ImageReference(object):
    """Data object for holding the imageReference data"""

    def __init__(self, osType, offer, version):
        super(ImageReference, self).__init__()
        self.osType = osType  # The attribute 'osType' of type 'str'
        self.offer = offer  # The attribute 'offer' of type 'str'
        self.version = version  # The attribute 'version' of type 'str'

    def __str__(self) -> str:
        return "osType: {}, offer: {}, version: {}".format(
            self.osType, self.offer, self.version)


class TestStatus(object):
    """The Test state and the error message"""

    def __init__(self, test_state, message):
        super(TestStatus, self).__init__()
        self.test_state = test_state
        self.message = message

    def __str__(self) -> str:
        return "Test's state: {}, message{}".format(
            self.test_state, self.message)


class TestState(Enum):
    NOT_STARTED = 1
    IN_PROGRESS = 2
    COMPLETE = 3
    POOL_FAILED = 4
    JOB_FAILED = 5
    TERMINAL_FAILURE = 6
    STOP_THREAD = 7
    TIMED_OUT = 8

timeout_delta_pool_resize = timedelta(minutes=15)
timeout_delta_node_idle = timedelta(minutes=15)
timeout_delta_job_complete = timedelta(minutes=15)

# The number of seconds given for the batch service to update state,
# e.g when we need to delay between disabling a job and patching it
service_state_transition_seconds = 30

output_fgrp_postfix = "-output"


def print_batch_exception(batch_exception: batchmodels.BatchErrorException):
    """
    Prints the contents of the specified Batch exception.

    :param batch_exception: The exception to convert into something readable
    :type batch_exception: batchmodels.batch_error.BatchErrorException
    """
    logger.error('Exception encountered:')
    if isinstance(batch_exception, str):
        logger.error('{}'.format(batch_exception))
    elif batch_exception.error \
            and batch_exception.error.message \
            and batch_exception.error.message.value:
        logger.error(batch_exception.error.message.value)
        if batch_exception.error.values:
            for mesg in batch_exception.error.values:
                logger.error('{}:\t{}'.format(mesg.key, mesg.value))
                logger.error('{}'.format(mesg.value))


def expected_exception(batch_exception: batchmodels.BatchErrorException, message: str) -> bool:
    """
    If the expected exception is hit we want to return True, this is to ignore the errors
    we do not care about.

    :param batch_exception: The batch error that we want to check
    :type batch_exception: batchmodels.batch_error.BatchErrorException
    :param message: expected message that we are expecting.
    :type message: str
    :return: If the expected exception is hit return a True.
    :rtype: bool
    """
    if batch_exception.error \
            and batch_exception.error.message \
            and batch_exception.error.message.value:
        if message in batch_exception.error.message.value:
            return True

    return False


def get_container_sas_token(block_blob_client: azureblob.BlockBlobService,
                            container_name: str, blob_permissions: ContainerPermissions) -> str:
    """
    Obtains a shared access signature granting the specified permissions to the
    container.

    :param block_blob_client: A blob service client.
    :type block_blob_client: `azure.storage.blob.BlockBlobService`
    :param container_name: The name of the Azure Blob storage container.
    :type container_name: str
    :param BlobPermissions blob_permissions:
    :type blob_permissions: azure.storage.blob.models.ContainerPermissions
    :return: A SAS token granting the specified permissions to the container.
    :rtype: str
    """
    # Obtain the SAS token for the container, setting the expiry time and
    # permissions. In this case, no start time is specified, so the shared
    # access signature becomes valid immediately.

    container_sas_token = \
        block_blob_client.generate_container_shared_access_signature(
            container_name,
            permission=blob_permissions,
            expiry=datetime.now(timezone.utc) + timedelta(hours=2))

    return container_sas_token


def upload_file_to_container(block_blob_client: azureblob.BlockBlobService, container_name: str, file_path: str):
    """
    Uploads a local file to an Azure Blob storage container.

    :param block_blob_client: A blob service client.
    :type block_blob_client: `azure.storage.blob.BlockBlobService`
    :param container_name: The name of the Azure Blob storage container.
    :type container_name: str
    :param str file_path: The local path to the file.
    :type file_path: str
    """
    blob_name = os.path.basename(file_path)

    logger.info(
        'Uploading file [{}] to container [{}]...'.format(
            file_path,
            container_name))

    block_blob_client.create_blob_from_path(container_name,
                                            blob_name,
                                            file_path)


def delete_pool(batch_service_client: batch.BatchExtensionsClient, pool_id: str):
    """Deletes a pool, if the pool has already been deleted or marked for deletion it logs and swallows the exception.
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param pool_id: Name of the pool to delete
    :type pool_id: str
    """
    logger.info("Deleting pool: {}".format(pool_id))
    try:
        run_with_jitter_retry(batch_service_client.pool.delete, pool_id)
    except batchmodels.BatchErrorException as batch_exception:
        if expected_exception(batch_exception, "The specified pool has been marked for deletion"):
            logger.warning(
                "The specified pool [{}] had already been marked for deletion when we went to delete ie.".format(pool_id))
        elif expected_exception(batch_exception, "The specified pool does not exist"):
            logger.warning(
                "The specified pool [{}] did not exist when we tried to delete it.".format(pool_id))
        else:
            traceback.print_exc()
            print_batch_exception(batch_exception)


def terminate_job(batch_service_client: batch.BatchExtensionsClient, job_id: str):
    """Terminates a pool, if the pool has already been completed, terminated or marked for termination it logs and swallows the exception.
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param job_id: The job to terminate
    :type job_id: str
    """
    try:
        run_with_jitter_retry(batch_service_client.job.terminate, job_id)

    except batchmodels.BatchErrorException as batch_exception:

        if expected_exception(batch_exception, "The specified job does not exist"):
            logger.info(
                "The specified Job [{}] did not exist when we tried to terminate it.".format(job_id))
            return
        if expected_exception(batch_exception, "The specified job is being terminated"):
            logger.info(
                "The specified Job [{}] was already being terminated when we tried to terminate it.".format(job_id))
            return
        if expected_exception(batch_exception, "The specified job is already in a completed state"):
            logger.info(
                "The specified Job [{}] was already in completed state when we tried to delete it.".format(job_id))
            return
        traceback.print_exc()
        print_batch_exception(batch_exception)


def delete_job(batch_service_client: batch.BatchExtensionsClient, job_id: str):
    """Deletes a job, if the job was not found or is already completed it logs and swallows the exception.
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param job_id: The job to delete
    :type job_id: str
    """
    try:
        run_with_jitter_retry(batch_service_client.job.delete, job_id)

    except batchmodels.BatchErrorException as batch_exception:

        if expected_exception(batch_exception, "The specified job does not exist"):
            logger.info(
                "The specified Job [{}] did not exist when we tried to delete it.".format(job_id))
            return

        if expected_exception(batch_exception, "The specified job is already in a completed state"):
            logger.info(
                "The specified Job [{}] was already in completed state when we tried to delete it.".format(job_id))
            return

        traceback.print_exc()
        print_batch_exception(batch_exception)

    except Exception as e:
        logger.info(
            "Exception thrown when deleting job [{}] - e".format(job_id, e))
        traceback.print_exc()


def terminate_and_delete_job(batch_service_client: batch.BatchExtensionsClient, job_id: str):
    """Terminates then deletes a job.
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param job_id: The job to terminate and delete
    :type job_id: str
    """
    terminate_job(batch_service_client, job_id)
    delete_job(batch_service_client, job_id)


def retarget_job_to_new_pool(batch_service_client: batch.BatchExtensionsClient, job_id: str, new_pool_id: str):
    """ Disables a job with task requeue, then patches it to target a new pool.
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param job_id: The job to retarget
    :type job_id: str
    :param new_pool_id: The id of the new pool
    :type new_pool_id: str
    """
    logger.info("Retargeting job [{}] to new pool [{}]".format(
        job_id, new_pool_id))

    try:

        batch_service_client.job.disable(job_id, "requeue")

    except batchmodels.BatchErrorException as batch_exception:
        # potential race condition where the nodes have gone idle and the job has 'Completed' between our internal 
        # node-idle-timeout check and the call to disable the job. Just return in this case 
        if expected_exception(batch_exception, "The specified job does not exist"):
            logger.info(
                "The specified Job [{}] did not exist when we tried to delete it.".format(job_id))
            raise ex.JobAlreadyCompleteException(job_id, "Job already complete and deleted.")

        if expected_exception(batch_exception, "The specified job is already in a completed state"):
            logger.info(
                "The specified Job [{}] was already in completed state when we tried to delete it.".format(job_id))
            raise ex.JobAlreadyCompleteException(job_id, "Job already complete.")

    # give the job time to move to disabled state before we try Patch it
    time.sleep(service_state_transition_seconds)

    looping_job_patch = True
    job_patch_retry_count = 0
    while looping_job_patch:
        try:
            batch_service_client.job.patch(job_id, batchmodels.JobPatchParameter(
                pool_info=batchmodels.PoolInformation(pool_id=new_pool_id)))
            looping_job_patch = False
        except batchmodels.BatchErrorException as batch_exception:
            if expected_exception(batch_exception, "The specified operation is not valid for the current state of the resource"):
                if job_patch_retry_count > 10:
                    logger.error(
                        "Exhausted retries and Failed to patch job [{}] due to the current state of the resource".format(job_id))
                    raise
                logger.info(
                    "Failed to patch job [{}] due to the current state of the resource, retrying....".format(job_id))
                time.sleep(5)
                job_patch_retry_count = job_patch_retry_count + 1

    logger.info("Successfully retargeted job [{}] to pool [{}]".format(
        job_id, new_pool_id))


def enable_job(batch_service_client: batch.BatchExtensionsClient, job_id: str):
    """Sets a job to 'enabled' state on Batch service
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param job_id: The job to enable
    :type job_id: str
    """
    batch_service_client.job.enable(job_id)
    logger.info("Successfully re-enabled job [{}]".format(job_id))


def does_task_output_file_exist(batch_service_client: batch.BatchExtensionsClient, job_id: str, expected_file_output_name: str, retry_count = 0) -> bool:
    """   Checks if a specified task output file was created by a task,
    
    :param batch_service_client: The batch client used for making batch operations
    :type batch_service_client: `azure.batch.BatchExtensionsClient`
    :param job_id: The job to check the task output file for
    :type job_id: str
    :param expected_file_output_name: The name of the expected output file
    :type expected_file_output_name: str
    :return: True if the task output file is found, otherwise false
    :rtype: bool
    """
    max_retries = 10

    tasks = batch_service_client.task.list(job_id)

    for task in tasks:
        all_files = batch_service_client.file.list_from_task(
            job_id, task.id, recursive=True)

        for f in all_files:
            if expected_file_output_name in f.name:
                logger.info("Job [{}] expected output matched {}".format(
                    job_id, expected_file_output_name))
                return True

    logger.warning("Did not find file {} in job {}".format(
        expected_file_output_name, job_id))

    if retry_count < max_retries:
        retry_count = retry_count + 1
        time.sleep(5)
        return does_task_output_file_exist(batch_service_client, job_id, expected_file_output_name, retry_count)

    logger.error("Error: Did not find output file {} in job {}".format(
        expected_file_output_name, job_id))
    return False


def cleanup_old_resources(blob_client: azureblob.BlockBlobService, batch_client: batch.BatchExtensionsClient, hours: int=1):
    """
    Delete any old resources from prior runs (storage containers, pools, jobs) older than "hours"

    :param blob_client: A blob service client.
    :type blob_client: `azure.storage.blob.BlockBlobService`
    :param batch_client: A batch service extensions client.
    :type batch_client: `azext.batch.BatchExtensionsClient`
    :param hours: Delete all resources older than this many hours
    :param int: 
    """
    # cleanup resources with last-modified before timeout
    timeout = datetime.now(timezone.utc) + timedelta(hours=-hours)

    try:
        pools = batch_client.pool.list()
        for pool in pools:
            if pool.last_modified < timeout:
                logger.info(
                    "Deleting pool {}, it is older than {} hours.".format(pool.id, hours))
                delete_pool(batch_client, pool.id)

        for job in batch_client.job.list():
            if job.last_modified < timeout:
                logger.info(
                    "Deleting job {}, it is older than {} hours.".format(job.id, hours))
                delete_job(batch_client, job.id)

        for container in blob_client.list_containers():
            if container.properties.last_modified < timeout:
                # don't delete output filegroups as we might need them for
                # diagnosis
                if 'fgrp' in container.name and not container.name.endswith(output_fgrp_postfix):
                    logger.info("Deleting container {}, it is older than {} hours.".format(
                        container.name, hours))
                    blob_client.delete_container(container.name)

    except Exception as e:
        logger.error(
            "Failed to clean up resources due to the error: {}".format(e))
        raise e


def check_for_pool_resize_error(pool_id: str, pool: str) -> bool:
    """
    Returns true if pool is in steady state with no pool resize errors. 
    Otherwise returns false.

    :param pool_id: The pool id.
    :type str:
    :param pool: The pool object.
    :type str:
    """
    if pool.allocation_state.value == "steady" and pool.resize_errors is not None:
        logger.warning("POOL {} FAILED TO ALLOCATE".format(pool_id))
        return True
    return False


def start_test_threads(method_name: str, test_managers: 'list[test_manager.TestManager]', *args) -> 'List[threading.thread]':
    """
    Executes the specified test manager methods in parallel and returns the list of threads.

    :param method_name: The test_managers method to be called
    :type method_name: str
    :param test_managers: a collection of tests for which to execute method_name 
    :type  test_managers: List[test_managers.TestManager]
    :param args: the arguments the method needs to run 
    """
    threads = []  # type: List[threading.Thread]

    for j in test_managers:
        thread = threading.Thread(target=getattr(j, method_name), args=args)
        threads.append(thread)
        thread.start()

    return threads


def update_params_with_values_from_keyvault(parameters: dict(), keyvault_client_with_url: tuple()):
    """
    Replaces parameters with keyvault placeholder values with the actual value fetched from keyvault.
    e.g. for Corona renderer we store the password used for the fairSaas login in keyVault

    :param parameters: The parameters file as dictionary, values are wrapped as {"value": "<inner_value>"}
    :type parameters:  dict(str, str)
    :param keyvault_client_with_url: Tuple holding the client for the keyVault along with the keyVault URL the client 
        is to be used with
    :type  keyvault_client_with_url: tuple(KeyVaultClient, str)
    """
    _keyVault_param_identifier = "KEYVAULT_"

    for parameter, value in parameters.items():
        # substring the inner_value from format {"value": "<inner_value>"}
        inner_value = str(value)[11:-2]
        if len(inner_value) > 0 and inner_value.startswith(_keyVault_param_identifier):

            logger.info("Replacing keyVault parameter {}".format(inner_value))
            if keyvault_client_with_url[0] == None:
                logger.error(
                    "No keyVault client is available, but keyVault parameter was specified: {}".format(inner_value))
                continue

            # substring the original value without the keyvault identifier
            # prefix
            secret_id = inner_value[len(_keyVault_param_identifier):]
            secret_bundle = keyvault_client_with_url[0].get_secret(
                keyvault_client_with_url[1], secret_id, '')

            # update the value in the parameters dict with the secret value
            # returned from keyVault
            parameters[parameter] = secret_bundle.value


def submit_job(batch_service_client: batch.BatchExtensionsClient, template: str, parameters: str, raw_job_id: str):
    """Constructs job json by combining template and parameters then submits the job to the batch service
    
    :param batch_service_client: A batch service extensions client.
    :type batch_service_client: batch.BatchExtensionsClient
    :param template: The job template loaded in form of a str
    :type template: str
    :param parameters: The parameters for the job template
    :type parameters: str
    :param raw_job_id: The job id as specified in the original template
    :type raw_job_id: str
    """
    try:
        job_json = batch_service_client.job.expand_template(
            template, parameters)
        job_parameters = batch_service_client.job.jobparameter_from_json(
            job_json)
        run_with_jitter_retry(batch_service_client.job.add, job_parameters)
    except batchmodels.BatchErrorException as err:
        logger.error(
            "Failed to submit job\n{}\n with params\n{}".format(
                template, parameters))
        traceback.print_exc()
        print_batch_exception("Error: {}".format(err))
        raise
    except batch.errors.MissingParameterValue as mpv:
        logger.error(
            "Job {}, failed to submit, because of the error: {}".format(raw_job_id, mpv))
        raise
    except:
        logger.error("Job {}, failed to submit, because of the error: {}".format(
            raw_job_id, sys.exc_info()[0]))
        raise


def wait_for_steady_nodes(batch_service_client: batch.BatchExtensionsClient, pool_id: str, min_required_vms: int, test_timeout: datetime, stop_thread):
    """Waits for a pool to go to steady state and then for the nodes to go to idle
    
    :param batch_service_client: A batch service extensions client.
    :type batch_service_client: batch.BatchExtensionsClient
    :param pool_id: ID of the pool to wait for steady nodes in
    :type pool_id: str
    :param min_required_vms: The min number of VM's required steady in order to run the test.
    :type min_required_vms: int
    :param test_timeout: Datetime at which to fail the test and run cleanup.
    :type test_timeout: datetime
    :param stop_thread: Lambda method which returns a bool when we want to trigger the test to immediately fail and perform cleanup.
    :type stop_thread: Func['bool']
    """
    try:
        wait_for_pool_resize_operation(
            batch_service_client, pool_id, test_timeout, stop_thread)

    except (ex.PoolResizeFailedException):
        # double the node count and try again
        pool = batch_service_client.pool.get(pool_id)
        new_node_count = pool.target_low_priority_nodes * 2
        logger.info("Resizing pool [{}] to '{}' nodes".format(
            pool_id, new_node_count))
        batch_service_client.pool.resize(pool_id, batchmodels.PoolResizeParameter(
            target_low_priority_nodes=new_node_count))
        # if exception thrown again here, will bubble up
        wait_for_pool_resize_operation(
            batch_service_client, pool_id, test_timeout, stop_thread)

    pool = batch_service_client.pool.get(pool_id)
    max_allowed_failed_nodes = pool.target_low_priority_nodes - min_required_vms

    wait_for_enough_idle_vms(batch_service_client, pool_id, min_required_vms,
                             max_allowed_failed_nodes, pool.state_transition_time, test_timeout, stop_thread)


def wait_for_pool_resize_operation(batch_service_client: batch.BatchExtensionsClient, pool_id: str, test_timeout: datetime, stop_thread) -> bool:
    """ Waits for a pool resize operation to complete and pool allocation state to go to steady.
    Raises a retryable exception on resize errors.
    
    :param batch_service_client: A batch service extensions client.
    :type batch_service_client: batch.BatchExtensionsClient
    :param pool_id: ID of the pool to wait to resize
    :type pool_id: str
    :param test_timeout: Datetime at which to fail the test and run cleanup.
    :type test_timeout: datetime
    :param stop_thread: Lambda method which returns a bool when we want to trigger the test to immediately fail and perform cleanup.
    :type stop_thread: Func['bool']
    :raises ex.PoolResizeFailedException: When the pool resize timed out
    :raises ex.PoolResizeFailedException: When the pool resize failed with errors
    :rtype: bool
    """
    time.sleep(10)  # make sure pool has time to change out of steady state
    pool = batch_service_client.pool.get(pool_id)
    timeout_pool_resize = pool.creation_time + timeout_delta_pool_resize

    while pool.allocation_state.value == "resizing":
        check_test_timeout(test_timeout)
        check_stop_thread(stop_thread)

        if has_timedout(timeout_pool_resize):
            raise ex.PoolResizeFailedException(
                pool_id, "Timed out waiting for resize of pool.")

        time.sleep(10)
        pool = batch_service_client.pool.get(pool_id)

    if pool.allocation_state.value == "steady" and pool.resize_errors is not None:
        exception_message = " {} Resize Errors: ".format(
            len(pool.resize_errors))
        for error in pool.resize_errors:
            exception_message += "ErrorCode: {}. ErrorMessage: {}".format(
                error.code, error.message)
        raise ex.PoolResizeFailedException(pool_id, exception_message)


def wait_for_enough_idle_vms(batch_service_client: batch.BatchExtensionsClient, pool_id: str, min_required_vms: int, max_allowed_failed_nodes: int, pool_resize_time: datetime, test_timeout: datetime, stop_thread) -> bool:
    """ Waits for a minimum number of VM's in the pool to enter idle state. 
    Raising retryable or terminal exceptions if errors are encountered.
    
    :param batch_service_client: A batch service extensions client.
    :type batch_service_client: batch.BatchExtensionsClient
    :param pool_id: ID of the pool to wait for enough idle VMs
    :type pool_id: str
    :param min_required_vms: The min number of VM's required steady in order to run the test.
    :type min_required_vms: int
    :param max_allowed_failed_nodes: The maximum number of nodes which are allowed to fail and still run the test.
    :type max_allowed_failed_nodes: int
    :param pool_resize_time: The time at which the pool completed resizing.
    :type pool_resize_time: datetime
    :param test_timeout: Datetime at which to fail the test and run cleanup.
    :type test_timeout: datetime
    :param stop_thread: Lambda method which returns a bool when we want to trigger the test to immediately fail and perform cleanup.
    :type stop_thread: Func['bool']
    :raises ex.NodesFailedToStartException: when we timeout waiting for the VMs to go idle
    :raises ex.NodesFailedToStartException: when too many nodes fail to start
    :raises ex.TerminalTestException: when too many nodes fail to start due to non-retryable errors.
    """
    nodes = []
    idle_node_count = 0
    retryable_failed_node_count = 0
    terminal_failed_node_count = 0

    retryable_failure_node_states = [batchmodels.ComputeNodeState.unusable]
    terminal_failure_node_states = [
        batchmodels.ComputeNodeState.start_task_failed]

    # set the timeout for nodes to go idle following pool resize completing
    timeout_idle_vms = pool_resize_time + timeout_delta_node_idle

    while idle_node_count < min_required_vms:
        check_test_timeout(test_timeout)
        check_stop_thread(stop_thread)

        if has_timedout(timeout_idle_vms):
            raise ex.NodesFailedToStartException(
                pool_id, "Timed out waiting for nodes to go idle following resize")

        time.sleep(10)
        # Need to cast since compute_node.list returns a list wrapper
        nodes = list(batch_service_client.compute_node.list(pool_id))

        # if combined errors are more than allowed, throw either 1: a retryable exception (when some nodes failed with retryable errors)
        # or 2: a terminal exception (when all failures were non-retryable)
        terminal_failed_node_count = len([(i, n) for i, n in enumerate(
            nodes, 1) if n.state in terminal_failure_node_states])
        retryable_failed_node_count = len([(i, n) for i, n in enumerate(
            nodes, 1) if n.state in retryable_failure_node_states])
        if retryable_failed_node_count + terminal_failed_node_count > max_allowed_failed_nodes:

            exception_message = "Node failure errors: "
            for n in nodes:
                exception_message += "Node state: {} ".format(n.state)

            # if we have at least a single node in a non-terminal failure
            # state, raise a retryable error
            if retryable_failed_node_count:
                raise ex.NodesFailedToStartException(
                    pool_id, exception_message)

            # all failures were terminal, treat this as a test-terminal failure
            raise ex.TerminalTestException(
                "For pool [{}], too many nodes failed with terminal errors: {}".format(pool_id, exception_message))

        idle_node_count = len([(i, n) for i, n in enumerate(
            nodes, 1) if n.state == batchmodels.ComputeNodeState.idle])


def wait_for_job_and_check_result(batch_service_client: batch.BatchExtensionsClient, job_id: str, expected_output: str, test_timeout: datetime, stop_thread):
    """  Waits for all tasks in a job to enter TaskState.completed, then checks all expected task outputs are present in storage before returning.
    Any tasks which fail throw an exception immediately.
    
    :param batch_service_client: A batch service extensions client.
    :type batch_service_client: batch.BatchExtensionsClient
    :param job_id: The job to monitor
    :type job_id: str
    :param expected_output: The expected output file for tasks in the job
    :type expected_output: str
    :param test_timeout: Datetime at which to fail the test and run cleanup.
    :type test_timeout: datetime
    :param stop_thread: Lambda method which returns a bool when we want to trigger the test to immediately fail and perform cleanup.
    :type stop_thread: Func['bool']
    :raises ex.JobTimedoutException: when we timed out waiting for the job to complete
    :raises ex.JobFailedException: when tasks in the job fail
    :raises ex.JobFailedException: when one or more task output files could not be located
    """
    timeout_jobs_tasks_complete = datetime.now(
        timezone.utc) + timeout_delta_job_complete

    # Wait for all tasks in the job to be in a terminal state
    job_has_completed = False
    while not job_has_completed:
        check_test_timeout(test_timeout)
        check_stop_thread(stop_thread)

        if has_timedout(timeout_jobs_tasks_complete):
            raise ex.JobTimedoutException(
                job_id, "Timed out waiting for job to complete.")

        tasks = batch_service_client.task.list(job_id)

        incomplete_tasks = [
            task for task in tasks if task.state != batchmodels.TaskState.completed]

        failed_tasks = [
            task for task in tasks if task.execution_info.failure_info]

        if failed_tasks:
            exception_message = " {} Task failure Errors: ".format(
                len(failed_tasks))
            for failed_task in failed_tasks:
                exception_message += "ErrorCode: {}. ErrorMessage: {}".format(
                    failed_task.execution_info.failure_info.code, failed_task.execution_info.failure_info.message)
            raise ex.JobFailedException(job_id, exception_message)

        if not incomplete_tasks:
            job_has_completed = True
            if not does_task_output_file_exist(batch_service_client, job_id, expected_output):
                raise ex.JobFailedException(
                    job_id, "Failed to find output {}".format(expected_output))
        else:
            logger.info("Job [{}] is running".format(job_id))
            time.sleep(5)


def timedelta_since(start_time: datetime):
    """Returns the timedelta between utcnow and start_time
    
    :param start_time: The time to calculate the timedelta since
    :type start_time: datetime
    :return: The timedelta between now and start_time
    :rtype: datetime.timedelta
    """
    return datetime.now(timezone.utc) - start_time


def run_with_jitter_retry(method, *args, retry_count=0):
    """Recursively retries a webservice call with a retry timing jitter between 0.1 - 1 second when the call fails with 503 or 'connection forcibly closed'

    This was found necessary when running job and pool submission to batch service naively multithreaded across 'n' threads where 'n' equals the number of tests, (should probably use threadpool if revisiting this).
    Jitter is to desync multiple failures so they aren't all retried at identical times and the batch FE's drop the connection again.
    
    :param method: The method to run with jitter retry
    :type method: Func<>
    :param retry_count: The current retry count, incremented for each recursive call, defaults to 0
    :type retry_count: int, optional
    """
    max_retry_count = 10
    try:
        method(*args)
    except UrlLibMaxRetryError as e:
        if ('too many 503 error' in e.message) and retry_count < max_retry_count:
            logger.info(
                "Retrying call due to 503 received from service - retryCount: {} of {}".format(retry_count, max_retry_count))
            time.sleep(random.uniform(0.1, 1))  # jitter the next request a bit
            run_with_jitter_retry(method, args, retry_count + 1)
        raise
    except requests_ConnectionError as e:
        if ('Connection aborted.' in e.message or 'An existing connection was forcibly closed by the remote host' in e.message) and retry_count < max_retry_count:
            logger.info(
                "Retrying call as connection forcibly closed by remote host - retryCount: {} of {}".format(retry_count, max_retry_count))
            time.sleep(random.uniform(0.1, 1))  # jitter the next request a bit
            run_with_jitter_retry(method, args, retry_count + 1)
        raise


def wait_for_threads_to_finish(threads: 'List[threading.thread]'):
    """Polls and waits until all threads in a list are no longer alive
    
    :param threads: The threads to wait for.
    :type threads: List[threading.thread]
    """
    waiting = True
    while waiting:
        waiting = False
        for thread in threads:
            if thread.isAlive():
                logger.info("Waiting for thread '{}' to complete".format(thread.ident))
                waiting = True
                thread.join(1)


def has_timedout(timeout: datetime) -> bool:
    """Checks if a timeout has been reached (timeout in the past)
    
    :param timeout: The timeout to check
    :type timeout: datetime
    :return: True if timeout is in the past, False if it is still yet to come
    :rtype: bool
    """
    return datetime.now(timezone.utc) > timeout


def check_test_timeout(timeout: datetime) -> bool:
    """Checks if the test timeout has been reached and raises TestTimedOutException if it has.
    
    :param timeout: The test timeout 
    :type timeout: datetime
    :raises ex.TestTimedOutException: when the test timeout is in the past
    """
    if datetime.now(timezone.utc) > timeout:
        raise ex.TestTimedOutException("Raising TestTimedOutException.")


def check_stop_thread(stop_thread):
    """Checks if the stop_thread lambda has been set (is returning true) by calling it
    
    :param stop_thread: Function set by main thread to trigger sub threads to perform cleanup and return.
    :type stop_thread: Func['bool']
    :raises ex.StopThreadException: If stop_thread() returns true
    """
    if stop_thread():
        raise ex.StopThreadException("Raising StopThreadException.")
