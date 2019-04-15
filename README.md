# Azure Batch Extension Templates
[![VSTS Build Status](https://azurebatch.visualstudio.com/BatchExplorer/_apis/build/status/batch-extension-templates/batch-extension-templates%20CI?branchName=master)](https://azurebatch.visualstudio.com/BatchExplorer/_build/latest?definitionId=23&branchName=master)

This repository contains templates that can be used with the [azure-batch-cli-extensions](https://github.com/Azure/azure-batch-cli-extensions)

This is also what [Batch Explorer](https://github.com/Azure/BatchExplorer) uses for its gallery.

Templates are located in the `templates` folder. They need to follow a **strict** folder structure for Batch Explorer to be able to parse it.

- templates/
  - index.json  _Index file that reference all applications_
  - [myappId]/
     - index.json _Index file that reference all different actions you can do in this application_
     - [actionId]/
        pool.template.json  _Template to build a pool for this action_
        job.template.json   _Template to build the job for this action. This shouldn't be using autoPool. Batch Explorer will automatically inject the pool template into the job if needs be._
