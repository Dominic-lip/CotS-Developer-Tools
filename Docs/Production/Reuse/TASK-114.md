# TASK-114 Reuse Decision

CotS adapts Shardlands' local-only HUD and inventory-presentation principle:
widgets may present state and submit intent, but never own gameplay or social
truth. Shardlands has no chat or voice service suitable for direct reuse, and
the Website and Platform API sources are not available locally; their future
adapters remain behind the TASK-102 session boundary.
