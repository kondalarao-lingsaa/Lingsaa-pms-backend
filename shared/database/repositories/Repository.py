from shared.database.repositories.RepositoryInterface import RepositoryInterface
from sqlalchemy.orm import Session


class Repository(RepositoryInterface):
    def __init__(self, model_cls, db: Session):
        self.session = db
        self.model_cls = model_cls

    def create(self, *args, **kwargs):
        obj = self.model_cls(*args, **kwargs) 
        self.session.add(obj)
        self.session.commit()
        return obj

    def list(self):
        return self.session.query(self.model_cls).all()

    def get(self, id_):
        return self.session.query(self.model_cls).get(id_)

    def update(self, id_, **fields):
        obj = self.get(id_)
        for field, value in fields.items():
            obj.__setattr__(field, value)
        self.session.commit()
        return obj

    def delete(self, id_):
        self.session.delete(self.get(id_))
        self.session.commit()


