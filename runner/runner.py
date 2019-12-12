from __future__ import print_function
from azure.common.credentials import ServicePrincipalCredentials
from azure.keyvault import KeyVaultClient
import traceback
from datetime import datetime, timezone, timedelta
import sys
import os
import logger
import json
import test_manager
import utils
import azure.storage.blob as azureblob
import azure.batch.models as batchmodels
import azext.batch as batch
import argparse
from pygit2 import Repository
import uuid

"""
This python module is used for validating the rendering templates by using the azure CLI. 
This module will load the manifest file 'TestConfiguration' specified by the user and
create pools and jobs based on this file.
"""

sys.path.append('.')
sys.path.append('..')

_timeout = 60  # type: int
_test_managers = []  # type: List[test_manager.TestManager]

def create_batch_client(args: object) -> batch.BatchExtensionsClient:
    """
    Create a batch client using AAD.

    :param args: The list of arguments that come in through the command line
    :type args: ArgumentParser
    :return batch.BatchExtensionsClient: returns the valid batch extension client that used AAD.
    """
    credentials = ServicePrincipalCredentials(
        client_id=args.ServicePrincipalCredentialsClientID,
        secret=args.ServicePrincipalCredentialsSecret,
        tenant=args.ServicePrincipalCredentialsTenant,
        resource=args.ServicePrincipalCredentialsResouce)

    return batch.BatchExtensionsClient(
        credentials=credentials,
        batch_account=args.BatchAccountName,
        batch_url=args.BatchAccountUrl,
        subscription_id=args.BatchAccountSub,)

def create_keyvault_client(args: object) -> tuple():
    """
    Create keyvault client namedTuple with url

    :param args: The list of arguments that come in through the command line
    :return: Returns a tuple holding the KeyVaultClient and the url of the KeyVault to use
    :rtype: tuple(KeyVaultClient, str)
    """
    if (args.KeyVaultUrl == None):
        return (None, None)

    credentials = ServicePrincipalCredentials(
        client_id = args.ServicePrincipalCredentialsClientID,
        secret = args.ServicePrincipalCredentialsSecret,
        tenant = args.ServicePrincipalCredentialsTenant)

    client = KeyVaultClient(credentials)

    return (client, args.KeyVaultUrl)


def runner_arguments():
    """
    
    Handles the user's input and what settings are needed when running this module.

    :return: Returns the parser that contains all settings this module needs from the user's input
    :rtype: Parser
    """
    parser = argparse.ArgumentParser()
    # "Tests/TestConfiguration.json"
    parser.add_argument(
        "TestConfig",
        help="A manifest file that contains a list of all the jobs and pools you want to create.")
    parser.add_argument("BatchAccountName", help="The batch account name")
    parser.add_argument("BatchAccountKey", help="The batch account key")
    parser.add_argument("BatchAccountUrl", help="The batch account url")
    parser.add_argument("BatchAccountSub", help="The batch account sub ")
    parser.add_argument("StorageAccountName", help="Storage name ")
    parser.add_argument("StorageAccountKey", help="storage key")
    parser.add_argument("ServicePrincipalCredentialsClientID", help="Service Principal id")
    parser.add_argument("ServicePrincipalCredentialsSecret", help="Service Principal secret")
    parser.add_argument("ServicePrincipalCredentialsTenant", help="Service Principal tenant")
    parser.add_argument("ServicePrincipalCredentialsResouce", help="Service Principal resource")
    parser.add_argument("-VMImageURL", default=None, help="The custom image resource URL, if you want the temlates to run on a custom image")
    parser.add_argument("-KeyVaultUrl", default=None, help="Azure Key vault to fetch secrets from, service principal must have access")
    parser.add_argument("-CleanUpResources", action="store_false")
    parser.add_argument("-RepositoryBranchName", default="master", help="Select the branch you want to pull your resources files from, default=master, current=Gets the branch you working on")

    return parser.parse_args()


def run_test_manager_tests(blob_client: azureblob.BlockBlobService, batch_client: batch.BatchExtensionsClient,
                          images_refs: 'List[utils.ImageReference]', VMImageURL: str):
    """
    Creates all resources needed to run the job, including creating the containers and the pool needed to run the job.
    Then creates job and checks if the expected output is correct.

    :param images_refs: The list of images the rendering image will run on
    :type images_refs: List[utils.ImageReference]
    :param blob_client: The blob client needed for making blob client operations
    :type blob_client: `azure.storage.blob.BlockBlobService`
    :param batch_client: The batch client needed for making batch operations
    :type batch_client: azure.batch.BatchExtensionsClient
    """
    logger.info("{} jobs will be created.".format(len(_test_managers)))
    
    stop_threads = False
    threads = [] # type: List[threading.Thread]
    try:
        threads = utils.start_test_threads("run_test", _test_managers, blob_client, batch_client, images_refs, True, _timeout, lambda: stop_threads, VMImageURL)

        waiting = True
        while waiting:
            waiting = False
            for thread in threads:
                if thread.isAlive():
                    waiting = True
                    thread.join(1)

    except KeyboardInterrupt:
        #A test has failed and triggered KeyboardInterrupt on main thread, so call stop_threads on all the other threads
        logger.error("Keyboard Interrupt triggered in main thread, calling stop_threads")
        stop_threads = True
        
def main():
    args = runner_arguments()
    logger.account_info(args)
    start_time = datetime.now(timezone.utc).replace(microsecond=0)
    logger.info('Template runner start time: [{}]'.format(start_time))

    #generate unique id for this run to prevent collisions
    run_unique_id = str(uuid.uuid4())[0:7]

    # Create the blob client, for use in obtaining references to
    # blob storage containers and uploading files to containers.
    blob_client = azureblob.BlockBlobService(
        account_name=args.StorageAccountName,
        account_key=args.StorageAccountKey)

    # Create a batch client using AAD    
    batch_client = create_batch_client(args)

    # Create a keyvault client using AAD    
    keyvault_client_with_url = create_keyvault_client(args)

    repository_branch_name = args.RepositoryBranchName
    if repository_branch_name == "current":
        repository_branch_name = Repository('../').head.shorthand
        
    logger.info('Pulling resource files from commit: {}'.format(repository_branch_name))

    #Clean up any storage container, pool or jobs older than some threshold.
    utils.cleanup_old_resources(blob_client, batch_client)

    try:
        images_refs = []  # type: List[utils.ImageReference]
        with open(args.TestConfig) as f:
            try:
                template = json.load(f)
            except ValueError as e:
                logger.error("Failed to read test config file due to the following error: {}".format(e))
                raise e

            for jobSetting in template["tests"]:
                application_licenses = None
                if 'applicationLicense' in jobSetting:
                    application_licenses = jobSetting["applicationLicense"]

                _test_managers.append(test_manager.TestManager(
                    jobSetting["template"],
                    jobSetting["poolTemplate"],
                    jobSetting["parameters"],
                    keyvault_client_with_url,
                    jobSetting["expectedOutput"],
                    application_licenses,
                    repository_branch_name,
                    run_unique_id))

            for image in template["images"]:
                images_refs.append(utils.ImageReference(image["osType"], image["offer"], image["version"]))

        run_test_manager_tests(blob_client, batch_client, images_refs, args.VMImageURL)

    except batchmodels.BatchErrorException as err:
        utils.print_batch_exception(err)
        raise
    finally:
        end_time = datetime.now(timezone.utc).replace(microsecond=0)
        logger.print_result(_test_managers)
        logger.export_result(_test_managers, (end_time - start_time))
    logger.info('Sample end: {}'.format(end_time))
    logger.info('Elapsed time: {}'.format(end_time - start_time))

if __name__ == '__main__':
    try:
        main()
        logger.info("Exit code 0")
        os._exit(0)
    except Exception as err:
        traceback.print_exc()
        logger.info("Exit code 1")
        os._exit(1)
