from constants import DBConstants
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import sys
import os
import urllib.parse

sys.path.append('.')
# custom imports

if DBConstants.DATABASE == 'sql':
    SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.CONN_STRING_SQL)
    HRMS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.HRMS_CONN_STRING_SQL)
    ACCOUNTS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.ACC_CONN_STRING_SQL)
    CRMS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.CRMS_CONN_STRING_SQL)
    PM_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.PM_CONN_STRING_SQL)
    
    engine_main = create_engine(SQLALCHEMY_DATABASE_URL)
    engine_hrms = create_engine(HRMS_SQLALCHEMY_DATABASE_URL)
    engine_accounts = create_engine(ACCOUNTS_SQLALCHEMY_DATABASE_URL)
    engine_crms = create_engine(CRMS_SQLALCHEMY_DATABASE_URL)
    engine_pm = create_engine(PM_SQLALCHEMY_DATABASE_URL)


    SessionLocal_main = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)
    SessionLocal_hrms = sessionmaker(autocommit=False, autoflush=False, bind=engine_hrms)
    SessionLocal_accounts = sessionmaker(autocommit=False, autoflush=False, bind=engine_accounts)
    SessionLocal_crms = sessionmaker(autocommit=False, autoflush=False, bind=engine_crms)
    SessionLocal_pm=sessionmaker(autocommit=False, autoflush=False, bind=engine_pm)


    Base_main = declarative_base()
    Base_hrms = declarative_base()
    Base_accounts = declarative_base()
    Base_crms = declarative_base()
    Base_pm=declarative_base()


elif DBConstants.DATABASE == 'ms_sql':
    SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.CONN_STRING_SQL)
    HRMS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.HRMS_CONN_STRING_SQL)
    ACCOUNTS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.ACC_CONN_STRING_SQL)
    CRMS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.CRMS_CONN_STRING_SQL)
    PM_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.PM_CONN_STRING_SQL)
    
    engine_main = create_engine(SQLALCHEMY_DATABASE_URL)
    engine_hrms = create_engine(HRMS_SQLALCHEMY_DATABASE_URL)
    engine_accounts = create_engine(ACCOUNTS_SQLALCHEMY_DATABASE_URL)
    engine_crms = create_engine(CRMS_SQLALCHEMY_DATABASE_URL)
    engine_pm = create_engine(PM_SQLALCHEMY_DATABASE_URL)


    SessionLocal_main = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)
    SessionLocal_hrms = sessionmaker(autocommit=False, autoflush=False, bind=engine_hrms)
    SessionLocal_accounts = sessionmaker(autocommit=False, autoflush=False, bind=engine_accounts)
    SessionLocal_crms = sessionmaker(autocommit=False, autoflush=False, bind=engine_crms)
    SessionLocal_pm=sessionmaker(autocommit=False, autoflush=False, bind=engine_pm)


    Base_main = declarative_base()
    Base_hrms = declarative_base()
    Base_accounts = declarative_base()
    Base_crms = declarative_base()
    Base_pm=declarative_base()


elif DBConstants.DATABASE == 'prod_sql':
    SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.CONN_STRING_SQL)
    HRMS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.HRMS_CONN_STRING_SQL)
    ACCOUNTS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.ACC_CONN_STRING_SQL)
    CRMS_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.CRMS_CONN_STRING_SQL)
    PM_SQLALCHEMY_DATABASE_URL = os.environ.get(DBConstants.PM_CONN_STRING_SQL)
    
    engine_main = create_engine(SQLALCHEMY_DATABASE_URL)
    engine_hrms = create_engine(HRMS_SQLALCHEMY_DATABASE_URL)
    engine_accounts = create_engine(ACCOUNTS_SQLALCHEMY_DATABASE_URL)
    engine_crms = create_engine(CRMS_SQLALCHEMY_DATABASE_URL)
    engine_pm = create_engine(PM_SQLALCHEMY_DATABASE_URL)


    SessionLocal_main = sessionmaker(autocommit=False, autoflush=False, bind=engine_main)
    SessionLocal_hrms = sessionmaker(autocommit=False, autoflush=False, bind=engine_hrms)
    SessionLocal_accounts = sessionmaker(autocommit=False, autoflush=False, bind=engine_accounts)
    SessionLocal_crms = sessionmaker(autocommit=False, autoflush=False, bind=engine_crms)
    SessionLocal_pm=sessionmaker(autocommit=False, autoflush=False, bind=engine_pm)


    Base_main = declarative_base()
    Base_hrms = declarative_base()
    Base_accounts = declarative_base()
    Base_crms = declarative_base()
    Base_pm=declarative_base()

