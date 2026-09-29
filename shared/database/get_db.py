from shared.database.database import SessionLocal_main,SessionLocal_hrms,SessionLocal_accounts,SessionLocal_crms, SessionLocal_pm


def get_db():
    db = SessionLocal_pm()
    try:
        yield db
    finally:
        db.close()
