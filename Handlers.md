on.<event name>[.<resource type>[.<resource name>].<handler type>
create.<resource type>[.<resource name>].<handler type>
update.<resource type>[.<resource name>].<handler type>
delete.<resource type>[.<resource name>].<handler type>

resource type and resource name are interchangeable (either can be present)


- when resources are initialised, they are created from top to bottom in the date order within folders, unless scripts have "x. " in front - then they are numbered steps
- on startup, the resources are initialised - create events are raised
- Q: how do we trigger scripts when instance is started? Is it different from "create"?
  A: there is 2 stage process: create -> created -> activate -> activated. Activated on parent automatically triggers "activate" handler on children