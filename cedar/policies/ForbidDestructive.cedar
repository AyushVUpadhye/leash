forbid (
    principal,
    action in [Leash::Action::"terminateInstance", Leash::Action::"deleteResource"],
    resource
);
