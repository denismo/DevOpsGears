Introduction
============

DevOpsGears is an automation engine that allows managing different resources in AWS cloud environment from within a source repository. The design of the engine follows the following principles:

- **Everything is source controlled** - the goal is that you should never login into the environment (be that an instance or just AWS console) when you need to change the configuration or install something. You manage all your resources, scripts, application and configurations within single, versioned, source repository. Any update to this repository is immediately reflected in the environment and by this the changes are automatically propagated. It's also easy to replicate or duplicate environments (copy), look at history and get the view of the whole environment in one place. The source repository becomes the single source of truth about your environment.

- **Convention over configuration** - where possible and makes sense, the naming conventions of the files are used to trigger an action or identify a resource. You can define handlers which work on types of resources, and by simply creating a resource of particular type (by name) you immediately plug it and make it alive. No need for "registries" or "maps".
 Also, if the natural order of files defines either resource creation order, or action execution order, so there is no need for any imperative flow control. Finally, simply put a file into a folder to define hierarchy between resources.

- **File is the unit of control** - resource or an action handler, it is just a file. The conventions define relations between these, but no scripting is required to bring the environment to life. You don't need to invoke anything - by mere fact of existence either a resource or a handler triggers a chain of actions that will automatically mutate the environment to the declared state.

- **Minimise boilerplate coding** - while writing code to automate infrastructure is standard thing in DevOps, no one likes writing basic operations like setting up cron scripts, figuring out how Chef/Puppet/etc is going to run, how to run scripts on instance startup or creation. To mitigate that, DevOpsGears is doing all this plumbing for you once and forever, and you can focus on writing the automation statements which are really specific to your environment.

If you are familiar with Chef/Puppet/etc, their main automation value is realised INSIDE of the server instance. DevOpsGears, on the other hand, aims to be the automation on the OUTSIDE of the servers, orchestrating the resources and actions across the environments.

Concepts
========

Repostory
---------
TODO

Resource
--------
TODO

Handler
-------

Handlers are pieces of code which run in response to an event. Typically handler is a script in one of the languages supported by the Linux system to be executed via Linux [shebang](http://en.wikipedia.org/wiki/Shebang_%28Unix%29)("#!"), or a native process.

When an event is dispatched, a list of handler is produced that can "handle" such event, using conventions similar to what [Apache Sling] uses for matching URLs to its handlers. The name of the handler is split into parts by "."(dot). The first part (or the second part - in case if the first one is "on") is matching the event name. The last part is the extension which defines the handler type for the execution purposes. The second part matches resource type, and the third part matches the resource name. Resource type and resource name parts are optional.

For example, considering the following handler "on.received.sqs.sh", here is the explanation of the parts:

| on | reserved action meaning "event handler"|
| received | matches event named "received"|
| sqs | matches resource type "sqs"|
| sh | the handler is a shell script|

So as the result, this handler will match any "received" event sent by any resource of type "sqs". In other words, it is used to process SQS messages.

There are two types of handlers which differ in purpose:

*Action handler* - action handlers are used to attach a behavior to a resource, because resources are by definition passive entities. There is a number of predefined reserved actions which apply to resources:
|register|raised when a resource is registered within the engine. This moves the resource to the "registered" state which is merely a declaration of the resource|
|activate|raised when a resource is to made active, for example, EC2 instance can be created. This moves the resource to the "active" state. Note that in case of EC2 instances, "active" state does not mean "running"|
|update|raised when a resource declaration changes. The handler can then modify the running resource|
|delete|raised when a resource is deleted from source repository. The handler needs to physically destroy the resource|
|unregister||
|deactivate||
|run|raised when a handler needs to run. Useful when either the handler's language is not supported by the system, or when "running" a handler means more than just running a script, for example if you want to run a script in a clustered environment. The handler which handles the "run" action should be runnable, or no other action will be performed. The "run" action is invoked automatically if the script fails to execute|
|on|raised for any event, either system action or user defined event. The handler is then declared as an "event handler", see below|

*Event handler* - event handlers are any handlers which start with "on". Event handlers can handle system events, but they are more useful for handling custom user-defined events that resources can raise. For example, SQS queue may send the "received" event when a new message arrives, or EC2 Instance can send the "started" event after it starts.

TODO: Installation, Examples

License
=======

[GNU General Public License, version 3](http://opensource.org/licenses/gpl-3.0.html)