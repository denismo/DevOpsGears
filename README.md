Introduction
============

DevOpsGears is an automation engine that allows managing different resources in AWS cloud environment from within a source repository. The design of the engine follows the following principles:

- **Everything is source controlled**. The goal is that you should never login into the environment (be that an instance or just AWS console) when you need to change the configuration or install something. You manage all your resources, scripts, application and configurations within single, versioned, source repository. Any update to this repository is immediately reflected in the environment and by this the changes are automatically propagated. It's also easy to replicate or duplicate environments (copy), look at history and get the view of the whole environment in one place. The source repository becomes the single source of truth about your environment.

- **Convention over configuration**. Where possible and makes sense, the naming conventions of the files are used to trigger an action or identify a resource. You can define handlers which work on types of resources, and by simply creating a resource of particular type (by name) you immediately plug it and make it alive. No need for "registries" or "maps".
 Also, if the natural order of files defines either resource creation order, or action execution order, so there is no need for any imperative flow control. Finally, simply put a file into a folder to define hierarchy between resources.

- **File is the unit of control**. Resource or an action handler, is just a file. The conventions define relations between these, but no scripting is required to bring the environment to life.

- **Minimum coding**. The engine is aimed at administrators or DevOps engineers, which while can write code,