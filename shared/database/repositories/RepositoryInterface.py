from abc import ABC


class RepositoryInterface(ABC):
    def create(self, *args, **kwargs):
        raise NotImplemented()

    def list(self):
        raise NotImplemented()

    def get(self, id_):
        raise NotImplemented()

    def update(self, **fields):
        raise NotImplemented()

    def delete(self, id_):
        raise NotImplemented()