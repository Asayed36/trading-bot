def running(cfg):
    """config.toml with every stopped strategy running again ([main],
    [early], [launch] and momentum variants with stopped = true), so the
    tests of their buying rules still test them. The stopping itself is
    tested with the real config."""
    import copy
    cfg = copy.deepcopy(cfg)
    for name in ("main", "early", "launch"):
        cfg.get(name, {}).pop("stopped", None)
    for v in cfg.get("momentum", {}).get("variants", []):
        v.pop("stopped", None)
    return cfg
