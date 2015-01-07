Introduction
============

DevOpsGears is an automation engine that allows managing different resources in AWS cloud environment from within a source repository. The design of the engine follows the following principles:

- **Everything is source controlled** - the goal is that you should never login into the environment (be that an instance or just AWS console) when you need to change the configuration or install something. You manage all your resources, scripts, application and configurations within single versioned source repository. Any update to this repository is immediately reflected in the environment and by this the changes are automatically propagated. It's also easy to replicate or duplicate environments (copy), look at history and get the view of the whole environment in one place. The source repository becomes the single source of truth about your environment.

- **Convention over configuration** - where possible and makes sense, the naming conventions of the files are used to trigger an action or identify a resource. You can define handlers which work on types of resources, and by simply creating a resource of particular type (by name) you immediately plug it and make it alive. No need for "registries" or "maps".
 Also, the natural order of files defines either resource creation order, or action execution order, so there is no need for any imperative flow control. Finally, simply put a file into a folder to define hierarchy between resources.

- **File is a unit of control** - resource or an action handler, it is just a file. The conventions define relations between these, but no scripting is required to bring the environment to life. You don't need to invoke anything - by mere fact of existence either a resource or a handler triggers a chain of actions that will automatically mutate the environment to the declared state.

- **Minimise boilerplate coding** - while writing code to automate infrastructure is standard thing in DevOps, no one likes writing basic operations like setting up cron scripts, figuring out how Chef/Puppet/etc is going to run, how to run scripts on instance startup or creation. To mitigate that, DevOpsGears is doing all this plumbing for you once and forever, and you can focus on writing the automation statements which are really specific to your environment.

If you are familiar with Chef/Puppet/etc, their main automation value is realised INSIDE of the server instance. DevOpsGears, on the other hand, aims to be the automation on the OUTSIDE of the servers, orchestrating the resources and actions across the environments.

Concepts
========

Repository
----------
Repository is where the resources and handlers are stored. Physically, repository usually matches your version control system (such as Git). The Repository is stored in memory, and contains the representation of the source repository plus any synthetic resources/handlers that you have created yourself.

On startup, the engine traverse the source repository top to bottom, discovering the handlers and resources on the way. They get added to the in-memory representation of the Repository, and then initial registration events are triggered on all the resources, top to bottom. From that moment on, the source repository is also monitored for changes which are then merged with the in-memory Repository, and the corresponding events are triggered.

Resource
--------
Resource is a passive object stored in the Repository. It has a number of properties, it can have some state, triggers events. Resources are organised into a hierarchy, typically mirroring the folder structure of the source repository (you can also add your own resources to any parent). Resources must have unique **name**, which by default is their path in source repository.

In source repository, the resource are typically represented by the YAML files, which define the resource properties.

The resources have the following default properties:
| Property | Meaning |
|----------|---------|
|name|The unique identified of the resource, the path in the source repository by default|
|type|The type of the resource, typically the extension of the file in the source repository|
|parent|The parent of the resource, the resource with the name of the folder containing the resource by default|
|desc|Optional descriptor which can contain arbitrary configuration properties for that resource|
|behavior|Optional list of Python classes that will be created and registered as the default handlers for that resource|
|description|Optional human-readable resource description|

Special note on the resource behavior. By default, resource as passive. They don't expose any behavior, and simply contain properties that others can read, raise the system events. In order for the resource to "act", you need to attach a Handler that would respond to the system events.

For example, consider a resource describing an AWS SQS queue. It can be simply represented by type "sqs", the queue name and region. By itself, the resource by won't create a queue in AWS, and won't receive or send message. You need to attach a handler which responds to the "activate" event, that would need to create (or attach) the queue. And "subscribe" to initiate the polling loop that would receive the message. An example of an implementation of such a handler is engine.handlers.SQSHandler.

Multiple handlers can be associated with a resource (typically via convention), adding multiple behaviors to the resource.

Resource State Machine
----------------------
From the time when resource are added to the Repository, they go through the pre-defined system states and raise predefined events:
ADDED -> Register -> REGISTERED -> Activate -> PENDING_ACTIVATION -...> ACTIVATED

For any events, there can be a handler, and the return result of the handler determines if the Resource moves to the next state. For example, a resource which is incorrectly configured, may be failed by the Register event handler, and will then move to the FAILED state.

The state transitions are tightly related to the Resource hierarchy. When resource is added and it's valid, it moves to the REGISTERED state. If the parent resource is ACTIVATED, the Activate event is raised for the child resource. If there is a handler, it'll move the Resource to the PENDING_ACTIVATION state on success. If there is no handler, the Resource remains in the Registered state, unless it is marked as "autoActivated" in which case it'll move to the ACTIVATED state automatically.

On the example of the SQS queue, on Register the queue descriptor can be validated, and on Activate the queue can be created, or verified to exist and "retrieved" vi API. However, PENDING_ACTIVATION does not mean it finished creating, as typically the creation is asynchronous. Only when the SQS queue has finished creating, it should move to the "ACTIVATED" state which should be implemented by a handler.

Handler
-------
Handlers are pieces of code which run in response to an event. Typically handler is a script in one of the languages supported by the Linux system to be executed via Linux [shebang](http://en.wikipedia.org/wiki/Shebang_%28Unix%29)("#!"), or a native process.

When an event is dispatched, a list of handler is produced that can "handle" such event, using conventions similar to what [Apache Sling] uses for matching URLs to its handlers. The name of the handler is split into parts by "."(dot). The first part (or the second part - in case if the first one is "on") is matching the event name. The last part is the extension which defines the handler type for the execution purposes. The second part matches resource type, and the third part matches the resource name. Resource type and resource name parts are optional.

For example, considering the following handler "on.received.sqs.sh", here is the explanation of the parts:

| Part | Role |
|-------|-------|
| on | reserved action meaning "event handler"|
| received | matches event named "received"|
| sqs | matches resource type "sqs"|
| sh | the handler is a shell script|

So as the result, this handler will match any "received" event sent by any resource of type "sqs". In other words, it will receive and can process SQS messages.

There are two types of handlers which differ in purpose:

*Action handler* - action handlers are used to attach a behavior to a resource, because resources are by definition passive entities. There is a number of predefined reserved actions which apply to resources:

| Action | When raised |
|-------|-------|
|register|raised when a resource is registered within the engine. This moves the resource to the "registered" state which is merely a declaration of the resource|
|activate|raised when a resource is to made active, for example, EC2 instance can be created. This moves the resource to the "active" state. Note that in case of EC2 instances, "active" state does not mean "running"|
|update|raised when a resource declaration changes. The handler can then modify the running resource|
|delete|raised when a resource is deleted from source repository. The handler needs to physically destroy the resource|
|unregister||
|deactivate||
|run|raised when a handler needs to run. Useful when either the handler's language is not supported by the system, or when "running" a handler means more than just running a script, for example if you want to run a script in a clustered environment. The handler which handles the "run" action should be system-runnable, or no other action will be performed. The "run" action is invoked automatically if the script fails to execute|
|on|raised for any event, either system action or user defined event. The handler is then declared as an "event handler", see below|
|finished|raised when a handler finished execution. The criteria either matches a resource which finished to be handled, or handler which finished execution|

TODO: Handler execution context (resource hierarchy, environment variables, gears instance or user instance)

*Event handler* - event handlers are any handlers which start with "on". Event handlers can handle system events, but they are more useful for handling custom user-defined events that resources can raise. For example, SQS queue may send the "received" event when a new message arrives, or EC2 Instance can send the "started" event after it starts.

Installation
============
TODO

Examples
========
TODO 1. SQS 2. ETL with a graph of jobs 3. EC2 environments

License
=======

[GNU General Public License, version 3](http://opensource.org/licenses/gpl-3.0.html)