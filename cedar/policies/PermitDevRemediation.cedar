permit (
    principal == Leash::Agent::"leash",
    action in [Leash::Action::"cleanDisk", Leash::Action::"restartService", Leash::Action::"scaleGroup"],
    resource
) when { resource.env == "dev" };
