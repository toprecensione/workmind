# Backward-compat shim.
# MEDIC router now lives in clients/medic/routes.py.
from clients.medic.routes import router, ROUTE_PREFIX, SECTOR  # noqa: F401
