import models
from database import engine

try:
    print("creating database ...")
    models.Base.metadata.create_all(bind=engine)
    print("created database")
except Exception as e:
    print(e)
