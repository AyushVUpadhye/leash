forbid (
    principal,
    action == Leash::Action::"scaleGroup",
    resource
) when { context.desiredCapacity > 4 };
