from azure.storage.blob.models import ContainerPermissions
from pathlib import Path
import azext.batch as batch
import azure.storage.blob as azureblob
import azure.batch.models as batchmodels
import traceback
import itertools
import utils
import os
from datetime import datetime, timezone, timedelta
import time
import custom_template_factory as ctm
import logger
import exceptions as ex
import threading
import _thread

"""
This module is responsible for creating, submitting and monitoring the pools and jobs

"""
class TestManager(object):

    def __init__(self, template_file: str, pool_template_file: str,
                 parameters_file: str, keyvault_client_with_url: tuple, expected_output: str, application_licenses: str = None, repository_branch_name: str = None, run_unique_id: str = None):
        super(TestManager, self).__init__()
        self.raw_job_id = ctm.get_job_id(parameters_file)  # The attribute 'raw_job_id' of type 'str'
        self.run_id = "{}-{}".format(repository_branch_name[:7], run_unique_id) # identifier for this run to append to job and pools and prevent collisions with parallel builds - for PR builds this is the git short sha, otherwise "master"
        self.job_id = self.run_id + "-" + self.raw_job_id  # The attribute 'job_id' of type 'str'
        self.pool_id = self.job_id                        # The attribute 'pool_id' of type 'str'
        self.template_file = template_file  # The attribute 'template_file' of type 'str'
        self.parameters_file = parameters_file  # The attribute 'parameters_file' of type 'str '
        self.keyvault_client_with_url = keyvault_client_with_url  # The attribute 'keyvault_client_with_url' of type 'tuple'
        self.application_licenses = application_licenses  # The attribute 'application_licenses' of type 'str'
        self.repository_branch_name = repository_branch_name # The attribute 'repository_branch_name' of type 'str'
        self.expected_output = expected_output  # The attribute 'expected_output' of type 'str'
        self.pool_template_file = pool_template_file  # The attribute 'pool_template_file' of type 'str'
        self.storage_info = None  # The attribute 'storage_info' of type 'utils.StorageInfo'
        self.status = utils.TestStatus(utils.TestState.NOT_STARTED, "Test hasn't started yet.")  # The attribute 'status' of type 'utils.JobState'
        self.total_duration = None  # The attribute 'duration' of type 'timedelta'
        self.pool_start_duration = None  # The attribute 'pool_start_duration' of type 'timedelta'
        self.job_run_duration = None # The attribute 'pool_start_duration' of type 'timedelta'
        self.min_required_vms = int(ctm.get_dedicated_vm_count(parameters_file)) # the minimum number of nodes which the test job needs in order to run
        self.start_time = datetime.now(timezone.utc)

    def __str__(self) -> str:
        return "job_id: [{}] pool_id: [{}] ".format(self.job_id, self.pool_id)

    def run_test(self, 
        blob_client: azureblob.BlockBlobService, 
        batch_service_client: batch.BatchExtensionsClient, 
        image_references: 'List[utils.ImageReference]', 
        interrupt_main_on_failure: bool, #should this test raise thread.interrupt_main() if it fails
        timeout: int,
        stop_thread, 
        VM_image_URL=None, 
        VM_OS_type=None):

        self.status = utils.TestStatus(utils.TestState.IN_PROGRESS, "Test starting for {}".format(self.job_id))
        
        test_timeout = datetime.now(timezone.utc) + timedelta(minutes=timeout)

        self.upload_assets(blob_client)
        self.create_and_submit_pool(batch_service_client, image_references, VM_image_URL, VM_OS_type)
        self.create_and_submit_job(batch_service_client)

        try:
            self.monitor_pool_and_retry_if_needed(batch_service_client, image_references, test_timeout, stop_thread, VM_image_URL, VM_OS_type)

            self.monitor_job_and_retry_if_needed(batch_service_client, test_timeout, stop_thread)

            self.on_test_completed_successfully(batch_service_client, blob_client)

        except (ex.PoolResizeFailedException, ex.NodesFailedToStartException) as e:
            self.status = utils.TestStatus(utils.TestState.POOL_FAILED, e)
            self.on_test_failed(batch_service_client, blob_client, interrupt_main_on_failure)

        except (ex.JobFailedException, ex.JobTimedoutException) as e:
            self.status = utils.TestStatus(utils.TestState.JOB_FAILED, e)
            self.on_test_failed(batch_service_client, blob_client, interrupt_main_on_failure)

        except ex.TestTimedOutException as e:
            self.status = utils.TestStatus(utils.TestState.TIMED_OUT, e)
            self.on_test_failed(batch_service_client, blob_client, interrupt_main_on_failure)

        except ex.StopThreadException as e:
            self.status = utils.TestStatus(utils.TestState.STOP_THREAD, e)
            self.on_test_failed(batch_service_client, blob_client, False)

        except (Exception, ex.TerminalTestException) as e:
            logger.error("TerminalException thrown for job id: [{}]. Exception: {} - '{}'. StackTrace '{}'."
                .format(self.job_id, e.__class__.__name__, e,  traceback.format_exc()))

            self.status = utils.TestStatus(utils.TestState.TERMINAL_FAILURE, e)
            self.on_test_failed(batch_service_client, blob_client, interrupt_main_on_failure)

    def monitor_pool_and_retry_if_needed(self, batch_service_client: batch.BatchExtensionsClient, image_references: 'List[utils.ImageReference]', test_timeout: datetime, stop_thread, VM_image_URL, VM_OS_type):
        try:
            utils.wait_for_steady_nodes(batch_service_client, self.pool_id, self.min_required_vms, test_timeout, stop_thread)
            self.pool_start_duration = utils.timedelta_since(self.start_time)

        except (ex.PoolResizeFailedException, ex.NodesFailedToStartException):
            #pool failed to get enough nodes to idle from both initial allocation and any secondary pool resize too - try create a whole new pool and change job to target it
            utils.delete_pool(batch_service_client, self.pool_id)
            self.pool_id = self.pool_id + "-retry"

            self.create_and_submit_pool(batch_service_client, image_references, VM_image_URL, VM_OS_type)
            utils.retarget_job_to_new_pool(batch_service_client, self.job_id, self.pool_id)

            utils.wait_for_steady_nodes(batch_service_client, self.pool_id, self.min_required_vms, test_timeout, stop_thread)
            self.pool_start_duration = utils.timedelta_since(self.start_time)

    def monitor_job_and_retry_if_needed(self, batch_service_client: batch.BatchExtensionsClient, test_timeout: datetime, stop_thread):
        try:
            utils.wait_for_job_and_check_result(batch_service_client, self.job_id, self.expected_output, test_timeout, stop_thread)
            self.job_run_duration = datetime.now(timezone.utc) - (self.start_time + self.pool_start_duration)

        except (ex.JobFailedException, ex.JobTimedoutException):
            failed_job_id = self.job_id
            utils.terminate_and_delete_job(batch_service_client, failed_job_id)

            self.job_id = self.job_id + "-retry"
            self.create_and_submit_job(batch_service_client)
            utils.wait_for_job_and_check_result(batch_service_client, self.job_id, self.expected_output, test_timeout, stop_thread)

    def on_test_failed(self, batch_service_client: batch.BatchExtensionsClient, blob_client: azureblob.BlockBlobService, interrupt_main: bool):
        logger.error("Test failed: {}".format(self.job_id))
        self.delete_resources(batch_service_client, blob_client, False)

        if interrupt_main:
            logger.error("Calling thread.interrupt_main for failed test with id [{}]".format(self.job_id))
            _thread.interrupt_main()

    def on_test_completed_successfully(self, batch_service_client: batch.BatchExtensionsClient, blob_client: azureblob.BlockBlobService):
        logger.info("Test Succeeded, Pool: {}, Job: {}".format(self.pool_id, self.job_id))

        self.total_duration = datetime.now(timezone.utc) - self.start_time
        
        self.delete_resources(batch_service_client, blob_client, False)
        self.status = utils.TestStatus(utils.TestState.COMPLETE, "Test completed successfully.")
        logger.info("Successful Test Cleanup Done. Pool: {}, Job: {}".format(self.pool_id, self.job_id))


    def create_and_submit_job(self, batch_client: batch.BatchExtensionsClient):
        """
        Creates the Job that will be submitted to the batch service

        :param batch_client: The batch client to use.
        :type batch_client: `azure.batch.BatchExtensionsClient`
        """
        logger.info('Creating Job [{}]... job will run on [{}]'.format(self.job_id, self.pool_id))

        # load the template and parameters file
        template = ctm.load_file(self.template_file)
        parameters = ctm.load_file(self.parameters_file)

        #updates any placeholder parameter values with the values from keyVault, if required
        utils.update_params_with_values_from_keyvault(parameters, self.keyvault_client_with_url)
        # overrides some of the parameters needed in the file, container SAS
        # tokens need to be generated for the container
        ctm.set_parameter_name(parameters, self.job_id)
        ctm.set_parameter_storage_info(parameters, self.storage_info)
        ctm.set_template_pool_id(parameters, self.pool_id)
        ctm.set_job_resource_file_urls_to_branch(template, self.repository_branch_name)

        # Submits the job
        utils.submit_job(batch_client, template, parameters, self.raw_job_id)

    def submit_pool(self, batch_service_client: batch.BatchExtensionsClient, template: str):
        """
        Submits a batch pool based on the template 

        :param batch_service_client: The batch client used for making batch operations
        :type batch_service_client: `azure.batch.BatchExtensionsClient`
        :param template: The in memory version of the template used to create a the job.
        :type template: str
        """
        parameters = ctm.load_file(self.parameters_file)
        
        #updates any placeholder parameter values with the values from keyVault, if required
        utils.update_params_with_values_from_keyvault(parameters, self.keyvault_client_with_url)
        pool_json = batch_service_client.pool.expand_template(template, parameters)
        ctm.set_template_pool_id(template, self.pool_id)
        pool = batch_service_client.pool.poolparameter_from_json(pool_json)
        logger.info('Creating pool [{}]...'.format(pool))
        try:
            utils.run_with_jitter_retry(batch_service_client.pool.add, pool)
        except batchmodels.BatchErrorException as err:
            if utils.expected_exception(
                    err, "The specified pool already exists"):
                logger.warning(
                    "Pool [{}] is already being created.".format(
                        self.pool_id))
            else:
                logger.info("Create pool error: {}".format(err))
                traceback.print_exc()
                utils.print_batch_exception(err)

    def create_and_submit_pool(self, batch_service_client: batch.BatchExtensionsClient,
                    image_references: 'List[utils.ImageReference]', VM_image_URL=None, VM_OS_type=None):
        """
        Creates the Pool that will be submitted to the batch service.

        :type batch_service_client: `azure.batch.BatchExtensionsClient`
        :param batch_service_client: The batch client used for making batch operations
        :type image_references: List['utils.ImageReference`]
        :param image_references: A list of image references that job can run
        :type VM_image_URL: str
        :param VM_image_URL: The resource link to an image inside your image repo. If this is resource link is provided
        the VMs will use the custom image you provided.
        :type VM_OS_type: str
        :param VM_OS_type: The custom image operating system type, this can be windows or centos. This is needed if you
        want to use a custom image.
        """

        # load the template file
        template = ctm.load_file(self.pool_template_file)

        # set extra license if needed
        if self.application_licenses is not None:
            template["pool"]["applicationLicenses"] = self.application_licenses.split(",")

        # Set rendering version
        ctm.set_image_reference(template, image_references)
        ctm.set_template_pool_id(template, self.pool_id)
        ctm.set_pool_resource_file_urls_to_branch(template, self.repository_branch_name)
        if VM_image_URL is not None:
            ctm.set_custom_image(template, VM_image_URL, VM_OS_type)

        all_pools = [p.id for p in batch_service_client.pool.list()]

        if self.pool_id not in all_pools:
            self.submit_pool(batch_service_client, template)
        else:
            logger.info('pool [{}] already exists'.format(self.pool_id))

    def upload_assets(self, blob_client: azureblob.BlockBlobService):
        """
        Uploads a the file specified in the json parameters file into a storage container 

        :param blob_client: A blob service client used for making blob operations.
        :type blob_client: `azure.storage.blob.BlockBlobService`
        """
        input_container_name = "fgrp-" + self.job_id
        output_container_name = "fgrp-" + self.job_id + utils.output_fgrp_postfix

        # Create input container
        blob_client.create_container(input_container_name, fail_on_exist=False)
        logger.info('creating a storage container: {}'.format(input_container_name))

        # Create output container
        blob_client.create_container(output_container_name, fail_on_exist=False)
        logger.info('creating a storage container: {}'.format(output_container_name))

        full_sas_url_input = 'https://{}.blob.core.windows.net/{}?{}'.format(
            blob_client.account_name,
            input_container_name,
            utils.get_container_sas_token(
                blob_client,
                input_container_name,
                ContainerPermissions.READ +
                ContainerPermissions.LIST))
        full_sas_url_output = 'https://{}.blob.core.windows.net/{}?{}'.format(
            blob_client.account_name,
            output_container_name,
            utils.get_container_sas_token(
                blob_client,
                output_container_name,
                ContainerPermissions.READ +
                ContainerPermissions.LIST +
                ContainerPermissions.WRITE))

        # Set the storage info for the container.
        self.storage_info = utils.StorageInfo(
            input_container_name,
            output_container_name,
            full_sas_url_input,
            full_sas_url_output)

        # Upload the asset file that will be rendered
        scenefile = ctm.get_scene_file(self.parameters_file)
        for file in os.listdir("Assets"):
            if scenefile == file:
                file_path = Path("Assets/" + file)
                utils.upload_file_to_container(blob_client, input_container_name, file_path)

    def delete_resources(self, batch_service_client: batch.BatchExtensionsClient, blob_client: azureblob.BlockBlobService, delete_storage_containers: bool):
        # delete the job
        utils.terminate_and_delete_job(batch_service_client, self.job_id)

        # delete the pool
        utils.delete_pool(batch_service_client, self.pool_id)

        if delete_storage_containers:
            logger.info('Deleting input container [{}]...'.format(self.storage_info.input_container))
            blob_client.delete_container(self.storage_info.input_container)

            logger.info('Deleting output container [{}]...'.format(self.storage_info.output_container))
            blob_client.delete_container(self.storage_info.output_container)
