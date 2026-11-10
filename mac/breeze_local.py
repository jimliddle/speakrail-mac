"""Run the pinned Breeze package behind the local controller boundary."""
from backend_security import ASGIGuard
from breeze_infer import api

original_create_app = api.create_app


def guarded_app(*args, **kwargs):
    return ASGIGuard(original_create_app(*args, **kwargs))


if __name__ == "__main__":
    api.create_app = guarded_app
    api.main()
