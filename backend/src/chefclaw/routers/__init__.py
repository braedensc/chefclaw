"""FastAPI routers — thin transport over the service layer (plan §4).

Routers parse/validate/serialize only; every route is auth-required via
``require_owner`` and owner-scoped in its queries.
"""
