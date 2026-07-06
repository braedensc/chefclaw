"""Framework-free service layer (plan §4): all worker/library logic lives
here; FastAPI routers are a thin transport over these modules.

- :mod:`chefclaw.services.repo` — the persistence seam (JobStore) the worker
  talks through; faked in CI-tier tests, real against postgres.
- :mod:`chefclaw.services.jobs` — enqueue + the strictly-serial no-broker
  worker.
- :mod:`chefclaw.services.recipes` — the recipe library (list/get/patch/
  delete).
"""
